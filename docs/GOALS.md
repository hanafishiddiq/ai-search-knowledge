# System goal and definition of effectiveness

Defined with the owner on 2026-11-02, Asia/Jakarta. This is the canonical goal for subsequent design and acceptance work. Technology choices remain implementation candidates, not the goal.

## Owner-confirmed decisions

1. Primary job: help an AI agent research and select technology for projects/work.
2. Initial acquisition covers six months of AI Search long-form videos; Shorts are excluded. The initial observed collection window was 2026-05-01 through 2026-11-01 in Asia/Jakarta.
3. After the initial acquisition, the archive grows. Knowledge must not disappear from active use simply because it becomes older than six months. This supersedes the previously documented rolling-six-month assumption.
4. The existing local-first library and public reusable repository remain in scope. Source material retains original language; reusable authored knowledge uses English. Scheduling is a later decision.

## Goal

Build a continuously growing, evidence-backed technology knowledge base from AI Search long-form videos and their original references, so an AI agent can understand a project's needs, identify relevant technologies, compare their suitability, and propose justified choices with clear sources, versions, dates, conditions and unknowns—while reusing stored knowledge and minimizing unnecessary rereading and browsing.

The useful outcome is a better-supported technical decision. File counts, graph size, a particular library, or a successful crawl are intermediate measures.

## What the AI must be able to do

- Understand the task and material constraints: intended output, hardware/platform, local/cloud preference, budget, privacy, commercial use and maturity requirements when relevant. Obtain missing constraints only when they could change the choice.
- Discover relevant candidates even when the request uses different words or Indonesian while sources use English or another language.
- Compare candidates using the evidence that matters for the request: capabilities, versions, access, hardware, reported benchmarks and their conditions, costs/licensing when relevant, limitations and project maturity. Do not pad the answer with unsupported candidates.
- Explain a recommendation and alternatives, including practical tradeoffs and the next validation needed before adoption. Publisher claims, preprints, demonstrations and independently tested behavior remain distinguishable.
- Trace factual claims to original source evidence, with dates and video timestamps where available. Missing dates, uncertain mappings and missing evidence stay explicit.
- Distinguish historical information, newer releases, superseded claims and information that requires a fresh check. Archived material must not be presented as guaranteed current availability, pricing or compatibility.
- Identify questions the stored evidence cannot support and state what is missing. In particular, a benchmark on an H200 does not establish Mac compatibility.

## Knowledge coverage

Track material technology topics and substantive claims discussed in the in-scope videos. Capture technical details and conditions that affect interpretation or selection. Intros, repeated calls to action and unrelated shopping links do not establish topic coverage.

Descriptions and linked primary documents are the discovery/evidence foundation. Information specific to a video's narration, comparison or demonstration must be accounted for when material; if it has not been reviewed, record the gap. Source text alone must not be labelled as understanding all audiovisual content.

Keep original source evidence and version history available alongside derived facts/notes. A source being cited once does not mean every relevant section has been reviewed. Collection, extraction quality, topic coverage, review state and answer quality require separate measures.

## Working acceptance criteria

These criteria define what a useful result must demonstrate. Numeric quality, latency and context-budget targets will be calibrated with a representative judged question set before selecting an architecture.

| Dimension | Observable result |
|---|---|
| Decision usefulness | The answer addresses the project's constraints, proposes relevant choices and explains why each fits or fails. |
| Evidence support | Material factual claims have supporting passages; versions, units, conditions and uncertainty are preserved. |
| Coverage | Relevant topics and unresolved evidence are accounted for; extraction success is not used as a proxy for completeness. |
| Temporal correctness | Historical claims and current recommendations are distinguished; conflicting or superseded information is surfaced. |
| Honest limits | Unsupported compatibility, benchmark generalization, availability or licensing conclusions are not invented. |
| Retrieval efficiency | The AI receives relevant compact evidence within an enforced budget instead of boilerplate, embedded payloads or the entire corpus. |
| Update efficiency | Reuse unchanged evidence and derived knowledge; process new/materially changed inputs and retain prior versions. |
| Reusability | Another AI can follow the documented interface and provenance without depending on this chat's memory. |

Evaluate the full research/answer workflow, including any external AI query rewriting; isolated search speed and functional unit tests are insufficient.

## Representative tasks to judge

1. Select Indonesian TTS options for a stated narration workload and machine/budget; explain model-size conventions, evaluation limitations and what still needs testing.
2. Compare local video-generation approaches against a stated memory/platform requirement; distinguish measured compatibility from assumptions and keep benchmark conditions intact.
3. Decide whether a newly covered research method is usable for a project now or is still a paper/demo, citing evidence about implementation and access.
4. Explain what changed between releases over time and whether the change affects an existing project's technology choice.
5. Handle a plausible request for which the corpus lacks sufficient evidence without producing a confident fabricated recommendation.

These are evaluation scenarios, not present-day product recommendations.

## Current implementation gap

The existing collector still applies a rolling six-month scope in metadata/manifest/index processing. It does not yet implement the newly confirmed growing-archive policy. Resolve that mismatch before the next acquisition/index update so previously captured knowledge remains available.

The latest architecture audit also records incomplete extraction, a preview-budget defect, imperfect query windows and incomplete review/synthesis. See [ARCHITECTURE-AUDIT-2026-11-01.md](ARCHITECTURE-AUDIT-2026-11-01.md). The system has not yet met the acceptance criteria above.

Graphify, multilingual semantic retrieval, typed knowledge graphs and other tools may be evaluated against these goals. None has been selected merely by appearing in this document. No scheduling or runtime migration was performed while defining this goal.
