---
name: bn
description: Use the local bn CLI for Binary Ninja reversing work through the bn bridge. Prefer this skill for decompilation, function search, callsite recovery, IL/disassembly, xrefs, type inspection, struct field edits, previewed mutations, and inline Python execution. Also covers launching the Binary Ninja GUI remotely (e.g. over SSH) and managing multiple open files/tabs.
---

# bn

Use this skill when the user wants reverse-engineering work against a Binary Ninja database and the local `bn` CLI is available. If no GUI instance is running yet, see "Launching the GUI Remotely" below.

## Workflow

1. Start with target discovery:

```bash
bn target list
bn doctor
```

Use `bn doctor` when bridge state is unclear or `bn target list` does not show what you expect.

2. Pick a target:
- If there is exactly one open BinaryView, target-scoped commands can omit `--target` entirely.
- If multiple targets are open, commands that omit `--target` fail; pass `--target <selector>` from `bn target list`.
- Use `--target active` only when you explicitly mean the GUI-selected target.

3. Pick the right output mode:
- Read commands default to `text`.
- Mutation, preview, setup, and export commands default to `json`.
- Other options: `--format json`, `--format ndjson`, `--out <path>`.

Outputs above `10_000` `o200k_base` tokens auto-spill to disk. When that happens, stdout is empty and stderr carries the spill metadata as plain text, so do not chain `bn ... | rg ...` and expect to search the real output. Use `--out <path>` when you want the full body written to a known file.

## Launching the GUI Remotely

The bridge lives inside the Binary Ninja GUI, so `bn` needs a running GUI instance. When the user is away (e.g. only connected over SSH) and `bn target list` reports no instances, launch the GUI onto their existing graphical session yourself instead of asking them to open it.

Requirements: a logged-in desktop session on the machine (a locked screen is fine). Licenses without headless API access cannot use `import binaryninja` outside the GUI, so this GUI-on-a-display approach is the workaround.

```bash
# Check that a graphical session exists to attach to
ls "$XDG_RUNTIME_DIR" | rg '^wayland-'   # Wayland socket, e.g. wayland-0
loginctl list-sessions                    # look for a session with a seat

# Launch as a background job (it is long-running)
bgjob start bn -- env WAYLAND_DISPLAY=wayland-0 DISPLAY=:0 XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" binaryninja /path/to/binary
bgjob wait <job-id> -t 15
bn target list                            # the file should appear once the bridge is up
```

- Adjust `WAYLAND_DISPLAY` / `DISPLAY` to what the session actually exposes. On a pure X11 session `DISPLAY=:0` alone is usually enough.
- Startup plus initial analysis takes a few seconds; poll `bn target list` (via `bgjob wait -t ...`, not `sleep`) until the target shows up.
- If nobody is logged in to a desktop, there is no display to attach to. Options are a virtual display (`Xvfb` / `xvfb-run`) or a headless Wayland compositor; ask the user before installing one.
- When finished, shut the instance down with `bgjob kill <job-id>`, but **only after saving** any work (see below). Killing discards unsaved analysis.

## Managing Multiple Files (Tabs)

One GUI instance can hold several files as tabs. Each tab is its own `bn` target, so prefer one instance with many tabs over many instances.

Tab control is not a built-in `bn` command; drive it through `bn py exec` with the `binaryninjaui` API, always on the main thread. Because more than one target is open, `py exec` itself needs `--target` (use `--target active` for UI-only scripts).

Open more files in the running instance:

```bash
bn py exec --target active --stdin <<'PY'
import binaryninjaui as ui
from binaryninja.mainthread import execute_on_main_thread_and_wait
out = {}
def go():
    ctx = ui.UIContext.activeContext()
    for p in ["/path/to/second.bin", "/path/to/third.bin"]:   # .bndb works too
        out[p] = bool(ctx.openFilename(p))
execute_on_main_thread_and_wait(go)
result = out
PY
bn target list
```

