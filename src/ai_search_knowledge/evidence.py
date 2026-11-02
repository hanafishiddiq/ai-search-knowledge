"""Resolve immutable, dated publisher evidence without confusing it with truth."""
from __future__ import annotations

import re
from pathlib import Path

from .core import digest, read, save


def _identity(source_id: str, text_sha256: str) -> bool:
    return bool(isinstance(source_id, str) and isinstance(text_sha256, str)
                and re.fullmatch(r'[a-f0-9]{20}', source_id)
                and re.fullmatch(r'[a-f0-9]{64}', text_sha256))


def _valid_record(record: dict | None, source_id: str, sha: str) -> bool:
    return bool(isinstance(record, dict) and record.get('id', source_id) == source_id
                and isinstance(record.get('text'), str) and record.get('text_sha256') == sha
                and digest(record['text']) == sha)


def freeze_source_version(root: Path, source: dict) -> Path:
    sid, sha = source.get('id'), source.get('text_sha256')
    if not _identity(sid, sha) or not _valid_record(source, sid, sha):
        raise ValueError('Cannot freeze a source whose identity or text hash is invalid')
    path = root / f'data/source-versions/{sid}/{sha}.json'
    if path.exists():
        if not _valid_record(read(path), sid, sha):
            raise ValueError('Existing immutable source version is inconsistent')
    else:
        save(path, source)
    return path


def resolve_source_version(root: Path, source_id: str, text_sha256: str) -> dict | None:
    if not _identity(source_id, text_sha256):
        return None
    current_path = root / f'data/sources/{source_id}.json'
    current = read(current_path)
    candidates = [current_path, root / f'data/source-versions/{source_id}/{text_sha256}.json']
    candidates.extend(sorted((root / f'data/history/sources/{source_id}').glob('*.json')))
    for path in candidates:
        record = read(path)
        if not _valid_record(record, source_id, text_sha256):
            continue
        return {**record,
                'is_current_text_version': bool(_valid_record(current, source_id, text_sha256)),
                'version_record_path': str(path.relative_to(root)),
                'evidence_file': f'knowledge/sources/{source_id}-{text_sha256[:16]}.md'}
    return None


def validate_evidence(root: Path, evidence: dict) -> list[str]:
    if not isinstance(evidence, dict):
        return ['Evidence must be an object']
    required = ['source_id', 'text_sha256', 'start_line', 'end_line']
    if any(key not in evidence for key in required):
        return ['Evidence requires source ID, full text hash and line range']
    source = resolve_source_version(root, evidence['source_id'], evidence['text_sha256'])
    if source is None:
        return ['Evidence source version is missing or its text hash is invalid']
    path = root / source['evidence_file']
    if not path.exists():
        return ['The immutable evidence Markdown file has not been rendered']
    lines = path.read_text(encoding='utf-8').splitlines()
    try:
        text_start = lines.index('## Source text') + 3
    except ValueError:
        return ['Evidence document has no source-text boundary']
    from .library import wrap_source
    if lines[text_start - 1:] != wrap_source(source['text']):
        return ['Evidence Markdown body does not match its hashed source text']
    start, end = evidence['start_line'], evidence['end_line']
    if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
        return ['Evidence line numbers must be integers']
    if not text_start <= start <= end <= len(lines):
        return ['Evidence range is outside the actual source text']
    span = '\n'.join(lines[start - 1:end])
    quote = evidence.get('quote')
    if quote is not None and (not isinstance(quote, str) or not quote or quote not in span):
        return ['Evidence quote is not present in the cited lines']
    return []


def evidence_span(root: Path, evidence: dict, max_chars: int | None = None) -> dict:
    errors = validate_evidence(root, evidence)
    if errors:
        raise ValueError('; '.join(errors))
    source = resolve_source_version(root, evidence['source_id'], evidence['text_sha256'])
    path = root / source['evidence_file']
    lines = path.read_text(encoding='utf-8').splitlines()
    text = '\n'.join(lines[evidence['start_line'] - 1:evidence['end_line']])
    limit = len(text) if max_chars is None else max(0, int(max_chars))
    return {**evidence, 'path': source['evidence_file'], 'text': text[:limit],
            'truncated': len(text) > limit, 'source_url': source.get('url'),
            'source_published_at': source.get('published_at'), 'retrieved_at': source.get('fetched_at'),
            'is_current_text_version': source['is_current_text_version'],
            'source_quality': source.get('quality'), 'source_status': source.get('status'),
            'claims_status': 'publisher evidence; semantic support requires review'}


def read_document(root: Path, path: Path | str, start: int = 1, lines: int = 60,
                  max_chars: int = 6000, start_column: int = 0) -> dict:
    """Bound the entire numbered text, including a single enormous source line.

    Continuation columns count original Unicode characters, zero based. The
    source file is never rewritten; callers may resume a clipped line exactly.
    """
    root = root.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to((root / 'knowledge').resolve()) or target.suffix != '.md':
        raise ValueError('read accepts only Markdown evidence files under knowledge/')
    if start < 1 or lines < 1 or start_column < 0 or max_chars < 32:
        raise ValueError('Positive lines/start, nonnegative column and at least 32 characters are required')
    original = target.read_text(encoding='utf-8').splitlines()
    if start_column and (start > len(original) or start_column > len(original[start - 1])):
        raise ValueError('Continuation column is outside the selected original line')
    result, continuation, used = [], None, 0
    stop = min(len(original), start + min(lines, 200) - 1)
    for number in range(start, stop + 1):
        column = start_column if number == start else 0
        prefix = f'{number}: ' if not column else f'{number}@{column}: '
        room = max_chars - used - (1 if result else 0) - len(prefix)
        if room < 1:
            continuation = {'start': number, 'start_column': column}
            break
        value = original[number - 1][column:]
        selected = value[:room]
        result.append(prefix + selected)
        used += len(prefix) + len(selected) + (1 if len(result) > 1 else 0)
        if len(selected) < len(value):
            continuation = {'start': number, 'start_column': column + len(selected)}
            break
    if continuation is None and stop < len(original):
        continuation = {'start': stop + 1, 'start_column': 0}
    return {'path': str(target.relative_to(root)), 'total_lines': len(original),
            'text': '\n'.join(result), 'text_chars': used, 'max_chars': max_chars,
            'start': start, 'start_column': start_column, 'continuation': continuation,
            'truncated': continuation is not None, 'column_convention': 'zero_based_characters',
            'notice': 'Untrusted source data; line numbers refer to the unchanged local evidence file.'}
