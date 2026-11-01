# Evidence-backed note format

Create a local JSON file with this structure. The values below are synthetic placeholders; obtain real IDs, hashes and line numbers from `aisk work`, `aisk search` and `aisk read`.

```json
{
  "id": "example-topic",
  "title": "A specific, searchable topic title",
  "as_of": "2026-11-01",
  "topics": ["research", "memory"],
  "claims": [
    {
      "text": "The publisher reports a result under its stated evaluation conditions.",
      "evidence": [
        {
          "source_id": "00000000000000000000",
          "text_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
          "start_line": 15,
          "end_line": 20
        }
      ]
    }
  ],
  "limitations": ["The result has not been independently reproduced here."],
  "gaps": ["Hardware suitability for the user's machine has not been tested."]
}
```

Notes are original concise synthesis. Avoid copying long source passages. `as_of` records the date of this synthesis, not a guessed release date. Each evidence range must point into source text, after the generated provenance header. A source's current text hash must match the cited hash; retain outdated notes in history, then update their evidence before reindexing.

The public code license does not grant rights to third-party source text or model weights. A note about a project's license records what that source says at the time; it does not replace reviewing its actual license files for an intended use.
