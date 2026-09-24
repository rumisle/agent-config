---
name: pangram-classify
description: Classify text as AI-generated, human-written, AI-assisted, or mixed via Pangram's sliding-window detector at web.pangram.com. Reads text from CLI args (echo-style) or stdin. Returns the full JSON response. Use when the user wants to detect AI-generated text, score authorship, or hit Pangram from the terminal.
---

# Pangram Classify

CLI wrapper around `POST https://web.pangram.com/api/classify-text-sliding-window/`.
Each call costs **1 credit** from your Pangram account, so prefer one call over many.

## Prerequisites

Set both env vars from a logged-in https://www.pangram.com browser session
(DevTools → Application → Cookies / Storage):

```bash
export PANGRAM_SESSION_ID='...'     # value of the `sessionid` cookie
export PANGRAM_CSRF_TOKEN='...'     # value sent as `X-CSRFToken` header (Django session-bound CSRF; the header alone suffices, no csrftoken cookie needed)
```

Both are required: dropping the CSRF token returns `403 {"detail":"CSRF Failed: CSRF token missing."}`.
They rotate when you log out / sessions expire — re-extract from the browser if you start getting 403s.

Also required:

```bash
export PANGRAM_DISTINCT_ID='you@example.com'   # analytics id
```

## Usage

```bash
# Echo-style positional args (joined with spaces)
{baseDir}/pangram.py The quick brown fox jumps over the lazy dog ...

# Stdin (preferred for multi-line / long text)
cat essay.txt | {baseDir}/pangram.py
echo "long passage..." | {baseDir}/pangram.py --pretty

# One-shot creds via flags
{baseDir}/pangram.py --session-id "$SID" --csrf-token "$CSRF" "text..."

# Disable server-side logging of the submission
echo "..." | {baseDir}/pangram.py --no-logging
```

JSON is written to stdout. Use `--pretty` for indented output.

## Args

| Arg | Description | Default |
|-----|-------------|---------|
| `text...` | Positional words, joined with spaces. Omit to read stdin. | stdin |
| `--session-id` | `sessionid` cookie value | env `PANGRAM_SESSION_ID` |
| `--csrf-token` | `X-CSRFToken` header value | env `PANGRAM_CSRF_TOKEN` |
| `--distinct-id` | Analytics distinctId in body | env `PANGRAM_DISTINCT_ID` |
| `--source` | `source` field in body | `product` |
| `--no-logging` | Send `logging=false` | logging=true |
| `--pretty` | Indent JSON | compact |
| `--timeout` | HTTP timeout (s) | `120` |

## Input requirements

- **Minimum ~50 words.** Shorter text returns HTTP 422 `{"error":"Please submit at least 50 words for an accurate prediction."}`.
- Submission text is truncated/windowed server-side (~512 chars per window).

## Response JSON

Top-level fields (verified against a real response):

| Field | Type | Meaning |
|-------|------|---------|
| `prediction` | string | Plain-English verdict, e.g. `"We believe that this document is fully AI-generated"` |
| `category_label` | string | Short verdict — `"AI"`, `"Human"`, `"Mixed"`, `"AI-Assisted"` |
| `ai_likelihood` | float (0–1) | Overall AI-likelihood, same as `response.overall.ai_likelihood` |
| `text` | string | Echo of the (truncated) submitted text |
| `credits_remaining` | int | Pangram credits left on the account after this call |
| `textquery_uuid` | string | UUID for this query; visible at `https://www.pangram.com/textquery/<uuid>` |
| `textquery_is_public` | bool | Whether the textquery page is publicly shareable |
| `disableLogging` | bool | Mirrors what the server stored for `logging` |
| `is_guest` | bool | Whether the call was made as a guest user |
| `response.overall` | object | Whole-document analysis (see below) |
| `response.in_page` | object | Per-page slice with richer per-window detail (see below) |

### `response.overall`

