# Architecture audit — 2026-11-01

This audit inspected the current implementation and local corpus with three independent subagents. It did not install software, build a Graphify graph, call a synthesis/embedding model, change the corpus/index, or migrate the implementation. Measurements are local snapshots, not a production answer-quality benchmark.

## Verdict

The system is a local evidence archive, lexical retrieval index and cited-note registry. It has useful network caching and provenance, but it is not yet an optimized knowledge system. It has no entity/concept knowledge graph, Graphify integration, embedding retrieval, reranker or autonomous synthesis loop. Retrieval speed is adequate at the observed size; content quality, evidence selection and output budgets need work first.

```mermaid
flowchart LR
  Y[YouTube descriptions and chapters] --> S[Linked source documents]
  S --> A[Versioned JSON and Markdown archive]
  A --> F[SQLite FTS5 and BM25]
  F --> X[External AI reads evidence]
  X --> N[Cited knowledge notes]
  N --> F
```

The existing JSON relations connect videos, URLs and nine explicitly followed primary artifacts. They establish provenance. They do not express model/version/capability/license/benchmark relationships or traverse such a graph. `update()` performs collection and indexing; the calling AI must separately read, interpret and author notes.

Implementation evidence: `src/ai_search_knowledge/sources.py:23`, `src/ai_search_knowledge/library.py:149`, `src/ai_search_knowledge/library.py:254`, `src/ai_search_knowledge/workflow.py:53`, `src/ai_search_knowledge/workflow.py:77`.

## Measured baseline

- SQLite: 17,702,912 bytes; 629 documents (55 descriptions, 569 source records, 5 notes); 1,520 passages.
- Twenty queries, five repeated direct calls each: median 7.49 ms, approximate p95 19.58 ms. This excludes process startup, tool calls and AI reasoning.
- Three warm `uv run aisk search` processes: median 686.23 ms. A Python module CLI median was 594.66 ms. These small samples include imports/serialization and exclude AI/tool overhead.
- A stored incremental collection reused fresh data with zero video/source fetches. It still rediscovered the channel and rebuilt the entire local index; total observed run time was 10.60 seconds.
- A known-positive smoke set found the expected source in the top five for 15/17 cases. Exact names were 5/5; direct Indonesian queries were 1/3. The targets were biased toward five already-known note topics, so this is not general accuracy, recall or answer correctness. The documented external assistant can translate/rewrite queries, which was not measured here.

No observed performance bottleneck justifies replacing SQLite with a graph database. A semantic graph may improve relationship questions; that is a separate hypothesis requiring evaluation.

## Verified limitations, in priority order

1. **Extracted text is not consistently complete or relevant.** All 569 successful records remain explicitly unreviewed. NVIDIA ASPIRE stored only 348 characters although retained static HTML contains 8,204 visible characters. One Genesis article URL stored waitlist/footer text. Some source pages need re-extraction or a different reader even though their status is `ok`.
2. **The output limit is not a hard bound.** Query `平均分数与推理成本关系图`, `kind=source`, `max_chars=1400` returned 46,325 characters from one embedded SVG data URI. Source ID: `db9ca812eb17b8c3b05a`. Long lines bypass the first-line preview check. This was reproduced by the primary agent; it is an unresolved efficiency defect, not a hypothetical concern.
3. **Correct document selection can return the wrong excerpt.** `Audio8 Indonesian codec` selected the relevant model card, but its 1,361-character preview contained neither “Indonesian” nor “codec”; it returned usage boilerplate. The caller must perform another read to get supporting evidence.
4. **Temporal and relationship metadata is incomplete.** Structured source publication dates exist for 112/569 records. Exact label matching links 479/1,039 chapter timestamps to sources. Some remaining chapters are introductions, sponsorships or differently labelled sections; these counts measure metadata/association coverage, not information recall.
5. **Knowledge review is incomplete.** Five notes contain 14 claims citing six source records. One citation marks a source/hash as used by the reading queue; there is no per-section review ledger. Hash/line validation checks mechanical references, not whether the claim is supported.
6. **Some work remains external.** Forty-six sources required browser imports, which `update()` does not automatically perform. No synthesis model, scheduled runner or automatic answer generator is implemented. Query dates, hardware and licensing constraints are not typed filters.

The prior functional tests remain useful evidence for the behavior they test. They do not establish semantic retrieval quality, complete extraction or the absence of oversized output. The 35 failed/incomplete URLs are therefore not the complete list of quality gaps.

## Graphify assessment

Graphify is installed globally as `graphifyy` 0.9.12, but this project has no Graphify output or dependency. Its official [architecture documentation](https://docs.graphify.com/concepts/architecture) distinguishes deterministic local code extraction from model-assisted extraction of document concepts/relations. Document graph construction has model/context cost; a free code-AST path is not evidence of free semantic processing for this corpus.

A knowledge graph is a representation of entities and relationships; Graphify is one tool for producing and navigating such graphs. Graph traversal is not itself a guarantee of multilingual semantic matching or correct facts. It cannot recover article content missing from its input. Its benefit here must be compared with the existing bounded-retrieval design after the current output bug is fixed.

Any Graphify pilot should use selected active, cleaned source snapshots. Running it against the repository root can instead analyze crawler code while `.gitignore` excludes `data/` and `knowledge/`; including all raw/history files can duplicate versions and waste extraction context. Preserve source hashes, line evidence, dates and explicit/inferred/ambiguous relationship distinctions.

## Recommended next architecture — proposal, not implementation

1. Re-extract retained HTML where content was lost; distinguish article text, index/listing pages, promotional/service links and incomplete media. Remove embedded payload/site chrome from derived retrieval text without losing raw evidence or citation-version integrity. Enforce hard output limits and select query-covering passages.
2. Create a judged set of real questions covering exact lookup, paraphrases, Indonesian, versions/dates, comparisons, constraints and unanswered questions. Measure evidence relevance, citation support, completeness, latency, context size and update/model cost.
3. Keep FTS as the baseline. Compare improved query rewriting/aliases with multilingual semantic retrieval and reranking. Choose the simplest measured winner for each query class.
4. Introduce dated structured records for organizations, model releases, capabilities, hardware/benchmark conditions and claims with supporting passages. Add a small typed evidence graph for relationship questions that benefit from it. This does not require a graph server at the current size.
5. Test Graphify on a bounded subset as a candidate extraction/exploration adapter. Compare FTS, hybrid retrieval, and hybrid-plus-graph using the same judged evidence set before choosing a broader integration.

Detailed audit receipts are local and ignored by Git: `scratch/architecture-audit/retrieval/REPORT.md`, `scratch/architecture-audit/pipeline/audit.md`, `scratch/architecture-audit/graphify/comparison.md`, and their measurement JSON files. No proposed retrieval/graph migration has been carried out.
