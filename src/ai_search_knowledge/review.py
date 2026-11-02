"""A review ledger separates evidence use from completion of source review."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .core import now, read, save
from .evidence import resolve_source_version, validate_evidence


def review_status(root: Path, source_id: str, text_sha256: str) -> dict:
    ledger = read(root / 'data/review-ledger.json', {'schema_version': 1, 'sources': {}})
    return ledger['sources'].get(f'{source_id}:{text_sha256}', {
        'source_id': source_id, 'text_sha256': text_sha256, 'state': 'pending',
        'covered_ranges': [], 'record_ids': [], 'unresolved': []})


def mark_review(root: Path, source_id: str, text_sha256: str, state: str, *,
                covered_ranges: list[dict] | None = None, unresolved: list[str] | None = None,
                note: str = '', reviewer: str = 'owner-directed agent') -> dict:
    if state not in {'pending', 'partial', 'complete', 'blocked'}:
        raise ValueError('Review state must be pending, partial, complete or blocked')
    source = resolve_source_version(root, source_id, text_sha256)
    if source is None:
        raise ValueError('Review must identify a real source text version')
    ranges = covered_ranges or []
    for item in ranges:
        evidence = {'source_id': source_id, 'text_sha256': text_sha256, **item}
        if errors := validate_evidence(root, evidence):
            raise ValueError('; '.join(errors))
    if state == 'complete':
        if source.get('status') != 'ok' or not note.strip() or not ranges or unresolved:
            raise ValueError('Complete review requires adequate extraction, coverage, an explicit review note and no unresolved items')
        lines = (root / source['evidence_file']).read_text(encoding='utf-8').splitlines()
        start = lines.index('## Source text') + 3
        reviewed = set()
        for item in ranges:
            reviewed.update(range(item['start_line'], item['end_line'] + 1))
        substantive = {i for i in range(start, len(lines) + 1) if lines[i - 1].strip()}
        if not substantive <= reviewed:
            raise ValueError('Complete review must account for every nonempty source-text line; use partial for a topic overview')
    old = review_status(root, source_id, text_sha256)
    result = {**old, 'state': state, 'covered_ranges': ranges, 'unresolved': unresolved or [],
              'note': note, 'reviewer': reviewer, 'reviewed_at': now(),
              'scope': 'reviewer attestation about this source text; not independent scientific verification'}
    ledger = read(root / 'data/review-ledger.json', {'schema_version': 1, 'sources': {}})
    ledger['sources'][f'{source_id}:{text_sha256}'] = result
    save(root / 'data/review-ledger.json', ledger)
    return result


def mark_claims_reviewed(root: Path, record_id: str, claims: list[dict]) -> None:
    grouped = {}
    for claim in claims:
        for evidence in claim.get('evidence', []):
            key = evidence['source_id'], evidence['text_sha256']
            item = {'start_line': evidence['start_line'], 'end_line': evidence['end_line']}
            grouped.setdefault(key, [])
            if item not in grouped[key]:
                grouped[key].append(item)
    ledger = read(root / 'data/review-ledger.json', {'schema_version': 1, 'sources': {}})
    for (sid, sha), ranges in grouped.items():
        old = review_status(root, sid, sha)
        merged = old.get('covered_ranges', [])[:]
        merged.extend(item for item in ranges if item not in merged)
        ledger['sources'][f'{sid}:{sha}'] = {**old, 'state': 'complete' if old['state'] == 'complete' else 'partial',
            'covered_ranges': merged, 'record_ids': list(dict.fromkeys(old.get('record_ids', []) + [record_id])),
            'reviewed_at': now(), 'reviewer': 'knowledge admission',
            'scope': 'cited passages only; adding a claim never marks the whole source complete'}
    save(root / 'data/review-ledger.json', ledger)


def review_summary(root: Path) -> dict:
    manifest = read(root / 'data/source-manifest.json') or {'sources': []}
    counts = Counter()
    for entry in manifest['sources']:
        if 'reference' not in entry['roles']:
            continue
        source = read(root / f"data/sources/{entry['id']}.json") or {}
        if source.get('status') != 'ok':
            counts['extraction_or_access_gap'] += 1
        else:
            counts[review_status(root, source['id'], source['text_sha256'])['state']] += 1
    return {'source_review_states': dict(counts),
            'definition': 'complete requires explicit full-text review; source extraction or one citation is not completion'}
