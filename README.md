# AI Search Knowledge

A local evidence library for AI-assisted technology research, built from [AI Search](https://www.youtube.com/@theAIsearch) long-form videos and their original references. Start with six months, exclude Shorts, then keep growing the archive.

An agent can discover candidates, inspect dated capabilities and conditions, compare project requirements, and produce a source-backed brief with explicit unknowns. Original URLs, video relationships, publication/retrieval dates, immutable evidence versions and unresolved gaps stay available. Collection and retrieval do not imply that every source or audiovisual demonstration has been reviewed.

## Start locally

Install [uv](https://docs.astral.sh/uv/), then:

```sh
git clone https://github.com/hanafishiddiq/ai-search-knowledge.git
cd ai-search-knowledge
uv sync --locked
uv run aisk update
uv run aisk research 'TTS bahasa Indonesia untuk narasi' --mode lexical --required supports_language --required license --max-chars 12000
uv run aisk status
```

No model API key is required. Your AI assistant performs the interpretation following [the agent workflow](docs/AGENT-WORKFLOW.md). The CLI returns evidence; it does not silently call an LLM or verify a recommendation.

The public repository contains code, [metadata and links](public/catalog.json), evaluation questions and [original research examples](examples/research/). A [portable fact export](public/technology-facts.json) contains original concise statements, conditions and source provenance. Full third-party snapshots, source-bound local record files, model weights and indexes stay in ignored `data/` and `knowledge/`. A fresh clone collects its own corpus; website access and coverage can differ from the owner's snapshot.

## Optional multilingual search

Lexical search includes a small explicit Indonesian/English vocabulary. The full-corpus development evaluation favored improved lexical search, which is the default. Local semantic/hybrid retrieval remains optional for exploration and comparison:

```sh
uv sync --locked --extra semantic
uv run aisk semantic-index --download-model
uv run aisk research 'model suara yang cocok untuk bahasa Indonesia' --mode hybrid --required license --max-chars 12000
```

The first explicit setup downloads pinned multilingual E5-small ONNX assets (about 492 MB). Embeddings then run on local CPU; subsequent searches do not download weights. Index rebuilds reuse unchanged vectors. Similarity scores are ranking signals, not factual confidence or compatibility. An unavailable or stale semantic index is reported explicitly; auto/hybrid fallback says which mode actually ran.

## Agent interfaces

```sh
uv run aisk search 'Audio8 Indonesian codec' --kind source --limit 3
uv run aisk search 'video generation' --mode hybrid --since 2026-09-01 --date-basis video
uv run aisk read knowledge/sources/SOURCE_ID-TEXT_HASH_PREFIX.md --start 40 --lines 50 --max-chars 4000
uv run aisk facts 'Audio8' --required runs_on --required license
uv run aisk graph 'Audio8-TTS-Realistic-0.6B' --limit 8
uv run aisk work --limit 3
uv run aisk gaps --limit 20
```

`search` preserves its lexical JSON-list interface unless a mode is explicitly selected. `--max-chars` caps each excerpt. `research --max-chars` caps the **whole compact JSON packet**, including provenance, profiles and constraints. Exact line/column citations refer to unchanged local evidence files. Typed facts and graph results depend on curated records; a newly collected corpus starts without those records. See [KNOWLEDGE-FORMAT.md](docs/KNOWLEDGE-FORMAT.md) for admission and [the usage prompt](prompts/use-library.md) for an agent entry point.

## Architecture and scope

The system combines versioned raw/normalized evidence, SQLite FTS retrieval, optional local multilingual embeddings, explicit typed technology claims and bounded graph traversal. The calling AI compares these against the project's constraints. [Architecture and limits](docs/RESEARCH-V2.md), [goals](docs/GOALS.md), [measured validation](docs/VALIDATION-V2.md) and [status](STATUS.md) explain what is implemented and what remains unreviewed. Graphify is not a runtime dependency.

The first run saves a fixed acquisition floor; later updates retain older captured knowledge. A source removed from a revised description stays in the provenance registry as historical. Dates are not interchangeable: video-publication filters and source-publication filters are explicit, with an unknown-date policy.

The document fetcher uses bounded requests, host spacing and robots checks. It does not sign in, bypass access challenges, execute downloaded code, download video media or follow entire websites. The optional embedding setup is a separate explicit weight download. Narration, unspoken visuals and audio demonstrations remain unreviewed. No schedule is installed.

## Development and license

```sh
uv sync --locked --dev
uv run pytest -q
# Requires a collected local corpus matching the dated fixture:
uv run aisk evaluate --mode lexical
```

Code and original documentation/synthesis are [MIT licensed](LICENSE). Third-party articles, research papers, model weights and linked materials retain their own terms. This project is independent of the channel and source publishers.
