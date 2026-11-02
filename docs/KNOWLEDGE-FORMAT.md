# Typed technology knowledge

Store an original JSON record locally and submit it through `aisk validate-knowledge FILE` / `aisk add-knowledge FILE`. Run `aisk index` afterward. The authoritative allowed entity types and predicates are `ENTITY_TYPES` and `PREDICATES` in `src/ai_search_knowledge/knowledge.py`.

```json
{
  "id": "example-speech",
  "title": "Example speech release",
  "as_of": "2026-11-02",
  "entities": [
    {"id":"model:example-speech","type":"model_release","name":"Example Speech","aliases":["Example TTS"]},
    {"id":"language:indonesian","type":"language","name":"Indonesian","aliases":["Bahasa Indonesia"]}
  ],
  "claims": [{
    "id":"indonesian",
    "subject":"model:example-speech",
    "predicate":"supports_language",
    "object_entity":"language:indonesian",
    "value":"Indonesian",
    "value_text":"Indonesian",
    "statement":"The publisher reports Indonesian support.",
    "assertion_kind":"publisher_reported",
    "conditions":{"verification":"Not independently tested"},
    "evidence":[{"source_id":"REPLACE_20_HEX","text_sha256":"REPLACE_FULL_64_HEX","start_line":15,"end_line":16}]
  }],
  "limitations":["Reported support does not establish quality for a particular voice or workload."],
  "gaps":["Mac runtime support and exact license terms require separate evidence."]
}
```

The placeholders intentionally do not pass validation. Use a real retained source version and exact source-text lines. An optional short `quote` must appear in those lines. `value_text` is a literal source anchor, separate from the readable original `statement`. Conditions preserve units, version, hardware, precision, test protocol and scope. Do not turn a tested device into an unsupported compatibility claim.

Stable entity IDs must retain the same type and name across records; aliases can enrich the same entity. Related entities without subject facts are not emitted as empty technology recommendations. `object_entity` creates an explicit traversable relationship; absent edges are not proof of incompatibility.

The validator checks source/Markdown integrity, literal support and narrow scalar normalization. Complex machine-readable values and semantic interpretation remain curator responsibilities; inspect the returned validation labels. A number or anchor alone does not prove that the predicate or conclusion is justified. Source claims are not independent runtime tests. Validate negation, table headings, conditions and licensing scope manually.

Existing records receive version history when materially changed. Evidence keeps original full text hashes and freshness flags; historical citations remain resolvable. Admission marks only the cited source ranges partial. A whole-source review is a separate explicit attestation.

Generated JSON records and rendered knowledge remain local by default. Any public examples must contain only original concise synthesis, metadata and appropriately short source anchors, never bulk source text or machine-specific paths.
