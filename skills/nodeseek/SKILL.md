---
name: nodeseek
description: "Read NodeSeek (nodeseek.com) forum threads from the terminal as Markdown or JSON. View posts by id/slug/URL with pagination, replies, images, code, and benchmark widgets. Pair with google-search (site: filters) to find post ids, since NodeSeek has no open search API."
---

# NodeSeek CLI

Read NodeSeek threads via `uvx nodeseek-cli`. Fetches a thread's server-rendered
HTML (no key, no login) and prints Markdown by default, or JSON with `--json`.

```bash
uvx nodeseek-cli <post> [options]
```

`<post>` = bare id, slug, or URL:

```bash
uvx nodeseek-cli 355740
uvx nodeseek-cli post-355740-1
uvx nodeseek-cli https://www.nodeseek.com/post-355740-1
```

## Options

| Option | Description |
|--------|-------------|
| `-p, --page N` | Fetch only page N (overrides page in the URL/slug) |
| `-a, --all` | Fetch and merge every page |
| `-j, --json` | JSON instead of Markdown |
| `--ansi` | Keep ANSI colour in code blocks (default: strip) |

Default fetches ONE page (page in the URL/slug, or page 1; ~20 comments each).
The Markdown footer shows how to reach the next page or the whole thread.

```bash
uvx nodeseek-cli 250906 --all
uvx nodeseek-cli post-250906-2
```

## Finding posts (use google-search)

No open search API, so find post ids with the `google-search` skill using a
`site:nodeseek.com` filter, then view them:

```bash
{google-search baseDir}/search.py "site:nodeseek.com 甲骨文 教程" -c cn -l zh-cn \
  | jq -r '.organic[].link | capture("post-(?<id>[0-9]+)").id'
uvx nodeseek-cli 742025
```

Bias results by adding the Chinese category word: `测评` (reviews), `交易`
(trades), `教程`, `投票` (polls), `日常`, `曝光`.

## JSON

```bash
uvx nodeseek-cli 355740 --json | jq '{title, pages, comments:(.comments|length)}'
uvx nodeseek-cli 250906 --all --json \
  | jq -r '.comments[] | "\(.floor)\t\(.author)\t\(.reply_to.floor // "-")"'
```

Shape: `post_id, title, pages, page_fetched (null with --all), url, comments[]`.
Each comment: `floor, comment_id, author, author_url, is_poster, created,
created_iso, edited, category, reply_to ({user,user_url,floor,floor_url}|null),
content (Markdown)`.

## Notes

- Stickers -> `[Sticker]`; images -> `![alt](url)`; replies -> `Reply to @user #N`.
- Benchmark "magic tab" widgets expand to one titled code block per tab.
- Deleted posts give a `404` error; on `429` wait and retry.
