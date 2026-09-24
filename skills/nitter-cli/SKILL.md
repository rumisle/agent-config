---
name: nitter-cli
description: Twitter/X data via Nitter. Fetch tweets, user timelines, profiles, and search.
---

# Nitter CLI

Fetch Twitter/X data via Nitter. Returns JSON.

## Commands

```bash
# Fetch tweet with conversation (parents, children, replies)
{baseDir}/nitter.py status <username> <tweet_id> [--pretty]

# Fetch user profile + timeline
{baseDir}/nitter.py user <username> [--tab tweets|with_replies|media] [--cursor <cursor>] [--pretty]

# Search tweets or users
{baseDir}/nitter.py search "<query>" [--kind tweets|users] [--user <username>] [--cursor <cursor>] [--pretty]
```

## Search Operators

Use in query string: `from:user`, `to:user`, `@user`, `#tag`, `since:YYYY-MM-DD`, `until:YYYY-MM-DD`, `filter:media|images|videos|links|news`, `-filter:retweets|replies`, `"exact phrase"`, `word1 OR word2`, `list:user/list-name`.

Example: `"rust filter:links -filter:retweets since:2024-01-01"`

## Output

JSON to stdout. Pagination via `cursor` field—pass back with `--cursor`. Use `--pretty` for indented output.

To convert Nitter URLs to X: `https://x.com/<handle>/status/<id>`
