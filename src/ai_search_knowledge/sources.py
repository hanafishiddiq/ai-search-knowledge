from __future__ import annotations

import json
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .core import Fetcher, FetchFailure, archive_config, canonical_url, config, digest, needs_fetch, in_scope, now, read, save
from .extraction import (PARSER_VERSION, extract_document, extract_markdown,
                         explicit_publication_date, extraction_status, sanitize_derived_text)
from .evidence import freeze_source_version


def videos(root: Path) -> list[dict]:
    cfg = archive_config(root, persist=False)
    return sorted((v for p in (root / "data/raw/videos").glob("*.json")
                   if in_scope(v := read(p), cfg)), key=lambda v: datetime.fromisoformat(v["published_at"]), reverse=True)


def build_manifest(root: Path) -> dict:
    archive_config(root)
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
                                     'video_description_sha256': video.get('description_sha256'),
                                     'video_metadata_fetched_at': video.get('fetched_at'),
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
            snapshot = read(root / f"data/sources/{parent['id']}.json") or {}
            linked_now = any(link.get('url') == edge['url'] for link in snapshot.get('outbound_links', []))
            for mention in parent["mentions"]:
                inherited = {**mention, "via_source_id": parent["id"], "source_link_label": edge["label"],
                             'via_source_text_sha256': snapshot.get('text_sha256') if linked_now else edge.get('parent_text_sha256'),
                             'reference_is_current': linked_now and mention.get('reference_is_current', True),
                             'parent_link_status': 'present_in_current_snapshot' if linked_now else 'historical_discovery_only',
                             "original_url": edge["url"], "description_line": None,
                             "role": "reference", "role_reason": "primary artifact explicitly linked from stored source"}
                if inherited not in child["mentions"]:
                    child["mentions"].append(inherited)
    result = {"generated_at": now(), "videos": [v["id"] for v in active], "sources": list(sources.values())}
    from .provenance import retain_manifest
    result = retain_manifest(root, result)
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
        edges.append({"parent_id": parent_id, "url": url, "label": label, "added_at": now(),
                      'parent_text_sha256': snapshot.get('text_sha256')})
        save(root / "data/extra-sources.json", edges)
    build_manifest(root)
    return {"id": digest(url)[:20], "url": url, "status": "queued", "parent_id": parent_id}

def store_source_result(root: Path, result: dict, previous: dict | None = None,
                        *, reprocessing: bool = False) -> bool:
    """Freeze cited versions and retain a good snapshot after a transient fetch failure."""
    path = root / f"data/sources/{result['id']}.json"
    previous = previous if previous is not None else read(path)
    material = bool(previous and any(previous.get(key) != result.get(key)
                                     for key in ('text_sha256', 'quality', 'status', 'content_kind')))
    if material and previous.get('text_sha256') and isinstance(previous.get('text'), str):
        freeze_source_version(root, previous)
    if previous and previous.get('status') == 'ok' and result.get('status') != 'ok' and not reprocessing:
        save(root / f"data/errors/sources/{result['id']}.json", result)
        return False
    if material and previous.get('text_sha256'):
        history_key = digest(json.dumps(previous, sort_keys=True, ensure_ascii=False))[:20]
        save(root / f"data/history/sources/{result['id']}/{history_key}.json", previous)
    save(path, result)
    return True


