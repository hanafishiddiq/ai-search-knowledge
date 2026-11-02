"""Command routing stays light: collection/model runtimes load only when used."""
import argparse
import json
import sys
from pathlib import Path

MODES = ['auto', 'lexical', 'semantic', 'hybrid']


def _filter_arguments(parser):
    parser.add_argument('--since', help='ISO publication date/timestamp lower bound')
    parser.add_argument('--until', help='ISO publication date/timestamp upper bound')
    parser.add_argument('--date-basis', choices=['source', 'video'], default='video')
    parser.add_argument('--unknown-dates', choices=['exclude', 'include'], default='exclude')
    parser.add_argument('--role', action='append', help='Allowed description-link role; repeatable')
    parser.add_argument('--quality', action='append', help='Allowed extraction quality; repeatable')


def _filters(args):
    return dict(since=args.since, until=args.until, date_basis=args.date_basis,
                unknown_dates=args.unknown_dates, roles=args.role, qualities=args.quality)


def _json_argument(value, expected_type):
    if value is None:
        return None
    # JSON objects/lists or a local filename; never eval.
    text = value if value.lstrip().startswith(('{', '[')) else Path(value.removeprefix('@')).read_text(encoding='utf-8')
    result = json.loads(text)
    if not isinstance(result, expected_type):
        raise ValueError(f'Expected a JSON {expected_type.__name__}')
    return result


def _run(root, args):
    command = args.command
    if command == 'videos':
        from .core import collect_videos
        return collect_videos(root, args.limit, args.refresh)
    if command == 'sources':
        from .sources import collect_sources
        return collect_sources(root, args.limit, args.refresh, args.retry, args.status)
    if command == 'manifest':
        from .sources import build_manifest
        manifest = build_manifest(root)
        return {'videos': len(manifest['videos']), 'urls': len(manifest['sources']),
                'references': sum('reference' in s['roles'] for s in manifest['sources'])}
    if command == 'discover':
        from .workflow import discover
        return discover(root)
    if command == 'index':
        from .workflow import rebuild_index
        return rebuild_index(root)
    if command == 'update':
        from .workflow import update
        return update(root, args.source_limit)
    if command == 'search':
        size = max(200, min(args.max_chars, 6000))
        if args.mode is None:
            from .library import search
            return search(root, args.query, args.limit, args.kind, size, **_filters(args))
        from .research import retrieve
        return retrieve(root, args.query, args.limit, args.kind, size, mode=args.mode, **_filters(args))
    if command == 'research':
        from .research import research
        return research(root, args.query, constraints=_json_argument(args.constraints, dict),
                        required=args.required, mode=args.mode, max_chars=args.max_chars,
                        limit=args.limit, **_filters(args))
    if command == 'facts':
        from .knowledge import technology_facts
        return technology_facts(root, args.query, required=args.required, limit=args.limit, **_filters(args))
    if command == 'graph':
        from .knowledge import graph
        return graph(root, args.entity, hops=args.hops, max_edges=args.limit)
    if command == 'gaps':
        from .library import gaps
        return gaps(root)[:max(1, args.limit)]
    if command == 'work':
        from .workflow import work_queue
        return work_queue(root, args.limit, args.max_chars)
    if command == 'add-note':
        from .workflow import add_note
        return add_note(root, args.path)
    if command in {'add-knowledge', 'validate-knowledge'}:
        from .core import read
        from .knowledge import add_knowledge, validate_knowledge
        record = read(args.path)
        if command == 'add-knowledge':
            return add_knowledge(root, record)
        errors = validate_knowledge(record, root)
        if errors:
            raise ValueError('; '.join(errors))
        return {'valid': True, 'scope': 'identity and literal evidence checks; not semantic or independent factual verification'}
    if command == 'import-snapshot':
        from .workflow import import_snapshot
        return import_snapshot(root, args.path)
    if command == 'add-source':
        from .sources import add_source
        return add_source(root, args.parent, args.url, args.label)
    if command == 'validate-note':
        from .core import read
        from .library import validate_note
        errors = validate_note(read(args.path), root)
        if errors:
            raise ValueError('; '.join(errors))
        return {'valid': True, 'scope': 'mechanical evidence checks; not semantic verification'}
    if command == 'read':
        from .evidence import read_document
        return read_document(root, args.path, start=args.start, lines=args.lines,
                             max_chars=args.max_chars, start_column=args.start_column)
    if command == 'review':
        from .review import mark_review, review_status
        old = review_status(root, args.source, args.sha)
        ranges = _json_argument(args.ranges, list) if args.ranges is not None else old['covered_ranges']
        return mark_review(root, args.source, args.sha, args.state, covered_ranges=ranges,
                           unresolved=args.unresolved if args.unresolved is not None else old.get('unresolved', []),
                           note=args.note, reviewer=args.reviewer)
    if command == 'review-status':
        from .review import review_status, review_summary
        if bool(args.source) != bool(args.sha):
            raise ValueError('review-status requires both --source and --sha, or neither')
        return review_status(root, args.source, args.sha) if args.source else review_summary(root)
    if command == 'reprocess':
        from .sources import reprocess_sources
        result = reprocess_sources(root, args.id, persist=not args.dry_run)
        if not args.dry_run and not args.no_index:
            from .workflow import rebuild_index
            result['index'] = rebuild_index(root)
        return result
    if command == 'semantic-index':
        from .core import config
        from .semantic import build_semantic_index
        settings = {**(config(root).get('semantic') or {}), 'enabled': True,
                    'allow_download': args.download_model}
        return build_semantic_index(root, config=settings)
    if command == 'evaluate':
        from .evaluation import evaluate
        result = evaluate(root, args.cases, modes=args.mode)
        if args.output:
            from .core import save
            save(args.output, result)
        return result
    from .library import coverage
    from .review import review_summary
    return {**coverage(root), 'review': review_summary(root)}


