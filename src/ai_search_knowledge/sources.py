from __future__ import annotations

import io
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit, urljoin

import trafilatura
from bs4 import BeautifulSoup
from pypdf import PdfReader

from .core import Fetcher, FetchFailure, canonical_url, config, digest, needs_fetch, in_scope, now, read, save


def videos(root: Path) -> list[dict]:
    cfg = config(root)
    return sorted((v for p in (root / "data/raw/videos").glob("*.json")
                   if in_scope(v := read(p), cfg)), key=lambda v: v["published_at"], reverse=True)


def build_manifest(root: Path) -> dict:
    sources = {}
    active = videos(root)
    for video in active:
        for link in video["links"]:
            url = link["url"]
            sid = digest(url)[:20]
            item = sources.setdefault(sid, {"id": sid, "url": url, "mentions": [], "roles": []})
            if link["role"] not in item["roles"]:
                item["roles"].append(link["role"])
            item["mentions"].append({"video_id": video["id"], "published_at": video["published_at"],
                                     **{k: v for k, v in link.items() if k != "url"}})
    # Explicit, evidence-checked primary artifacts added by a reading agent.
    # Two hops is sufficient for landing page → paper/model card without an open crawl.
    extras = read(root / "data/extra-sources.json", [])
    for depth in range(1, 3):
        for edge in extras:
            parent = sources.get(edge["parent_id"])
            if not parent or parent.get("depth", 0) != depth - 1:
                continue
            sid = digest(edge["url"])[:20]
            if sid == parent["id"]:
                continue
            child = sources.setdefault(sid, {"id": sid, "url": edge["url"], "mentions": [], "roles": ["reference"], "depth": depth})
            if "reference" not in child["roles"]:
                child["roles"].append("reference")
            for mention in parent["mentions"]:
                inherited = {**mention, "via_source_id": parent["id"], "source_link_label": edge["label"],
                             "original_url": edge["url"], "description_line": None,
                             "role": "reference", "role_reason": "primary artifact explicitly linked from stored source"}
                if inherited not in child["mentions"]:
                    child["mentions"].append(inherited)
    result = {"generated_at": now(), "videos": [v["id"] for v in active], "sources": list(sources.values())}
    save(root / "data/source-manifest.json", result)
    return result


def add_source(root: Path, parent_id: str, url: str, label: str) -> dict:
    manifest = build_manifest(root)
    parent = next((s for s in manifest["sources"] if s["id"] == parent_id), None)
    if not parent or parent.get("depth", 0) >= 2:
        raise ValueError("Parent must be an active source at depth 0 or 1")
    url = canonical_url(url)
    snapshot = read(root / f"data/sources/{parent_id}.json") or {}
    if not any(link["url"] == url for link in snapshot.get("outbound_links", [])):
        raise ValueError("URL must appear in the parent's stored outbound links; do not invent references")
    edges = read(root / "data/extra-sources.json", [])
    if not any(e["parent_id"] == parent_id and e["url"] == url for e in edges):
        edges.append({"parent_id": parent_id, "url": url, "label": label, "added_at": now()})
        save(root / "data/extra-sources.json", edges)
    build_manifest(root)
    return {"id": digest(url)[:20], "url": url, "status": "queued", "parent_id": parent_id}


def _meta(soup: BeautifulSoup, names: list[str]) -> tuple[str | None, str | None]:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"itemprop": name})
        if tag and tag.get("content"):
            return str(tag["content"]), name
    return None, None