def reprocess_document(root: Path, source: dict, *, persist: bool = True) -> dict:
    """Re-extract retained raw bytes locally; do not change the retrieval timestamp.

    Local parser corrections may downgrade inadequate legacy text. Old source
    versions and their immutable Markdown evidence files remain available.
    """
    raw_name = source.get('raw_path')
    if not raw_name:
        return {'id': source.get('id'), 'reprocess_status': 'missing_raw', 'status': source.get('status'),
                'reason': 'No retained raw snapshot; a targeted retrieval would be required'}
    raw = (root / raw_name).resolve()
    if not raw.is_relative_to((root / 'data').resolve()):
        raise ValueError('Raw snapshot must stay inside this library data directory')
    if not raw.is_file():
        return {'id': source.get('id'), 'reprocess_status': 'missing_raw', 'status': source.get('status'),
                'reason': 'The retained raw snapshot file is missing'}
    body = raw.read_bytes()
    if source.get('format') == 'markdown':
        receipt = json.loads(body.decode('utf-8'))
        returned = receipt.get('result', {})
        if returned.get('isError'):
            raise ValueError('Stored browser receipt contains a tool error')
        text = '\n\n'.join(item['text'] for item in returned.get('content', []) if item.get('type') == 'text')
        document = extract_markdown(text, source['url'], title=source.get('title'))
    else:
        content_type = source.get('content_type') or {
            '.html': 'text/html', '.pdf': 'application/pdf', '.json': 'application/json',
            '.txt': 'text/plain', '.md': 'text/markdown'}.get(raw.suffix.lower(), '')
        document = extract_document(body, content_type, source.get('final_url') or source['url'])
    result = {**source, **document, 'status': extraction_status(document),
              'text_sha256': digest(document['text']), 'raw_file_sha256': digest(body),
              'fetched_at': source.get('fetched_at'),
              'reprocessed_from': {'text_sha256': source.get('text_sha256'),
                                   'parser_version': source.get('parser_version', 'legacy'), 'raw_path': raw_name}}
    changed = any(source.get(key) != result.get(key) for key in
                  ('text_sha256', 'quality', 'status', 'content_kind', 'parser_version', 'coverage'))
    if persist and changed:
        store_source_result(root, result, source, reprocessing=True)
    return {'id': source['id'], 'reprocess_status': 'updated' if changed else 'unchanged',
            'status': result['status'], 'previous_status': source.get('status'),
            'previous_text_sha256': source.get('text_sha256'), 'text_sha256': result['text_sha256'],
            'content_kind': result.get('content_kind'), 'quality': result['quality'],
            'coverage': result.get('coverage'), 'fetched_at': result.get('fetched_at'),
            'extracted_at': result.get('extracted_at'), 'parser_version': PARSER_VERSION,
            **({'document': result} if not persist else {})}


def reprocess_sources(root: Path, ids: list[str] | None = None, *, persist: bool = True) -> dict:
    """Public local migration helper; caller owns the writer lock and later index step."""
    requested = set(ids) if ids is not None else None
    results = []
    for path in sorted((root / 'data/sources').glob('*.json')):
        if requested is not None and path.stem not in requested:
            continue
        try:
            results.append(reprocess_document(root, read(path), persist=persist))
        except Exception as exc:
            results.append({'id': path.stem, 'reprocess_status': 'error', 'error': str(exc),
                            'error_type': type(exc).__name__})
    if requested is not None:
        seen = {item['id'] for item in results}
        results.extend({'id': sid, 'reprocess_status': 'missing_source'} for sid in sorted(requested - seen))
    counts = {}
    for result in results:
        status = result['reprocess_status']
        counts[status] = counts.get(status, 0) + 1
    return {'parser_version': PARSER_VERSION, 'processed_at': now(), 'persisted': persist,
            'results': counts, 'items': results}


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
                      "status": extraction_status(doc),
                      "evidence_level": "publisher_text; claims_not_independently_verified"}
            suffix = {'pdf': 'pdf', 'html': 'html', 'json': 'json'}.get(doc['format'], 'txt')
            raw_path = root / f"data/raw/pages/{item['id']}/{digest(body)}.{suffix}"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            if not raw_path.exists():
                raw_path.write_bytes(body)
            result["raw_path"] = str(raw_path.relative_to(root))
            store_source_result(root, result, old)
            return result["status"]
        except Exception as exc:
            result = {**base, "status": getattr(exc, "status", "error"), "error": str(exc),
                      "error_type": type(exc).__name__}
            store_source_result(root, result, old)
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
