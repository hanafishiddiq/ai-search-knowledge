# Research v2 validation — 2026-11-02

Implementation baseline `2dfca14`; main v2 code `c6d75a0`, named-profile ranking follow-up `b4fcae2` and typed-target validation `2df0a41`. This report distinguishes software checks, retained-source retrieval diagnostics, authored research review and unfinished corpus understanding. Historical validation remains in [VALIDATION.md](VALIDATION.md).

## Corpus migration and integrity

The existing owner corpus was copied into an isolated worktree before reprocessing. Original source records, old Markdown citations and raw snapshots were retained. The fixed acquisition floor is 2026-05-01 Asia/Jakarta; the archive grows from that seed.

- 55 long-form videos, 1,039 chapters and 604 reference URLs (595 direct, 9 selected primary artifacts); 94 other URLs remain classified separately.
- 535 sources now qualify as adequate source text. The stricter parser no longer calls every legacy extraction complete: 22 discovery-only pages, 23 thin/interactive pages, 10 robots denials, 2 unavailable robots checks, 11 HTTP failures and 1 inadequate document remain explicit, totaling 69 access/extraction/discovery gaps. These are not 69 missing videos or proven missing news topics.
- ASPIRE retained raw HTML now yields its substantive 9,267-character research body rather than a 348-character fragment. The Genesis footer/waitlist snapshot is inadequate evidence for the article. Audio8's full model card is retained, including parameter and evaluation distinctions.
- A targeted retry recovered the previously unsupported public `yue2_full.json` as JSON data. No complete recrawl was required.
- Index: 55 video descriptions, 535 source documents, 5 prose notes, 15 typed records and 1,458 lexical passages. Typed knowledge has 37 entities and 85 attributed claims; the older notes have 14 claims, with overlap rather than 99 distinct facts.
- Current source review: 16 partial, 519 pending, zero whole-source complete; 69 access/extraction gaps. Full audiovisual review remains zero. Admission never converts one cited paragraph into complete review.

Source citations verify real full text hashes and Markdown-body equality. Historical source versions remain resolvable. Removed description links and changed parent-source relationships retain historical flags. Chapter timestamps use the matching description version, or remain absent when it is unavailable.

## Retrieval diagnostics and architecture decision

[The fixed 40-case development set](../evaluation/research-cases.json) was independently authored from 18 retained substantive sources across five source-publication months and 16 hosts, before retrieval was run. It has 23 English and 17 Indonesian questions, including paraphrase, version, quantitative conditions, cross-source comparison, partial evidence and unsupported conclusions. Gold sources are known relevant examples, not exhaustive relevance judgments. The set was subsequently used for debugging; it is not a held-out accuracy estimate.

Top five **distinct source documents**, per-passage text cap 1,400 characters; anchors normalize only wrapping whitespace. A document hit does not establish that the returned window contains support. A context hit for an unsupported question does not establish a correct answer or safe abstention.

| Method | Any expected document /40 | All expected documents /40 | Any anchor /40 | All anchors /40 | Median query time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original library/index | 38 | 38 | 12 | 10 | 10 ms |
| Improved lexical | 39 | 38 | 26 | 23 | 88 ms |
| Local multilingual E5 | 31 | 30 | 19 | 15 | 606 ms |
| Hybrid rank fusion | 36 | 36 | 26 | 22 | 972 ms |

The old index uses old extraction, so its comparison measures the combined product change rather than an isolated ranking intervention. Timings are sequential in-process queries on a shared local Mac and are diagnostic, not a hardware benchmark or CLI startup guarantee. Every final optional-mode case actually ran its named mode; a preliminary run during an index update was discarded because semantic retrieval correctly reported stale evidence.

On the 17 Indonesian questions, improved lexical found all 17 expected documents and an anchor for 13; semantic found 13/8, hybrid16/12. The earlier tiny semantic pilot looked promising but did not generalize. **Improved lexical is the API/CLI default.** Semantic and hybrid remain explicit optional exploration modes, without a universal quality claim. No Graphify runtime was selected.

All final 120 case/mode outputs obeyed the excerpt cap, and every returned citation range reconstructed exactly. A separate audit checked all 4,210 semantic segments and 123,982 source spans against 610 immutable Markdown documents: zero mismatches. Synthetic regressions additionally cover the observed giant encoded-line failure, including numbered reads with exact continuation columns.

