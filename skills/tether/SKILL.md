---
name: tether
description: Drive a Chromium browser over the Chrome DevTools Protocol, either one the user already has open (Chrome, Helium, Brave, Edge, Arc, ...) or a fresh headless/headful Chromium that tether launches itself. A persistent named daemon holds ONE connection; you send it arbitrary async Playwright code with per-namespace isolated state. Use to automate, scrape, fill forms, or check status inside the user's real, logged-in session, or in a clean throwaway/persistent browser.
---

# tether

Attach to an **already-running** Chromium browser and drive it with Playwright,
reusing the user's real profile (logins, cookies, tabs). A long-lived daemon
holds one CDP connection so the browser's "allow remote debugging" prompt is
approved **once**, not per command.

- **daemon** = one browser connection (= one approval). Named.
- **namespace** (`-n`) = an isolated state bucket inside a daemon.
- You send **arbitrary async Python** that runs against a live Playwright `Browser`.

Self-contained via a `uv` shebang + PEP 723 deps — no venv. Attaching needs no
`playwright install`; `--launch` uses an installed Chrome/Chromium, or downloads
Playwright's Chromium on first use if none is found.

## One-time setup (user does this in their browser)

The browser must expose remote debugging. Two ways:

- **Chrome/Helium/Edge 144+** (no relaunch): open `chrome://inspect/#remote-debugging`
  and turn on "Allow remote debugging for this browser instance". Persists across
  restarts. Each new connection still shows a one-click **Allow** dialog.
- **Any Chromium** (older / explicit): launch it with
  `--remote-debugging-port=9222 --user-data-dir=<a non-default dir>`.

`tether` finds the browser by reading `<user-data-dir>/DevToolsActivePort`, so the
port can change between launches and it still works.

## Commands

```bash
{baseDir}/tether.py run <daemon> [code] [-n NS] [target opts]  # exec code; auto-creates daemon
{baseDir}/tether.py ls                                          # list daemons (● live / ○ stale)
{baseDir}/tether.py info <daemon>                               # health, namespaces, reconnects
{baseDir}/tether.py kill <daemon>                               # stop a daemon
```

`code` is positional, or omit it (or pass `-`) to read from **stdin** — use stdin
for anything with quotes to avoid shell-escaping pain (see below).

## Launch a fresh browser instead (`--launch`)

When the user's real session isn't needed (or no browser is open, e.g. on a
server), let the daemon start its own Chromium. No approval dialog, no
remote-debugging setup; the browser lives and dies with the daemon.

```bash
{baseDir}/tether.py run scratch --launch 'p = await new_bg_page(); await p.goto("https://example.com"); return await p.title()'
{baseDir}/tether.py run scratch --launch --headful ...        # visible window (needs a display)
{baseDir}/tether.py run work --launch --profile shop ...       # persistent profile: logins survive restarts
{baseDir}/tether.py run t --launch --executable /path/to/chrome ...
```

- Headless by default; `--headful` (implies `--launch`) opens a window and on Linux
  needs `DISPLAY`/`WAYLAND_DISPLAY` (or wrap in `xvfb-run`).
- No `--profile`: a throwaway temp profile, deleted when the daemon is killed.
  `--profile NAME`: `~/.tether/profiles/NAME`, reused by any daemon with that name.
- Executable: `--executable` > `TETHER_CHROMIUM` > installed Chrome/Chromium/Brave/Edge >
  Playwright's bundled Chromium.
- `tether kill <daemon>` closes the browser; on Linux it also dies if the daemon is
  killed hard. Browser output goes to `~/.tether/<daemon>.browser.log`.
- The "stay out of the user's way" rules below exist for the user's own browser; in a
  launched browser nobody else is looking, so focus doesn't matter.

## Target selection (only when a daemon is first created)

Priority: `--cdp-url` > `--user-data-dir` > `--browser` > auto-detect. Also via
env: `TETHER_CDP_URL`, `TETHER_USER_DATA_DIR`, `TETHER_BROWSER`.

```bash
{baseDir}/tether.py run main 'return 1'                       # auto-detect (1 debuggable browser)
{baseDir}/tether.py run main 'return 1' --browser helium      # named: chrome|helium|brave|edge|chromium|vivaldi|arc|opera
{baseDir}/tether.py run main 'return 1' --user-data-dir "~/Library/Application Support/Google/Chrome"
{baseDir}/tether.py run main 'return 1' --cdp-url ws://127.0.0.1:9222/devtools/browser/<uuid>
```

Auto-reconnect: a `--browser`/`--user-data-dir`/auto target re-reads
`DevToolsActivePort` and recovers after the browser restarts. A raw `--cdp-url`
with a fixed UUID cannot (the UUID is gone after a restart).

## The execution context

Inside the code you run, these names are injected:

| name | what |
|------|------|
| `browser` | Playwright `Browser` (shared by the whole daemon) |
| `ctx` | `browser.contexts[0]` |
| `S` | dict, persistent, **isolated per namespace** |
| `G` | dict, persistent, **shared across namespaces** in the daemon |
| `out` | dict; set `out['result']` (or `return ...`) to send a value back |
| `asyncio` | the module |
| `new_bg_page(url=None)` | async; open & return a **background** tab (see below) |