List, focus, and close tabs:

```bash
bn py exec --target active --stdin <<'PY'
import binaryninjaui as ui
from binaryninja.mainthread import execute_on_main_thread_and_wait
FOCUS, CLOSE = "first.bin", "third.bin"
out = {}
def name(ctx, t):
    f = ctx.getViewFrameForTab(t)
    return f.getCurrentBinaryView().file.filename if f else None
def go():
    ctx = ui.UIContext.activeContext()
    out["before"] = [name(ctx, t) for t in ctx.getTabs()]
    for t in ctx.getTabs():
        if (name(ctx, t) or "").endswith(FOCUS):
            ctx.activateTab(t)
    for t in ctx.getTabs():
        if (name(ctx, t) or "").endswith(CLOSE):
            ctx.closeTab(t)
    out["after"] = [name(ctx, t) for t in ctx.getTabs()]
execute_on_main_thread_and_wait(go)
result = out
PY
```

Rules for safe tab handling:

- **Always target explicitly.** With several tabs open, pass `--target <selector>` from `bn target list` on every command. Use the target id rather than the basename when two files share a name.
- **Save before closing or quitting.** Closing a tab with unsaved changes can pop a modal "save changes?" dialog that nobody can click remotely. That would block the GUI main thread and hang the bridge. Save first:

  ```bash
  bn py exec --target <selector> --code "result = bv.file.create_database('/path/to/file.bndb')"
  ```

  Saving to an existing `.bndb` path updates it. Reopening the `.bndb` later restores renames, types, and comments.
- **Do not trust `bv.file.modified`.** It can read `False` even right after a `bn` mutation, so save unconditionally instead of checking it.
- **Guard risky UI calls with a timeout**, e.g. `timeout 20 bn py exec ...`, so a modal dialog shows up as a failure instead of an indefinite hang.
- Keep the focused tab meaningful. `--target active` follows the GUI-selected tab, so after opening files (the last one opened becomes active) refocus deliberately or use explicit selectors.

## High-Value Read Commands

```bash
bn target list
bn target info
bn function list
bn function list --min-address 0x401000 --max-address 0x40ffff
bn function search attachment
bn function search --regex 'attach|detach|follow'
bn function info sample_track_floor_height_at_position
bn callsites crt_rand --within bonus_pick_random_type
bn callsites crt_rand --within-file /tmp/rng-functions.txt --format ndjson
bn proto get sample_track_floor_height_at_position
bn local list sample_track_floor_height_at_position
bn decompile sample_track_floor_height_at_position
bn il sample_track_floor_height_at_position
bn disasm sample_track_floor_height_at_position
bn xrefs sample_track_floor_height_at_position
bn xrefs field TrackRowCell.tile_type
bn comment get --address 0x401000
bn types --query Player
bn types show Player
bn struct show Player
bn strings --query follow
bn imports
```

`bn function search` is case-insensitive substring matching by default. Add `--regex` when you need regular expressions. `bn function list` and `bn function search` both accept `--min-address` and `--max-address`.

## Caller-Static Mapping

Prefer `bn callsites` over ad hoc `py exec` when the task is "find exact native RNG return-address callers" or any similar direct-call mapping workflow.

`bn callsites` reports both:
- `call_addr`: the native `call ...` instruction address
- `caller_static`: the exact post-call return address

The key rule is:
- `caller_static = call_addr + instruction_length`

Use it like this:

```bash
bn callsites crt_rand --within bonus_pick_random_type --caller-static
bn callsites crt_rand --within fx_queue_add_random --caller-static
bn callsites crt_rand --within-file /tmp/rng-functions.txt --format json
```

The `--within-file` format is one function identifier per non-empty line. Lines beginning with `#` are ignored.

For close-together callsites, `bn callsites` also returns:
- previous instructions
- next instructions
- `call_index` within the containing function
- `within_query` with the original unresolved scope token
- a local-or-null HLIL statement
- a best-effort `pre_branch_condition`

