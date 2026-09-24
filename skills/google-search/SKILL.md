---
name: google-search
description: Google search via Serper API. Search the web with country, language, and date filters.
---

# Google Search

Search Google via serper.dev API.

## Usage

```bash
# Basic search
{baseDir}/search.py "apple inc"

# With country and language
{baseDir}/search.py "apple inc" -c cn -l zh-cn

# With date range (past hour)
{baseDir}/search.py "breaking news" -t qdr:h

# All options
{baseDir}/search.py "query" -c jp -l ja -t qdr:d --no-autocorrect

# Parse with jq
{baseDir}/search.py "apple" | jq '.organic[0].title'
```

## Args

| Arg | Description | Example |
|-----|-------------|---------|
| `query` | Search query (required) | `"apple inc"` |
| `-c, --country` | Country code | `cn`, `us`, `jp` |
| `-l, --language` | Language code | `zh-cn`, `en`, `ja` |
| `-t, --time` | Date range | See below |
| `--no-autocorrect` | Disable autocorrect | - |

### Date Range Values (`-t`)

- `qdr:h` - Past hour
- `qdr:d` - Past day
- `qdr:w` - Past week
- `qdr:m` - Past month
- `qdr:y` - Past year

## Output Schema

Returns JSON. Use `jq` to parse.

```
{
  "searchParameters": { "q", "gl", "hl", "type" },
  "organic": [                    # Main results
    { "title", "link", "snippet", "position" }
  ]
}
```
