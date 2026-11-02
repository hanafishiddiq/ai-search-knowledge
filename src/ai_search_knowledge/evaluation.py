"""Diagnostic evaluation from independently annotated retained-source anchors.

No judge model is called. Document hits, literal evidence hits, coordinates and
budgets are measured separately. This cannot score answer faithfulness.
"""
from __future__ import annotations

import json
import statistics
import time
from collections import Counter
from pathlib import Path

from .core import digest, now, read
from .research import retrieve


def _original_span(root: Path, hit: dict) -> str:
    target = (root / hit['path']).resolve()
    if not target.is_relative_to((root / 'knowledge').resolve()):
        raise ValueError('Evidence path is outside knowledge/')
    lines = target.read_text(encoding='utf-8').splitlines()
    parts = []
    for span in hit.get('citation_ranges', []):
        first, last = span['start_line'], span['end_line']
        selected = lines[first - 1:last]
        if not selected or first < 1 or last > len(lines):
            raise ValueError('Invalid citation line range')
        if len(selected) == 1:
            selected[0] = selected[0][span.get('start_column', 0):span.get('end_column', len(selected[0]))]
        else:
            selected[0] = selected[0][span.get('start_column', 0):]
            selected[-1] = selected[-1][:span.get('end_column', len(selected[-1]))]
        parts.append('\n'.join(selected))
    return '\n'.join(parts)


def _slice(rows: list[dict]) -> dict:
    durations = sorted(row['elapsed_seconds'] for row in rows)
    return {'cases': len(rows), 'any_expected_document_at_5': sum(r['any_document_hit'] for r in rows),
            'all_expected_documents_at_5': sum(r['all_documents_hit'] for r in rows),
            'any_expected_anchor_at_5': sum(r['any_anchor_hit'] for r in rows),
            'all_expected_anchors_at_5': sum(r['all_anchors_hit'] for r in rows),
            'median_seconds': statistics.median(durations) if rows else None,
            'p95_seconds': durations[min(len(durations) - 1, int(len(durations) * .95))] if rows else None,
            'excerpt_budget_violations': sum(r['excerpt_budget_violations'] for r in rows),
            'provenance_errors': sum(r['provenance_errors'] for r in rows)}


def evaluate(root: Path, cases_path: Path | str | None = None, modes=None) -> dict:
    path = Path(cases_path or root / 'evaluation/research-cases.json')
    fixture = read(path)
    if not isinstance(fixture, dict) or not isinstance(fixture.get('cases'), list) or not fixture['cases']:
        raise ValueError('Evaluation requires an annotated cases[] fixture')
    cases = fixture['cases']
    problems = []
    for case in cases:
        for evidence in case['evidence']:
            source = read(root / f"data/sources/{evidence['source_id']}.json") or {}
            if source.get('text_sha256') != evidence['text_sha256'] or digest(source.get('text', '')) != evidence['text_sha256']:
                problems.append({'case': case['id'], 'source': evidence['source_id'], 'reason': 'source version changed/missing'})
            elif evidence['quote'] not in source['text']:
                problems.append({'case': case['id'], 'source': evidence['source_id'], 'reason': 'anchor is not literal source text'})
    if problems:
        return {'status': 'fixture_stale', 'problems': problems,
                'notice': 'Re-annotate source versions before interpreting retrieval scores.'}
    output = {'schema_version': 1, 'evaluated_at': now(), 'fixture_sha256': digest(path.read_bytes()),
              'case_count': len(cases), 'known_relevant_sources': len({s for c in cases for s in c['expected_sources']}),
              'scope': fixture.get('annotation_policy', {}), 'modes': {}}
    for mode in modes or ['lexical', 'semantic', 'hybrid']:
        # Record cold initialization separately. Cached in-process queries below
        # retain local model weights; subprocess CLI startup costs are separate.
        started = time.perf_counter()
        warmup = retrieve(root, cases[0]['query'], 5, 'source', 1400, mode=mode)
        warmup_seconds = time.perf_counter() - started
        rows = []
        for case in cases:
            result = retrieve(root, case['query'], 5, 'source', 1400, mode=mode, **case.get('filters', {}))
            hits = result['hits']
            ids = [hit['id'].removeprefix('source:') for hit in hits]
            expected = set(case['expected_sources'])
            anchor_hits = []
            for evidence in case['evidence']:
                target = 'source:' + evidence['source_id']
                # Immutable Markdown wraps original text for line citations;
                # wrapping whitespace must not turn a present anchor into a miss.
                anchor = ' '.join(evidence['quote'].split())
                anchor_hits.append(any(hit['id'] == target and anchor in ' '.join(hit['text'].split()) for hit in hits))
            errors = 0
            for hit in hits:
                try:
                    errors += _original_span(root, hit) != hit['text']
                except (ValueError, KeyError, OSError, IndexError):
                    errors += 1
            rows.append({'id': case['id'], 'language': case['language'], 'category': case['category'],
                         'answerability': case['answerability'], 'actual_mode': result['actual_mode'],
                         'expected_sources': sorted(expected), 'retrieved_sources': ids,
                         'any_document_hit': bool(expected.intersection(ids)),
                         'all_documents_hit': expected <= set(ids),
                         'any_anchor_hit': any(anchor_hits), 'all_anchors_hit': all(anchor_hits),
                         'anchor_hits': sum(anchor_hits), 'anchor_count': len(anchor_hits),
                         'elapsed_seconds': result['elapsed_seconds'],
                         'excerpt_budget_violations': sum(len(hit['text']) > 1400 for hit in hits),
                         'provenance_errors': errors,
                         'serialized_chars': len(json.dumps(result, ensure_ascii=False, separators=(',', ':'))),
                         'required_unknowns': case.get('required_unknowns', [])})
        slices = {}
        for field in ['language', 'category', 'answerability']:
            slices[field] = {value: _slice([r for r in rows if r[field] == value])
                             for value in sorted({r[field] for r in rows})}
        output['modes'][mode] = {'summary': _slice(rows), 'slices': slices,
                                'cold_initialization_seconds': warmup_seconds,
                                'availability': warmup['semantic'],
                                'actual_modes': dict(Counter(r['actual_mode'] for r in rows)), 'cases': rows}
    output['status'] = 'completed'
    output['limits'] = ['Known relevant sources are not exhaustive judgments; this development set is not a held-out accuracy estimate.',
                        'Relevant context for an unsupported question is not evidence of a supported answer or safe abstention.',
                        'Literal anchor hit and exact coordinates do not prove semantic entailment or current suitability.',
                        'No generated recommendation or audiovisual understanding was scored by this runner.']
    return output
