from __future__ import annotations

import json
import re
import sqlite3
import textwrap
from collections import Counter
from datetime import datetime
from pathlib import Path

from .core import archive_config, config, cutoff, digest, now, read, save
from .sources import build_manifest, videos
from .retrieval import (filter_document, focus_segments, load_segments, normalized_segments, preview,
                        query_plan, relevance, segment_chunks, segments_payload, fold, weighted_query)


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


def mention_association(root: Path, current_video: dict, mention: dict) -> dict | None:
    """Never attach today's chapters to an older description relationship."""
    sha = mention.get('video_description_sha256')
    if sha and sha == current_video.get('description_sha256'):
        version, freshness = current_video, 'current_description_snapshot'
    else:
        version = next((candidate for path in sorted((root / f"data/history/videos/{current_video['id']}").glob('*.json'))
                        if (candidate := read(path)) and sha and candidate.get('description_sha256') == sha), None)
        freshness = 'historical_description_snapshot'
    if version is None:
        return None
    match = association(version, mention.get('label', ''))
    return {**match, 'description_sha256': sha, 'description_freshness': freshness} if match else None


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
        path.write_text("\n".join(lines) + "\n", encoding='utf-8')
    else:
        # Immutable evidence files keep the original retrieval provenance.
        lines = path.read_text(encoding='utf-8').splitlines()
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
        path.write_text("\n".join(lines) + "\n", encoding='utf-8')
    else:
        lines = path.read_text(encoding='utf-8').splitlines()
    return path, lines


def chunks(lines: list[str], size: int = 5500, overlap: int = 3):
    # Compatibility wrapper; the index additionally persists exact column spans.
    segments, _ = normalized_segments(lines, fragment_chars=min(1000, size))
    for selected in segment_chunks(segments, size=size, overlap=overlap):
        yield selected[0]['line'], selected[-1]['line'], '\n'.join(s['text'] for s in selected)


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


def _resolve_version(root: Path, source_id: str, text_sha256: str, source_resolver=None):
    if source_resolver is None:
        try:
            from .evidence import resolve_source_version
            source_resolver = resolve_source_version
        except ImportError:
            # Older installations without the version ledger retain current-only
            # validation. Never resolve an arbitrary hash by guessing a filename.
            current = read(root / f'data/sources/{source_id}.json') or {}
            return ({**current, 'is_current_text_version': True} if current.get('text_sha256') == text_sha256 else None)
    return source_resolver(root, source_id, text_sha256)


def validate_note(note: dict, root: Path, source_resolver=None) -> list[str]:
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
            source = _resolve_version(root, sid, sha, source_resolver) or {}
            path = root / f"knowledge/sources/{sid}-{sha[:16]}.md"
            if source.get("status") != "ok" or source.get("text_sha256") != sha or digest(source.get('text', '')) != sha or not path.exists():
                errors.append(f"claim {i} evidence missing, unsuccessful or stale: {sid}")
                continue
            lines = path.read_text(encoding='utf-8').splitlines()
            marker = next((i for i, line in enumerate(lines) if line == '## Source text'), None)
            body_start = marker + 2 if marker is not None else None
            if body_start is None or lines[body_start:] != wrap_source(source['text']):
                errors.append(f'claim {i} rendered evidence differs from stored source version: {sid}')
                continue
            if not isinstance(e["start_line"], int) or not isinstance(e["end_line"], int) or not (body_start + 1 <= e["start_line"] <= e["end_line"] <= len(lines)):
                errors.append(f"claim {i} line range invalid or points only to metadata")
                continue
            quote = e.get('quote')
            if quote is not None and (not isinstance(quote, str) or not quote or quote not in '\n'.join(lines[e['start_line'] - 1:e['end_line']])):
                errors.append(f'claim {i} quote is not present in the cited historical/source lines')
    return errors


