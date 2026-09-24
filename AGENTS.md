## Python

Use `uv` for all Python operations. Never invoke `python` or `python3` directly.

```bash
# Run scripts
uv run script.py

# Run with dependencies (ephemeral)
uv run --with pyyaml python3 script.py
uv run --with requests,beautifulsoup4 python3 -c "..."

# Install packages in a project
uv add package-name
```

## Non-Interactive Commands Only

Never run commands that block waiting for user input, unless in a tmux session or similar where it won't block the agent:

- Use `GIT_EDITOR=true git rebase --continue`
- Use `git merge --no-edit`
- Use `ssh -o BatchMode=yes`
- Use `apt-get -y` not `apt-get`
- Pipe to `head` if output might trigger a pager

## Misc

- Use write for new files or near-complete rewrites; prefer edit for partial changes to existing files
- Prefer `fd` and `rg` over `find` and `grep`

## Tmux

Use tmux for interactive or long-running commands that would otherwise block the agent.

Name sessions `pi-<purpose>-<sha>` with a random short sha so parallel agents never collide:

```bash
S=pi-build-$(openssl rand -hex 3)          # -> pi-build-1abd75
tmux new-session -d -s "$S" 'cargo build --release'
tmux capture-pane -pt "$S" -S - | rg -v '^$'   # read output (-S - = full scrollback)
tmux send-keys -t "$S" 'y' Enter               # answer a prompt
tmux kill-session -t "$S"                      # always clean up
```

- Always `-d`. Never attach: it blocks the agent.
- `tmux ls | rg '^pi-'` lists agent sessions.
- Plain `capture-pane -p` pads with blank lines; `-S -` plus `rg -v '^$'` is cleaner.

## SSH Command Execution

Use `-tt` by default for abort capability. PTY ensures remote process dies when connection closes.

```bash
ssh -tt host 'command'
ssh -tt host 'command' < /dev/null   # In loops/scripts to prevent stdin consumption
```

### Stdin Decision Tree

```
Does command need stdin?
├─ NO    → ssh -tt host 'cmd'
├─ Small → ssh -tt host 'cmd' (may hang if >500B)
└─ Large → scp first:
             scp data host:/tmp/x
             ssh -tt host 'cmd < /tmp/x; rm /tmp/x'
```

### Why `-tt`

| Mode | Abort | Stdin | Limitation |
|------|-------|-------|------------|
| `-tt` | ✓ | ✗ >500B | PTY buffer |
| plain | ✗ orphans | ✓ | No signal propagation |

### Examples

```bash
# No stdin
ssh -tt host 'cat /var/log/app.log'

# In a loop (use < /dev/null to protect outer stdin)
for f in *.txt; do
    ssh -tt host "process $f" < /dev/null
done

# Small stdin
echo "pattern" | ssh -tt host 'grep -r . /src'

# Large stdin
scp dump.sql host:/tmp/
ssh -tt host 'mysql < /tmp/dump.sql; rm /tmp/dump.sql'
```
