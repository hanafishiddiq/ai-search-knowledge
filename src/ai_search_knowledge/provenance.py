"""Retain observed video/source relationships when descriptions are edited."""
from __future__ import annotations

from pathlib import Path

from .core import digest, read, save


def _key(source_id: str, mention: dict) -> str:
    import json
    fields = {key: mention.get(key) for key in ['video_id', 'video_description_sha256',
              'description_line', 'original_url', 'label', 'via_source_id', 'via_source_text_sha256']}
    return digest(source_id + json.dumps(fields, sort_keys=True, ensure_ascii=False))


def retain_manifest(root: Path, current: dict) -> dict:
    """Merge observed provenance, without labelling removed links as current.

    The caller supplies currently eligible long-form video IDs. Relationships
    outside that eligibility remain in the registry but not the active view.
    """
    cfg = read(root / 'config.json') or {}
    path = root / 'data/source-registry.json'
    registry = read(path) or {'schema_version': 1, 'channel_id': cfg.get('channel_id'), 'sources': {}}
    if registry.get('channel_id') and cfg.get('channel_id') and registry['channel_id'] != cfg['channel_id']:
        raise ValueError('Source registry belongs to another channel')
    old_registry = read(path)
    # Repair registries created by the first migration before hash enrichment
    # was deduplicated. A no-hash legacy copy cannot establish another version.
    relation = ['video_id', 'description_line', 'original_url', 'label', 'via_source_id']
    for stored in registry['sources'].values():
        for oldkey, old in list(stored['mentions'].items()):
            if old.get('video_description_sha256') or old.get('via_source_text_sha256'):
                continue
            enriched = next((item for key, item in stored['mentions'].items() if key != oldkey
                             and (item.get('video_description_sha256') or item.get('via_source_text_sha256'))
                             and all(old.get(field) == item.get(field) for field in relation)), None)
            if enriched is not None:
                if old.get('first_seen_at'):
                    enriched['first_seen_at'] = min(old['first_seen_at'], enriched.get('first_seen_at') or old['first_seen_at'])
                del stored['mentions'][oldkey]
    prior = read(root / 'data/source-manifest.json') or {'sources': []}
    allowed = set(current['videos'])
    # A first migration captures the previous manifest before a rebuild can
    # discard removed URLs. It does not claim a new website observation.
    incoming = [*([] if old_registry else prior.get('sources', [])), *current['sources']]
    for source in incoming:
        stored = registry['sources'].setdefault(source['id'], {'id': source['id'], 'url': source['url'],
                  'depth': source.get('depth', 0), 'roles': source['roles'], 'mentions': {}})
        if stored['url'] != source['url']:
            raise ValueError('Source identity collision in provenance registry')
        for mention in source['mentions']:
            key = _key(source['id'], mention)
            existing = stored['mentions'].get(key, {})
            # Older manifests did not record a description/parent hash. Enrich
            # the same observed relationship once, rather than inventing a
            # second historical edge during the migration.
            if not existing and (mention.get('video_description_sha256') or mention.get('via_source_text_sha256')):
                legacy = next((oldkey for oldkey, old in stored['mentions'].items()
                               if not old.get('video_description_sha256') and not old.get('via_source_text_sha256')
                               and all(old.get(field) == mention.get(field) for field in relation)), None)
                if legacy is not None:
                    existing = stored['mentions'].pop(legacy)
            stored['mentions'][key] = {**mention, 'first_seen_at': existing.get('first_seen_at') or
                                      mention.get('video_metadata_fetched_at') or prior.get('generated_at') or current['generated_at']}
    observed = {}
    for source in current['sources']:
        observed[source['id']] = {_key(source['id'], m) for m in source['mentions'] if m.get('reference_is_current', True)}
        registry['sources'][source['id']]['roles'] = source['roles']
        registry['sources'][source['id']]['depth'] = source.get('depth', 0)
    result = []
    current_by_id = {source['id']: source for source in current['sources']}
    for sid, source in registry['sources'].items():
        mentions = []
        for key, mention in source['mentions'].items():
            if mention['video_id'] not in allowed:
                continue
            is_current = key in observed.get(sid, set())
            mentions.append({**mention, 'current_reference': is_current,
                             'current_in_description': is_current and not mention.get('via_source_id'),
                             'provenance_state': 'current_snapshot_reference' if is_current else 'historical_reference'})
        if not mentions:
            continue
        roles = current_by_id[sid]['roles'] if sid in current_by_id else source['roles']
        result.append({'id': sid, 'url': source['url'], 'depth': source.get('depth', 0),
                       'roles': roles, 'mentions': mentions, 'current_reference': bool(observed.get(sid))})
    if registry != old_registry:
        save(path, registry)
    return {**current, 'sources': result, 'provenance_policy': 'retain_observed_references_with_current_historical_flags',
            'historical_source_count': sum(not entry['current_reference'] for entry in result)}
