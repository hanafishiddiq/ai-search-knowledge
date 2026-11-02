# Retained-source evaluation

`research-cases.json` has 40 source-grounded development questions, 23 English/17 Indonesian, with known relevant IDs, full retained text hashes, short literal anchors, expected facts and required unknowns. Questions were authored from direct source reading before retrieval, then used to diagnose changes. They are not a held-out universal answer benchmark.

`results-2026-11-02.json` records final lexical/semantic/hybrid diagnostics, baseline comparison and the decision to default to improved lexical retrieval. Original source snapshots are local; the public fixture does not distribute them.

Run `uv run aisk evaluate --mode lexical` after collecting matching source versions. A changed hash yields `fixture_stale`; re-annotation is required before interpreting scores. Document hit, literal evidence-window hit, provenance fidelity and full answer support are separate measures. Partial/unsupported questions still have relevant context sources, so retrieving them does not prove an answer or safe abstention.

See [VALIDATION-V2.md](../docs/VALIDATION-V2.md) for metrics, manual research review, cost and limits.