def main(argv=None):
    # Corpus text and JSON are UTF-8 even when a Windows pipe defaults to cp1252.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Local source-linked AI Search knowledge library')
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='Project directory containing config.json')
    commands = parser.add_subparsers(dest='command', required=True)
    videos = commands.add_parser('videos', help='Fetch missing/stale public video metadata and descriptions')
    videos.add_argument('--limit', type=int, default=0)
    videos.add_argument('--refresh', action='store_true')
    commands.add_parser('status', help='Show current local coverage, dates, gaps and review states')
    sources = commands.add_parser('sources', help='Fetch missing/stale linked reference documents')
    sources.add_argument('--limit', type=int, default=0)
    sources.add_argument('--refresh', action='store_true')
    sources.add_argument('--retry', action='store_true')
    sources.add_argument('--status', action='append', help='Retry only this recorded status; repeatable')
    commands.add_parser('manifest', help='Build retained video-to-source manifest')
    commands.add_parser('discover', help='Refresh public channel inventory')
    commands.add_parser('index', help='Build evidence, curated knowledge and local retrieval index')
    updater = commands.add_parser('update', help='Incremental discover → metadata → sources → index; does not run an external AI model')
    updater.add_argument('--source-limit', type=int, default=0)
    finder = commands.add_parser('search', help='Retrieve evidence; legacy list unless --mode requests an envelope')
    finder.add_argument('query')
    finder.add_argument('--limit', type=int, default=5)
    finder.add_argument('--kind', choices=['video', 'source', 'note', 'knowledge'])
    finder.add_argument('--max-chars', type=int, default=1400, help='Per-passage text budget')
    finder.add_argument('--mode', choices=MODES)
    _filter_arguments(finder)
    researcher = commands.add_parser('research', help='Prepare a compact bounded JSON evidence packet for a calling AI')
    researcher.add_argument('query')
    researcher.add_argument('--constraints', help='JSON object or local JSON filename (@filename also accepted)')
    researcher.add_argument('--required', action='append', help='Required knowledge predicate; repeatable')
    researcher.add_argument('--mode', choices=MODES, default='lexical')
    researcher.add_argument('--limit', type=int, default=6)
    researcher.add_argument('--max-chars', type=int, default=12000, help='Whole compact JSON packet budget')
    _filter_arguments(researcher)
    facts = commands.add_parser('facts', help='Retrieve evidence-backed technology facts and missing requirements')
    facts.add_argument('query')
    facts.add_argument('--required', action='append')
    facts.add_argument('--limit', type=int, default=8)
    _filter_arguments(facts)
    graph = commands.add_parser('graph', help='Traverse curated typed evidence-backed relationships')
    graph.add_argument('entity')
    graph.add_argument('--hops', type=int, default=1)
    graph.add_argument('--limit', '--max-edges', type=int, default=30, help='Maximum returned edges')
    gap = commands.add_parser('gaps', help='List unavailable/unresolved reference links')
    gap.add_argument('--limit', type=int, default=30)
    work = commands.add_parser('work', help='Prepare pending/partial source-review tasks for an AI agent')
    work.add_argument('--limit', type=int, default=3)
    work.add_argument('--max-chars', type=int, default=1800, help='Numbered preview text budget per item')
    for name, help_text in [('add-note', 'Validate and save an evidence-backed knowledge note'),
                            ('validate-note', "Check a note's source hashes and line ranges"),
                            ('add-knowledge', 'Validate and save a dated typed knowledge record'),
                            ('validate-knowledge', 'Check a typed knowledge record and its literal evidence'),
                            ('import-snapshot', 'Import a provenance-preserving public browser tool snapshot')]:
        item = commands.add_parser(name, help=help_text)
        item.add_argument('path', type=Path)
    extra = commands.add_parser('add-source', help='Queue a primary artifact actually linked from a stored source (max 2 hops)')
    extra.add_argument('--parent', required=True)
    extra.add_argument('--url', required=True)
    extra.add_argument('--label', required=True)
    reader = commands.add_parser('read', help='Read bounded numbered local evidence with exact continuation columns')
    reader.add_argument('path', type=Path)
    reader.add_argument('--start', type=int, default=1)
    reader.add_argument('--lines', type=int, default=60)
    reader.add_argument('--max-chars', type=int, default=6000)
    reader.add_argument('--start-column', type=int, default=0)
    review = commands.add_parser('review', help='Record an explicit source-version review attestation')
    review.add_argument('--source', required=True)
    review.add_argument('--sha', required=True)
    review.add_argument('--state', choices=['pending', 'partial', 'complete', 'blocked'], required=True)
    review.add_argument('--ranges', help='JSON line-range list or local JSON filename; preserves previous ranges if omitted')
    review.add_argument('--unresolved', action='append', help='Unresolved issue; repeatable')
    review.add_argument('--note', default='')
    review.add_argument('--reviewer', default='owner-directed agent')
    review_status = commands.add_parser('review-status', help='Show overall review progress or one source/hash version')
    review_status.add_argument('--source')
    review_status.add_argument('--sha')
    reprocess = commands.add_parser('reprocess', help='Re-extract retained raw locally without fetching; then rebuild indexes')
    reprocess.add_argument('--id', action='append', help='Source ID; repeatable (default all retained sources)')
    reprocess.add_argument('--dry-run', action='store_true', help='Compute changes without storing or indexing')
    reprocess.add_argument('--no-index', action='store_true')
    semantic = commands.add_parser('semantic-index', help='Explicitly build optional local semantic retrieval')
    semantic.add_argument('--download-model', action='store_true', help='Opt in to downloading the configured pinned model if absent')
    evaluation = commands.add_parser('evaluate', help='Measure judged source-document and literal-span retrieval separately')
    evaluation.add_argument('--cases', type=Path, help='Defaults to evaluation/research-cases.json under --root')
    evaluation.add_argument('--mode', choices=['lexical', 'semantic', 'hybrid'], action='append')
    evaluation.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not (root / 'config.json').exists():
        parser.error('Run in the project directory or provide --root')
    try:
        # Status may initialize a missing archive policy/manifest/registry.
        # Serialize those writes with collection and index operations as well.
        mutations = {'status', 'videos', 'sources', 'manifest', 'discover', 'index', 'update', 'add-note', 'work',
                     'import-snapshot', 'add-source', 'add-knowledge', 'review', 'reprocess', 'semantic-index'}
        if args.command in mutations:
            from .workflow import writer_lock
            with writer_lock(root):
                result = _run(root, args)
        else:
            result = _run(root, args)
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        parser.exit(2, f'aisk: {exc}\n')
    # Pretty printing would invalidate research's whole-packet serialized budget.
    options = {'separators': (',', ':')} if args.command == 'research' else {'indent': 2}
    print(json.dumps(result, ensure_ascii=False, **options))


if __name__ == '__main__':
    main()