`hlil_statement` is intentionally local-or-null. If Binary Ninja only exposes a coarse enclosing region instead of the smallest call-containing expression or statement, expect `hlil_statement: null` rather than a noisy whole-function blob.

`pre_branch_condition` means the nearest enclosing pre-call HLIL condition when it can be recovered confidently. It is not a generic "related branch" field, so `null` is normal when the condition cannot be derived cleanly.

Use `bn xrefs` when you only need inbound references. Use `bn callsites` when you need exact return-address recovery and local context around the call.

## Bundles

Use bundles when you want a reusable artifact instead of pasting long output into context:

```bash
bn bundle function sample_track_floor_height_at_position --out /tmp/floor.json
```

With `--out`, the CLI returns a JSON envelope for the written artifact instead of dumping the whole bundle to stdout.

## Python Escape Hatch

Use inline Python as a normal lane for one-off Binary Ninja inspection that is awkward to express as a built-in command:

```bash
bn py exec --code "print(hex(bv.entry_point)); result = {'functions': len(list(bv.functions))}"
```

Use `--stdin` with a quoted heredoc for multiline Python snippets:

Shell details matter here:
- Quote the heredoc delimiter as `<<'PY'` so the shell does not expand `$vars`, backticks, or backslashes before Binary Ninja sees the Python.
- Keep the closing `PY` on its own line with no indentation or trailing spaces.
- Use `--script <file>` only for real files you want to keep on disk.
- Use `--code` for true one-liners only.
- If you are counting or collecting BN iterators such as `f.hlil.instructions`, materialize them explicitly with `list(...)` or a generator consumption pattern instead of assuming random-access behavior.

Use this pattern for larger inspection snippets:

```bash
bn py exec --stdin <<'PY'
out = []
for f in bv.functions:
    if 0x416000 <= f.start < 0x41C000:
        out.append((f.start, f.symbol.short_name))
out.sort()
print("\n".join(f"{addr:#x} {name}" for addr, name in out))
PY
```

The `py exec` environment includes:`bn`, `binaryninja`, `bv`, `result`.

`py exec` always returns `stdout` and `result`. If `result` is not JSON-serializable, the CLI returns `repr(result)` plus a warning instead of silently flattening it.

## Mutation Workflow

Prefer preview first:

```bash
bn types declare "typedef struct Player { int hp; } Player;" --preview
bn types declare --file /path/to/win32_min.h --preview
bn struct field set Player 0x308 movement_flag_selector uint32_t --preview
bn symbol rename sub_401000 player_update --preview
bn proto get sub_401000
bn local list sub_401000
bn proto set sub_401000 "int __cdecl player_update(Player* self)" --preview
```

Preview mode applies the change, refreshes analysis, captures affected decompile diffs, and then reverts the mutation.

For struct previews, inspect:`results`, `affected_types`, `affected_functions`.

For the first few changed functions, `affected_functions` may also include `before_excerpt` and `after_excerpt` HLIL snippets around the first changed lines.

If a struct edit is already identical, preview may report `changed: false` with `No effective change detected`.

`bn types declare` uses Binary Ninja's source parser when available. With `--file`, it forwards the real source path so relative includes work like GUI header import.

If a declaration only introduces functions or extern variables and no named types, `types declare` now reports a no-op instead of failing with `No named types found in declaration`.

Non-preview writes are live-verified by default. If the requested state does not read back from Binary Ninja, the command exits nonzero and the whole mutation or batch is reverted.

After any live type or prototype mutation, do an explicit readback:

```bash
bn proto get sub_401000
bn struct show Player
bn types show Player
bn decompile sub_401000
```

Key result statuses:
- `verified`
- `noop`
- `unsupported`
- `verification_failed`

When verification fails, JSON output also includes the requested and observed state for the failed operation.

If you need to force BN to recalculate presentation after a type change, run:

```bash
bn refresh
```
