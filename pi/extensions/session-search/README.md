# session-search

Full-text search across all your saved sessions, with ranked results.

`/session-search` opens a **live incremental picker**: results update as you
type (debounced), ranked by relevance. Arrow keys move the selection, Enter
opens the highlighted session, Esc/Ctrl+C cancels. Pass an initial query with
`/session-search <query>` to prefill the search box.

```
/session-search

  Search sessions  ·  ↑↓ move · enter open · esc cancel
  > auth middleware
  12 matches
  → 2026-07-15 · Refactor auth middleware · ~/src/pi-extensions · a1b2c3d4
    2026-07-14 · Fix proxy auth header · ~/src/earl/zeno · 9f8e7d6c
    ...
```

Opening a result offers a follow-up menu: resume, fork at the matching entry,
copy the excerpt, or put it in the editor.

### How it stays fast

JS never parses the corpus. Per keystroke (debounced, abortable):

1. **rg does search + ranking in one pass**: `rg --count-matches` per term
   (~20ms over the whole corpus), AND-intersected, score = summed hit count.
2. **Labels need zero parsing**: they come from the already-loaded
   `SessionInfo` metadata.
3. **Only the selected row's file is parsed** (lazily, ~10ms) to produce the
   exact snippet and the entry id used for forking.

Byte-level counting is a sound superset of the exact scorer (a content match is
never dropped). Escape-unsafe terms (chars JSON might escape) or a missing rg
fall back to the exact per-entry scan (6-way concurrent, 64MB cap per session).
Up to 100 results, each shown as `date · title · path · session-id`.

Non-TUI runs (rpc/json/print) fall back to a one-shot prompt + static selector.

Known limitation: opening with `/session-search <query>` and pressing Enter
*immediately* (before typing) can require a second Enter, because the first key
after the command→picker focus handoff is dropped by the host. Typing first (the
normal flow) is unaffected.

## Dependencies

- **Runtime:** [Pi](https://github.com/earendil-works/pi-coding-agent) extension API.
- **Depends on extensions:** None.
- **Used by extensions:** None.
