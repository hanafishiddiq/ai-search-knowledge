import json
import sqlite3
from pathlib import Path

import pytest

from ai_search_knowledge import library
from ai_search_knowledge.core import digest, read, save
from ai_search_knowledge.retrieval import query_plan, relevance


@pytest.fixture
def make_library(tmp_path, monkeypatch):
    """Exercise the index/search seam without making acquisition/date assumptions."""
    root = tmp_path
    save(root / 'config.json', {'lookback_months': 6, 'scope_timezone': 'Asia/Jakarta', 'tabs': ['videos']})
    active, sources = [], []
    monkeypatch.setattr(library, 'videos', lambda _: active)
    monkeypatch.setattr(library, 'build_manifest', lambda _: {'sources': sources, 'videos': [v['id'] for v in active]})
    monkeypatch.setattr(library, 'coverage', lambda _: {'video_count': len(active)})

    def create(records, *, extra_documents=None, index_hooks=None):
        for i, record in enumerate(records):
            vid = 'video' + str(i)
            published = record.get('video_date', '2026-10-31T12:00:00+00:00')
            active.append({'id': vid, 'title': 'Video ' + record['title'], 'url': f'https://youtube.com/watch?v={vid}',
                           'published_at': published, 'fetched_at': '2026-11-01T00:00:00+00:00',
                           'description': record['title'], 'description_sha256': digest(record['title']),
                           'coverage': 'description only', 'chapters': []})
            url = f'https://example.org/source-{i}'
            sid = digest(url)[:20]
            source = {'id': sid, 'url': url, 'title': record['title'], 'text': record['text'],
                      'text_sha256': digest(record['text']), 'status': 'ok',
                      'fetched_at': '2026-11-01T00:00:00+00:00', 'published_at': record.get('source_date'),
                      'quality': record.get('quality', 'extracted_unreviewed'), 'extraction_method': 'synthetic fixture'}
            save(root / f'data/sources/{sid}.json', source)
            sources.append({'id': sid, 'url': url, 'roles': record.get('roles', ['reference']),
                            'mentions': [{'video_id': vid, 'label': record['title']}]})
        report = library.build_index(root, extra_documents=extra_documents, index_hooks=index_hooks)
        return root, sources, report
    return create


def assert_source_spans(root, result):
    source = (root / result['path']).read_text(encoding='utf-8').splitlines()
    recovered = []
    for span in result['citation_ranges']:
        lines = source[span['start_line'] - 1:span['end_line']]
        if len(lines) == 1:
            recovered.append(lines[0][span['start_column']:span['end_column']])
        else:
            lines[0] = lines[0][span['start_column']:]
            lines[-1] = lines[-1][:span['end_column']]
            recovered.append('\n'.join(lines))
    assert result['text'] == '\n'.join(recovered)


def test_long_embedded_payload_is_not_indexed_or_returned_and_evidence_file_is_unchanged(make_library):
    original = 'Chart evidence: efficiency\n![cost comparison](data:image/svg+xml;base64,' + 'A' * 47000 + ')\nThe actual model uses compact memory.'
    root, entries, _ = make_library([{'title': 'Model research', 'text': original}])
    sid = entries[0]['id']
    saved_source = read(root / f'data/sources/{sid}.json')
    path = root / f"knowledge/sources/{sid}-{saved_source['text_sha256'][:16]}.md"
    before = path.read_bytes()
    result = library.search(root, 'cost comparison', kind='source', max_chars=1400)[0]
    assert len(result['text']) <= 1400
    assert 'base64' not in result['text'] and 'AAAA' not in result['text']
    assert result['normalization']['data_uri_omissions'] == 1
    assert_source_spans(root, result)
    assert path.read_bytes() == before
    assert 'A' * 47000 in path.read_text(encoding='utf-8')
    db = sqlite3.connect(root / 'data/knowledge.sqlite')
    assert db.execute('SELECT max(length(text)) FROM passages').fetchone()[0] <= 5500
    assert db.execute("SELECT count(*) FROM passages WHERE text LIKE '%data:image%'").fetchone()[0] == 0


