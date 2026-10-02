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

Never run commands that block waiting for user input, except as a bgjob (see below):

- Use `GIT_EDITOR=true git rebase --continue`
- Use `git merge --no-edit`
- Use `ssh -o BatchMode=yes`
- Use `apt-get -y` not `apt-get`
- Pipe to `head` if output might trigger a pager

## Misc

- Use write for new files or near-complete rewrites; prefer edit for partial changes to existing files
- Prefer `fd` and `rg` over `find` and `grep`

## Long-running and Interactive Commands

Run anything that may take more than ~30 s, or that asks for input, as a bgjob. Never `sleep` to wait.

```bash
bgjob start build -- cargo build --release        # returns at once: "build-3fa started ..."
bgjob log build-3fa                               # right away: did it start?
bgjob wait build-3fa -t 10; bgjob log build-3fa   # a little later: early errors show up here
bgjob wait build-3fa -t 600                       # then as long as the task needs; repeat while it says running
```

- Pick the check times for the task: a build that fails on a typo fails in seconds, a training run in minutes.
- Keep `wait -t` below your shell tool's own timeout (OpenCode: 2 min unless you pass a larger `timeout`); waiting again is free.
- `wait` only prints a status line: `running 1m35s`, `exited 0 after 2m41s`, `killed`, or `died` (gone without an exit status). Read output with `log` (`-n 200` for more).
- One argument after `--` is a shell line (`-- 'make && make test'`); several are a command and its arguments. `-C DIR` sets the directory.
- Interactive: `bgjob peek ID` shows the screen; once the prompt is there, `bgjob send ID 'yes' Enter`.
- Jobs outlive your tool call and your session. `bgjob ls` lists them; `bgjob kill ID` stops one and everything it started.
- The user can watch a job with `tmux -L agent attach -t ID`.

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
