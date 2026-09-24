---
name: exa
description: Web search, content retrieval, and question answering via Exa API. Search with filters, get page contents, find similar pages, and get cited answers.
---

# Exa

Web search API for AI. Requires `EXA_API_KEY` env var.

All commands use: `uv run --with exa-py python3 -c '...'`

## Search

```bash
# Basic search (returns text by default)
uv run --with exa-py python3 -c "
from exa_py import Exa
exa = Exa(api_key=None)  # reads EXA_API_KEY from env
results = exa.search('your query here', num_results=5, contents={'highlights': True})
for r in results.results:
    print(r.title, '|', r.url)
    if r.highlights: print('  ', r.highlights[0][:200])
"
```

### Filters

```python
results = exa.search(
    'query',
    num_results=10,                              # default 10
    include_domains=['reuters.com', 'bbc.com'],  # restrict to domains
    exclude_domains=['reddit.com'],              # exclude domains
    start_published_date='2025-01-01',           # ISO date
    end_published_date='2025-12-31',
    include_text=['python'],                     # must contain
    exclude_text=['javascript'],                 # must not contain
    category='news',                             # see categories below
)
```

**Categories**: `company`, `news`, `research paper`, `tweet`, `github`, `linkedin profile`, `pdf`, `personal site`, `song`, `movie`, `book`

### Contents options

```python
contents={'highlights': True}                    # key excerpts
contents={'text': {'max_characters': 5000}}      # full text (default 10000)
contents={'summary': True}                       # AI summary
contents=False                                   # metadata only (fastest)
```

### Structured output

```python
results = exa.search(
    'top AI startups 2025',
    type='auto',
    output_schema={
        'type': 'object',
        'properties': {
            'companies': {'type': 'array', 'items': {'type': 'string'}},
            'summary': {'type': 'string'}
        },
        'required': ['companies', 'summary']
    },
    contents=False
)
print(results.output.content)  # parsed dict
```

## Answer (search + LLM)

```bash
uv run --with exa-py python3 -c "
from exa_py import Exa
exa = Exa(api_key=None)  # reads EXA_API_KEY from env
resp = exa.answer('What is the population of Tokyo?')
print(resp.answer)
for c in resp.citations:
    print(f'  [{c.title}]({c.url})')
"
```

Options: `text=True` (include full citation text), `model='exa-pro'`, `system_prompt='...'`

## Find similar

```bash
uv run --with exa-py python3 -c "
from exa_py import Exa
exa = Exa(api_key=None)  # reads EXA_API_KEY from env
results = exa.find_similar('https://news.ycombinator.com', num_results=5, exclude_source_domain=True, contents=False)
for r in results.results:
    print(r.title, '|', r.url)
"
```

## Get contents

```bash
uv run --with exa-py python3 -c "
from exa_py import Exa
exa = Exa(api_key=None)  # reads EXA_API_KEY from env
results = exa.get_contents(['https://example.com'], text={'max_characters': 3000})
for r in results.results:
    print(r.text)
"
```

## Search types

| Type | Speed | Notes |
|------|-------|-------|
| `auto` | varies | Default, picks best type |
| `fast` | fast | Quick keyword-style |
| `neural` | medium | Semantic embedding search |
| `deep-lite` | slow | LLM-expanded queries |
| `deep` | slower | More thorough expansion |
| `deep-reasoning` | slowest | Multi-step reasoning |

Deep types (`deep-lite`, `deep`, `deep-reasoning`) support `additional_queries` to skip auto-expansion.

## Result fields

Each result has: `url`, `title`, `score`, `published_date`, `author`, `text`, `highlights`, `summary`