def test_first_long_line_is_hard_capped_and_partial_columns_are_explicit(make_library):
    # This old-index shape reproduces the original bug too: compatibility must
    # work before an existing owner corpus is rebuilt.
    root, _, _ = make_library([{'title': 'Long line', 'text': 'needle:' + 'x' * 45000}])
    db = sqlite3.connect(root / 'data/knowledge.sqlite')
    db.execute('DROP TABLE passage_details')
    db.execute('DELETE FROM passages')
    db.execute('INSERT INTO passages VALUES(?,?,?,?,?)', ('source:' + digest('https://example.org/source-0')[:20], 'Long line', 'needle:' + 'x' * 45000, 15, 15))
    db.commit(); db.close()
    result = library.search(root, 'needle', kind='source', max_chars=37)[0]
    assert len(result['text']) <= 37
    assert result['partial_line'] and result['truncated']
    assert result['range_kind'] == 'bounding_lines_with_explicit_spans'
    assert result['citation_ranges'][0]['end_column'] <= 37
    assert_source_spans(root, result)


def test_query_covering_preview_skips_earlier_usage_boilerplate(make_library):
    text = 'Audio8 usage\n' + ('from transformers import helper_for_Audio8\n' * 35)
    text += '## Evidence\nAudio8 supports Indonesian synthesis. Its separate codec is excluded from the model-size count.\nReported evaluation details remain conditional.'
    root, _, _ = make_library([{'title': 'Audio8 model card', 'text': text}])
    result = library.search(root, 'Audio8 Indonesian codec', kind='source', max_chars=250)[0]
    assert 'Indonesian' in result['text'] and 'codec' in result['text']
    assert 'transformers' not in result['text']
    assert_source_spans(root, result)


def test_body_evidence_ranks_above_an_unrelated_title_only_hit(make_library):
    root, _, _ = make_library([
        {'title': 'Audio8 Indonesian codec', 'text': 'Sign in\nAn unrelated banner and account controls.'},
        {'title': 'Technical model card', 'text': 'Audio8 supports Indonesian. Its codec is separate from the main model.'},
    ])
    results = library.search(root, 'Audio8 Indonesian codec', kind='source')
    assert results[0]['title'] == 'Technical model card'
    assert results[0]['ranking']['title_only'] is False


def test_rare_technology_name_outweighs_many_generic_query_words(make_library):
    # The invented name is absent from fixtures/evaluation. Many generic body
    # matches used to displace the actual named technology from the shortlist.
    records = [{'title': f'Generic voice platform {i}',
                'text': 'A voice agent can change delivery inside its generated text for expressive speech.'}
               for i in range(12)]
    records.append({'title': 'Zelora TTS documentation',
                    'text': 'Zelora TTS accepts inline expression tags.'})
    root, _, _ = make_library(records)
    results = library.search(root, 'How does Zelora TTS let a voice agent change delivery inside its generated text?',
                             kind='source', limit=3)
    assert results[0]['title'] == 'Zelora TTS documentation'
    assert 'inverse frequency' in results[0]['ranking']['weighting']
    assert_source_spans(root, results[0])


def test_function_words_and_bare_version_integer_do_not_displace_named_evidence(make_library):
    root, _, _ = make_library([
        {'title': 'Unrelated release', 'text': 'Does this let its user have all 3 tools? A change is available.'},
        {'title': 'Quendor control reference', 'text': 'Quendor supports prosody tags for synthesis.'},
    ])
    result = library.search(root, 'Does Quendor 3 let its user change synthesis prosody?', kind='source', limit=1)[0]
    assert result['title'] == 'Quendor control reference'


def test_query_window_scores_rare_constraint_terms_above_repeated_generic_context(make_library):
    generic = 'Voice generation delivers expressive voice generation.\n' * 30
    records = [{'title': f'Generic speech {i}', 'text': generic} for i in range(8)]
    records.append({'title': 'Zelora technical documentation',
                    'text': generic + 'Zelora: the codebook is excluded from the size count.\n'})
    root, _, _ = make_library(records)
    result = library.search(root, 'Zelora voice generation codebook size', kind='source', max_chars=180)[0]
    assert result['title'] == 'Zelora technical documentation'
    assert 'codebook' in result['text'] and 'excluded' in result['text']
    assert_source_spans(root, result)


