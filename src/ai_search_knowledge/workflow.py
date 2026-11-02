from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from filelock import FileLock, Timeout

from .core import config, digest, now, read, save


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
    from yt_dlp import YoutubeDL

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
            # A fresh observation timestamp alone does not make new evidence.
            if old and {k: v for k, v in old.items() if k != 'discovered_at'} == {k: v for k, v in data.items() if k != 'discovered_at'}:
                result[tab] = len(data["entries"])
                continue
            if old:
                save(root / f"data/history/channel/{tab}-{digest(json.dumps(old, sort_keys=True))[:16]}.json", old)
            save(path, data)
            result[tab] = len(data["entries"])
    return result


def rebuild_index(root: Path) -> dict:
    """Index source/notes/curated facts; refresh an opted-in local semantic index."""
    from .research import build_research_index

    result = build_research_index(root)
    if (root / 'data/semantic.sqlite').exists():
        from .semantic import build_semantic_index
        settings = {**(config(root).get('semantic') or {}), 'allow_download': False}
        settings.setdefault('enabled', True)
        try:
            result['semantic'] = build_semantic_index(root, config=settings)
        except Exception as exc:
            result['semantic'] = {'status': 'failed', 'reason': type(exc).__name__, 'detail': str(exc)}
    else:
        result['semantic'] = {'status': 'not_built', 'reason': 'no_existing_semantic_index',
                              'detail': 'Run semantic-index explicitly to opt in; no model was downloaded.'}
    save(root / 'data/coverage.json', result)
    return result


def update(root: Path, source_limit: int = 0) -> dict:
    from .core import collect_videos
    from .sources import collect_sources

    run_id = now().replace(":", "-")
    path = root / f"data/runs/{run_id}.json"
    record = {"started_at": now(), "status": "running", "steps": {}}
    save(path, record)
    try:
        for name, action in [("discover", lambda: discover(root)),
                             ("videos", lambda: collect_videos(root)),
                             ("sources", lambda: collect_sources(root, source_limit)),
                             ("index", lambda: rebuild_index(root))]:
            record["steps"][name] = action()
            save(path, record)
        report = record["steps"]["index"]
        incomplete = report["source_statuses"].get("ok", 0) < report["reference_urls"] or report["metadata_unresolved"] or not report["metadata_boundary_reached"]
        # Retained successful evidence can keep coverage at 100% while the
        # current refresh failed. Report both dimensions; old errors from a
        # different run must not turn a successful retry into a new failure.
        refresh_gaps = {name: {status: count for status, count in record['steps'][name].get('results', {}).items()
                              if status != 'ok' and count}
                        for name in ['videos', 'sources']}
        semantic = report.get('semantic', {})
        refresh_gaps['semantic'] = ({key: semantic[key] for key in ['status', 'reason', 'detail'] if key in semantic}
                                    if semantic.get('status') in {'failed', 'unavailable'} else {})
        has_refresh_gaps = any(refresh_gaps.values())
        record['freshness'] = {'state': 'refresh_gaps' if has_refresh_gaps else 'no_current_run_refresh_errors',
                               'current_run_gaps': refresh_gaps,
                               'scope': 'Current attempted refreshes only; retained evidence coverage does not prove freshness.'}
        if incomplete:
            record['status'] = 'completed_with_recorded_gaps'
        elif has_refresh_gaps:
            record['status'] = 'retained_evidence_with_refresh_gaps'
        else:
            record['status'] = 'collection_complete'
    except BaseException as exc:
        record.update({"status": "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", "error": str(exc)})
        raise
    finally:
        record["finished_at"] = now()
        save(path, record)
    return record


