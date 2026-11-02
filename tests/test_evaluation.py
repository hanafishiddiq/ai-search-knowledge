from ai_search_knowledge.core import digest, save
from ai_search_knowledge.evaluation import evaluate, _original_span


def test_evaluation_rejects_stale_gold_instead_of_reporting_zero_accuracy(tmp_path):
    case = {'id': 'stale', 'evidence': [{'source_id': 'a'*20, 'text_sha256': 'b'*64, 'quote': 'expected'}]}
    save(tmp_path / 'evaluation/research-cases.json', {'cases': [case]})
    result = evaluate(tmp_path)
    assert result['status'] == 'fixture_stale'
    assert result['problems'][0]['reason'] == 'source version changed/missing'


def test_citation_reconstruction_checks_columns_and_multiple_ranges(tmp_path):
    doc = tmp_path / 'knowledge/evidence.md'
    doc.parent.mkdir()
    doc.write_text('A useful statement.\nAnother detail.\nIgnored image.\nEnding caveat.\n', encoding='utf-8')
    hit = {'path': 'knowledge/evidence.md', 'citation_ranges': [
        {'start_line': 1, 'end_line': 2, 'start_column': 2, 'end_column': 7},
        {'start_line': 4, 'end_line': 4, 'start_column': 0, 'end_column': 6}]}
    assert _original_span(tmp_path, hit) == 'useful statement.\nAnother\nEnding'
