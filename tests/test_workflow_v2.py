"""Integration checks use synthetic sources only; no network or embedding calls."""
import json
import subprocess
import sys
import types
from datetime import datetime, timezone

import pytest

from ai_search_knowledge import cli, workflow
from ai_search_knowledge.core import digest, read, save
from ai_search_knowledge.library import source_document
from ai_search_knowledge.research import build_research_index
from ai_search_knowledge.review import mark_review, review_status


@pytest.fixture
def library(tmp_path):
    save(tmp_path / 'config.json', {'tabs': ['videos'], 'lookback_months': 6,
                                  'scope_timezone': 'Asia/Jakarta'})
    fetched = datetime.now(timezone.utc).isoformat()
    url = 'https://example.org/research'
    sid = digest(url)[:20]
    text = 'Synthetic speech supports Indonesian.\n' + 'X' * 9000 + '\nSeparate runtime limitations remain unknown.'
    source = {'id': sid, 'url': url, 'title': 'Synthetic speech research', 'status': 'ok',
              'quality': 'extracted_unreviewed', 'text': text, 'text_sha256': digest(text),
              'fetched_at': fetched, 'published_at': '2026-09-01', 'extraction_method': 'synthetic fixture'}
    save(tmp_path / f'data/sources/{sid}.json', source)
    save(tmp_path / 'data/raw/videos/example.json', {
        'id': 'example', 'status': 'ok', 'tabs': ['videos'], 'title': 'Synthetic speech',
        'url': 'https://youtube.com/watch?v=example', 'published_at': fetched, 'fetched_at': fetched,
        'description': 'Synthetic speech ' + url, 'description_sha256': digest('synthetic description'),
        'coverage': 'description only', 'chapters': [],
        'links': [{'url': url, 'label': 'Synthetic speech', 'role': 'reference',
                   'original_url': url, 'description_line': 1}]})
    build_research_index(tmp_path)
    return tmp_path, source


def invoke(root, capsys, *arguments):
    cli.main(['--root', str(root), *arguments])
    output = capsys.readouterr().out
    return json.loads(output), output


