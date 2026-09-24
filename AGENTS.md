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

Never run commands that block waiting for user input, except inside tmux (see below):

- Use `GIT_EDITOR=true git rebase --continue`
- Use `git merge --no-edit`
- Use `ssh -o BatchMode=yes`
- Use `apt-get -y` not `apt-get`
- Pipe to `head` if output might trigger a pager

## Misc

- Use write for new files or near-complete rewrites; prefer edit for partial changes to existing files
- Prefer `fd` and `rg` over `find` and `grep`

## Long-running Commands

- If your shell tool can run commands in the background and notify you when they finish (OpenCode: `background: true`), use that for long non-interactive commands. OpenCode kills foreground commands after 2 minutes unless you pass a larger `timeout`.
- Otherwise, and for anything interactive or that must outlive your session, use tmux.
- Never `sleep N` to wait for a command to finish. Wait on the command itself.

## Tmux

Name sessions `agent-<purpose>-<sha>` with a random short sha so parallel agents never collide. Always `-d`; never attach, it blocks you.

Long command: log to a file, signal when done, wait on the signal. `tmux wait-for` returns the moment the command ends, even if it ended before you started waiting.

```bash
S=agent-build-$(openssl rand -hex 3); L=/tmp/$S.log
tmux new-session -d -s "$S" -e S="$S" -e L="$L" '(cargo build --release) >"$L" 2>&1; echo "[exit $?]" >>"$L"; tmux wait-for -S "$S"'
timeout 10 tmux wait-for "$S"; tail -n 20 "$L"                                       # short first wait: did it start OK?
tail -n1 "$L" | rg -q '^\[exit' || timeout 600 tmux wait-for "$S"; tail -n 40 "$L"  # then wait long; safe to repeat
```

- Keep the command inside `( )` so all of its output goes to the log.
- Wait short first to catch immediate failures and check the output looks right, then wait long.
- Done when the log's last line is `[exit N]`. The signal is consumed by the first wait that sees it, so a bare second `wait-for` on a finished job hangs until its timeout; always wait through the guarded line.
- The log outlives the session.

Interactive program: wait for the text you expect, then answer.

```bash
S=agent-ssh-$(openssl rand -hex 3)
tmux new-session -d -s "$S" 'ssh host'
timeout 30 sh -c "until tmux capture-pane -pt $S | rg -q 'password:'; do sleep 0.3; done"
tmux send-keys -t "$S" 'y' Enter
tmux capture-pane -pt "$S" -S - | rg -v '^$'
tmux kill-session -t "$S"
```

- `tmux ls | rg '^agent-'` lists agent sessions. Kill yours when done.

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