[Machine-readable results](../evaluation/results-2026-11-02.json) contain scores, slices, IDs and limits without raw passages. The evidence-window results are still imperfect: 14 lexical cases miss every annotated anchor in the first response, and cross-source/constraint tasks can need further reading. Focused follow-up search/read is part of the supported workflow. This report does not claim autonomous answer faithfulness or exhaustive relevance.

## Full research workflow review

Three [original worked examples](../examples/research/) exercise Indonesian TTS on a 16 GB Apple Silicon Mac, local image-to-video with 12 GB VRAM, and a bounded repository agent trial. They are authored interpretations and proposed experiments, not automatically generated or production-qualified recommendations.

The final lexical packets contain 3/4/3 profiles, 6/8/6 facts and two passages each. Exact compact JSON sizes are 16,559 /17,666 /16,822 characters under an 18,000-character whole-packet cap. Deduplicated evidence registries, original URL/date/freshness, full hashes, line ranges and passage coordinates all validated. Omitted required facts are flagged separately from unknown facts.

A reviewer performed 31 actual supplemental CLI actions, including focused facts for all 12 named candidates, exact reads and targeted searches. Thirteen source versions and 41 cited ranges supported the three briefs; no material unsupported factual claim was found. Unknown Mac/runtime compatibility, complete-pipeline memory, current licenses/access and production reliability stay open. Broad-query context such as Bonsai or a MiniMax model announcement was not used as proof for an unrelated video/coding tool. One packet alone did not produce each four-candidate brief.

This is a manual boundary/support review of three examples, not a scored universal recommendation benchmark. `facts` can still be context-heavy (roughly 11.6–20.3k pretty-JSON characters per focused candidate in this run); use bounded research packets and targeted reads for context control.

## Efficiency and software verification

A real incremental update rediscovered 433 Videos entries, visited 58 retained/boundary records, fetched zero video descriptions and queued zero reference downloads. The scope remained May 1; source/access gaps remained visible. Good retained evidence never hides fresh refresh failures in the update status.

The first local semantic build encoded 4,163 unique texts into 4,165 segments in 785.8 seconds on CPU 2, writing an approximately88 MB index. Adding the typed records reused 4,165 segments and encoded 45 new texts in 73.3 seconds. A later cached rebuild encoded zero texts but still took 47.6 seconds; this exposed redundant segmentation. The final whole-index reuse path checks evidence hash/configuration before loading runtime or tokenizer: the unchanged semantic step reused the artifact in11 ms with zero encoding. This fast path states that runtime/model revalidation has not occurred; actual semantic queries still verify backend/artifact identity.

Pinned multilingual E5-small assets total 492,421,556 bytes. No remote repository Python or cloud embedding/synthesis API is executed. Real semantic inference was tested on the owner's Mac; cross-platform CI uses injected synthetic encoders and does not claim real ONNX execution on every OS.

The final local suite has 144 tests covering growing scope, extraction quality/raw history, immutable citations, literal typed-value binding, aliases, filters, budgets, review state, fallback, cache reuse, CLI/workflow locking and UTF-8. Main implementation `c6d75a0` passed macOS/Python3.14, Linux/Python3.11 and Windows/Python3.14 in [CI run 41390113641](https://github.com/hanafishiddiq/ai-search-knowledge/actions/runs/41390113641). The named-profile follow-up has its own final CI receipt recorded in STATUS.

## Reproduce and observe

```sh
uv sync --locked --dev
uv run pytest -q
uv run aisk status
uv run aisk research 'Audio8 Indonesian narration Mac' --required supports_language --required runs_on --required license --max-chars 12000
uv run aisk evaluate --mode lexical
# Optional, after explicit local model setup:
uv run aisk evaluate --mode semantic --mode hybrid
```

Expected: tests pass; research uses lexical by default, stays inside its compact whole-JSON budget and preserves unknown/omitted requirements with valid source refs. Observe versions, context, dates and conditions before interpreting facts. Evaluation requires a local corpus matching the fixture hashes; changed source versions should return `fixture_stale`, not a misleading accuracy score.

No schedule, video/audio inference test, paid provider setup or unattended adoption/deployment was installed.
