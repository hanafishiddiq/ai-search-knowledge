from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path

from yt_dlp import YoutubeDL
from filelock import FileLock, Timeout

from .core import canonical_url, collect_videos, config, digest, now, read, save
from .library import build_index, source_document, validate_note
from .sources import build_manifest, collect_sources


@contextmanager
def writer_lock(root: Path):
    path = root / "data/writer.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(path, timeout=0)
    try:
        lock.acquire()
    except Timeout:
        raise RuntimeError("Another collection/index process is running for this library") from None
    try:
        yield
    finally:
        lock.release()


def discover(root: Path) -> dict:
    cfg = config(root)
    result = {}
    with YoutubeDL({"extract_flat": True, "skip_download": True, "quiet": True, "no_warnings": True}) as ydl:
        for tab in cfg["tabs"]:
            url = cfg["channel_url"].rstrip("/") + "/" + tab
            raw = ydl.extract_info(url, download=False)
            if raw.get("channel_id") != cfg["channel_id"]:
                raise ValueError("Discovered channel identity does not match config.json")
            data = {"id": raw.get("id"), "channel_id": raw["channel_id"], "channel": raw.get("channel"),
                    "url": url, "discovered_at": now(), "sort": "default latest-first Videos tab",
                    "entries": [{k: e.get(k) for k in ["id", "title", "url", "duration", "timestamp"]}
                                for e in raw.get("entries", []) if e]}
            path = root / f"data/raw/channel/{tab}.json"
            old = read(path)
            if old:
                save(root / f"data/history/channel/{tab}-{digest(json.dumps(old, sort_keys=True))[:16]}.json", old)
            save(path, data)
            result[tab] = len(data["entries"])
    return result


def update(root: Path, source_limit: int = 0) -> dict:
    run_id = now().replace(":", "-")
    path = root / f"data/runs/{run_id}.json"
    record = {"started_at": now(), "status": "running", "steps": {}}
    save(path, record)
    try:
        for name, action in [("discover", lambda: discover(root)),
                             ("videos", lambda: collect_videos(root)),
                             ("sources", lambda: collect_sources(root, source_limit)),
                             ("index", lambda: build_index(root))]:
            record["steps"][name] = action()
            save(path, record)
        report = record["steps"]["index"]
        incomplete = report["source_statuses"].get("ok", 0) < report["reference_urls"] or report["metadata_unresolved"] or not report["metadata_boundary_reached"]
        record["status"] = "completed_with_recorded_gaps" if incomplete else "collection_complete"
    except BaseException as exc:
        record.update({"status": "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", "error": str(exc)})
        raise
    finally:
        record["finished_at"] = now()
        save(path, record)
    return record


def work_queue(root: Path, limit: int = 3) -> list[dict]:
    manifest = read(root / "data/source-manifest.json") or build_manifest(root)
    covered = set()
    for path in (root / "data/notes").glob("*.json"):
        note = read(path)
        if not validate_note(note, root):
            for claim in note["claims"]:
                covered.update((e["source_id"], e["text_sha256"]) for e in claim["evidence"])
    result = []
    for item in manifest["sources"]:
        source = read(root / f"data/sources/{item['id']}.json")
        if not source or source.get("status") != "ok" or (source["id"], source["text_sha256"]) in covered:
            continue
        path, lines = source_document(root, source, item["mentions"])
        result.append({"source_id": source["id"], "text_sha256": source["text_sha256"], "title": source["title"],
                       "url": source["url"], "source_published_at": source.get("published_at"),
                       "fetched_at": source["fetched_at"], "path": str(path.relative_to(root)),
                       "line_count": len(lines), "video_mentions": item["mentions"],
                       "primary_link_candidates": [link for link in source.get('outbound_links', []) if any(word in link['label'].lower() for word in ['paper', 'code', 'model card', 'github', 'arxiv', 'license'])][:12],
                       "preview": "\n".join(f"{i}: {line}" for i, line in enumerate(lines[:50], 1)),
                       "task": "Read relevant source passages. Write original English synthesis with exact evidence line ranges. Preserve publisher attribution, dates, limits and gaps. Validate before adding. A source appearing in a note does not mean all its details were reviewed."})
        if len(result) >= max(1, min(limit, 20)):
            break
    return result


def add_note(root: Path, path: Path) -> dict:
    note = read(path)
    errors = validate_note(note, root)
    if errors:
        raise ValueError("; ".join(errors))
    target = root / f"data/notes/{note['id']}.json"
    old = read(target)
    if old:
        save(root / f"data/history/notes/{note['id']}/{digest(json.dumps(old, sort_keys=True))[:16]}.json", old)
    save(target, note)
    return {"id": note["id"], "status": "accepted", "validation": "references and line ranges checked; factual interpretation still requires review"}


def import_snapshot(root: Path, path: Path) -> dict:
    """Import text actually returned by an approved browser/reader tool, with provenance."""
    snapshot = read(path)
    manifest = read(root / "data/source-manifest.json") or build_manifest(root)
    entry = next((s for s in manifest["sources"] if s["id"] == snapshot.get("id")), None)
    if not entry or entry["url"] != snapshot.get("url") or "reference" not in entry["roles"]:
        raise ValueError("Snapshot must identify an existing reference URL exactly")
    target = root / f"data/sources/{entry['id']}.json"
    old = read(target) or {}
    if old.get("status") == "robots_denied":
        raise ValueError("Do not use a browser fallback to bypass a robots denial")
    if snapshot.get("result", {}).get("isError"):
        raise ValueError("Tool returned an error")
    text = "\n\n".join(c["text"] for c in snapshot.get("result", {}).get("content", []) if c.get("type") == "text")
    if len(text.strip()) < 250 or any(s in text[:2000].lower() for s in ["verify you are human", "access denied", "just a moment...", "enable javascript and cookies"]):
        raise ValueError("Tool snapshot is too short or contains an access challenge")
    from datetime import datetime
    datetime.fromisoformat(snapshot["fetched_at"].replace("Z", "+00:00"))
    heading = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("# ")), None)
    title = snapshot.get("title") or heading or old.get("title") or text.splitlines()[0]
    sha = digest(text)
    if old.get('text_sha256') == sha and old.get('fetched_at') == snapshot['fetched_at'] and old.get('format') == 'markdown':
        return {'id': entry['id'], 'status': 'unchanged'}
    raw_path = root / f"data/raw/browser/{entry['id']}/{sha}.json"
    save(raw_path, snapshot)
    if old:
        save(root / f"data/history/sources/{entry['id']}/{digest(json.dumps(old, sort_keys=True))[:16]}.json", old)
    source = {"id": entry["id"], "url": entry["url"], "final_url": None,
              "title": title, "text": text, "fetched_at": snapshot["fetched_at"],
              "published_at": None, "date_evidence": None, "format": "markdown",
              "content_type": "text/markdown; browser tool output", "status": "ok", "quality": "browser_text_unreviewed",
              "extraction_method": snapshot["tool_name"], "http_status": None,
              "text_sha256": sha, "body_sha256": sha, "body_bytes": len(text.encode()),
              "raw_path": str(raw_path.relative_to(root)),
              "outbound_links": [{"url": canonical_url(url), "label": label} for label, url in re.findall(r'\[([^\]]*)\]\((https?://[^\s)]+)\)', text)],
              "evidence_level": "browser-retrieved publisher text; claims_not_independently_verified"}
    save(target, source)
    return {"id": source["id"], "title": title, "characters": len(text), "status": "imported"}