## Stay out of the user's way (DEFAULT behavior)

The user is usually **actively using this browser**. Do **not** steal their focus:

- **Never** call `page.bring_to_front()`.
- **Never** create tabs with `ctx.new_page()` — Playwright opens them in the
  **foreground** and yanks the user onto the new tab.
- **Never** navigate (`goto`) a tab the user is currently looking at. Keep your
  own dedicated **background work tab** per namespace and reuse it.

Instead, open tabs with the injected **`new_bg_page(url=None)`** helper. It
creates ONE silent background tab via CDP (`Target.createTarget background:true`)
and returns the `Page`. Background tabs still render, so `goto`, `aria_snapshot`,
locators, forms, and screenshots all work normally.

`new_bg_page` is **stateless** — it makes no assumption about "the" page. Call it
as often as you like and keep the pages however suits the task (a single var, a
list in `S`, a dict keyed by job, etc.):

```python
# one work tab, persisted across calls
page = next((p for p in [S.get("page")] if p and not p.is_closed()), None) \
       or await new_bg_page()
S["page"] = page
await page.goto("https://example.com", wait_until="domcontentloaded")
```

```python
# several tabs at once, scraped concurrently
pages = await asyncio.gather(*[new_bg_page(u) for u in urls])
S["pages"] = pages
titles = await asyncio.gather(*[p.title() for p in pages])
```

You can also reuse tabs the user already has open (read them, don't navigate
them) — `new_bg_page` is only for tabs *you* create.

**Exception — only when the user explicitly asks you to "show your work"**
(watch it live, drive their visible tab, demo a flow): then it's fine to use
`ctx.new_page()` and/or `page.bring_to_front()` to surface the action. Otherwise,
stay background by default.

Note: a background tab is silent but still appears in the tab strip. If even that
is unwanted, do the work in a separate background **window** (`new_context`)
instead of a tab.

## Common workflows

### Always-pass-stdin pattern (recommended)
Quotes in JS break a single-quoted shell arg. Pipe via stdin instead:

```bash
{baseDir}/tether.py run main -n task <<'PY'
page = await new_bg_page()          # silent background tab (see default-behavior section)
await page.goto("https://example.com", wait_until="domcontentloaded")
out["result"] = await page.title()
PY
```

### Look at a page — prefer the a11y tree over screenshots
The accessibility tree is ~100x smaller than a screenshot PNG and includes link
URLs + roles. Default to it; screenshot only for pixels (layout, canvas, captcha).

```bash
{baseDir}/tether.py run main -n task <<'PY'
page = S["page"]
aria = await page.locator("body").aria_snapshot()          # full tree (roles, names, /url)
hits = [l for l in aria.splitlines() if "申请" in l]        # grep the lines you care about
out["result"] = hits[:30]
PY
```
Scope it to cut noise: `await page.locator("#main").aria_snapshot()`.
Note: the tree only reflects **rendered** nodes — open dropdowns / wait for lazy
iframes first (`await page.get_by_text("我的申请").first.click()`), then snapshot.

### Jump by URL instead of clicking menus
Custom UIs hide links behind dropdowns; the tree's `/url` lines (or an anchor
scrape) let you navigate directly:

```bash
{baseDir}/tether.py run main -n task <<'PY'
page = S["page"]
links = await page.evaluate("""() => [...document.querySelectorAll('a')]
  .map(a=>({t:(a.textContent||'').trim().slice(0,40), h:a.href})).filter(x=>x.t&&x.h)""")
out["result"] = [x for x in links if "keyword" in x["t"]]
PY
```

### Fill / click
```bash
{baseDir}/tether.py run main -n task <<'PY'
page = S["page"]
await page.fill("input[name='firstname']", "Priya")
await page.get_by_role("button", name="Continue").click()
await page.wait_for_load_state("networkidle")
out["result"] = page.url
PY
```

### Screenshot (when you truly need pixels)
```bash
{baseDir}/tether.py run main -n task 'await S["page"].screenshot(path="/tmp/shot.png", full_page=True)'
```
Then read `/tmp/shot.png`.

### Parallel work across tabs (one connection, true concurrency)
```bash
{baseDir}/tether.py run main <<'PY'
pages = [p for c in browser.contexts for p in c.pages if p.url.startswith("http")]
titles = await asyncio.gather(*[p.title() for p in pages])
out["result"] = titles
PY
```

### Isolation vs sharing
`S` is per-namespace (two tasks won't clobber each other's `page`); `G` is shared
when you *want* cross-namespace state (counters, a shared lookup, etc.).

### Clean up a working tab
```bash
{baseDir}/tether.py run main -n task 'p=S.pop("page",None);
if p: await p.close()'
```

## Notes & limits

- Every new connection (incl. auto-reconnect after a browser restart) shows the
  browser's one-click **Allow** dialog — that's the M144 security model, not
  something tether can suppress.
- Runtime state lives in `~/.tether/` (`<daemon>.sock` Unix socket `0600`,
  `<daemon>.lock` single-winner flock, `<daemon>.json` meta, `<daemon>.log`).
- The daemon `exec`s arbitrary code over a user-only Unix socket — it's a local
  dev tool, treat it as such.
- macOS/Linux only (Unix sockets). Officially Chrome; other Chromium browsers
  usually work.