def work_queue(root: Path, limit: int = 3, preview_chars: int = 1800) -> list[dict]:
    from .evidence import read_document
    from .library import source_document
    from .review import review_status
    from .sources import build_manifest

    if preview_chars < 32:
        raise ValueError('Work preview budget must be at least 32 characters')
    preview_chars = min(int(preview_chars), 6000)
    manifest = read(root / "data/source-manifest.json") or build_manifest(root)
    result = []
    for item in manifest["sources"]:
        if 'reference' not in item.get('roles', []):
            continue
        source = read(root / f"data/sources/{item['id']}.json")
        if not source or source.get("status") != "ok":
            continue
        review = review_status(root, source['id'], source['text_sha256'])
        if review['state'] not in {'pending', 'partial'}:
            continue
        path, lines = source_document(root, source, item["mentions"])
        body_start = lines.index('## Source text') + 3
        ranges = sorted(review.get('covered_ranges', []), key=lambda r: r['start_line'])
        start = body_start
        for covered in ranges:
            if covered['start_line'] <= start <= covered['end_line']:
                start = covered['end_line'] + 1
        while start <= len(lines) and not lines[start - 1].strip():
            start += 1
            for covered in ranges:
                if covered['start_line'] <= start <= covered['end_line']:
                    start = covered['end_line'] + 1
        remaining_stop = min([r['start_line'] - 1 for r in ranges if r['start_line'] > start] or [len(lines)])
        if start > len(lines):
            # Cited every line is still not an explicit full review attestation.
            preview = {'text': '', 'continuation': None}
            next_range = None
        else:
            next_range = {'start_line': start, 'end_line': remaining_stop}
            preview = read_document(root, path, start=start, lines=min(50, remaining_stop - start + 1),
                                    max_chars=preview_chars)
        result.append({"source_id": source["id"], "text_sha256": source["text_sha256"], "title": source["title"],
                       "url": source["url"], "source_published_at": source.get("published_at"),
                       "fetched_at": source["fetched_at"], "path": str(path.relative_to(root)),
                       "line_count": len(lines), "video_mentions": item["mentions"][:3],
                       'video_mention_count': len(item['mentions']), 'review_state': review['state'],
                       'covered_ranges': ranges, 'unresolved': review.get('unresolved', []),
                       'next_unreviewed_range': next_range,
                       "primary_link_candidates": [link for link in source.get('outbound_links', []) if any(word in link['label'].lower() for word in ['paper', 'code', 'model card', 'github', 'arxiv', 'license'])][:12],
                       "preview": preview['text'], 'preview_max_chars': preview_chars,
                       'preview_continuation': preview.get('continuation'),
                       "task": "Read relevant source passages. Write original English synthesis with exact evidence line ranges. Preserve publisher attribution, dates, limits and gaps. Validate before adding. A source appearing in a note does not mean all its details were reviewed."})
        if len(result) >= max(1, min(limit, 20)):
            break
    return result


def add_note(root: Path, path: Path) -> dict:
    from .library import validate_note
    from .review import mark_claims_reviewed

    note = read(path)
    errors = validate_note(note, root)
    if errors:
        raise ValueError("; ".join(errors))
    target = root / f"data/notes/{note['id']}.json"
    old = read(target)
    if old:
        save(root / f"data/history/notes/{note['id']}/{digest(json.dumps(old, sort_keys=True))[:16]}.json", old)
    save(target, note)
    mark_claims_reviewed(root, note['id'], note['claims'])
    return {"id": note["id"], "status": "accepted", "validation": "references and line ranges checked; factual interpretation still requires review"}


def import_snapshot(root: Path, path: Path) -> dict:
    """Import text actually returned by an approved browser/reader tool, with provenance."""
    from .extraction import extract_markdown, extraction_status
    from .sources import build_manifest, store_source_result

    snapshot = read(path)
    if not isinstance(snapshot, dict):
        raise ValueError('Snapshot must be a JSON object')
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
    fetched = datetime.fromisoformat(snapshot["fetched_at"].replace("Z", "+00:00"))
    if fetched.tzinfo is None or fetched.utcoffset() is None:
        raise ValueError('Snapshot fetched_at must include an explicit timezone')
    if not isinstance(snapshot.get('tool_name'), str) or not snapshot['tool_name'].strip():
        raise ValueError('Snapshot must identify the browser/reader tool')
    heading = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("# ")), None)
    title = snapshot.get("title") or heading or old.get("title") or text.splitlines()[0]
    document = extract_markdown(text, entry['url'], title=title)
    sha = digest(document['text'])
    status = extraction_status(document)
    if (old.get('text_sha256') == sha and old.get('fetched_at') == snapshot['fetched_at']
            and old.get('format') == 'markdown' and old.get('parser_version') == document['parser_version']
            and old.get('quality') == document['quality'] and old.get('status') == status
            and old.get('browser_tool') == snapshot['tool_name']):
        return {'id': entry['id'], 'status': 'unchanged'}
    receipt_sha = digest(json.dumps(snapshot, sort_keys=True, ensure_ascii=False))
    raw_path = root / f"data/raw/browser/{entry['id']}/{receipt_sha}.json"
    save(raw_path, snapshot)
    source = {"id": entry["id"], "url": entry["url"], "final_url": None,
              **document, "fetched_at": snapshot["fetched_at"],
              "content_type": "text/markdown; browser tool output", "status": status,
              "browser_tool": snapshot['tool_name'], "http_status": None,
              "text_sha256": sha, "body_sha256": digest(text), "body_bytes": len(text.encode()),
              "raw_path": str(raw_path.relative_to(root)),
              "evidence_level": "browser-retrieved publisher text; claims_not_independently_verified"}
    stored = store_source_result(root, source, old or None)
    return {"id": source["id"], "title": title, "characters": len(document['text']),
            "status": 'imported' if stored and status == 'ok' else status,
            'quality': document['quality'], 'stored_as_current': stored,
            'previous_good_snapshot_retained': not stored and old.get('status') == 'ok'}
