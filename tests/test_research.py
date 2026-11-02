import json
from datetime import datetime, timezone

import pytest

from ai_search_knowledge.core import digest, save
from ai_search_knowledge.research import build_research_index, retrieve, research


@pytest.fixture
def research_library(tmp_path):
    save(tmp_path / 'config.json', {'tabs': ['videos'], 'lookback_months': 6, 'scope_timezone': 'Asia/Jakarta'})
    published = datetime.now(timezone.utc).isoformat()
    url = 'https://example.org/speech';sid = digest(url)[:20]
    text = ('General setup instructions.\n' * 20 +
            'The speech model supports Indonesian.\nThe main model excludes the separate codec.\n'
            'The reported test used an H200, not a Mac compatibility measurement.')
    save(tmp_path / 'data/raw/videos/example.json', {'id': 'example', 'status': 'ok', 'tabs': ['videos'],
         'title': 'Speech model', 'url': 'https://youtube.com/watch?v=example', 'description': 'Speech model ' + url,
         'description_sha256': digest('description'), 'published_at': published, 'fetched_at': published,
         'coverage': 'description only', 'chapters': [],
         'links': [{'url': url, 'label': 'Speech model', 'role': 'reference', 'original_url': url, 'description_line': 1}]})
    save(tmp_path / f'data/sources/{sid}.json', {'id': sid, 'url': url, 'title': 'Speech model', 'text': text,
         'text_sha256': digest(text), 'status': 'ok', 'quality': 'extracted_unreviewed',
         'fetched_at': published, 'extraction_method': 'synthetic fixture'})
    build_research_index(tmp_path)
    return tmp_path, sid


def test_auto_mode_explicitly_reports_missing_semantic_index(research_library):
    root, sid = research_library
    result = retrieve(root, 'Indonesian codec', mode='auto')
    assert result['actual_mode'] == 'lexical'
    assert result['semantic']['status'] == 'unavailable'
    assert result['semantic']['reason'] == 'index_missing'
    assert result['hits'][0]['id'] == 'source:' + sid
    assert 'Indonesian' in result['hits'][0]['text'] and 'codec' in result['hits'][0]['text']


def test_explicit_semantic_mode_does_not_claim_lexical_fallback(research_library):
    root, _ = research_library
    result = retrieve(root, 'Indonesian codec', mode='semantic')
    assert result['actual_mode'] == 'unavailable'
    assert result['hits'] == []


def test_research_packet_has_a_hard_whole_json_budget_and_retains_unknowns(research_library):
    root, _ = research_library
    result = research(root, 'TTS bahasa Indonesia untuk Mac', constraints={'platform': 'Mac'},
                      required=['runs_on', 'license'], mode='lexical', max_chars=3500)
    serialized = json.dumps(result, ensure_ascii=False, separators=(',', ':'))
    assert len(serialized) <= 3500
    assert result['budget']['serialized_chars'] == len(serialized)
    assert result['constraints']['platform'] == 'Mac'
    assert result['candidate_profiles'] == []
    assert 'no recommendation has been automatically verified' in result['answer_state']
    assert any('Mac compatibility' in instruction for instruction in result['instructions'])


def test_date_basis_is_validated_even_when_semantic_is_unavailable(research_library):
    root, _ = research_library
    with pytest.raises(ValueError, match='date_basis'):
        retrieve(root, 'speech model', mode='semantic', date_basis='guessed-release-date')


def test_research_deduplicates_source_identity_without_dangling_citations(research_library):
    from ai_search_knowledge.core import read
    from ai_search_knowledge.knowledge import add_knowledge
    from ai_search_knowledge.evidence import validate_evidence
    root, sid = research_library
    source = read(root / f'data/sources/{sid}.json')
    record = {'id': 'speech-profile', 'title': 'Speech profile', 'as_of': '2026-11-02',
              'entities': [{'id': 'model:speech', 'name': 'Speech model', 'type': 'model_release'}],
              'claims': [], 'limitations': ['Publisher statements only.'], 'gaps': ['Mac support unknown.']}
    for cid, predicate, value, line in [('language', 'supports_language', 'Indonesian', 35),
                                        ('hardware', 'tested_on', 'H200', 37)]:
        record['claims'].append({'id': cid, 'subject': 'model:speech', 'predicate': predicate,
          'value': value, 'value_text': value, 'statement': f'The source reports {value}.',
          'assertion_kind': 'publisher_reported', 'evidence': [{'source_id': sid,
          'text_sha256': source['text_sha256'], 'start_line': line, 'end_line': line}]})
    add_knowledge(root, record)
    for budget in [5000, 12000]:
        packet = research(root, 'Speech model', mode='lexical', required=['supports_language'], max_chars=budget)
        refs = {e['source_ref'] for p in packet['candidate_profiles'] for fact in p['facts'] for e in fact['evidence']}
        assert refs == set(packet['evidence_sources'])
        assert len(refs) <= 1
        for p in packet['candidate_profiles']:
            for fact in p['facts']:
                for e in fact['evidence']:
                    identity = packet['evidence_sources'][e['source_ref']]
                    assert validate_evidence(root, {**identity, **e}) == []
        assert len(json.dumps(packet, ensure_ascii=False, separators=(',', ':'))) <= budget
