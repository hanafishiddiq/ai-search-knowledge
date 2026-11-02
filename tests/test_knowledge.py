import copy
import json
import sqlite3
from pathlib import Path

import pytest

from ai_search_knowledge.core import digest, save
from ai_search_knowledge.knowledge import (add_knowledge, validate_knowledge, graph,
                                         technology_facts, value_binding, index_knowledge)


@pytest.fixture
def knowledge_case(tmp_path):
    url = 'https://example.org/speech-card'
    sid = digest(url)[:20]
    text = 'Speech Example supports Indonesian.\nEvaluation used an H200.\nMac compatibility was not tested.'
    source = {'id': sid, 'url': url, 'title': 'Speech Example', 'status': 'ok', 'text': text,
              'text_sha256': digest(text), 'fetched_at': '2026-11-01T01:00:00+00:00'}
    save(tmp_path / f'data/sources/{sid}.json', source)
    path = tmp_path / f'knowledge/sources/{sid}-{source["text_sha256"][:16]}.md'
    path.parent.mkdir(parents=True)
    path.write_text('\n'.join(['# Speech Example', '', 'ID', 'URL', 'Resolved', 'Retrieved', 'Published',
                                'Date evidence', 'Hash', 'Extraction', 'Publisher claims', '', '## Source text', ''] + text.splitlines()) + '\n', encoding='utf-8')
    evidence = {'source_id': sid, 'text_sha256': source['text_sha256'], 'start_line': 15, 'end_line': 15, 'quote': 'supports Indonesian'}
    record = {'id': 'speech-example', 'title': 'Speech Example technology profile', 'as_of': '2026-11-02',
              'entities': [{'id': 'model:speech-example', 'type': 'model_release', 'name': 'Speech Example', 'aliases': ['contoh suara']},
                           {'id': 'language:indonesian', 'type': 'language', 'name': 'Indonesian', 'aliases': ['Bahasa Indonesia']}],
              'claims': [{'id': 'language', 'subject': 'model:speech-example', 'predicate': 'supports_language',
                          'value': 'Indonesian', 'value_text': 'Indonesian', 'object_entity': 'language:indonesian',
                          'statement': 'The source reports Indonesian support.', 'assertion_kind': 'publisher_reported', 'evidence': [evidence]}],
              'limitations': ['Publisher report, not an independent runtime test.'], 'gaps': ['Mac compatibility is unknown.']}
    return tmp_path, record


def test_knowledge_requires_real_support_before_becoming_graph_edges(knowledge_case):
    root, record = knowledge_case
    assert validate_knowledge(record, root) == []
    add_knowledge(root, record)
    result = graph(root, 'model:speech-example')
    assert result['nodes'][0]['id'] == 'model:speech-example'
    assert result['edges'][0]['predicate'] == 'supports_language'
    assert result['edges'][0]['evidence'][0]['source_url'] == 'https://example.org/speech-card'
    assert not any(edge['predicate'] == 'runs_on' for edge in result['edges'])


def test_invalid_facts_do_not_enter_the_graph(knowledge_case):
    root, record = knowledge_case
    record['claims'][0]['value_text'] = 'English'
    assert any('value_text' in error for error in validate_knowledge(record, root))
    with pytest.raises(ValueError):
        add_knowledge(root, record)
    assert graph(root, 'model:speech-example')['nodes'] == []


def test_technology_research_keeps_unknown_fields_instead_of_inventing_compatibility(knowledge_case):
    root, record = knowledge_case
    add_knowledge(root, record)
    result = technology_facts(root, 'contoh suara', required=['supports_language', 'runs_on', 'license'])
    assert result['technologies'][0]['name'] == 'Speech Example'
    assert result['technologies'][0]['unknown_requirements'] == ['runs_on', 'license']
    assert result['technologies'][0]['facts'][0]['assertion_kind'] == 'publisher_reported'


def test_entity_type_collisions_are_not_silently_merged(knowledge_case):
    root, record = knowledge_case
    add_knowledge(root, record)
    changed = {**record, 'id': 'conflicting-profile', 'entities': [dict(e) for e in record['entities']]}
    changed['entities'][0]['type'] = 'organization'
    assert any('conflict' in error for error in validate_knowledge(changed, root))


def test_profiles_do_not_bypass_source_date_filters_or_emit_empty_related_models(knowledge_case):
    root, record = knowledge_case
    record['entities'].append({'id': 'model:related', 'name': 'Related Speech', 'type': 'model_release'})
    add_knowledge(root, record)
    assert technology_facts(root, 'Related')['technologies'] == []
    assert technology_facts(root, 'Speech', since='2026-01-01', date_basis='source')['technologies'] == []
    assert technology_facts(root, 'Speech', since='2026-01-01', date_basis='source', unknown_dates='include')['technologies']


@pytest.mark.parametrize('predicate,value,literal,line', [
    ('supports_language', 'English', 'Indonesian', 15),
    ('runs_on', 'Mac', 'H200', 16),
    ('license', 'Apache-2.0', 'H200', 16),
])
def test_scalar_values_cannot_contradict_their_literal_anchor(knowledge_case, predicate, value, literal, line):
    root, record = knowledge_case
    claim = record['claims'][0]
    claim.update(predicate=predicate, value=value, value_text=literal)
    claim['evidence'][0].update(start_line=line, end_line=line, quote=literal)
    assert any('typed value does not bind' in error for error in validate_knowledge(record, root))
    with pytest.raises(ValueError, match='typed value does not bind'):
        add_knowledge(root, record)