def test_fast_term_matching_keeps_unicode_and_punctuation_boundaries():
    plan = query_plan('Zelora v3.8 text-to-speech café')
    _, matched = relevance('ZELORA/v3.8: text-to-speech café. NotZelora and v3x8 differ.', '', plan)
    assert set(matched['body_terms']) >= {'zelora', 'v3.8', 'café'}
    assert 'capability:tts' in matched['body_alias_groups']
    _, absent = relevance('NotZelora v3x8 uncafé', '', query_plan('zelora v3.8 café'))
    assert absent['body_terms'] == []


def test_indonesian_aliases_are_explicit_and_retrieve_supported_concepts(make_library):
    root, _, _ = make_library([
        {'title': 'Audio8', 'text': 'A compact text-to-speech model supports Indonesian speech synthesis.'},
        {'title': 'SLEEP', 'text': 'Continual learning and memory consolidation reduce catastrophic forgetting.'},
    ])
    result = library.search(root, 'model suara bahasa Indonesia ukuran kecil', kind='source')[0]
    assert result['title'] == 'Audio8'
    assert result['query_mode'] == 'expanded_lexical'
    assert {a['name'] for a in result['query_normalization']['aliases']} >= {'language:indonesian', 'capability:tts'}
    assert 'no general translation' in result['query_normalization']['normalization_scope']
    assert library.search(root, 'memori jangka panjang belajar tanpa lupa', kind='source')[0]['title'] == 'SLEEP'


def test_date_filters_do_not_confuse_source_and_video_dates_or_guess_unknown(make_library):
    root, _, _ = make_library([
        {'title': 'Older paper discussed recently', 'text': 'Memory research findings.', 'source_date': '2025-02-01', 'video_date': '2026-10-31T12:00:00+00:00'},
        {'title': 'Unknown paper date', 'text': 'Memory research findings.', 'video_date': '2026-10-31T12:00:00+00:00'},
    ])
    by_video = library.search(root, 'memory', kind='source', since='2026-10-01', date_basis='video')
    assert len(by_video) == 2
    assert all(x['date_filter']['basis'] == 'video_publication' for x in by_video)
    assert library.search(root, 'memory', kind='source', since='2026-10-01', date_basis='source') == []
    unknown = library.search(root, 'memory', kind='source', since='2026-10-01', date_basis='source', unknown_dates='include')
    assert [r['title'] for r in unknown] == ['Unknown paper date']
    assert unknown[0]['date_filter']['date_known'] is False
    assert unknown[0]['date_filter']['matched_evidenced_dates'] == []
    assert library.search(root, 'memory', kind='source', until='2025-12-31', date_basis='source')[0]['title'] == 'Older paper discussed recently'


def test_role_quality_filters_and_invalid_dates_are_explicit(make_library):
    root, _, _ = make_library([
        {'title': 'Research', 'text': 'Memory consolidation.', 'quality': 'extracted_unreviewed', 'roles': ['reference']},
        {'title': 'Browser research', 'text': 'Memory consolidation.', 'quality': 'browser_text_unreviewed', 'roles': ['reference', 'promotion']},
    ])
    result = library.search(root, 'memory', kind='source', roles=['promotion'], qualities=['browser_text_unreviewed'])
    assert [r['title'] for r in result] == ['Browser research']
    with pytest.raises(ValueError, match='ISO'):
        library.search(root, 'memory', since='tomorrow')
    with pytest.raises(ValueError, match='must not be after'):
        library.search(root, 'memory', since='2027-01-01', until='2026-01-01')


