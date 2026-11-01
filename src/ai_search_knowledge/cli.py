import argparse
import json
import sys
from pathlib import Path

from .core import collect_videos, config, inventory, read
from .sources import collect_sources, build_manifest, add_source
from .library import build_index, coverage, search, gaps, validate_note
from .workflow import add_note, discover, update, work_queue, writer_lock, import_snapshot


def main():
    # Corpus text and JSON are UTF-8 even when a Windows pipe defaults to cp1252.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="Local source-linked AI Search knowledge library")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project directory containing config.json")
    commands = parser.add_subparsers(dest="command", required=True)
    videos = commands.add_parser("videos", help="Fetch missing/stale public video metadata and descriptions")
    videos.add_argument("--limit", type=int, default=0)
    videos.add_argument("--refresh", action="store_true")
    commands.add_parser("status", help="Show current local coverage, dates and gaps")
    sources = commands.add_parser("sources", help="Fetch missing/stale linked reference documents")
    sources.add_argument("--limit", type=int, default=0)
    sources.add_argument("--refresh", action="store_true")
    sources.add_argument("--retry", action="store_true")
    sources.add_argument("--status", action="append", help="Retry only this recorded status; repeatable")
    commands.add_parser("manifest", help="Build scoped video-to-source manifest")
    commands.add_parser("discover", help="Refresh public channel inventory")
    commands.add_parser("index", help="Build local Markdown evidence files and SQLite FTS index")
    updater = commands.add_parser("update", help="Incremental discover → metadata → sources → index; does not run an external AI model")
    updater.add_argument("--source-limit", type=int, default=0)
    finder = commands.add_parser("search", help="Retrieve bounded evidence passages as JSON")
    finder.add_argument("query")
    finder.add_argument("--limit", type=int, default=5)
    finder.add_argument("--kind", choices=["video", "source", "note"])
    finder.add_argument("--max-chars", type=int, default=1400)
    gap = commands.add_parser("gaps", help="List unavailable/unresolved reference links")
    gap.add_argument("--limit", type=int, default=30)
    work = commands.add_parser("work", help="Prepare source-reading tasks for an AI agent")
    work.add_argument("--limit", type=int, default=3)
    note = commands.add_parser("add-note", help="Validate and save an evidence-backed knowledge note")
    note.add_argument("path", type=Path)
    validate = commands.add_parser("validate-note", help="Check a note's source hashes and line ranges")
    validate.add_argument("path", type=Path)
    snapshot = commands.add_parser("import-snapshot", help="Import a provenance-preserving public browser tool snapshot")
    snapshot.add_argument("path", type=Path)
    extra = commands.add_parser("add-source", help="Queue a primary artifact actually linked from a stored source (max 2 hops)")
    extra.add_argument("--parent", required=True)
    extra.add_argument("--url", required=True)
    extra.add_argument("--label", required=True)
    reader = commands.add_parser("read", help="Read numbered lines from a local evidence Markdown file")
    reader.add_argument("path", type=Path)
    reader.add_argument("--start", type=int, default=1)
    reader.add_argument("--lines", type=int, default=60)
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / "config.json").exists():
        parser.error("Run in the project directory or provide --root")
    def run():
        if args.command == "videos":
            return collect_videos(root, args.limit, args.refresh)
        if args.command == "sources":
            return collect_sources(root, args.limit, args.refresh, args.retry, args.status)
        if args.command == "manifest":
            manifest = build_manifest(root)
            return {"videos": len(manifest["videos"]), "urls": len(manifest["sources"]),
                    "references": sum("reference" in s["roles"] for s in manifest["sources"])}
        if args.command == "discover":
            return discover(root)
        if args.command == "index":
            return build_index(root)
        if args.command == "update":
            return update(root, args.source_limit)
        if args.command == "search":
            return search(root, args.query, args.limit, args.kind, max(200, min(args.max_chars, 6000)))
        if args.command == "gaps":
            return gaps(root)[:max(1, args.limit)]
        if args.command == "work":
            return work_queue(root, args.limit)
        if args.command == "add-note":
            return add_note(root, args.path)
        if args.command == "import-snapshot":
            return import_snapshot(root, args.path)
        if args.command == "add-source":
            return add_source(root, args.parent, args.url, args.label)
        if args.command == "validate-note":
            errors = validate_note(read(args.path), root)
            if errors:
                raise ValueError("; ".join(errors))
            return {"valid": True, "scope": "mechanical evidence checks; not semantic verification"}
        if args.command == "read":
            path = (root / args.path).resolve()
            if not path.is_relative_to(root / "knowledge") or path.suffix != ".md":
                raise ValueError("read accepts only Markdown evidence files under knowledge/")
            lines = path.read_text(encoding='utf-8').splitlines()
            start = max(1, args.start)
            return {"path": str(path.relative_to(root)), "total_lines": len(lines),
                    "text": "\n".join(f"{i}: {line}" for i, line in enumerate(lines, 1)
                                       if start <= i < start + max(1, min(args.lines, 200)))}
        return coverage(root)

    if args.command in {"videos", "sources", "manifest", "discover", "index", "update", "add-note", "work", "import-snapshot", "add-source"}:
        with writer_lock(root):
            result = run()
    else:
        result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