@pytest.mark.parametrize('value,literal,predicate', [
    ('zero_shot_voice_cloning', 'Zero-shot voice cloning', 'capability'),
    ('INDONESIAN', 'Ｉｎｄｏｎｅｓｉａｎ', 'supports_language'),
    ('Apache-2.0', 'Apache License, Version 2.0', 'license'),
    ('MIT', 'MIT License', 'license'),
    (601159424, '601,159,424', 'parameters_main'),
    (170000000, '170M', 'parameters_main'),
    (800000000, '~0.8B', 'parameters_main'),
])
def test_explicit_representation_normalization_binds_without_claiming_entailment(value, literal, predicate):
    binding = value_binding({'value': value, 'value_text': literal, 'predicate': predicate})
    assert binding['status'] == 'literal_bound'
    assert 'relation' in binding['scope']
    if literal == '~0.8B':
        assert binding['approximate_literal'] is True
    assert value_binding({'value': 'Mac', 'value_text': 'machine', 'predicate': 'runs_on'})['status'] == 'unbound'
    assert value_binding({'value': 170000000, 'value_text': '170MB', 'predicate': 'parameters_main'})['status'] == 'unbound'


@pytest.mark.parametrize('value', [True, {'language': 'Indonesian', 'additional_curated_field': True}])
def test_unchecked_structured_values_are_explicitly_curator_interpretation(knowledge_case, value):
    root, record = knowledge_case
    record['claims'][0]['value'] = value
    add_knowledge(root, record)
    claim = technology_facts(root, 'Speech')['technologies'][0]['facts'][0]
    assert claim['typed_value_binding']['status'] == 'curator_interpretation'
    assert claim['value_support'] == 'curator_interpretation'
    assert 'curator interpretation' in claim['semantic_support']
    literal_json = json.dumps(value)
    assert value_binding({'value': value, 'value_text': literal_json})['status'] == 'literal_bound'
    assert value_binding({'value': True, 'value_text': '1'})['status'] == 'curator_interpretation'


def test_stable_identity_unions_aliases_and_facts_before_matching(knowledge_case):
    root, first = knowledge_case
    second = copy.deepcopy(first)
    second.update(id='second-speech-record', title='Second source interpretation')
    second['entities'][0]['aliases'] = ['suara tambahan']
    second['claims'][0].update(id='hardware', predicate='tested_on', value='H200', value_text='H200',
                               statement='Evaluation used H200 hardware.', object_entity=None)
    second['claims'][0]['evidence'][0].update(start_line=16, end_line=16, quote='H200')
    add_knowledge(root, first)
    add_knowledge(root, second)
    result = technology_facts(root, 'suara tambahan', required=['supports_language', 'tested_on'])
    assert result['rejected_records'] == {}
    profile = result['technologies'][0]
    assert {claim['predicate'] for claim in profile['facts']} == {'supports_language', 'tested_on'}
    assert profile['unknown_requirements'] == []
    assert set(profile['aliases']) == {'contoh suara', 'suara tambahan'}
    for alias in ['contoh suara', 'suara tambahan']:
        linked = graph(root, alias)
        assert linked['rejected_records'] == {}
        assert {edge['predicate'] for edge in linked['edges']} == {'supports_language', 'tested_on'}
        assert linked['nodes'][0]['aliases'] == profile['aliases']
    with sqlite3.connect(':memory:') as db:
        assert index_knowledge(root, db)['typed_claims'] == 2
        aliases = json.loads(db.execute('SELECT aliases FROM entities WHERE id=?', (profile['id'],)).fetchone()[0])
        assert aliases == profile['aliases']
    # Reversing the file iteration order must not choose a different declaration.
    path = root / 'data/knowledge/second-speech-record.json'
    path.rename(path.with_name('aaa-second-record.json'))
    reordered = technology_facts(root, 'suara tambahan')['technologies'][0]
    assert reordered['aliases'] == profile['aliases']
    assert {fact['claim_id'] for fact in reordered['facts']} == {fact['claim_id'] for fact in profile['facts']}


def test_public_knowledge_export_excludes_source_text_anchors_and_local_paths(knowledge_case):
    from ai_search_knowledge.knowledge import export_public_knowledge
    from ai_search_knowledge.core import read
    root, record = knowledge_case
    add_knowledge(root, record)
    report = export_public_knowledge(root)
    public = read(root / report['path'])
    claim = public['records'][0]['claims'][0]
    assert claim['statement'] == record['claims'][0]['statement']
    assert 'value_text' not in claim and 'quote' not in claim['evidence'][0]
    assert 'text' not in claim['evidence'][0] and 'path' not in claim['evidence'][0]
    assert claim['evidence'][0]['source_url'] == 'https://example.org/speech-card'


def test_named_technology_outranks_incidental_generic_context(knowledge_case):
    import copy
    root, record = knowledge_case
    add_knowledge(root, record)
    general = copy.deepcopy(record)
    general['id'] = 'general-utility'
    general['entities'][0] = {'id': 'tool:general', 'type': 'tool', 'name': 'General Utility'}
    general['claims'][0]['subject'] = 'tool:general'
    general['claims'][0]['statement'] = ('The source reports Indonesian support. Coding repository production '
                                         'compatibility is not established by this passage.')
    add_knowledge(root, general)
    result = technology_facts(root, 'Speech Example coding repository production', limit=1)
    assert result['technologies'][0]['id'] == 'model:speech-example'


def test_graph_language_target_cannot_disagree_with_supported_scalar(knowledge_case):
    root, record = knowledge_case
    record['entities'][1]['name'] = 'English'
    record['entities'][1]['aliases'] = []
    assert any('object entity contradicts' in e for e in validate_knowledge(record, root))


def test_graph_language_target_requires_a_language_entity(knowledge_case):
    root, record = knowledge_case
    record['entities'][1]['type'] = 'hardware'
    assert any('incompatible type' in e for e in validate_knowledge(record, root))
