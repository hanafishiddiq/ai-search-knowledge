# AI Search Knowledge

A local, searchable evidence library built from [AI Search](https://www.youtube.com/@theAIsearch) long-form videos from the last six months and the original sources linked in their descriptions. Shorts are excluded.

The library preserves publication dates, video timestamps, original URLs, retrieval dates, source text and explicit coverage gaps. English authored notes retain the terminology of the original sources. You can ask your AI assistant questions in any language.

## Use it locally

Install [uv](https://docs.astral.sh/uv/), then:

```sh
git clone https://github.com/hanafishiddiq/ai-search-knowledge.git
cd ai-search-knowledge
uv sync --locked
uv run aisk update
uv run aisk search 'continual learning memory' --limit 4
uv run aisk status
```

The collector needs no model API key. AI synthesis runs through your own assistant following [the agent workflow](docs/AGENT-WORKFLOW.md); the CLI does not silently call an LLM. Ordinary browser/reader tools are an optional fallback for JavaScript pages. A plain HTTP-only run can have more gaps than the initial owner-assisted collection.

Generated snapshots, the SQLite index and full source text stay in `data/` and `knowledge/`, excluded from Git. The public repository includes a [video/source catalog](public/catalog.json) and [five original synthesis examples](examples/KNOWLEDGE.md). Clone-and-update builds a new local corpus; the full owner snapshot is not downloaded from this repository.

## Use it with an AI agent

Give your assistant [this task prompt](prompts/use-library.md), or ask it to read `AGENTS.md` and `docs/AGENT-WORKFLOW.md` in your checkout. It can search passages, inspect exact source lines, deepen a reference to its linked paper/model card, and validate reusable notes.

```sh
uv run aisk search 'Audio8 Indonesian codec' --kind source --limit 3
uv run aisk work --limit 3
uv run aisk gaps --limit 20
```

Search uses local SQLite FTS5 and returns JSON evidence excerpts with original links, timestamps and line citations. It requires no embedding service or running database server. Summaries are cached when useful; full evidence remains available for questions that need more detail. The [architecture audit](docs/ARCHITECTURE-AUDIT-2026-11-01.md) records current limits: incomplete extraction on some pages, query previews that can miss supporting text, and an unresolved long-line case that exceeds the requested preview budget. Graphify, semantic embeddings and entity-graph reasoning are not currently implemented.

## Observed coverage

See [STATUS.md](STATUS.md) for the dated initial collection and validation report. The initial inventory contains 55 long-form videos in the six-month window, 1,039 chapters and 689 distinct description URLs. Nine additional primary artifacts were followed explicitly. The local corpus contains 569 successful reference snapshots and 35 recorded gaps. Source collection, authored-note coverage and audiovisual review are separate measures.

## Evidence model

1. **Video metadata** records what the channel published, its description and chapter links.
2. **Source snapshots** record text actually retrieved from linked public pages. Publisher claims remain attributed claims.
3. **Knowledge notes** synthesize evidence, link exact source passages and preserve limitations.
4. **Search index** lets an agent retrieve a small set of relevant passages before reading the originals.

Video dates, source publication dates, event dates and retrieval dates are separate fields. Unknown dates stay unknown. Old news is not silently rewritten into a statement about the present.

## Collection scope

The public Videos tab is traversed newest first, validating exact publication dates until the six-month boundary. The boundary rolls in `Asia/Jakarta`; for the initial 2026-11-01 run it is 2026-05-01. Shorts are excluded. All in-scope description URLs are retained. Reference links are queued for text collection; detected shopping, support and channel profile links remain in the manifest with their classification. These classifications are heuristics, not human review.

The document fetcher uses bounded requests, per-host spacing and robots checks; channel inventory extraction uses yt-dlp. It does not sign in, solve CAPTCHAs, bypass paywalls, download model weights or download video media. Failed, blocked, inaccessible and truncated links are reported as gaps. Descriptions and source documents cannot capture unspoken visual demonstrations; that coverage remains explicit.

No schedule is installed. Incremental reruns and a documented agent workflow will support a later scheduling decision.

## Development and license

```sh
uv sync --locked --dev
uv run pytest -q
```

Code and original documentation/synthesis are [MIT licensed](LICENSE). Third-party articles, research papers, model weights and other linked materials retain their own terms. This project is independent of the channel and its source publishers.
