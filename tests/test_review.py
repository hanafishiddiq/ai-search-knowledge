import pytest

from ai_search_knowledge.core import digest, save
from ai_search_knowledge.review import mark_claims_reviewed, mark_review, review_status


@pytest.fixture
def review_source(tmp_path):
    sid = digest('https://example.org')[:20]
    text = 'The first relevant claim.\nThe second relevant claim.'
    sha = digest(text)
    save(tmp_path / f'data/sources/{sid}.json', {'id': sid, 'status': 'ok', 'text': text, 'text_sha256': sha})
    path = tmp_path / f'knowledge/sources/{sid}-{sha[:16]}.md';path.parent.mkdir(parents=True)
    path.write_text('\n'.join(['header'] * 12 + ['## Source text', ''] + text.splitlines()) + '\n', encoding='utf-8')
    return tmp_path, sid, sha


def test_one_cited_claim_is_partial_review_and_new_versions_are_pending(review_source):
    root, sid, sha = review_source
    mark_claims_reviewed(root, 'example-note', [{'evidence': [{'source_id': sid, 'text_sha256': sha, 'start_line': 15, 'end_line': 15}]}])
    assert review_status(root, sid, sha)['state'] == 'partial'
    assert review_status(root, sid, digest('a new source version'))['state'] == 'pending'


def test_complete_review_requires_full_text_coverage_and_explicit_attestation(review_source):
    root, sid, sha = review_source
    with pytest.raises(ValueError):
        mark_review(root, sid, sha, 'complete', covered_ranges=[{'start_line': 15, 'end_line': 15}], note='Only one topic read.')
    result = mark_review(root, sid, sha, 'complete', covered_ranges=[{'start_line': 15, 'end_line': 16}], note='Both normalized source paragraphs checked.')
    assert result['state'] == 'complete'
    mark_claims_reviewed(root, 'later-note', [{'evidence': [{'source_id': sid, 'text_sha256': sha, 'start_line': 15, 'end_line': 15}]}])
    assert review_status(root, sid, sha)['state'] == 'complete'
