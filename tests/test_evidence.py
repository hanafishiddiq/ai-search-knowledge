from pathlib import Path

import pytest

from ai_search_knowledge.core import digest, save
from ai_search_knowledge.evidence import freeze_source_version, resolve_source_version, evidence_span, validate_evidence


@pytest.fixture
def stored_source(tmp_path):
    url = 'https://example.org/model-card'
    sid = digest(url)[:20]
    text = 'The model supports Indonesian.\nThe evaluation used an H200 GPU.'
    source = {'id': sid, 'url': url, 'title': 'Example model', 'status': 'ok',
              'text': text, 'text_sha256': digest(text), 'fetched_at': '2026-11-01T01:00:00+00:00'}
    save(tmp_path / f'data/sources/{sid}.json', source)
    lines = ['# Example model', '', f'Source ID: {sid}', f'Original URL: {url}',
             'Resolved URL: unknown', 'Retrieved at: 2026-11-01', 'Publication: unknown',
             'Date evidence: none', f'Text SHA-256: {source["text_sha256"]}', 'Extraction: fixture',
             'Publisher claims.', '', '## Source text', ''] + text.splitlines()
    doc = tmp_path / f'knowledge/sources/{sid}-{source["text_sha256"][:16]}.md'
    doc.parent.mkdir(parents=True)
    doc.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    evidence = {'source_id': sid, 'text_sha256': source['text_sha256'], 'start_line': 15, 'end_line': 15}
    return tmp_path, source, evidence


def test_historical_source_evidence_survives_a_new_source_version(stored_source):
    root, old, evidence = stored_source
    freeze_source_version(root, old)
    newer = {**old, 'text': 'A materially newer source.', 'text_sha256': digest('A materially newer source.'),
             'fetched_at': '2026-11-02T01:00:00+00:00'}
    save(root / f'data/sources/{old["id"]}.json', newer)
    resolved = resolve_source_version(root, old['id'], old['text_sha256'])
    assert resolved['is_current_text_version'] is False
    assert resolved['fetched_at'] == '2026-11-01T01:00:00+00:00'
    assert evidence_span(root, evidence)['text'] == 'The model supports Indonesian.'
    assert validate_evidence(root, evidence) == []


def test_nonexistent_and_corrupted_versions_are_not_admitted(stored_source):
    root, source, evidence = stored_source
    assert resolve_source_version(root, source['id'], '0' * 64) is None
    corrupt = {**source, 'text': 'This does not have the declared hash.'}
    save(root / f'data/sources/{source["id"]}.json', corrupt)
    assert resolve_source_version(root, source['id'], source['text_sha256']) is None
    assert validate_evidence(root, evidence)


def test_evidence_requires_real_text_lines_and_supported_quotes(stored_source):
    root, _, evidence = stored_source
    assert validate_evidence(root, {**evidence, 'start_line': 1, 'end_line': 1})
    assert validate_evidence(root, {**evidence, 'quote': 'runs on a Mac'})
    assert validate_evidence(root, {**evidence, 'quote': 'supports Indonesian'}) == []


def test_evidence_budget_is_explicit_without_losing_the_original_location(stored_source):
    root, _, evidence = stored_source
    result = evidence_span(root, evidence, max_chars=12)
    assert result['text'] == 'The model su'
    assert result['truncated'] is True
    assert result['start_line'] == 15
    assert result['source_url'] == 'https://example.org/model-card'


def test_tampered_rendered_evidence_is_rejected(stored_source):
    root, source, evidence = stored_source
    doc = root / f'knowledge/sources/{source["id"]}-{source["text_sha256"][:16]}.md'
    doc.write_text(doc.read_text().replace('supports Indonesian', 'supports every language'), encoding='utf-8')
    assert 'does not match' in validate_evidence(root, evidence)[0]


def test_numbered_reader_bounds_a_giant_line_and_resumes_without_loss(tmp_path):
    from ai_search_knowledge.evidence import read_document
    path = tmp_path / 'knowledge/example.md'
    path.parent.mkdir()
    line = 'Indonesian ' + 'x' * 45000
    path.write_text(line + '\nnext line\n', encoding='utf-8')
    result = read_document(tmp_path, path, max_chars=1400)
    assert len(result['text']) == 1400 and result['truncated']
    assert result['continuation'] == {'start': 1, 'start_column': 1397}
    second = read_document(tmp_path, path, max_chars=1400, **result['continuation'])
    assert second['text'].startswith('1@1397: ')
    assert second['continuation']['start_column'] > 1397
    with pytest.raises(ValueError):
        read_document(tmp_path, '../outside.md')