def test_cli_import_does_not_load_crawler_or_optional_model_runtimes():
    result = subprocess.run([sys.executable, '-c',
        'import sys,json;import ai_search_knowledge.cli;'
        'print(json.dumps([n for n in ("bs4","trafilatura","pypdf","yt_dlp","fastembed") if n in sys.modules]))'],
        capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == []


def test_search_preserves_list_output_and_explicit_mode_returns_envelope(library, capsys):
    root, source = library
    legacy, _ = invoke(root, capsys, 'search', 'Indonesian', '--kind', 'source')
    assert isinstance(legacy, list) and legacy[0]['id'] == 'source:' + source['id']
    explicit, _ = invoke(root, capsys, 'search', 'Indonesian', '--kind', 'source', '--mode', 'lexical')
    assert explicit['actual_mode'] == explicit['requested_mode'] == 'lexical'
    assert explicit['hits'][0]['id'] == legacy[0]['id']


def test_search_cli_passes_repeatable_filters(library, capsys, monkeypatch):
    import ai_search_knowledge.research as research_module
    root, _ = library
    captured = {}
    def retrieve(*args, **kwargs):
        captured.update(kwargs)
        return {'hits': []}
    monkeypatch.setattr(research_module, 'retrieve', retrieve)
    invoke(root, capsys, 'search', 'speech', '--mode', 'hybrid', '--since', '2026-08-01',
           '--until', '2026-09-30', '--date-basis', 'source', '--unknown-dates', 'include',
           '--role', 'reference', '--role', 'artifact', '--quality', 'extracted_unreviewed',
           '--quality', 'browser_text_unreviewed')
    assert captured == {'mode': 'hybrid', 'since': '2026-08-01', 'until': '2026-09-30',
                        'date_basis': 'source', 'unknown_dates': 'include',
                        'roles': ['reference', 'artifact'],
                        'qualities': ['extracted_unreviewed', 'browser_text_unreviewed']}


@pytest.mark.parametrize('use_file', [False, True])
def test_research_cli_preserves_compact_whole_packet_budget(library, capsys, use_file):
    root, _ = library
    constraints = {'platform': 'Mac', 'language': 'Indonesian'}
    argument = json.dumps(constraints)
    if use_file:
        path = root / 'constraints.json'
        save(path, constraints)
        argument = '@' + str(path)
    result, output = invoke(root, capsys, 'research', 'Indonesian speech', '--mode', 'lexical',
                            '--constraints', argument, '--required', 'runs_on', '--required', 'license',
                            '--max-chars', '3000')
    assert len(output.strip()) <= 3000
    assert result['budget']['serialized_chars'] == len(output.strip())
    assert result['constraints'] == constraints
    assert 'no recommendation has been automatically verified' in result['answer_state']


def test_read_cli_resumes_a_huge_original_line_without_overrunning_budget(library, capsys):
    root, source = library
    path, _ = source_document(root, source, [])
    result, _ = invoke(root, capsys, 'read', str(path.relative_to(root)), '--start', '16',
                       '--lines', '1', '--max-chars', '128')
    assert len(result['text']) <= 128
    assert result['continuation']['start'] == 16
    column = result['continuation']['start_column']
    resumed, _ = invoke(root, capsys, 'read', str(path.relative_to(root)), '--start', '16',
                         '--start-column', str(column), '--lines', '1', '--max-chars', '128')
    assert resumed['text'].startswith(f'16@{column}: ')
    assert resumed['continuation']['start_column'] > column


def test_citing_one_passage_keeps_source_in_partial_work_queue(library):
    root, source = library
    pending = workflow.work_queue(root, preview_chars=128)[0]
    assert pending['review_state'] == 'pending' and pending['next_unreviewed_range']['start_line'] == 15
    note = {'id': 'synthetic-note', 'title': 'Synthetic speech note', 'as_of': '2026-11-02',
            'claims': [{'text': 'The source says it supports Indonesian.', 'evidence': [
                {'source_id': source['id'], 'text_sha256': source['text_sha256'],
                 'start_line': 15, 'end_line': 15}]}], 'limitations': [], 'gaps': []}
    path = root / 'note.json'; save(path, note)
    workflow.add_note(root, path)
    task = workflow.work_queue(root, preview_chars=128)[0]
    assert task['review_state'] == 'partial'
    assert task['next_unreviewed_range']['start_line'] == 16
    assert task['preview'].startswith('16: ') and len(task['preview']) <= 128
    assert task['preview_continuation']['start_column'] > 0
    mark_review(root, source['id'], source['text_sha256'], 'complete',
                covered_ranges=[{'start_line': 15, 'end_line': 17}], note='All synthetic text reviewed.')
    assert workflow.work_queue(root) == []


def test_work_queue_stops_preview_before_an_already_reviewed_range(library):
    root, source = library
    mark_review(root, source['id'], source['text_sha256'], 'partial',
                covered_ranges=[{'start_line': 16, 'end_line': 16}])
    item = workflow.work_queue(root)[0]
    assert item['next_unreviewed_range'] == {'start_line': 15, 'end_line': 15}
    assert '16:' not in item['preview']


def test_work_queue_rejects_a_budget_too_small_for_a_numbered_preview(library):
    root, _ = library
    with pytest.raises(ValueError, match='at least 32'):
        workflow.work_queue(root, preview_chars=20)


def snapshot(root, source, text, *, fetched_at='2026-11-02T01:00:00+00:00'):
    path = root / 'snapshot.json'
    save(path, {'id': source['id'], 'url': source['url'], 'title': 'Synthetic snapshot',
                'fetched_at': fetched_at, 'tool_name': 'approved synthetic reader',
                'result': {'content': [{'type': 'text', 'text': text}]}})
    return path


def test_browser_import_sanitizes_derived_text_but_preserves_raw_and_old_evidence(library):
    root, old = library
    text = '# Synthetic research\n' + 'Architecture and benchmark limitations are reported. ' * 12
    text += '\n![Useful diagram alt](data:image/svg+xml;base64,' + 'A' * 3000 + ')'
    result = workflow.import_snapshot(root, snapshot(root, old, text))
    current = read(root / f"data/sources/{old['id']}.json")
    assert result['status'] == 'imported' and current['status'] == 'ok'
    assert 'data:image' not in current['text'] and 'Useful diagram alt' in current['text']
    assert current['coverage']['data_uri_payloads_removed'] == 1
    assert 'data:image' in (root / current['raw_path']).read_text()
    assert (root / f"data/source-versions/{old['id']}/{old['text_sha256']}.json").exists()
    old_path = root / f"knowledge/sources/{old['id']}-{old['text_sha256'][:16]}.md"
    assert old_path.exists() and 'Synthetic speech supports Indonesian.' in old_path.read_text()


def test_inadequate_browser_import_cannot_replace_good_snapshot(library):
    root, old = library
    text = '# Join the waitlist\nBy submitting you accept our Privacy policy.\n'
    text += '![logo](data:image/png;base64,' + 'A' * 3000 + ')'
    result = workflow.import_snapshot(root, snapshot(root, old, text))
    assert result['status'] == 'inadequate_content'
    assert result['previous_good_snapshot_retained']
    assert read(root / f"data/sources/{old['id']}.json")['text_sha256'] == old['text_sha256']
    assert read(root / f"data/errors/sources/{old['id']}.json")['quality'] == 'inadequate_content'


def test_browser_import_rejects_naive_fetch_timestamp(library):
    root, source = library
    text = '# Synthetic research\n' + 'Architecture and benchmark details. ' * 20
    with pytest.raises(ValueError, match='timezone'):
        workflow.import_snapshot(root, snapshot(root, source, text, fetched_at='2026-11-02T01:00:00'))


def test_rebuild_uses_research_index_and_only_refreshes_existing_semantics_without_download(tmp_path, monkeypatch):
    import ai_search_knowledge.research as research_module
    import ai_search_knowledge.semantic as semantic_module
    save(tmp_path / 'config.json', {'semantic': {'enabled': True, 'allow_download': True}})
    monkeypatch.setattr(research_module, 'build_research_index', lambda root: {'indexed': 'research'})
    calls = []
    monkeypatch.setattr(semantic_module, 'build_semantic_index', lambda root, **kw: calls.append(kw) or {'status': 'ok'})
    result = workflow.rebuild_index(tmp_path)
    assert result['indexed'] == 'research' and result['semantic']['status'] == 'not_built'
    assert calls == []
    (tmp_path / 'data/semantic.sqlite').touch()
    result = workflow.rebuild_index(tmp_path)
    assert result['semantic']['status'] == 'ok'
    assert calls[0]['config']['allow_download'] is False


def test_update_uses_research_rebuild_and_records_gap_status(tmp_path, monkeypatch):
    import ai_search_knowledge.core as core_module
    import ai_search_knowledge.sources as sources_module
    calls = []
    monkeypatch.setattr(workflow, 'discover', lambda root: calls.append('discover') or {})
    monkeypatch.setattr(core_module, 'collect_videos', lambda root: calls.append('videos') or {})
    monkeypatch.setattr(sources_module, 'collect_sources', lambda root, limit: calls.append(('sources', limit)) or {})
    monkeypatch.setattr(workflow, 'rebuild_index', lambda root: calls.append('research-index') or {
        'source_statuses': {'ok': 1}, 'reference_urls': 2, 'metadata_unresolved': [], 'metadata_boundary_reached': True})
    result = workflow.update(tmp_path, 7)
    assert calls == ['discover', 'videos', ('sources', 7), 'research-index']
    assert result['status'] == 'completed_with_recorded_gaps'
    assert 'index' in result['steps']


@pytest.mark.parametrize('video_results,source_results,semantic', [
    ({'ok': 1, 'http_error': 1}, {}, {'status': 'not_built'}),
    ({}, {'http_error': 1}, {'status': 'not_built'}),
    ({}, {}, {'status': 'failed', 'reason': 'RuntimeError'}),
    ({}, {}, {'status': 'unavailable', 'reason': 'index_model_mismatch'}),
])
def test_update_reports_current_refresh_gaps_even_with_complete_retained_coverage(
        tmp_path, monkeypatch, video_results, source_results, semantic):
    import ai_search_knowledge.core as core_module
    import ai_search_knowledge.sources as sources_module
    monkeypatch.setattr(workflow, 'discover', lambda root: {})
    monkeypatch.setattr(core_module, 'collect_videos', lambda root: {'results': video_results})
    monkeypatch.setattr(sources_module, 'collect_sources', lambda root, limit: {'results': source_results})
    monkeypatch.setattr(workflow, 'rebuild_index', lambda root: {
        'source_statuses': {'ok': 2}, 'reference_urls': 2, 'metadata_unresolved': [],
        'metadata_boundary_reached': True, 'semantic': semantic})
    result = workflow.update(tmp_path)
    assert result['status'] == 'retained_evidence_with_refresh_gaps'
    assert result['freshness']['state'] == 'refresh_gaps'
    assert any(result['freshness']['current_run_gaps'].values())
    persisted = read(next((tmp_path / 'data/runs').glob('*.json')))
    assert persisted['status'] == result['status'] and persisted['finished_at']


def test_update_successful_retry_is_not_poisoned_by_historical_error_files(tmp_path, monkeypatch):
    import ai_search_knowledge.core as core_module
    import ai_search_knowledge.sources as sources_module
    save(tmp_path / 'data/errors/sources/old-error.json', {'status': 'http_error'})
    monkeypatch.setattr(workflow, 'discover', lambda root: {})
    monkeypatch.setattr(core_module, 'collect_videos', lambda root: {'results': {'ok': 1}})
    monkeypatch.setattr(sources_module, 'collect_sources', lambda root, limit: {'results': {'ok': 2}})
    monkeypatch.setattr(workflow, 'rebuild_index', lambda root: {
        'source_statuses': {'ok': 2}, 'reference_urls': 2, 'metadata_unresolved': [],
        'metadata_boundary_reached': True, 'semantic': {'status': 'not_built'}})
    result = workflow.update(tmp_path)
    assert result['status'] == 'collection_complete'
    assert result['freshness']['state'] == 'no_current_run_refresh_errors'
    assert not any(result['freshness']['current_run_gaps'].values())


def test_discover_leaves_identical_inventory_and_timestamp_untouched(tmp_path, monkeypatch):
    raw = {'id': 'videos', 'channel_id': 'channel', 'channel': 'Synthetic channel',
           'entries': [{'id': 'video', 'title': 'First title', 'url': 'https://youtube.com/watch?v=video'}]}
    class FakeYoutubeDL:
        def __init__(self, options): pass
        def __enter__(self): return self
        def __exit__(self, *exc): pass
        def extract_info(self, url, download=False): return raw
    monkeypatch.setitem(sys.modules, 'yt_dlp', types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    save(tmp_path / 'config.json', {'tabs': ['videos'], 'channel_id': 'channel', 'channel_url': 'https://youtube.com/@example'})
    workflow.discover(tmp_path)
    path = tmp_path / 'data/raw/channel/videos.json'; first = path.read_bytes()
    workflow.discover(tmp_path)
    assert path.read_bytes() == first
    assert not list((tmp_path / 'data/history/channel').glob('*.json'))
    raw['entries'][0]['title'] = 'Changed title'
    workflow.discover(tmp_path)
    assert read(path)['entries'][0]['title'] == 'Changed title'
    assert len(list((tmp_path / 'data/history/channel').glob('*.json'))) == 1


def test_semantic_cli_download_is_opt_in_even_if_saved_config_allows_it(tmp_path, capsys, monkeypatch):
    import ai_search_knowledge.semantic as semantic_module
    save(tmp_path / 'config.json', {'semantic': {'allow_download': True}})
    calls = []
    monkeypatch.setattr(semantic_module, 'build_semantic_index', lambda root, **kw: calls.append(kw['config']) or {'status': 'unavailable'})
    invoke(tmp_path, capsys, 'semantic-index')
    invoke(tmp_path, capsys, 'semantic-index', '--download-model')
    assert [c['allow_download'] for c in calls] == [False, True]


def test_reprocess_cli_dry_run_does_not_index(tmp_path, capsys, monkeypatch):
    import ai_search_knowledge.sources as sources_module
    save(tmp_path / 'config.json', {})
    calls = []
    monkeypatch.setattr(sources_module, 'reprocess_sources', lambda root, ids, persist: calls.append((ids, persist)) or {'results': {}})
    monkeypatch.setattr(workflow, 'rebuild_index', lambda root: pytest.fail('dry run must not index'))
    invoke(tmp_path, capsys, 'reprocess', '--id', 'one', '--id', 'two', '--dry-run')
    assert calls == [(['one', 'two'], False)]


def test_evaluate_cli_routes_modes_and_writes_requested_report(tmp_path, capsys, monkeypatch):
    import ai_search_knowledge.evaluation as evaluation_module
    save(tmp_path / 'config.json', {})
    calls = []
    monkeypatch.setattr(evaluation_module, 'evaluate', lambda root, path, modes: calls.append((path, modes)) or {'cases': 3})
    output = tmp_path / 'report.json'
    result, _ = invoke(tmp_path, capsys, 'evaluate', '--mode', 'lexical', '--mode', 'hybrid', '--output', str(output))
    assert calls[0][1] == ['lexical', 'hybrid']
    assert result == read(output) == {'cases': 3}


def test_knowledge_cli_admission_facts_graph_and_review_status(library, capsys):
    root, source = library
    evidence = {'source_id': source['id'], 'text_sha256': source['text_sha256'],
                'start_line': 15, 'end_line': 15, 'quote': 'supports Indonesian'}
    record = {'id': 'synthetic-speech', 'title': 'Synthetic speech', 'as_of': '2026-11-02',
              'entities': [{'id': 'model:synthetic', 'type': 'model_release', 'name': 'Synthetic speech'},
                           {'id': 'language:id', 'type': 'language', 'name': 'Indonesian'}],
              'claims': [{'id': 'indonesian', 'subject': 'model:synthetic', 'predicate': 'supports_language',
                          'object_entity': 'language:id', 'value': 'Indonesian', 'value_text': 'Indonesian',
                          'statement': 'The source reports Indonesian support.', 'assertion_kind': 'source_stated',
                          'evidence': [evidence]}], 'limitations': ['Synthetic fixture only.'], 'gaps': []}
    path = root / 'record.json'; save(path, record)
    valid, _ = invoke(root, capsys, 'validate-knowledge', str(path))
    assert valid['valid']
    accepted, _ = invoke(root, capsys, 'add-knowledge', str(path))
    assert accepted['status'] == 'accepted'
    facts, _ = invoke(root, capsys, 'facts', 'Synthetic', '--required', 'license')
    assert facts['technologies'][0]['unknown_requirements'] == ['license']
    relation, _ = invoke(root, capsys, 'graph', 'model:synthetic')
    assert len(relation['edges']) == 1
    status, _ = invoke(root, capsys, 'review-status', '--source', source['id'], '--sha', source['text_sha256'])
    assert status['state'] == 'partial'
    reviewed, _ = invoke(root, capsys, 'review', '--source', source['id'], '--sha', source['text_sha256'],
                         '--state', 'partial', '--note', 'Keep cited coverage.')
    assert reviewed['covered_ranges'] == [{'start_line': 15, 'end_line': 15}]
