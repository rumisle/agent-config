#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
private="${AGENT_CONFIG_PRIVATE:-$(dirname "$here")/agent-config-private}"
config="${XDG_CONFIG_HOME:-$HOME/.config}"

link() {
  local target=$1 path=$2
  mkdir -p "$(dirname "$path")"
  if [ -e "$path" ] && [ ! -L "$path" ]; then
    local bak="$path.bak.$(date +%s)"
    mv "$path" "$bak"
    echo "backed up $path -> $bak"
    [ -f "$bak/service.json" ] && [ ! -e "$target/service.json" ] && cp -p "$bak/service.json" "$target/"
  fi
  ln -sfn "$target" "$path"
  echo "$path -> $target"
}

link "$here/AGENTS.md" "$HOME/.pi/agent/AGENTS.md"
link "$here/pi/extensions" "$HOME/.pi/agent/extensions"
link "$here/pi/piacct" "$HOME/.local/bin/piacct"
link "$here/opencode" "$config/opencode"

[ -L "$HOME/.pi/agent/skills" ] && rm "$HOME/.pi/agent/skills" && echo "removed ~/.pi/agent/skills (pi reads ~/.agents/skills)"

skills="$HOME/.agents/skills"
[ -L "$skills" ] && rm "$skills"
mkdir -p "$skills"
find "$skills" -maxdepth 1 -type l ! -exec test -e {} \; -print -delete
for d in "$here"/skills/*/ "$private"/skills/*/; do
  [ -f "$d/SKILL.md" ] || continue
  link "${d%/}" "$skills/$(basename "$d")"
done
