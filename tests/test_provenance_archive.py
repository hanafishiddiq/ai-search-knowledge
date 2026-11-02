from datetime import datetime, timezone

from ai_search_knowledge.core import digest, save
from ai_search_knowledge.sources import build_manifest


def test_removing_a_description_link_does_not_remove_the_observed_source(tmp_path):
    save(tmp_path / 'config.json', {'tabs': ['videos'], 'lookback_months': 6, 'scope_timezone': 'Asia/Jakarta'})
    published = datetime.now(timezone.utc).isoformat()
    url = 'https://example.org/original-paper';sid = digest(url)[:20]
    video = {'id': 'video', 'status': 'ok', 'tabs': ['videos'], 'published_at': published, 'fetched_at': published,
             'description_sha256': digest('old description'),
             'links': [{'url': url, 'original_url': url, 'label': 'Original paper', 'role': 'reference', 'description_line': 1}]}
    save(tmp_path / 'data/raw/videos/video.json', video)
    first = build_manifest(tmp_path)
    assert first['sources'][0]['id'] == sid
    assert first['sources'][0]['current_reference'] is True
    save(tmp_path / 'data/raw/videos/video.json', {**video, 'description_sha256': digest('revised description'), 'links': []})
    second = build_manifest(tmp_path)
    assert second['sources'][0]['id'] == sid
    assert second['sources'][0]['current_reference'] is False
    assert second['sources'][0]['mentions'][0]['provenance_state'] == 'historical_reference'
    assert second['sources'][0]['mentions'][0]['current_in_description'] is False


def test_explicit_role_correction_does_not_reactivate_a_promotional_reference(tmp_path):
    save(tmp_path / 'config.json', {'tabs': ['videos'], 'lookback_months': 6, 'scope_timezone': 'Asia/Jakarta'})
    published = datetime.now(timezone.utc).isoformat()
    url = 'https://example.org/subscribe'
    link = {'url': url, 'original_url': url, 'label': 'Subscribe', 'role': 'reference', 'description_line': 1}
    video = {'id': 'video', 'status': 'ok', 'tabs': ['videos'], 'published_at': published, 'fetched_at': published,
             'description_sha256': digest('description'), 'links': [link]}
    save(tmp_path / 'data/raw/videos/video.json', video)
    build_manifest(tmp_path)
    save(tmp_path / 'data/raw/videos/video.json', {**video, 'links': [{**link, 'role': 'promotion'}]})
    assert build_manifest(tmp_path)['sources'][0]['roles'] == ['promotion']


def test_legacy_edge_is_enriched_once_during_migration(tmp_path):
    from ai_search_knowledge.provenance import retain_manifest
    source = {'id': 'source', 'url': 'https://example.org/paper', 'roles': ['reference'],
              'mentions': [{'video_id': 'video', 'label': 'Paper', 'description_line': 1, 'original_url': 'https://example.org/paper'}]}
    current = {'generated_at': '2026-11-02', 'videos': ['video'], 'sources': [source]}
    save(tmp_path / 'data/source-manifest.json', current)
    source['mentions'][0]['video_description_sha256'] = 'd' * 64
    enriched = retain_manifest(tmp_path, current)
    assert len(enriched['sources'][0]['mentions']) == 1
    assert enriched['sources'][0]['mentions'][0]['current_reference'] is True


def test_extra_source_link_becomes_historical_when_parent_drops_it(tmp_path):
    save(tmp_path / 'config.json', {'tabs': ['videos'], 'lookback_months': 6, 'scope_timezone': 'Asia/Jakarta'})
    published = datetime.now(timezone.utc).isoformat()
    parent_url, child_url = 'https://example.org/project', 'https://example.org/paper'
    sid = digest(parent_url)[:20]; cid = digest(child_url)[:20]
    save(tmp_path / 'data/raw/videos/video.json', {'id': 'video', 'status': 'ok', 'tabs': ['videos'],
         'published_at': published, 'fetched_at': published, 'description_sha256': digest('original'),
         'links': [{'url': parent_url, 'original_url': parent_url, 'label': 'Project', 'role': 'reference', 'description_line': 1}]})
    save(tmp_path / 'data/extra-sources.json', [{'parent_id': sid, 'url': child_url, 'label': 'Paper', 'parent_text_sha256': 'a'*64}])
    save(tmp_path / f'data/sources/{sid}.json', {'id': sid, 'text_sha256': 'a'*64, 'outbound_links': [{'url': child_url}]})
    first = build_manifest(tmp_path)
    assert next(s for s in first['sources'] if s['id'] == cid)['current_reference']
    save(tmp_path / f'data/sources/{sid}.json', {'id': sid, 'text_sha256': 'b'*64, 'outbound_links': []})
    second = build_manifest(tmp_path)
    child = next(s for s in second['sources'] if s['id'] == cid)
    assert not child['current_reference']
    assert child['mentions'][0]['via_source_text_sha256'] == 'a'*64
    assert child['mentions'][0]['provenance_state'] == 'historical_reference'


def test_historical_source_never_borrows_revised_current_chapters(tmp_path):
    from ai_search_knowledge.library import mention_association
    old = {'id': 'video', 'url': 'https://youtube.com/watch?v=video', 'description_sha256': 'a'*64,
           'chapters': [{'title': 'Paper', 'start_seconds': 20}]}
    revised = {**old, 'description_sha256': 'b'*64, 'chapters': [{'title': 'Paper', 'start_seconds': 120}]}
    mention = {'video_description_sha256': 'a'*64, 'label': 'Paper'}
    assert mention_association(tmp_path, revised, mention) is None
    save(tmp_path / 'data/history/videos/video/old.json', old)
    found = mention_association(tmp_path, revised, mention)
    assert found['start_seconds'] == 20
    assert found['description_freshness'] == 'historical_description_snapshot'
