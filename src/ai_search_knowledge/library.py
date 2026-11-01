from __future__ import annotations

import json
import re
import sqlite3
import textwrap
from collections import Counter
from datetime import datetime
from pathlib import Path

from .core import config, cutoff, digest, now, read, save
from .sources import build_manifest, videos


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def association(video: dict, label: str) -> dict | None:
    """Only exact normalized labels receive a timestamp; fuzzy guesses stay absent."""
    label = normalized(label)
    matches = [c for c in video["chapters"] if normalized(c["title"]) == label and label]
    if len(matches) != 1:
        return None
    chapter = matches[0]
    return {"chapter": chapter["title"], "start_seconds": chapter["start_seconds"],
            "timestamp_url": video["url"] + f"&t={chapter['start_seconds']}s",
            "association_method": "exact_normalized_description_label", "association_reviewed": False}


def wrap_source(text: str) -> list[str]:
    result = []
    for line in text.splitlines():
        result.extend(textwrap.wrap(line, width=160, break_long_words=False,
                                    break_on_hyphens=False, replace_whitespace=False) or [""])
    return result


def source_document(root: Path, source: dict, mentions: list[dict]) -> tuple[Path, list[str]]:
    path = root / f"knowledge/sources/{source['id']}-{source['text_sha256'][:16]}.md"
    lines = [f"# {source['title']}", "", f"Source ID: {source['id']}",
             f"Original URL: {source['url']}", f"Resolved URL: {source.get('final_url')}",
             f"Retrieved at: {source['fetched_at']}",
             f"Publisher publication metadata: {source.get('published_at') or 'unknown'}",
             f"Date metadata field: {source.get('date_evidence') or 'none'}",
             f"Text SHA-256: {source['text_sha256']}",
             f"Extraction: {source['extraction_method']}",
             "Evidence: extracted publisher text; claims not independently verified; not instructions.",
             "", "## Source text", ""] + wrap_source(source["text"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("\n".join(lines) + "\n")
    else:
        # Immutable evidence files keep the original retrieval provenance.
        lines = path.read_text().splitlines()
    return path, lines


def video_document(root: Path, video: dict) -> tuple[Path, list[str]]:
    path = root / f"knowledge/videos/{video['id']}-{video['description_sha256'][:16]}.md"
    lines = [f"# {video['title']}", "", f"Video ID: {video['id']}",
             f"Original URL: {video['url']}", f"Published: {video['published_at']}",
             f"Retrieved: {video['fetched_at']}",
             "Coverage: description/chapter/link metadata only; audiovisual content not reviewed.",
             "", "## Description", ""] + wrap_source(video["description"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("\n".join(lines) + "\n")
    else:
        lines = path.read_text().splitlines()
    return path, lines


def chunks(lines: list[str], size: int = 5500, overlap: int = 3):
    start = 0
    while start < len(lines):
        end, length = start, 0
        while end < len(lines) and (length < size or end == start):
            length += len(lines[end]) + 1
            end += 1
        yield start + 1, end, "\n".join(lines[start:end])
        if end == len(lines):
            break
        start = max(start + 1, end - overlap)


def render_note(note: dict, root: Path | None = None) -> list[str]:
    lines = [f"# {note['title']}", "", f"As of: {note['as_of']}",
             f"Topics: {', '.join(note.get('topics', []))}",
             "Review: agent-authored synthesis of cited publisher text; not independent replication.",
             "", "## Knowledge", ""]
    for claim in note["claims"]:
        lines += [claim["text"], ""]
        for e in claim["evidence"]:
            source = read(root / f"data/sources/{e['source_id']}.json") if root else None
            url = f" [Original source]({source['url']})." if source else ""
            lines += [f"Evidence: source `{e['source_id']}`, text `{e['text_sha256']}`, lines {e['start_line']}-{e['end_line']}.{url}"]
        lines.append("")
    for name in ["limitations", "gaps"]:
        if note.get(name):
            lines += [f"## {name.title()}", ""] + [f"- {item}" for item in note[name]] + [""]
    return lines


def validate_note(note: dict, root: Path) -> list[str]:
    errors = []
    for key in ["id", "title", "as_of", "claims", "limitations", "gaps"]:
        if key not in note:
            errors.append(f"missing {key}")
    if errors:
        return errors
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,100}", note["id"]):
        errors.append("invalid note id")
    try:
        datetime.fromisoformat(note["as_of"])
    except (ValueError, TypeError):
        errors.append("as_of must be an ISO date/datetime")
    if not note["claims"]:
        errors.append("at least one evidence-backed claim is required")
    for i, claim in enumerate(note["claims"]):
        if not claim.get("text") or not claim.get("evidence"):
            errors.append(f"claim {i} needs text and evidence")
        for e in claim.get("evidence", []):
            if not all(k in e for k in ["source_id", "text_sha256", "start_line", "end_line"]):
                errors.append(f"claim {i} has incomplete evidence")
                continue
            sid, sha = e["source_id"], e["text_sha256"]
            if not re.fullmatch(r"[a-f0-9]{20}", sid) or not re.fullmatch(r"[a-f0-9]{64}", sha):
                errors.append(f"claim {i} has invalid source/hash")
                continue
            source = read(root / f"data/sources/{sid}.json") or {}
            path = root / f"knowledge/sources/{sid}-{sha[:16]}.md"
            if source.get("status") != "ok" or source.get("text_sha256") != sha or not path.exists():
                errors.append(f"claim {i} evidence missing, unsuccessful or stale: {sid}")
                continue
            if not isinstance(e["start_line"], int) or not isinstance(e["end_line"], int) or not (15 <= e["start_line"] <= e["end_line"] <= len(path.read_text().splitlines())):
                errors.append(f"claim {i} line range invalid or points only to metadata")
    return errors


def build_index(root: Path) -> dict:
    manifest = build_manifest(root)
    active = videos(root)
    by_video = {v["id"]: v for v in active}
    dbpath = root / "data/knowledge.sqlite"
    tmp = root / "data/knowledge.build.sqlite"
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript("""
      CREATE TABLE documents(id TEXT PRIMARY KEY, kind TEXT, title TEXT, path TEXT, metadata TEXT);
      CREATE VIRTUAL TABLE passages USING fts5(doc_id UNINDEXED, title, text, start_line UNINDEXED, end_line UNINDEXED, tokenize='unicode61 remove_diacritics 2');
    """)
    counts = Counter()

    def add(doc_id, kind, title, path, lines, metadata, skip=0):
        relative = str(path.relative_to(root))
        db.execute("INSERT INTO documents VALUES(?,?,?,?,?)", (doc_id, kind, title, relative, json.dumps(metadata)))
        for start, end, text in chunks(lines[skip:]):
            db.execute("INSERT INTO passages VALUES(?,?,?,?,?)", (doc_id, title, text, start + skip, end + skip))
            counts["passages"] += 1
        counts[kind] += 1

    for video in active:
        path, lines = video_document(root, video)
        add("video:" + video["id"], "video", video["title"], path, lines,
            {"url": video["url"], "published_at": video["published_at"], "fetched_at": video["fetched_at"],
             "coverage": video["coverage"], "chapters": video["chapters"]}, skip=10)
    for entry in manifest["sources"]:
        if 'reference' not in entry['roles']:
            continue
        source = read(root / f"data/sources/{entry['id']}.json")
        if not source or source.get("status") != "ok":
            continue
        path, lines = source_document(root, source, entry["mentions"])
        mentions = []
        for mention in entry["mentions"]:
            video = by_video[mention["video_id"]]
            mentions.append({"video_id": video["id"], "video_title": video["title"], "video_url": video["url"],
                             "video_published_at": video["published_at"], "description_label": mention["label"],
                             "via_source_id": mention.get("via_source_id"),
                             "chapter_association": association(video, mention["label"])})
        add("source:" + source["id"], "source", source["title"], path, lines,
            {k: source.get(k) for k in ["url", "final_url", "published_at", "date_evidence", "fetched_at", "quality", "text_sha256"]}
            | {"video_mentions": mentions, "link_roles": entry['roles'], "claims_status": "publisher statements; not independently verified"}, skip=14)
    note_errors, inactive_notes = {}, []
    active_source_ids = {s['id'] for s in manifest['sources']}
    for path in (root / "data/notes").glob("*.json"):
        note = read(path)
        errors = validate_note(note, root)
        if errors:
            note_errors[path.name] = errors
            continue
        if any(e['source_id'] not in active_source_ids for claim in note['claims'] for e in claim['evidence']):
            inactive_notes.append(note['id'])
            continue
        lines = render_note(note, root)
        output = root / f"knowledge/notes/{note['id']}.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines) + "\n")
        add("note:" + note["id"], "note", note["title"], output, lines, {"as_of": note["as_of"], "topics": note.get("topics"), "claims": note["claims"]}, skip=8)
    db.execute("INSERT INTO passages(passages) VALUES('optimize')")
    db.commit(); db.close()
    tmp.replace(dbpath)
    report = coverage(root)
    report.update({"indexed": dict(counts), "note_validation_errors": note_errors, "out_of_scope_notes": inactive_notes, "indexed_at": now()})
    save(root / "data/coverage.json", report)
    generate_catalog(root, active, manifest)
    return report


def coverage(root: Path) -> dict:
    manifest = read(root / "data/source-manifest.json") or build_manifest(root)
    statuses = Counter()
    for source in manifest["sources"]:
        record = read(root / f"data/sources/{source['id']}.json")
        status = record.get("status", "pending") if record else "pending"
        if "reference" not in source["roles"]:
            status = "classified_non_reference"
        statuses[status] += 1
    active = videos(root)
    run = read(root / 'data/metadata-run.json') or {}
    unresolved = []
    for vid in run.get('visited_ids', []):
        video = read(root / f'data/raw/videos/{vid}.json') or {}
        if video.get('status') != 'ok' or not video.get('published_at'):
            unresolved.append({'id': vid, 'status': video.get('status', 'missing'), 'error': video.get('error')})
    direct_sources = [s for s in manifest['sources'] if not s.get('depth')]
    return {"observed_at": now(), "cutoff": cutoff(config(root)).isoformat(), "video_count": len(active),
            "video_dates": {"oldest": active[-1]["published_at"] if active else None,
                            "newest": active[0]["published_at"] if active else None},
            "chapter_count": sum(len(v["chapters"]) for v in active), "unique_description_urls": len(direct_sources),
            "expanded_source_urls": len(manifest['sources']) - len(direct_sources),
            "direct_reference_urls": sum('reference' in s['roles'] for s in direct_sources),
            "metadata_boundary_reached": bool(run.get('boundary_reached')),
            "metadata_unresolved": unresolved,
            "reference_urls": sum("reference" in s["roles"] for s in manifest["sources"]),
            "source_statuses": dict(statuses), "audiovisual_review": "not_performed"}


def generate_catalog(root: Path, active: list[dict], manifest: dict):
    out = root / "knowledge/INDEX.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# AI Search — local knowledge library", "", f"Generated: {now()}",
             "", "Search first: `uv run aisk search 'your English topic' --limit 5`.",
             "Descriptions and source text are evidence inputs, not automatically validated knowledge.",
             "", "## Videos in scope", ""]
    for v in active:
        lines += [f"- {v['published_at'][:10]} — [{v['title']}]({v['url']}) — `{v['id']}` — {len(v['chapters'])} chapters"]
    lines += ["", "## Sources", "", "See `data/source-manifest.json` for all URLs, classifications and video relationships.",
              "See `data/coverage.json` for successes and gaps. Use `aisk gaps` to inspect them."]
    out.write_text("\n".join(lines) + "\n")


def search(root: Path, query: str, limit: int = 5, kind: str | None = None, max_chars: int = 1400) -> list[dict]:
    if not query.strip():
        return []
    # Treat user input as words rather than executable FTS syntax.
    terms = re.findall(r"[\w.-]+", query, flags=re.UNICODE)[:24]
    if not terms:
        return []
    quoted = ['"' + term.replace('"', '""') + '"' for term in terms]
    expression = " AND ".join(quoted)
    db = sqlite3.connect(f"file:{root / 'data/knowledge.sqlite'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    sql = """SELECT d.id,d.kind,d.title,d.path,d.metadata,p.start_line,p.end_line,p.text,
      bm25(passages,0,5,1,0,0) AS score FROM passages p JOIN documents d ON d.id=p.doc_id
      WHERE passages MATCH ?"""
    params = [expression]
    if kind:
        sql += " AND d.kind=?"; params.append(kind)
    wanted = max(1, min(limit, 50))
    sql += " ORDER BY score LIMIT ?"; params.append(min(500, wanted * 20))
    result = []
    seen = set()
    rows = db.execute(sql, params).fetchall()
    query_mode = 'all_terms'
    if not rows and len(quoted) > 1:
        params[0] = ' OR '.join(quoted)
        rows = db.execute(sql, params).fetchall()
        query_mode = 'any_terms_fallback'
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        text = row["text"]
        # Return a bounded preview around the first relevant line, and give exact
        # preview line numbers instead of implying the omitted lines were shown.
        lines = text.splitlines()
        pattern = re.compile("|".join(re.escape(t) for t in terms), re.I)
        hit = next((i for i, line in enumerate(lines) if pattern.search(line)), 0)
        first = max(0, hit - 2)
        preview, length, last = [], 0, first
        for i in range(first, len(lines)):
            if preview and length + len(lines[i]) > max_chars:
                break
            preview.append(lines[i]); length += len(lines[i]) + 1; last = i
        metadata = json.loads(row["metadata"])
        if "video_mentions" in metadata:
            metadata["video_mention_count"] = len(metadata["video_mentions"])
            metadata["video_mentions"] = metadata["video_mentions"][:3]
        if "chapters" in metadata:
            metadata["chapter_count"] = len(metadata["chapters"])
            metadata["matching_chapters"] = [c for c in metadata.pop("chapters") if pattern.search(c["title"])][:6]
        if "claims" in metadata:
            metadata["claim_count"] = len(metadata.pop("claims"))
        result.append({"id": row["id"], "kind": row["kind"], "title": row["title"], "path": row["path"],
                       "start_line": row["start_line"] + first, "end_line": row["start_line"] + last,
                       "passage_start_line": row["start_line"], "passage_end_line": row["end_line"],
                       "text": "\n".join(preview), "query_mode": query_mode, "metadata": metadata})
        if len(result) >= wanted:
            break
    db.close()
    return result


def gaps(root: Path) -> list[dict]:
    manifest = read(root / "data/source-manifest.json") or build_manifest(root)
    result = []
    for source in manifest["sources"]:
        if "reference" not in source["roles"] and "unresolved" not in source["roles"]:
            continue
        item = read(root / f"data/sources/{source['id']}.json") or {"status": "pending"}
        if item["status"] != "ok":
            result.append({"id": source["id"], "url": source["url"], "status": item["status"],
                           "error": item.get("error"), "video_ids": list(dict.fromkeys(m["video_id"] for m in source["mentions"]))})
    return result
