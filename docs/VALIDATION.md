# Validation snapshot — 2026-11-01

## What was checked

- Public channel identity and exact video IDs; newest-first publication dates through the six-month boundary. The active set has 55 Videos entries. Three older videos confirm the stop boundary. All visited active metadata has a publication timestamp.
- 604 reference URLs were attempted: 595 directly described references plus 9 explicitly followed artifacts. 569 successful text snapshots are stored locally. 35 gaps retain their status and original relationship to the video.
- The index contains 55 video descriptions, 569 source documents, 5 authored notes and 1,520 passages.
- Eleven automated tests passed on macOS with Python 3.14.6. Tests cover calendar/timezone boundaries, URL provenance, exact chapter association, channel identity, explicit publication-date evidence, prompt-injection text remaining data, research-page caveats outside a `main` element, passage bounds and line matches, stale evidence rejection, writer locking, linked-artifact provenance, and preservation/backoff after a failed refresh.
- Five live-corpus retrieval checks found the expected notes for SLEEP, Audio8, MatAnyone-E, AutoSwarm and MotionBricks. Returned text matched its stated local line ranges.
- A complete incremental rerun discovered the channel again, reused all fresh video descriptions and existing references, and queued **zero** video fetches and **zero** source fetches. Later, four newly selected landing-page artifacts were fetched separately.

## Reproduce the checks

```sh
uv sync --locked --dev
uv run pytest -q
uv run aisk search 'Audio8 Indonesian codec' --kind note --limit 1
uv run aisk search 'MatAnyone H200 4K' --kind source --limit 2
uv run aisk status
```

Expected: tests pass; retrieval returns relevant evidence with publication/retrieval information, original URLs and exact local line numbers. Observe the hardware, evaluation and parameter-count caveats in the notes. On a fresh clone, collect the corpus first; its coverage can differ as source access changes.

## Practical limits

The source archive is an evidence base, not a complete human/AI review of every document. Five notes are original synthesis; other texts are retrieved publisher material. Mechanical note validation does not prove semantic correctness. Descriptions and articles do not establish that the video itself, audio samples, demonstrations, benchmarks, model code or hardware behavior were tested.

Some JavaScript pages required an optional public browser connector. That connector allowed one active session; capacity rejections were retried sequentially and kept separate from website failures. The reusable HTTP collector does not include that external connector or silently purchase browser/model access.

The full local snapshots are excluded from Git. The public catalog contains metadata and links, and the examples contain concise original synthesis. Local raw data was not published as a bulk third-party corpus.

Remote CI and clean-checkout status are recorded in STATUS.md after publication checks. No scheduled collection or ongoing monitor was installed.
