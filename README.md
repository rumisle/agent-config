# agent-config

Config, skills and extensions for [pi](https://github.com/badlogic/pi-mono) and [OpenCode](https://github.com/anomalyco/opencode).

```bash
git clone https://github.com/rumisle/agent-config ~/work/agent-config
~/work/agent-config/install.sh
```

`install.sh` symlinks everything into place. It backs up anything it would replace and is safe to re-run.

| Path | Linked to |
|---|---|
| `AGENTS.md` | `~/.pi/agent/AGENTS.md`, `~/.config/opencode/AGENTS.md` |
| `skills/*` | `~/.agents/skills/*`, read by both pi and OpenCode |
| `pi/extensions` | `~/.pi/agent/extensions` |
| `pi/piacct` | `~/.local/bin/piacct` |
| `opencode/` | `~/.config/opencode` |

Skills from a sibling `agent-config-private` checkout (or `$AGENT_CONFIG_PRIVATE`) are linked too, if it exists.

## Skills

| Skill | |
|---|---|
| `amap` | AMap (高德) geocoding, POI search, routing |
| `bn` | Binary Ninja via the `bn` CLI |
| `exa` | Exa search, contents, answers |
| `flights-cn` | China domestic flights (ly.com) |
| `flights-intl` | International flights (Kiwi.com) |
| `google-search` | Google via Serper |
| `linear` | Linear GraphQL API |
| `nexusphp` | NexusPHP tracker search and details |
| `nitter-cli` | Twitter/X via Nitter |
| `nodeseek` | NodeSeek forum threads |
| `pangram-classify` | AI-text detection via Pangram |
| `py12306` | China Railway tickets |
| `tether` | Drive your running browser over CDP, or launch a fresh headless/headful Chromium |
| `youtube-subtitle` | YouTube subtitles |

API keys come from environment variables named in each `SKILL.md`.

## pi

Extensions: `turn-stats` (per-turn cost and cache), `session-search`, `working-timer`.

`piacct` switches between accounts on the same provider. `~/.pi/agent/auth.json` becomes a symlink into `~/.pi/agent/accounts/<name>.json`, and pi writes token rotations through it, so every account stays current.

```bash
piacct              # current account + list
piacct <name>       # switch
piacct new <name>   # create, then run pi and /login
```

## OpenCode

`opencode/opencode.jsonc` loads [opencode-anth](https://github.com/rumisle/opencode-anth) and [opencode-cache-warmer](https://github.com/rumisle/opencode-cache-warmer) (pi-style cache warming, `idle` mode), and disables `question`, `websearch`, `webfetch` and the MCP resource tools.
