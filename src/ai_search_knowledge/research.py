"""Bounded research context for a calling AI, with explicit retrieval modes."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .core import now
from .library import build_index, search
from .knowledge import index_knowledge, knowledge_documents, technology_facts
from .retrieval import filter_document, normalized_segments, preview, query_plan
from .review import review_summary


def build_research_index(root: Path) -> dict:
    result = build_index(root, extra_documents=knowledge_documents(root), index_hooks=[index_knowledge])
    result['review'] = review_summary(root)
    from .knowledge import export_public_knowledge
    result['public_knowledge'] = export_public_knowledge(root)
    from .core import save
    save(root / 'data/coverage.json', result)
    return result


def _lean_metadata(metadata: dict) -> dict:
    result = {key: metadata[key] for key in ['url', 'final_url', 'published_at', 'source_published_at',
              'video_published_at', 'fetched_at', 'as_of', 'quality', 'content_kind', 'text_sha256',
              'historical_evidence', 'source_manifest_status', 'claims_status'] if metadata.get(key) is not None}
    result.update({key: metadata[key] for key in ['current_reference', 'reference_scope'] if key in metadata})
    mentions = metadata.get('video_mentions', [])
    if mentions:
        first = next((m for m in mentions if m.get('provenance_state') == 'current_snapshot_reference'), mentions[0])
        result['video'] = {k: first.get(k) for k in ['video_id', 'video_url', 'video_published_at', 'chapter_association',
                                                   'video_description_sha256', 'provenance_state', 'current_in_description', 'parent_link_status']}
        result['video_mention_count'] = metadata.get('video_mention_count', len(mentions))
    return result


def _lean_hit(hit: dict) -> dict:
    return {key: hit[key] for key in ['id', 'kind', 'title', 'path', 'text', 'start_line', 'end_line',
            'citation_ranges', 'citation_column_convention', 'partial_line', 'truncated', 'range_kind',
            'passage_rowid', 'semantic_score'] if key in hit} | {
            'metadata': _lean_metadata(hit.get('metadata', {})),
            'retrieval': hit.get('retrieval', {'mode': hit.get('retrieval_mode', hit.get('query_mode', 'lexical'))})}


def retrieve(root: Path, query: str, limit: int = 5, kind: str | None = None, max_chars: int = 1400, *,
             mode: str = 'lexical', since: str | None = None, until: str | None = None,
             date_basis: str = 'video', unknown_dates: str = 'exclude', roles=None, qualities=None,
             semantic_backend=None, semantic_config=None) -> dict:
    """Rank fusion adds candidates, never facts or suitability confidence.

    Explicit semantic mode does not silently substitute lexical results. Auto and
    hybrid modes may degrade to lexical, but the returned envelope says so.
    """
    started = time.perf_counter()
    if mode not in {'auto', 'lexical', 'semantic', 'hybrid'}:
        raise ValueError('mode must be auto, lexical, semantic or hybrid')
    if not query.strip() or len(query) > 4000:
        raise ValueError('Research query must contain 1–4000 characters')
    count = max(1, min(int(limit), 30))
    filters = dict(since=since, until=until, date_basis=date_basis, unknown_dates=unknown_dates,
                   roles=roles, qualities=qualities)
    # Validate even when a semantic backend or corpus is unavailable.
    filter_document('source', {}, **filters)
    lexical_count = count if mode == 'lexical' else max(20, count * 4)
    lexical = [] if mode == 'semantic' else search(root, query, lexical_count, kind, max_chars, **filters)
    semantic = {'status': 'not_requested', 'hits': []}
    if mode != 'lexical':
        from .semantic import SemanticConfig, search_semantic
        if semantic_config is None:
            from .core import read
            settings = (read(root / 'config.json') or {}).get('semantic', {})
            config = {'enabled': True, **settings, 'allow_download': False}
        else:
            config = semantic_config
        def accepted(item):
            return (not kind or item['kind'] == kind) and filter_document(item['kind'], item.get('metadata', {}), **filters)[0]
        semantic = search_semantic(root, query, min(100, max(30, count * 8)), config=config,
                                   backend=semantic_backend, predicate=accepted)
    semantic_hits, seen = [], set()
    plan = query_plan(query)
    for item in semantic.get('hits', []):
        doc_id = item.get('doc_id', item['id'])
        if doc_id in seen:
            continue
        seen.add(doc_id)
        segments = item.get('source_segments')
        if segments is None:
            segments, _ = normalized_segments(item['text'].splitlines(), item['start_line'])
        window = preview(segments, plan, max_chars, item['path'])
        semantic_hits.append({**item, **window, 'id': doc_id,
                              'retrieval': {'mode': 'semantic', 'cosine': item['semantic_score'],
                                            'score_meaning': 'ranking similarity, not confidence or compatibility'}})
    active = semantic.get('status') == 'ok'
    if mode == 'semantic':
        chosen = semantic_hits[:count]
        actual = 'semantic' if active else 'unavailable'
    elif not active:
        chosen = lexical[:count]
        actual = 'lexical'
    else:
        # Reciprocal-rank fusion avoids mixing uncalibrated BM25/coverage and
        # cosine values as though either were factual confidence probabilities.
        fused = {}
        for label, stream in [('lexical', lexical), ('semantic', semantic_hits)]:
            for rank, item in enumerate(stream, 1):
                entry = fused.setdefault(item['id'], {'score': 0, 'hit': item, 'ranks': {}})
                entry['score'] += 1 / (60 + rank)
                entry['ranks'][label] = rank
                if label == 'semantic' and entry['hit'].get('ranking', {}).get('title_only'):
                    entry['hit'] = item
        chosen = []
        for item in sorted(fused.values(), key=lambda item: (-item['score'], item['hit']['id']))[:count]:
            chosen.append({**item['hit'], 'retrieval': {'mode': 'hybrid_rrf', 'ranks': item['ranks'],
                           'fusion_score': item['score'], 'score_meaning': 'retrieval rank, not technology suitability'}})
        actual = 'hybrid'
    envelope = {key: value for key, value in semantic.items() if key in ['status', 'reason', 'detail', 'model', 'index_built_at', 'score_note']}
    return {'requested_mode': mode, 'actual_mode': actual, 'semantic': envelope,
            'query_normalization': plan, 'hits': [_lean_hit(hit) for hit in chosen],
            'elapsed_seconds': time.perf_counter() - started,
            'notice': 'Retrieved similarity is not proof; the calling AI must check supporting evidence and unknowns.'}


def research(root: Path, query: str, *, constraints: dict | None = None, required: list[str] | None = None,
             mode: str = 'lexical', max_chars: int = 12000, limit: int = 6, **filters) -> dict:
    """Create one strictly bounded JSON research packet, not a hidden LLM answer."""
    if max_chars < 1000:
        raise ValueError('Research packet budget must be at least 1000 characters')
    constraints = constraints or {}
    if not isinstance(constraints, dict) or len(json.dumps(constraints, ensure_ascii=False)) > 3000:
        raise ValueError('Constraints must be an object within 3000 characters')
    result = retrieve(root, query, limit, 'source', min(1500, max(300, max_chars // (max(1, limit) * 2))), mode=mode, **filters)
    plan = query_plan(query)
    profiles = technology_facts(root, ' '.join(plan['expanded_terms']), required=required or ['access', 'maturity', 'license'], limit=6, **filters)
    candidates, evidence_sources, source_refs = [], {}, {}
    requested = set(required or ['access', 'maturity', 'license'])
    for profile in profiles['technologies'][:4]:
        compact = {key: profile[key] for key in ['id', 'name', 'type', 'as_of', 'unknown_requirements', 'limitations', 'gaps']}
        compact['facts'] = []
        ranked_facts = sorted(profile['facts'], key=lambda fact: (fact['predicate'] not in requested, fact['predicate']))
        compact['omitted_facts'] = max(0, len(ranked_facts) - 6)
        for fact in ranked_facts[:6]:
            value = {key: fact[key] for key in ['claim_id', 'predicate', 'value', 'statement', 'assertion_kind', 'as_of', 'freshness',
                                              'typed_value_binding', 'value_support'] if key in fact}
            value['conditions'] = fact.get('conditions', {})
            value['evidence'] = []
            for evidence in fact['evidence']:
                key = evidence['source_id'], evidence['text_sha256']
                ref = source_refs.setdefault(key, 'e' + str(len(source_refs) + 1))
                evidence_sources[ref] = {field: evidence.get(field) for field in ['source_id', 'text_sha256', 'source_url', 'path',
                                         'retrieved_at', 'source_published_at', 'is_current_text_version']}
                value['evidence'].append({'source_ref': ref, 'start_line': evidence['start_line'], 'end_line': evidence['end_line']})
            compact['facts'].append(value)
        candidates.append(compact)
    packet = {'schema_version': 'aisk.research.v2', 'query': query, 'prepared_at': now(),
              'constraints': constraints, 'retrieval': {k: result[k] for k in ['requested_mode', 'actual_mode', 'semantic']},
              'candidate_profiles': candidates, 'evidence_sources': evidence_sources, 'evidence_passages': result['hits'],
              'answer_state': 'evidence_packet_for_external_AI; no recommendation has been automatically verified',
              'instructions': ['Compare against the stated project constraints; separate evidence from inference.',
                               'Treat absent facts as unknown, and do not infer Mac compatibility from H200 results.',
                               'Cite original passages with version/date/conditions; recheck changing current facts when material.',
                               'State missing evidence and propose a bounded validation before adoption.'],
              'budget': {'max_chars': max_chars, 'serialized_chars': 0, 'truncated': False,
                         'omitted_passages': 0, 'omitted_profile_facts': 0}}
    def size():
        for profile in packet['candidate_profiles']:
            present = {fact['predicate'] for fact in profile['facts']}
            profile['omitted_required_fields'] = [field for field in sorted(requested) if field not in present and field not in profile['unknown_requirements']]
        used = {e['source_ref'] for p in packet['candidate_profiles'] for fact in p['facts'] for e in fact['evidence']}
        packet['evidence_sources'] = {ref: value for ref, value in packet['evidence_sources'].items() if ref in used}
        return len(json.dumps(packet, ensure_ascii=False, separators=(',', ':')))
    # Removing least-prioritized whole evidence items preserves exact quotes and
    # citation spans. It never truncates JSON or silently cuts a factual value.
    while size() + 20 > max_chars:
        packet['budget']['truncated'] = True
        if len(packet['evidence_passages']) > 2:
            packet['evidence_passages'].pop(); packet['budget']['omitted_passages'] += 1
        elif packet['candidate_profiles'] and any(len(p['facts']) > 3 for p in packet['candidate_profiles']):
            last = next(p for p in reversed(packet['candidate_profiles']) if len(p['facts']) > 3)
            last['facts'].pop(); last['omitted_facts'] += 1; packet['budget']['omitted_profile_facts'] += 1
        elif packet['candidate_profiles'] and any(len(p['facts']) > 2 for p in packet['candidate_profiles']):
            last = next(p for p in reversed(packet['candidate_profiles']) if len(p['facts']) > 2)
            last['facts'].pop(); last['omitted_facts'] += 1; packet['budget']['omitted_profile_facts'] += 1
        elif len(packet['candidate_profiles']) > 2:
            packet['budget']['omitted_profile_facts'] += len(packet['candidate_profiles'][-1]['facts'])
            packet['candidate_profiles'].pop()
        elif len(packet['evidence_passages']) > 1:
            packet['evidence_passages'].pop(); packet['budget']['omitted_passages'] += 1
        elif packet['candidate_profiles']:
            last = packet['candidate_profiles'][-1]
            if last['facts']:
                last['facts'].pop(); packet['budget']['omitted_profile_facts'] += 1
            else:
                packet['candidate_profiles'].pop()
        elif packet['instructions']:
            packet['instructions'].pop()
        else:
            raise ValueError('Budget too small for query and constraints; increase it or narrow the request')
    packet['budget']['serialized_chars'] = size()
    for _ in range(3):
        packet['budget']['serialized_chars'] = size()
    assert size() <= max_chars
    return packet
