---
name: py12306
description: China Railway (12306) ticket queries. Search tickets, transfers, train stops, and station info.
---

# 12306 CLI

Query China Railway tickets, transfers, and schedules. Returns JSON.

## Commands

```bash
# Search tickets
uvx py12306 tickets --date 2026-01-25 --from 北京 --to 上海 [options]

# Search transfer routes
uvx py12306 transfers --date 2026-01-25 --from 成都 --to 杭州 [options]

# Get train stops/schedule
uvx py12306 stops G1 --date 2026-01-25

# Lookup station info
uvx py12306 stations 北京
```

## Tickets Options

| Option | Description |
|--------|-------------|
| `--date` | Travel date YYYY-MM-DD (required) |
| `--from/--to` | Station or city name in Chinese (required) |
| `--trains` | Filter: G/D/C/Z/T/K (combinable, e.g., `GD`) |
| `--depart-after/--depart-before` | Hour range 0-23 |
| `--sort` | `depart` (default), `arrive`, `duration` |
| `--limit` | Max results |

```bash
# Morning G trains, sorted by duration
uvx py12306 tickets --date 2026-01-25 --from 北京南 --to 上海虹桥 \
    --trains G --depart-after 8 --depart-before 12 --sort duration --limit 5
```

## Transfers Options

| Option | Description |
|--------|-------------|
| `--date` | Travel date YYYY-MM-DD (required) |
| `--from/--to` | Station or city name (required) |
| `--via` | Transfer station (optional, auto-detected) |
| `--trains` | Filter: G/D/C/Z/T/K |
| `--min-wait/--max-wait` | Transfer time in minutes (default: 30/180) |
| `--sort` | `duration` (default), `depart`, `arrive` |
| `--limit` | Max results |

```bash
uvx py12306 transfers --date 2026-01-25 --from 成都 --to 杭州 --trains G --limit 3
```

## Train Types

| Code | Type |
|------|------|
| G | 高铁 (High-speed 300-350 km/h) |
| D | 动车 (EMU 200-250 km/h) |
| C | 城际 (Intercity) |
| Z | 直达 (Direct express) |
| T | 特快 (Express) |
| K | 快速 (Fast) |

## Output

JSON to stdout. Parse with `jq`:

```bash
# Get first train code and duration
uvx py12306 tickets --date 2026-01-25 --from 北京 --to 上海 --limit 1 | jq '.[0] | {train, duration}'

# List all seat prices
uvx py12306 tickets --date 2026-01-25 --from 北京 --to 上海 --limit 1 | jq '.[0].seats[] | "\(.name): ¥\(.price)"'
```

## Notes

- Station names auto-resolve (city name → all stations in city)
- Use `uvx py12306 <command> --help` for full options
