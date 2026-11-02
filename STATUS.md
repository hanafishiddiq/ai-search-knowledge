# Status

Observed 2026-11-02, Asia/Jakarta. Goal: [evidence-backed technology research and selection](docs/GOALS.md). Six months is the initial seed; the archive now grows without aging captured knowledge out.

**Research library v2 is implemented. Exhaustive corpus understanding is unfinished.** The system provides versioned evidence, improved lexical retrieval, optional local multilingual retrieval, typed evidence relationships, explicit review states and budgeted research packets. The calling AI still interprets the evidence and prepares a decision. See [architecture](docs/RESEARCH-V2.md) and [measured validation](docs/VALIDATION-V2.md).

1. **Acquisition and archive:** 55 long-form videos, 1,039 chapters; fixed initial floor 2026-05-01. A real incremental update fetched zero descriptions and queued zero source downloads. Shorts remain excluded; old descriptions/source relationships and source text versions remain attributable.
2. **Source normalization:** 535 adequate sources out of 604 reference URLs. The 69 remaining access/extraction/discovery gaps include 22 discovery-only pages. Lower adequate counts than the old569 reflect stricter quality classification and recovered text, not deletion of history. The previous unsupported JSON download is recovered.
3. **Knowledge and research:** 15 typed profiles, 37 entities, 85 attributed claims, five older prose notes and three source-reviewed research examples. Review ledger: 16 current sources partial, 519 pending, none complete. Audiovisual content remains unreviewed.
4. **Retrieval acceptance:** improved lexical finds a known relevant document for 39/40 development questions and a literal anchor for 26/40; every returned range and excerpt budget validates. Original library/index scored 38/12. Semantic scored 31/19 and hybrid 36/26 and were slower, so lexical is the default. These are diagnostic development results, not universal accuracy or automatic recommendation quality.
5. **Reusable public delivery:** public MIT [hanafishiddiq/ai-search-knowledge](https://github.com/hanafishiddiq/ai-search-knowledge), with code, metadata, original fact export, judged questions/results and research examples. Full source snapshots, model weights and private runtime artifacts remain local.

Final local checks: 144 tests. Final code `2df0a41` passed macOS/Python 3.14, Linux/Python 3.11 and Windows/Python 3.14 in [CI 41390715622](https://github.com/hanafishiddiq/ai-search-knowledge/actions/runs/41390715622). Code and data provenance are separate from independent scientific/runtime validation.

Remaining work toward complete knowledge coverage: prioritize unresolved source/discovery gaps by question, expand verified topic/claim review beyond selected profiles, account for narration/visual demonstrations when material, and maintain a larger held-out end-to-end decision evaluation. Current prices, access, licensing and platform compatibility may need a fresh owning-source check before adoption. Public facts are snapshot synthesis, not guaranteed current advice.

No schedule is installed. Owner action/blocker for this v2 delivery: none. Scheduling and any subsequent paid/runtime experiments remain later decisions.