def test_extra_documents_and_index_hook_share_the_index_seam(make_library, tmp_path):
    path = tmp_path / 'knowledge/typed-model.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('Typed model evidence: memory limits are unknown.\n', encoding='utf-8')
    def hook(root, db):
        db.execute('CREATE TABLE extension_marker(value TEXT)')
        db.execute("INSERT INTO extension_marker VALUES('typed')")
        return {'extension': 'synthetic'}
    root, _, report = make_library([], extra_documents=[{'id': 'technology:model', 'kind': 'knowledge', 'title': 'Typed model',
                                                       'path': path, 'lines': path.read_text().splitlines(), 'metadata': {}}], index_hooks=[hook])
    assert report['extensions'] == [{'extension': 'synthetic'}]
    assert library.search(root, 'typed memory', kind='knowledge')[0]['id'] == 'technology:model'


def test_optional_candidate_provider_still_obeys_metadata_filters(make_library):
    root, _, _ = make_library([
        {'title': 'Relevant supplied candidate', 'text': 'Unusual nomenclature for speech.', 'source_date': '2026-10-01'},
        {'title': 'Too old supplied candidate', 'text': 'Another uncommon term.', 'source_date': '2020-01-01'},
    ])
    db = sqlite3.connect(root / 'data/knowledge.sqlite')
    rowids = [x[0] for x in db.execute("SELECT rowid FROM passages WHERE doc_id LIKE 'source:%'")]
    provider = lambda root, query, limit: [{'passage_rowid': rowid, 'score': 0.9} for rowid in rowids]
    results = library.search(root, 'unmatched-query', kind='source', since='2026-01-01', date_basis='source', candidate_provider=provider)
    assert [r['title'] for r in results] == ['Relevant supplied candidate']
    assert results[0]['ranking']['candidate_prior'] == 0.9


def test_semantic_paraphrase_window_does_not_collapse_to_a_tiny_tail(make_library):
    text = 'A bounded research context about long horizon retention.\n' * 12 + 'End.'
    root, _, _ = make_library([{'title': 'A relevant semantic candidate', 'text': text}])
    db = sqlite3.connect(root / 'data/knowledge.sqlite')
    rowid = db.execute("SELECT rowid FROM passages WHERE doc_id LIKE 'source:%'").fetchone()[0]
    provider = lambda root, query, limit: [{'passage_rowid': rowid, 'score': 0.9}]
    result = library.search(root, 'synonym-only-query', kind='source', max_chars=250, candidate_provider=provider)[0]
    assert 150 < len(result['text']) <= 250
    assert result['candidate_origin'] == 'external'
    assert_source_spans(root, result)
    assert len(result['citation_ranges']) == 1


def test_valid_historical_note_survives_source_change_and_missing_current_manifest(make_library):
    from ai_search_knowledge.evidence import freeze_source_version
    root, sources, _ = make_library([{'title': 'Legacy source', 'text': 'Old memory evidence persists.'}])
    sid = sources[0]['id']
    old = read(root / f'data/sources/{sid}.json')
    freeze_source_version(root, old)
    note = {'id': 'legacy-memory', 'title': 'Legacy memory', 'as_of': '2026-11-01',
            'claims': [{'text': 'Old memory evidence persists.', 'evidence': [{'source_id': sid, 'text_sha256': old['text_sha256'], 'start_line': 15, 'end_line': 15}]}],
            'limitations': [], 'gaps': []}
    save(root / 'data/notes/legacy-memory.json', note)
    changed = {**old, 'text': 'The current source changed.', 'text_sha256': digest('The current source changed.')}
    save(root / f'data/sources/{sid}.json', changed)
    sources.clear()
    assert library.validate_note(note, root) == []
    note['claims'][0]['evidence'][0]['quote'] = 'This invented quote is absent.'
    assert library.validate_note(note, root)
    note['claims'][0]['evidence'][0].pop('quote')
    report = library.build_index(root)
    assert report['retained_historical_notes'] == ['legacy-memory']
    result = library.search(root, 'legacy memory', kind='note')[0]
    assert result['metadata']['historical_evidence'] is True
    assert result['metadata']['source_manifest_status'] == 'historical_links_retained'
