---
name: recall
description: Search and read past coding-agent sessions (ocelot/OpenCode, Claude Code, Codex, pi) with the `recall` CLI. Full text over titles, prompts, replies, reasoning, tool calls and tool output. Use when the user refers to earlier work ("what did we decide about X", "that bug last week", "the command we used", "the session called ..."), or to recover detail from your own session after compaction.
---

# recall

Search first, then read around the hit. The index updates itself on every call.

```bash
recall "auth middleware"                    # sessions, best first, with highlighted excerpts
recall "in:title quarterly report"          # find a session by title
recall read ses_4f2a91 --around 81           # messages #76–#86 around a hit (#81)
recall read ses_4f2a91 --from -20            # last 20 messages
recall read ses_4f2a91 --part 81.2           # one part in full (cut ones say so)
recall read self --from -30                 # your own session, e.g. after compaction
```

Each hit reads `#81 thinking …«match»…`: message number, then kind. Sessions are printed as short ids; pass them as
is. Reads include everything (user, assistant, thinking, tool calls with their results); narrow with
`--in user,assistant`. `--json` for structured output.

**Scope:** searches cover only your own harness (recall detects it). Add `--all` or `agent:...` only when the user
asks about other agents or everything.

## Query

| | |
|---|---|
| `words` | all must appear; prefixes and one-letter typos also match (ranked below exact) |
| `"exact phrase"` `-word` | phrase in order; leave out sessions containing word |
| `agent:claude,codex` `-agent:pi` | harness: `ocelot opencode claude codex pi` |
| `dir:project` | working directory contains |
| `date:<2d` `date:>1w` `today` `yesterday` | last activity (`m h d w mo y`) |
| `in:title` `in:user,reasoning` `-in:tool` | `title user assistant reasoning tool call result system` |
| `is:archived` `-is:child` | archived / subagent sessions |
| `session:ID` `session:self` | within one session |

## Tips

- Your own session shows up for words you just used; skip it.
- Few hits: drop words, or use `in:tool` for commands and outputs. Too many: add `dir:`, `date:`, quotes.
- Chinese and other CJK text matches as exact substrings; identifiers match by part (`palette` finds `CommandPalette`).
