# Optional browser snapshot import

Use an ordinary approved public browser or reader tool when a normal HTTP extraction is incomplete. Preserve the actual response, without inventing or paraphrasing its content:

```json
{
  "id": "EXISTING_SOURCE_ID",
  "url": "EXACT_URL_FROM_SOURCE_MANIFEST",
  "fetched_at": "2026-11-01T13:00:00Z",
  "tool_name": "Name of the browser/reader tool",
  "title": "Optional title actually observed on the page",
  "result": {
    "content": [{"type": "text", "text": "Actual returned page text or Markdown"}],
    "isError": false
  }
}
```

Then run `uv run aisk import-snapshot data/browser/SOURCE_ID.json` and rebuild the index. Only existing reference URLs are accepted. Tool errors, short snapshots and detected access challenges are rejected; robots-denied sources cannot use this fallback. The imported text remains unreviewed evidence. HTTP status, redirects and publication dates are not invented when the tool did not expose them.
