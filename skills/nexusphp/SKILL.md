---
name: nexusphp
description: "Search and read NexusPHP private-tracker torrents from the terminal as Markdown or JSON. List/search torrents with category, area and mode filters; view a torrent's details; print or save the .torrent (via passkey). Use when the user wants to find, inspect, or download torrents from a NexusPHP site."
---

# nexusphp CLI

Read a NexusPHP tracker via `uvx --from nexusphp-cli nexusphp`. Scrapes the
server-rendered `torrents.php` / `details.php` using a session cookie; prints
Markdown by default, or JSON with `-j`.

Auth comes from env (already set on this machine): `NEXUS_BASE` (site URL) and
`NEXUS_TOKEN` (the `access_token` cookie). Override per-call with `--base` /
`--token`. Passkey for downloads is auto-discovered from any page.

```bash
uvx --from nexusphp-cli nexusphp <command> [options]
```

## Commands

| Command | Description |
|---------|-------------|
| `search <query>` | Search/browse torrents (empty query = latest) |
| `details <id>` | One torrent's info (name, size, 中文名/英文名, subtitle, imdb) |
| `url <id>` | Print `download.php` URL incl. your passkey (nothing saved) |
| `download <id>` | Fetch and save the `.torrent` (`-o` for filename) |

## Options

`search`: `--area title|subtitle|uploader|imdb|douban` · `--mode and|or|exact` ·
`--cat movie,tv,anime,doc,music,game,software,...` (or numeric ids) ·
`--incldead 0|1|2` (all/alive/dead) · `-p/--page N` (0-indexed).
Global: `--base`, `--token`, `-j/--json`.

```bash
uvx --from nexusphp-cli nexusphp search "人生切割术"
uvx --from nexusphp-cli nexusphp search severance --cat tv,anime --incldead 1
uvx --from nexusphp-cli nexusphp details 472747 -j
uvx --from nexusphp-cli nexusphp download 472747 -o sev.torrent
```

## JSON

```bash
uvx --from nexusphp-cli nexusphp search "无职转生" -j \
  | jq '.torrents[] | {id, title, seeders, size, is_sticky}'
```

Search shape: `{count, range_hint, torrents[]}`. Each torrent: `id, title,
subtitle, category, is_sticky, tags[], imdb, my_state, promotion, comments,
added, size, size_bytes, seeders, leechers, snatched, uploader`.

## Notes

- `is_sticky` = pinned (竞价置顶). `promotion` e.g. `"2X"`, else null.
- `imdb.score` is often `"NA"` (site fills it via JS, not in HTML).
- Exit codes: `2` = auth (token missing/expired), `130` = Ctrl-C.
- Source/PyPI: `nexusphp-cli`. Install standalone with `uv tool install nexusphp-cli` (then just `nexusphp`).