| Field | Type | Meaning |
|-------|------|---------|
| `prediction` | string | Same long-form verdict as top-level `prediction` |
| `prediction_short` | string | `"AI"` / `"Human"` / `"Mixed"` / `"AI-Assisted"` |
| `headline` | string | UI headline, e.g. `"AI Generated"`, `"Human Written"` |
| `word_count` | int | Words in the submitted text |
| `fraction_ai` | float (0–1) | Share of text predicted AI |
| `fraction_ai_assisted` | float (0–1) | Share predicted AI-assisted |
| `fraction_human` | float (0–1) | Share predicted human |
| `fraction_mixed` | float \| null | Share predicted mixed |
| `ai_segments` / `ai_assisted_segments` / `human_segments` | int | Count of windows in each bucket |
| `avg_ai_likelihood` | float (0–1) | Mean AI-likelihood across windows |
| `max_ai_likelihood` | float (0–1) | Max AI-likelihood across windows |
| `ai_likelihood` | float (0–1) | Overall AI-likelihood score |
| `window_likelihoods` | float[] | Per-window AI-likelihoods, parallel to `windows` |
| `window_indices` | [int, int][] | `[start_char, end_char]` per window |
| `window_per_page` | int | Window batching used by the UI (typically 20) |
| `fraction_breakdown` | object | Nested confidence buckets: `{ai: {high/medium/low-confidence}, ai-assisted: {lightly, moderately}, human: {high/medium/low-confidence}}` |
| `windows` | object[] | Sliding-window analyses (see below) |
| `pages` | object[] | Page slices: `{page_index, start_index, end_index, window_indices: {start, end}}` |
| `ngram` | object | `{text, keywords}` from the n-gram pass |
| `plagiarism` | object \| null | Plagiarism subreport (null when not run) |
| `version` | string | Model/pipeline version (e.g. `"3.3.2"`) |
| `isPremium` | bool | Whether the response used the premium model |
| `metadata` | object | Misc server metadata (often `{}`) |
| `text` | string | Truncated preview of the submitted text |

### `response.overall.windows[]` and `response.in_page.windows[]`

Each window is one sliding-window slice of the text:

| Field | Type | Meaning |
|-------|------|---------|
| `text` | string | The window's text (truncated in `overall`, full in `in_page`) |
| `label` | string | `"AI-Generated"`, `"Human"`, `"AI-Assisted"`, `"Mixed"` |
| `confidence` | string | `"High"`, `"Medium"`, `"Low"` |
| `ai_likelihood` | float (0–1) | AI-likelihood for this window |
| `ai_graph_visualization` | float (0–1) | Smoothed value used by the UI bar |
| `start_index` / `end_index` | int | Character offsets within the document |
| `word_count` | int | Words in this window |
| `token_length` | int | Tokens in this window (`in_page` only) |
| `window_index` | int | 0-based index |
| `editlens` | object | Edit-likelihood subreport: `prediction_text`, `confidence_score`, `edit_score_prediction`, `edit_bucket_prediction`, `edit_bucket_probabilities[]` (richer in `in_page`, just `{prediction_text}` in `overall`) |

### Quick reads

```bash
# Just the verdict
echo "long text..." | {baseDir}/pangram.py | jq -r '.prediction'

# Score + category
echo "long text..." | {baseDir}/pangram.py | jq '{category: .category_label, score: .ai_likelihood, credits: .credits_remaining}'

# Per-window labels
echo "long text..." | {baseDir}/pangram.py | jq '.response.overall.windows[] | {start: .start_index, end: .end_index, label, confidence, ai_likelihood}'
```

## Errors

| HTTP | Body | Cause |
|------|------|-------|
| 403 | `{"detail":"CSRF Failed: CSRF token missing."}` | Missing/wrong `X-CSRFToken` |
| 403 | `{"detail":"Authentication credentials were not provided."}` | Missing/expired `sessionid` |
| 422 | `{"error":"Please submit at least 50 words for an accurate prediction."}` | Text too short |

On any non-200, the script prints `pangram: HTTP <code>: <body>` to stderr and exits 1.

## Credit safety

- Each successful call costs **1 credit**. Check `credits_remaining` in the response to track usage.
- Do not loop the script across many inputs without batching/caching — there is no client-side rate limit.
- Use `--no-logging` if you don't want the submission stored server-side.
