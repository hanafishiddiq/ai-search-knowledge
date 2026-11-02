# Research library v2 — implementation and acceptance plan

Started 2026-11-02 against baseline `2dfca14`. Goal: [GOALS.md](GOALS.md). This plan describes the authorized build; progress and measured acceptance results will be recorded separately.

## Delivery outcome

An AI assistant can take a project's technology requirements, retrieve compact relevant evidence in English or Indonesian, inspect dated/typed technology claims and relationships, compare supported capabilities and unknowns, and prepare a source-backed research brief. The archive grows from its initial seed and retains verifiable historical evidence. Collection success, extraction quality, review coverage and recommendation support are separate concepts.

## Implementation slices

1. **Archive/evidence integrity:** persist the initial date floor; retain prior eligible videos, source versions and citations. Resolve current and historical evidence by full text hash. Never age out knowledge through a rolling lookback.
2. **Source normalization and quality:** recover substantive static page sections, detect footer/waitlist/service/listing text, handle JSON as data, omit encoded binary payloads from derived text and expose extraction limitations. Reprocess stored raw evidence before using new network requests.
3. **Retrieval:** enforce hard output limits, preserve exact immutable evidence locations through transformed excerpts, select query-covering windows, support explicit date/quality/role filters, evaluate multilingual lexical expansion and optional local semantic retrieval.
4. **Research knowledge:** dated entities and supported typed claims, an evidence-linked relationship index, a review ledger distinct from source-use, and a bounded research-pack interface for an external AI. Unknown hardware/licensing/availability remains unknown. No hidden model invocation or fabricated recommendation.
5. **Evaluation:** source-grounded exact, paraphrase, Indonesian, temporal, comparison, hardware/constraint and unanswerable tasks. Measure evidence hits/spans, claim support, missing evidence, context size, latency and ingest/update cost. Compare optional semantic/hybrid against the improved lexical baseline.
6. **Release:** independent code/spec review, local and cross-platform checks, public-export inspection, documentation, and publication of code plus safe metadata/original synthesis. Preserve full source snapshots locally. Scheduling remains undecided and is not installed.

## Observable interfaces under test

- Collection/archive API: fixed seed floor, incremental reuse, source failures and quality flags; does not establish audiovisual understanding.
- Evidence/knowledge admission API: real source versions, exact spans, typed predicates and historical freshness; mechanical validation does not establish truth.
- Search/research API and CLI: relevant evidence within a strict budget, explicit filters/modes and unknowns; no claim that an isolated lookup is a completed technology decision.
- Optional semantic adapter: explicit availability, cached local vectors, source/span identity and index freshness; no silent cloud calls or implicit semantic-success claim on fallback.

## Required acceptance checks

- Existing captured long-form videos remain usable after the original six-month boundary; Shorts remain excluded.
- The observed 46,325-character payload cannot violate a 1,400-character excerpt request. Raw evidence and original note citations survive normalization/reprocessing.
- ASPIRE extraction contains its substantive method/sections; the observed Genesis waitlist/footer is not counted as complete article evidence.
- The known Audio8 Indonesian/codec question retrieves the requested evidence, not only usage boilerplate. Indonesian and paraphrase cases are evaluated separately.
- Date filtering distinguishes video publication from source publication and treats unknown dates explicitly.
- Historical source references remain resolvable, with freshness surfaced; nonexistent hashes or unsupported spans are rejected.
- A source cited once is not marked fully reviewed. Research output preserves unresolved constraints and does not infer Mac support from H200 results.
- Unchanged inputs reuse derived work where practical; measurements distinguish network reuse, index rebuilds, embedding work and external AI reasoning.

## Architecture selection gate

Keep the evidence archive and SQLite lexical index as a measured baseline. Add a lightweight typed evidence graph for supported technology facts and relationships. Evaluate one optional local multilingual semantic backend with no paid/cloud calls. Graphify remains a possible adapter/pilot; a code graph alone does not satisfy document knowledge goals. Choose or retain components based on judged evidence quality and cost, not graph/node counts.

## Work boundaries

Implementation is isolated in a repository worktree. Agent file ownership separates ingestion, retrieval and semantic adapter changes. The parent coordinates knowledge/research interfaces, corpus migration, evaluation and release. No raw third-party corpus, credentials, local machine paths or private logs are published.