def build_index(root: Path, *, extra_documents=None, note_validator=None, index_hooks=None) -> dict:
    manifest = build_manifest(root)
    active = videos(root)
    by_video = {v["id"]: v for v in active}
    dbpath = root / "data/knowledge.sqlite"
    dbpath.parent.mkdir(parents=True, exist_ok=True)
    tmp = root / "data/knowledge.build.sqlite"
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript("""
      CREATE TABLE documents(id TEXT PRIMARY KEY, kind TEXT, title TEXT, path TEXT, metadata TEXT);
      CREATE VIRTUAL TABLE passages USING fts5(doc_id UNINDEXED, title, text, start_line UNINDEXED, end_line UNINDEXED, tokenize='unicode61 remove_diacritics 2');
      CREATE TABLE passage_details(passage_rowid INTEGER PRIMARY KEY, segments TEXT NOT NULL, normalization TEXT NOT NULL);
    """)
    counts = Counter()

    def add(doc_id, kind, title, path, lines, metadata, skip=0):
        relative = str(path.relative_to(root))
        db.execute("INSERT INTO documents VALUES(?,?,?,?,?)", (doc_id, kind, title, relative, json.dumps(metadata)))
        segments, normalization = normalized_segments(lines[skip:], start_line=skip + 1)
        for selected in segment_chunks(segments):
            text = '\n'.join(s['text'] for s in selected)
            cursor = db.execute("INSERT INTO passages VALUES(?,?,?,?,?)", (doc_id, title, text, selected[0]['line'], selected[-1]['line']))
            db.execute('INSERT INTO passage_details VALUES(?,?,?)', (cursor.lastrowid, segments_payload(selected), json.dumps(normalization)))
            counts["passages"] += 1
        counts[kind] += 1

    for video in active:
        path, lines = video_document(root, video)
        add("video:" + video["id"], "video", video["title"], path, lines,
            {"url": video["url"], "published_at": video["published_at"], 'video_published_at': video['published_at'], "fetched_at": video["fetched_at"],
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
                             "provenance_state": mention.get('provenance_state'),
                             "current_in_description": mention.get('current_in_description'),
                             "video_description_sha256": mention.get('video_description_sha256'),
                             "parent_link_status": mention.get('parent_link_status'),
                             "chapter_association": mention_association(root, video, mention)})
        add("source:" + source["id"], "source", source["title"], path, lines,
            {k: source.get(k) for k in ["url", "final_url", "published_at", "date_evidence", "fetched_at", "quality", "content_kind", "text_sha256"]}
            | {'source_published_at': source.get('published_at'), "video_mentions": mentions, "link_roles": entry['roles'],
               'current_reference': entry.get('current_reference'),
               'reference_scope': 'current_snapshot_link' if entry.get('current_reference') else 'historical_observed_link',
               "claims_status": "publisher statements; not independently verified"}, skip=14)
    note_errors, inactive_notes = {}, []
    active_source_ids = {s['id'] for s in manifest['sources']}
    for path in (root / "data/notes").glob("*.json"):
        note = read(path)
        errors = (note_validator or validate_note)(note, root)
        if errors:
            note_errors[path.name] = errors
            continue
        absent_source_ids = sorted({e['source_id'] for claim in note['claims'] for e in claim['evidence']
                                    if e['source_id'] not in active_source_ids})
        if absent_source_ids:
            inactive_notes.append(note['id'])
        lines = render_note(note, root)
        output = root / f"knowledge/notes/{note['id']}.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines) + "\n", encoding='utf-8')
        evidence_versions, source_dates, video_dates = [], [], []
        for claim in note['claims']:
            for evidence in claim['evidence']:
                resolved = _resolve_version(root, evidence['source_id'], evidence['text_sha256']) or {}
                evidence_versions.append({k: resolved.get(k) for k in ['is_current_text_version', 'version_record_path']} |
                                         {'source_id': evidence['source_id'], 'text_sha256': evidence['text_sha256']})
                if resolved.get('published_at'):
                    source_dates.append(resolved['published_at'])
                entry = next((s for s in manifest['sources'] if s['id'] == evidence['source_id']), None)
                if entry:
                    video_dates.extend(by_video[m['video_id']]['published_at'] for m in entry['mentions'])
        add("note:" + note["id"], "note", note["title"], output, lines,
            {"as_of": note["as_of"], "topics": note.get("topics"), "claims": note["claims"],
             'evidence_versions': evidence_versions,
             'historical_evidence': any(v.get('is_current_text_version') is False for v in evidence_versions),
             'source_manifest_status': 'historical_links_retained' if absent_source_ids else 'all_currently_linked',
             'source_ids_not_in_current_manifest': absent_source_ids,
             'source_publication_dates': list(dict.fromkeys(source_dates)),
             'video_publication_dates': list(dict.fromkeys(video_dates))}, skip=8)
    for item in extra_documents or []:
        path = Path(item['path'])
        if not path.is_absolute():
            path = root / path
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('extra document path must be inside the library root')
        lines = item.get('lines')
        if lines is None:
            lines = item['text'].splitlines() if 'text' in item else path.read_text(encoding='utf-8').splitlines()
        add(item['id'], item['kind'], item['title'], path, lines, item.get('metadata', {}), item.get('skip', 0))
    extensions = []
    for hook in index_hooks or []:
        extensions.append(hook(root, db))
    db.execute("INSERT INTO passages(passages) VALUES('optimize')")
    db.commit(); db.close()
    tmp.replace(dbpath)
    report = coverage(root)
    report.update({"indexed": dict(counts), "note_validation_errors": note_errors, "out_of_scope_notes": [],
                   'retained_historical_notes': inactive_notes, 'extensions': extensions, "indexed_at": now()})
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
    effective_config = archive_config(root, persist=False)
    return {"observed_at": now(), "cutoff": cutoff(effective_config).isoformat(), 'archive_mode': 'growing', "video_count": len(active),
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
    out.write_text("\n".join(lines) + "\n", encoding='utf-8')


def search(root: Path, query: str, limit: int = 5, kind: str | None = None, max_chars: int = 1400,
           *, since: str | None = None, until: str | None = None,
           date_basis: str = 'video', unknown_dates: str = 'exclude',
           roles=None, qualities=None, candidate_provider=None) -> list[dict]:
    """Retrieve bounded, source-addressable evidence with explicit filter semantics.

    Optional candidate_provider(root, normalized_query, limit) may return
    {passage_rowid, score} records (score 0..1). It adds candidates, never facts,
    and all candidates still pass metadata filters and source-span rendering.
    """
    if max_chars < 1:
        raise ValueError('max_chars must be positive')
    plan = query_plan(query)
    if not plan['expanded_terms']:
        return []
    # Validate filters even for an empty index; source and video publication
    # dates have separate meanings and are never substituted for each other.
    filter_options = dict(since=since, until=until, date_basis=date_basis,
                          unknown_dates=unknown_dates, roles=roles, qualities=qualities)
    filter_document('source', {}, **filter_options)
    db = sqlite3.connect(f"file:{(root / 'data/knowledge.sqlite').as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        documents = {}
        for doc in db.execute('SELECT id,kind,title,path,metadata FROM documents'):
            if kind and doc['kind'] != kind:
                continue
            metadata = json.loads(doc['metadata'])
            accepted, date_filter = filter_document(doc['kind'], metadata, **filter_options)
            if accepted:
                documents[doc['id']] = (dict(doc), metadata, date_filter)
        if not documents:
            return []
        detailed = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='passage_details'").fetchone() is not None
        fields = 'p.rowid AS passage_rowid,p.doc_id,p.title,p.text,p.start_line,p.end_line'
        join = ' LEFT JOIN passage_details pd ON pd.passage_rowid=p.rowid' if detailed else ''
        fields += ',pd.segments,pd.normalization' if detailed else ',NULL AS segments,NULL AS normalization'
        quoted = lambda xs: ' OR '.join('"' + x.replace('"', '""') + '"' for x in xs)
        # FTS provides document occurrence counts without loading full source
        # bodies. Repeated passages in a long README count as one document.
        eligible = list(documents)
        marks = ','.join('?' for _ in eligible)
        corpus_size = len(eligible)
        groups = [(term, [term]) for term in plan['terms']]
        groups += [(alias['name'], alias['terms']) for alias in plan['aliases']]
        frequencies = {name: db.execute('SELECT count(DISTINCT doc_id) FROM passages WHERE passages MATCH ? '
                                        f'AND doc_id IN ({marks})',
                                        [quoted(terms), *eligible]).fetchone()[0] for name, terms in groups}
        plan = weighted_query(plan, corpus_size, frequencies)
        wanted = max(1, min(int(limit), 50))
        candidate_limit = min(3000, max(200, wanted * 60))
        rows = db.execute(f"SELECT {fields},bm25(passages,0,2,1,0,0) AS bm25_score FROM passages p{join} "
                          f"WHERE passages MATCH ? AND p.doc_id IN ({marks}) ORDER BY bm25_score LIMIT ?",
                          [quoted(plan['expanded_terms']), *eligible, candidate_limit]).fetchall()
        lexical_rowids = {row['passage_rowid'] for row in rows}
        candidate_priors, candidate_spans, candidate_metadata = {}, {}, {}
        if candidate_provider is not None:
            for extra in candidate_provider(root, plan['normalized'], candidate_limit) or []:
                rowid = int(extra['passage_rowid'])
                prior = max(0.0, min(float(extra.get('score', 0)), 1.0))
                if prior >= candidate_priors.get(rowid, -1):
                    candidate_priors[rowid] = prior
                    candidate_spans[rowid] = extra.get('source_segments') or extra.get('citation_ranges')
                    candidate_metadata[rowid] = {key: extra[key] for key in ['retrieval_mode', 'model_key', 'semantic_rank', 'semantic_cosine'] if key in extra}
            known = {row['passage_rowid'] for row in rows}
            missing = [rowid for rowid in candidate_priors if rowid not in known]
            if missing:
                more = db.execute(f"SELECT {fields},0.0 AS bm25_score FROM passages p{join} WHERE p.rowid IN ({','.join('?' for _ in missing)})", missing).fetchall()
                rows = [*rows, *(row for row in more if row['doc_id'] in documents)]
        candidates = []
        titles = {doc_id: fold(value[0]['title']) for doc_id, value in documents.items()}
        for row in rows:
            doc, metadata, date_filter = documents[row['doc_id']]
            segments, compatibility_cleaning = None, {}
            body = row['text']
            if not row['segments']:
                segments, compatibility_cleaning = load_segments(body, None, row['start_line'])
                if not segments:
                    continue
                body = '\n'.join(s['text'] for s in segments)
            lexical_score, match = relevance(fold(body), titles[doc['id']], plan, folded=True)
            # Candidate priors are explicit optional signals, not source evidence.
            prior = candidate_priors.get(row['passage_rowid'], 0)
            score = lexical_score + prior * 4
            candidates.append((score, -float(row['bm25_score']), row, doc, metadata, date_filter,
                               segments, match, compatibility_cleaning, prior))
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        result, seen = [], set()
        for score, _, row, doc, original_metadata, date_filter, segments, match, cleaning, prior in candidates:
            if doc['id'] in seen:
                continue
            if segments is None:
                segments, cleaning = load_segments(row['text'], row['segments'], row['start_line'])
            focused = focus_segments(segments, candidate_spans.get(row['passage_rowid']))
            if not focused:
                continue
            excerpt = preview(focused, plan, max_chars, doc['path'])
            if not excerpt['text'].strip():
                continue
            # Prefer the actual evidence-window coverage over a title-only hit.
            metadata = dict(original_metadata)
            if 'video_mentions' in metadata:
                metadata['video_mention_count'] = len(metadata['video_mentions'])
                metadata['video_mentions'] = metadata['video_mentions'][:3]
            if 'chapters' in metadata:
                chapters = metadata.pop('chapters')
                metadata['chapter_count'] = len(chapters)
                metadata['matching_chapters'] = [c for c in chapters if relevance(c['title'], '', plan)[0] > 0][:6]
            if 'claims' in metadata:
                metadata['claim_count'] = len(metadata.pop('claims'))
            normalization = json.loads(row['normalization']) if row['normalization'] else cleaning
            result.append({'id': doc['id'], 'kind': doc['kind'], 'title': doc['title'], 'path': doc['path'],
                           **excerpt, 'passage_rowid': row['passage_rowid'],
                           'passage_start_line': row['start_line'], 'passage_end_line': row['end_line'],
                           'query_mode': 'expanded_lexical' if plan['aliases'] else 'lexical_coverage',
                           'query_normalization': {'normalized': plan['normalized'],
                               'aliases': [{'name': a['name'], 'terms': a['terms']} for a in plan['aliases']],
                               'normalization_scope': 'Unicode/case, stopwords and explicit aliases; no general translation'},
                           'normalization': normalization,
                           'date_filter': date_filter,
                           'ranking': {'lexical_coverage_score': score - prior * 4, 'candidate_prior': prior,
                                       'title_only': match['title_only'], 'passage_match': match,
                                       'weighting': plan['weighting']},
                           'candidate_origin': ('lexical_and_external' if row['passage_rowid'] in lexical_rowids else 'external') if row['passage_rowid'] in candidate_priors else 'lexical',
                           'external_candidate': candidate_metadata.get(row['passage_rowid']),
                           'metadata': metadata})
            seen.add(doc['id'])
            if len(result) >= wanted:
                break
        return result
    finally:
        db.close()


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