def explicit_publication_date(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    value, evidence = _meta(soup, ["article:published_time", "datePublished", "citation_publication_date", "DC.date.issued"])
    if value:
        return value, evidence
    def scan(item):
        if isinstance(item, dict):
            if item.get("datePublished"):
                return str(item["datePublished"])
            for v in item.values():
                if found := scan(v):
                    return found
        elif isinstance(item, list):
            for v in item:
                if found := scan(v):
                    return found
        return None
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            if value := scan(json.loads(tag.get_text())):
                return value, "JSON-LD datePublished"
        except (ValueError, TypeError):
            continue
    return None, None


def extract_document(body: bytes, content_type: str, url: str) -> dict:
    if "application/pdf" in content_type or body.startswith(b"%PDF-"):
        pdf = PdfReader(io.BytesIO(body))
        if len(pdf.pages) > 250:
            raise FetchFailure("pdf_too_long", "PDF exceeds 250-page limit; manual review needed")
        pages = [(page.extract_text() or "").strip() for page in pdf.pages]
        text = "\n\n".join(f"[PDF page {i}]\n{page}" for i, page in enumerate(pages, 1))
        return {"title": str((pdf.metadata or {}).get("/Title") or urlsplit(url).path.rsplit("/", 1)[-1]),
                "text": text, "format": "pdf", "extraction_method": "pypdf; text layer only; no OCR",
                "published_at": None, "date_evidence": None, "page_count": len(pages),
                "description": None, "outbound_links": [], "quality": "text_layer_unreviewed"}
    if "text/plain" in content_type or urlsplit(url).path.lower().endswith((".md", ".txt")):
        text = body.decode("utf-8", "replace")
        return {"title": urlsplit(url).path.rsplit("/", 1)[-1], "text": text,
                "format": "text", "extraction_method": "UTF-8 plain text", "published_at": None,
                "date_evidence": None, "description": None, "outbound_links": [], "quality": "text_unreviewed"}
    if not any(x in content_type for x in ["html", "xml", "text/"]):
        raise FetchFailure("unsupported_content", f"Unsupported content type: {content_type}")
    html = body.decode("utf-8", "replace")
    soup = BeautifulSoup(html, "lxml")
    title, _ = _meta(soup, ["og:title", "twitter:title"])
    title = title or (soup.title.get_text(" ", strip=True) if soup.title else url)
    description, _ = _meta(soup, ["description", "og:description", "twitter:description"])
    published, date_evidence = explicit_publication_date(soup)
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    # Use README/article regions when publishers expose them. Never clone/run a repository.
    article = None
    if host == "github.com":
        article = soup.select_one("article.markdown-body, .markdown-body")
    elif host.endswith(".github.io"):
        # Demo sites spread caveats across small sections that article extractors
        # can discard. Preserve the full project region, including limitations.
        article = soup.body
    elif host in {"arxiv.org", "export.arxiv.org"} and "/abs/" in url:
        article = soup.select_one("#content, main")
    method = "publisher article/README region" if article else "trafilatura main text"
    if article:
        for tag in article.select("script, style, nav, button"):
            tag.decompose()
        text = article.get_text("\n", strip=True)
    else:
        text = trafilatura.extract(html, url=url, include_links=True, include_tables=True,
                                   include_comments=False, favor_recall=True) or ""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    quality = "extracted_unreviewed"
    low = (title + "\n" + text[:2500]).lower()
    if any(x in low for x in ["just a moment...", "verify you are human", "access denied", "enable javascript and cookies to continue", "checking your browser", "this page is not available", "something went wrong, but don’t fret", "you’ve been blocked"]):
        quality = "access_challenge"
    elif len(text) < 250:
        quality = "thin_or_js_required"
    # Outbound URLs are discovery hints only; this does not recursively crawl the web.
    outlinks = []
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        if href and not href.startswith(("#", "mailto:", "javascript:", "tel:", "data:")):
            target = urljoin(url, href)
            if target.startswith(("http://", "https://")):
                outlinks.append({"url": canonical_url(target), "label": anchor.get_text(" ", strip=True)[:300]})
    return {"title": title, "description": description, "published_at": published,
            "date_evidence": date_evidence, "text": text, "format": "html",
            "extraction_method": method, "outbound_links": outlinks, "quality": quality}


def collect_sources(root: Path, limit: int = 0, refresh: bool = False, retry: bool = False, statuses: list[str] | None = None) -> dict:
    cfg = config(root)
    manifest = build_manifest(root)
    pending = []
    for item in manifest["sources"]:
        if "reference" not in item["roles"]:
            continue
        old = read(root / f"data/sources/{item['id']}.json")
        if statuses and (old or {}).get("status", "pending") not in statuses:
            continue
        error = read(root / f"data/errors/sources/{item['id']}.json")
        if refresh or needs_fetch(old, error, cfg["source_recheck_days"], cfg["retry_days"]) or (retry and old and old.get("status") != "ok"):
            pending.append(item)
    if limit:
        pending = pending[:limit]
    fetcher = Fetcher(cfg)

    def task(item):
        path = root / f"data/sources/{item['id']}.json"
        old = read(path)
        base = {"id": item["id"], "url": item["url"], "fetched_at": now()}
        try:
            final_url, response, body = fetcher.get(item["url"])
            content_type = response.headers.get("content-type", "")
            doc = extract_document(body, content_type, final_url)
            result = {**base, **doc, "final_url": final_url, "http_status": response.status_code,
                      "content_type": content_type, "body_sha256": digest(body), "body_bytes": len(body),
                      "text_sha256": digest(doc["text"]),
                      "status": "ok" if doc["quality"] not in {"access_challenge", "thin_or_js_required"} else doc["quality"],
                      "evidence_level": "publisher_text; claims_not_independently_verified"}
            suffix = "pdf" if doc["format"] == "pdf" else "html" if doc["format"] == "html" else "txt"
            raw_path = root / f"data/raw/pages/{item['id']}/{digest(body)}.{suffix}"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            if not raw_path.exists():
                raw_path.write_bytes(body)
            result["raw_path"] = str(raw_path.relative_to(root))
            if old and old.get("text_sha256") and old.get("text_sha256") != result["text_sha256"]:
                save(root / f"data/history/sources/{item['id']}/{digest(old['fetched_at'])[:16]}.json", old)
            if old and old.get("status") == "ok" and result["status"] != "ok":
                save(root / f"data/errors/sources/{item['id']}.json", result)
            else:
                save(path, result)
            return result["status"]
        except Exception as exc:
            result = {**base, "status": getattr(exc, "status", "error"), "error": str(exc),
                      "error_type": type(exc).__name__}
            if old and old.get("status") == "ok":
                save(root / f"data/errors/sources/{item['id']}.json", result)
            else:
                save(path, result)
            return result["status"]

    counts = {}
    try:
        with ThreadPoolExecutor(max_workers=cfg["source_workers"]) as pool:
            futures = [pool.submit(task, item) for item in pending]
            for i, future in enumerate(as_completed(futures), 1):
                status = future.result(); counts[status] = counts.get(status, 0) + 1
                if i % 25 == 0 or i == len(pending):
                    print(json.dumps({"phase": "sources", "completed": i, "queued": len(pending), "results": counts}), flush=True)
    finally:
        fetcher.close()
    result = {"fetched_at": now(), "queued": len(pending), "results": counts}
    save(root / "data/sources-run.json", result)
    return result
