"""Dated technology claims with typed, evidence-backed relationships.

This module validates references and literal support, not scientific truth or
general semantic entailment. An external curator must check interpretation.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import deque
from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path

from .core import digest, now, read, save
from .evidence import evidence_span, validate_evidence, resolve_source_version
from .retrieval import filter_document

ENTITY_TYPES = {'model_release', 'project', 'method', 'organization', 'capability',
                'hardware', 'language', 'license', 'benchmark', 'dataset', 'tool'}
PREDICATES = {'supports_language', 'language_count', 'parameters_main', 'parameter_convention',
              'codec', 'license', 'access', 'maturity', 'capability', 'architecture', 'tested_on',
              'runs_on', 'memory_requirement', 'benchmark_result', 'benchmark', 'latency',
              'throughput', 'context_length', 'repository', 'paper', 'announced_at',
              'released_at', 'supersedes', 'developed_by', 'uses_method', 'limitation'}
TECH_TYPES = {'model_release', 'project', 'method', 'tool'}
ID = re.compile(r'[a-z0-9][a-z0-9:._-]{0,140}')


def _raw_records(root: Path):
    for path in sorted((root / 'data/knowledge').glob('*.json')):
        value = read(path)
        if isinstance(value, dict):
            yield path, value


def _compact(text: str) -> str:
    return ' '.join(text.casefold().split())


def _literal_tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', text).casefold()))


def _contains_tokens(haystack: tuple, needle: tuple) -> bool:
    return bool(needle) and any(haystack[i:i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1))


_LICENSE_LITERALS = {
    'apache20': ['Apache License 2.0', 'Apache License, Version 2.0', 'Apache 2.0'],
    'mit': ['MIT', 'MIT License'],
}
_NUMBER_LITERAL = re.compile(
    r'(?<![\w.])(?P<approx>~|≈|about\s+|approximately\s+|approx\.?\s+)?\s*'
    r'(?P<number>[+-]?(?:\d{1,3}(?:[,_ ]\d{3})+|\d+)(?:\.\d+)?(?:e[+-]?\d+)?)'
    r'(?:\s*(?P<scale>thousand|million|billion|[kmb](?![a-z])))?(?![\d.])', re.I)


def value_binding(claim: dict) -> dict:
    """Check representation only; do not infer the predicate's semantic truth.

    Simple values bind to literal tokens/quantities. Arbitrary structured values
    and booleans remain curator interpretation unless their entire JSON literal
    appears verbatim in value_text. No unit compatibility/conversion is guessed.
    """
    value, literal = claim.get('value'), claim.get('value_text', '')
    if not isinstance(literal, str) or not literal.strip():
        return {'status': 'unbound', 'reason': 'A nonempty source literal is required'}
    if isinstance(value, str):
        targets = [_literal_tokens(value)]
        normalized_id = re.sub(r'[^a-z0-9]', '', value.casefold())
        if claim.get('predicate') == 'license':
            targets.extend(_literal_tokens(alias) for alias in _LICENSE_LITERALS.get(normalized_id, []))
        if any(_contains_tokens(_literal_tokens(literal), target) for target in targets):
            return {'status': 'literal_bound', 'normalization': 'Unicode/case/separator tokens and explicit license aliases',
                    'scope': 'typed string representation only; relation, negation and conditions require curator review'}
        return {'status': 'unbound', 'reason': 'Typed string is absent from its declared source literal'}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            expected = Decimal(str(value))
        except InvalidOperation:
            return {'status': 'unbound', 'reason': 'Numeric value is invalid'}
        if not expected.is_finite():
            return {'status': 'unbound', 'reason': 'Numeric value must be finite'}
        literal = unicodedata.normalize('NFKC', literal).replace('−', '-')
        for match in _NUMBER_LITERAL.finditer(literal):
            number = Decimal(re.sub(r'[, _]', '', match['number']))
            scale = (match['scale'] or '').casefold()
            number *= {'k': 1000, 'thousand': 1000, 'm': 1000000, 'million': 1000000,
                       'b': 1000000000, 'billion': 1000000000}.get(scale, 1)
            if number == expected:
                return {'status': 'literal_bound', 'normalization': 'decimal separators and explicit K/M/B research quantity scale',
                        'matched_literal': match[0].strip(), 'approximate_literal': bool(match['approx']),
                        'scope': 'numeric representation only; units, benchmark conditions and relation require curator review'}
        return {'status': 'unbound', 'reason': 'Typed numeric value does not match a literal quantity'}
    try:
        parsed = json.loads(literal)
        if json.dumps(parsed, sort_keys=True, ensure_ascii=False) == json.dumps(value, sort_keys=True, ensure_ascii=False):
            return {'status': 'literal_bound', 'normalization': 'complete identical JSON literal',
                    'scope': 'JSON representation only; semantic relation requires curator review'}
    except (ValueError, TypeError):
        pass
    return {'status': 'curator_interpretation', 'reason': 'Structured/boolean value has no complete identical source JSON literal',
            'scope': 'no automatic typed-value support claim; curator must verify every field and condition'}


def _entity_catalog(raw_records) -> dict:
    catalog = {}
    for _, record in raw_records:
        for entity in record.get('entities', []):
            if isinstance(entity, dict) and isinstance(entity.get('id'), str):
                catalog.setdefault(entity['id'], []).append((record.get('id'), entity.get('type'), _compact(entity.get('name', ''))))
    return catalog


def validate_knowledge(record: dict, root: Path, *, _catalog: dict | None = None) -> list[str]:
    if not isinstance(record, dict):
        return ['Knowledge record must be an object']
    required = ['id', 'title', 'as_of', 'entities', 'claims', 'limitations', 'gaps']
    if any(key not in record for key in required):
        return ['Knowledge record is missing required identity, entities, claims or limitations']
    if not isinstance(record['id'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,100}', record['id']):
        return ['Record ID must be a portable filename slug']
    try:
        datetime.fromisoformat(record['as_of'])
    except (ValueError, TypeError):
        return ['as_of must be an ISO date or datetime']
    errors, entities = [], {}
    if not isinstance(record['entities'], list) or not record['entities']:
        return ['At least one typed entity is required']
    for entity in record['entities']:
        if not isinstance(entity, dict) or not isinstance(entity.get('id'), str) or not ID.fullmatch(entity['id']):
            errors.append('Entity identity is invalid'); continue
        if entity.get('type') not in ENTITY_TYPES or not isinstance(entity.get('name'), str) or not entity['name'].strip():
            errors.append(f"Entity {entity['id']} needs an allowed type and name")
        if not isinstance(entity.get('aliases', []), list) or any(not isinstance(x, str) for x in entity.get('aliases', [])):
            errors.append(f"Entity {entity['id']} aliases must be strings")
        if entity['id'] in entities:
            errors.append(f"Duplicate entity {entity['id']}")
        entities[entity['id']] = entity
    catalog = _catalog if _catalog is not None else _entity_catalog(_raw_records(root))
    for own in entities.values():
        for record_id, kind, name in catalog.get(own['id'], []):
            if record_id != record['id'] and (own.get('type') != kind or _compact(own.get('name', '')) != name):
                errors.append(f"Entity identity conflict for {own['id']}")
    if not isinstance(record['claims'], list) or not record['claims']:
        return errors + ['At least one supported claim is required']
    claim_ids = set()
    for claim in record['claims']:
        if not isinstance(claim, dict):
            errors.append('Claim must be an object'); continue
        cid = claim.get('id')
        if not isinstance(cid, str) or not ID.fullmatch(cid) or cid in claim_ids:
            errors.append('Claim ID is invalid or duplicated')
        claim_ids.add(cid)
        if claim.get('subject') not in entities:
            errors.append(f'Claim {cid} subject is not a declared entity')
        if claim.get('predicate') not in PREDICATES:
            errors.append(f'Claim {cid} uses an unsupported predicate')
        if claim.get('object_entity') is not None and claim['object_entity'] not in entities:
            errors.append(f'Claim {cid} object entity is not declared')
        if claim.get('assertion_kind') not in {'publisher_reported', 'source_stated'}:
            errors.append(f'Claim {cid} must retain publisher/source attribution')
        if not isinstance(claim.get('statement'), str) or not claim['statement'].strip():
            errors.append(f'Claim {cid} needs a readable statement')
        if 'value' not in claim or not isinstance(claim.get('value_text'), str) or not claim['value_text'].strip():
            errors.append(f'Claim {cid} needs a typed value and literal value_text')
        supports = claim.get('evidence')
        if not isinstance(supports, list) or not supports:
            errors.append(f'Claim {cid} needs source evidence'); continue
        snippets = []
        for evidence in supports:
            issues = validate_evidence(root, evidence)
            errors.extend(f'Claim {cid}: {issue}' for issue in issues)
            if not issues:
                snippets.append(evidence_span(root, evidence)['text'])
        if snippets and _compact(claim.get('value_text', '')) not in _compact('\n'.join(snippets)):
            errors.append(f'Claim {cid} value_text is not present in the cited evidence')
        binding = value_binding(claim)
        if binding['status'] == 'unbound':
            errors.append(f"Claim {cid} typed value does not bind value_text: {binding['reason']}")
        if not isinstance(claim.get('conditions', {}), dict):
            errors.append(f'Claim {cid} conditions must be an object')
    for field in ['limitations', 'gaps']:
        if not isinstance(record[field], list) or any(not isinstance(x, str) for x in record[field]):
            errors.append(f'{field} must be a list of strings')
    return errors


def add_knowledge(root: Path, record: dict) -> dict:
    errors = validate_knowledge(record, root)
    if errors:
        raise ValueError('; '.join(errors))
    path = root / f"data/knowledge/{record['id']}.json"
    old = read(path)
    sha = digest(json.dumps(record, sort_keys=True, ensure_ascii=False))
    if old == record:
        return {'id': record['id'], 'status': 'unchanged', 'record_sha256': sha}
    if old:
        previous = digest(json.dumps(old, sort_keys=True, ensure_ascii=False))
        save(root / f"data/knowledge-history/{record['id']}/{previous}.json", old)
    save(path, record)
    from .review import mark_claims_reviewed
    mark_claims_reviewed(root, record['id'], record['claims'])
    return {'id': record['id'], 'status': 'accepted', 'record_sha256': sha,
            'validation': 'identity, literal evidence and provenance checked; curator interpretation is not independently verified'}


def records(root: Path) -> tuple[list[dict], dict]:
    accepted, rejected = [], {}
    raw = list(_raw_records(root))
    catalog = _entity_catalog(raw)
    for path, record in raw:
        errors = validate_knowledge(record, root, _catalog=catalog)
        if errors:
            rejected[path.name] = errors
        else:
            accepted.append(record)
    return accepted, rejected


def _merged_entities(current: list[dict]) -> dict:
    """Union declared labels by validated stable identity before query matching."""
    declarations = {}
    for record in current:
        for entity in record['entities']:
            declarations.setdefault(entity['id'], []).append(entity)
    result = {}
    for key in sorted(declarations):
        items = declarations[key]
        # Identity validation already rejects different types/names. Select a
        # reproducible declaration, independently of record/file iteration order.
        representative = min(items, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
        aliases = sorted((alias for item in items for alias in item.get('aliases', [])),
                         key=lambda alias: (_compact(alias), alias))
        unique = {}
        for alias in aliases:
            unique.setdefault(_compact(alias), alias)
        result[key] = {**representative, 'aliases': list(unique.values())}
    return result


def _supported_claim(root: Path, record: dict, claim: dict, excerpt_chars=500) -> dict:
    evidence = [evidence_span(root, item, max_chars=excerpt_chars) for item in claim['evidence']]
    binding = value_binding(claim)
    return {**claim, 'claim_id': f"{record['id']}:{claim['id']}", 'record_id': record['id'],
            'as_of': record['as_of'], 'evidence': evidence,
            'typed_value_binding': binding,
            'value_support': 'literal_normalization_checked' if binding['status'] == 'literal_bound' else 'curator_interpretation',
            'freshness': 'current_text' if all(e['is_current_text_version'] for e in evidence) else 'historical_text',
            'semantic_support': 'curator interpretation; mechanical citation checks only'}


def graph(root: Path, entity: str, hops: int = 1, max_edges: int = 30) -> dict:
    current, rejected = records(root)
    nodes, claims = _merged_entities(current), []
    for record in current:
        claims.extend((record, claim) for claim in record['claims'])
    needle = _compact(entity)
    seeds = [key for key, node in nodes.items() if key == entity or needle == _compact(node['name'])
             or any(needle == _compact(x) for x in node.get('aliases', []))]
    if not seeds:
        return {'nodes': [], 'edges': [], 'status': 'not_found', 'rejected_records': rejected}
    visited, found, edge_ids = set(seeds), [], set()
    frontier = deque((key, 0) for key in seeds)
    cap = max(1, min(max_edges, 100))
    while frontier and len(found) < cap:
        key, depth = frontier.popleft()
        if depth >= max(1, min(hops, 3)):
            continue
        for record, claim in claims:
            target = claim.get('object_entity')
            if key not in {claim['subject'], target}:
                continue
            cid = f"{record['id']}:{claim['id']}"
            if cid in edge_ids:
                continue
            edge_ids.add(cid)
            found.append(_supported_claim(root, record, claim))
            for linked in [claim['subject'], target]:
                if linked and linked not in visited:
                    visited.add(linked); frontier.append((linked, depth + 1))
            if len(found) >= cap:
                break
    ordered = seeds + sorted(visited - set(seeds))
    return {'status': 'ok', 'nodes': [nodes[key] for key in ordered], 'edges': found,
            'truncated': len(found) >= cap, 'rejected_records': rejected,
            'scope': 'explicit curated technology claims; no automatically inferred relationships'}


def _evidence_metadata(root: Path, evidence: dict, entries: dict) -> dict:
    source = resolve_source_version(root, evidence['source_id'], evidence['text_sha256']) or {}
    entry = entries.get(evidence['source_id'], {})
    dates = []
    for mention in entry.get('mentions', []):
        video = read(root / f"data/raw/videos/{mention['video_id']}.json") or {}
        if video.get('published_at'):
            dates.append(video['published_at'])
    return {'source_published_at': source.get('published_at'),
            'video_publication_dates': list(dict.fromkeys(dates)),
            'link_roles': entry.get('roles', []), 'quality': source.get('quality')}


def technology_facts(root: Path, query: str, required: list[str] | None = None, limit: int = 8,
                     **filters) -> dict:
    current, rejected = records(root)
    filter_document('source', {}, **filters)
    manifest = read(root / 'data/source-manifest.json') or {'sources': []}
    entries = {entry['id']: entry for entry in manifest['sources']}
    metadata = {}
    def accepted(claim):
        if not filters:
            return True
        for evidence in claim['evidence']:
            key = evidence['source_id'], evidence['text_sha256']
            if key not in metadata:
                metadata[key] = _evidence_metadata(root, evidence, entries)
            if not filter_document('source', metadata[key], **filters)[0]:
                return False
        return True
    words = set(re.findall(r'\w+', query.casefold()))
    entities, memberships = _merged_entities(current), {}
    for record in current:
        for claim in record['claims']:
            if entities[claim['subject']]['type'] in TECH_TYPES and accepted(claim):
                memberships.setdefault(claim['subject'], []).append((record, claim))
    ranked = []
    for key, pairs in memberships.items():
        entity = entities[key]
        labels = ' '.join([entity['name']] + entity.get('aliases', []))
        fact_text = ' '.join(claim['statement'] for _, claim in pairs)
        label_words = set(re.findall(r'\w+', labels.casefold()))
        hits = 4 * len(words & label_words) + len(words & set(re.findall(r'\w+', fact_text.casefold())))
        # A named candidate must outrank an unrelated profile that happens to
        # repeat generic words such as code, local, production and repository.
        normalized_query = ' ' + ' '.join(re.findall(r'\w+', query.casefold())) + ' '
        if any(' ' + ' '.join(re.findall(r'\w+', label.casefold())) + ' ' in normalized_query
               for label in [entity['name']] + entity.get('aliases', []) if len(label) >= 4):
            hits += 8
        if hits or _compact(query) in _compact(labels):
            ranked.append((hits, key))
    result = []
    # Materialize evidence only for selected identities. Every eligible record
    # contributes facts even when the matching alias was declared elsewhere.
    for score, key in sorted(ranked, key=lambda item: (-item[0], item[1]))[:max(1, min(limit, 20))]:
        pairs = memberships[key]
        contributing = {record['id']: record for record, _ in pairs}.values()
        item = {**entities[key], 'facts': [_supported_claim(root, record, claim) for record, claim in pairs],
                'score': score, 'limitations': [x for record in contributing for x in record['limitations']],
                'gaps': [x for record in contributing for x in record['gaps']], 'as_of': pairs[0][0]['as_of']}
        result.append(item)
    for item in result:
        known = {claim['predicate'] for claim in item['facts']}
        item['unknown_requirements'] = [field for field in (required or []) if field not in known]
        item['limitations'] = list(dict.fromkeys(item['limitations']))
        item['gaps'] = list(dict.fromkeys(item['gaps']))
        item['decision_status'] = 'evidence_available_for_comparison; compatibility and current suitability are not inferred'
    return {'technologies': result, 'rejected_records': rejected,
            'status': 'ok' if result else 'no_curated_match',
            'notice': 'Unknown fields are absent evidence, not proof that a capability is unsupported.'}


def knowledge_documents(root: Path) -> list[dict]:
    current, _ = records(root)
    manifest = read(root / 'data/source-manifest.json') or {'sources': []}
    entries = {entry['id']: entry for entry in manifest['sources']}
    result = []
    for record in current:
        sha = digest(json.dumps(record, sort_keys=True, ensure_ascii=False))
        path = root / f"knowledge/records/{record['id']}-{sha[:16]}.md"
        lines = [f"# {record['title']}", '', f"As of: {record['as_of']}",
                 'Evidence: curator-authored source interpretation, not independent validation.', '', '## Supported claims', '']
        for claim in record['claims']:
            lines += [f"### {claim['subject']} — {claim['predicate']}", claim['statement'],
                      f"Value: {json.dumps(claim['value'], ensure_ascii=False)}", f"Conditions: {json.dumps(claim.get('conditions', {}), ensure_ascii=False)}"]
            for evidence in claim['evidence']:
                span = evidence_span(root, evidence, max_chars=0)
                lines.append(f"Evidence: {span['source_url']} — source {evidence['source_id']}, text {evidence['text_sha256']}, lines {evidence['start_line']}-{evidence['end_line']}")
            lines.append('')
        lines += ['## Limitations'] + ['- ' + x for x in record['limitations']]
        lines += ['', '## Missing evidence'] + ['- ' + x for x in record['gaps']]
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        dates = [_evidence_metadata(root, e, entries) for c in record['claims'] for e in c['evidence']]
        result.append({'id': 'knowledge:' + record['id'], 'kind': 'knowledge', 'title': record['title'],
                       'path': path, 'lines': lines, 'metadata': {'as_of': record['as_of'],
                       'source_publication_dates': list(dict.fromkeys(d['source_published_at'] for d in dates if d['source_published_at'])),
                       'video_publication_dates': list(dict.fromkeys(v for d in dates for v in d['video_publication_dates'])),
                       'entities': record['entities'], 'claims': record['claims'], 'source_urls': list(dict.fromkeys(
                           evidence_span(root, e, 0)['source_url'] for c in record['claims'] for e in c['evidence'])),
                       'date_filter_scope': 'document includes at least one dated evidence item; inspect each claim date'}, 'skip': 6})
    return result


def index_knowledge(root: Path, db) -> dict:
    current, rejected = records(root)
    db.executescript('''CREATE TABLE IF NOT EXISTS entities(id TEXT PRIMARY KEY, type TEXT, name TEXT, aliases TEXT);
      CREATE TABLE IF NOT EXISTS technology_claims(id TEXT PRIMARY KEY, record_id TEXT, subject TEXT, predicate TEXT,
      value TEXT, object_entity TEXT, evidence TEXT, as_of TEXT, conditions TEXT, assertion_kind TEXT);''')
    db.execute('DELETE FROM entities'); db.execute('DELETE FROM technology_claims')
    count = 0
    for entity in _merged_entities(current).values():
        db.execute('INSERT INTO entities VALUES(?,?,?,?)', (entity['id'], entity['type'], entity['name'], json.dumps(entity['aliases'])))
    for record in current:
        for claim in record['claims']:
            db.execute('INSERT INTO technology_claims VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (f"{record['id']}:{claim['id']}", record['id'], claim['subject'], claim['predicate'],
                        json.dumps(claim['value']), claim.get('object_entity'), json.dumps(claim['evidence']),
                        record['as_of'], json.dumps(claim.get('conditions', {})), claim['assertion_kind']))
            count += 1
    return {'knowledge_records': len(current), 'entities': db.execute('SELECT COUNT(*) FROM entities').fetchone()[0],
            'typed_claims': count, 'rejected_knowledge': rejected}


def export_public_knowledge(root: Path) -> dict:
    """Publish original concise facts/provenance, never source text or local paths."""
    current, rejected = records(root)
    exported = []
    for record in current:
        claims = []
        for claim in record['claims']:
            item = {key: claim[key] for key in ['id', 'subject', 'predicate', 'object_entity', 'value',
                                               'statement', 'assertion_kind', 'conditions'] if key in claim}
            item['evidence'] = []
            for evidence in claim['evidence']:
                span = evidence_span(root, evidence, max_chars=0)
                item['evidence'].append({key: span.get(key) for key in ['source_id', 'text_sha256', 'start_line', 'end_line',
                                          'source_url', 'source_published_at', 'retrieved_at', 'is_current_text_version']})
            claims.append(item)
        exported.append({key: record[key] for key in ['id', 'title', 'as_of', 'entities', 'limitations', 'gaps']} | {'claims': claims})
    output = {'schema_version': 'aisk.public-facts.v1', 'scope': 'Original curator-authored publisher-attributed facts; partial source review, not independently reproduced or guaranteed current.',
              'usage': 'Read-only portable synthesis. To admit local typed records, inspect original evidence and author literal value_text anchors against your retained source versions.',
              'records': exported, 'rejected_record_count': len(rejected)}
    path = root / 'public/technology-facts.json'
    save(path, output)
    return {'path': 'public/technology-facts.json', 'records': len(exported), 'claims': sum(len(r['claims']) for r in exported),
            'scope': 'Original concise synthesis and source metadata only; no raw source snapshots or local machine paths'}
