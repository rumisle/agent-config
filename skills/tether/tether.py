#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""tether - a tiny broker to drive a Chromium browser over CDP.

Self-contained: run directly (`./tether.py ...`) or `uv run tether.py ...`.
By default we attach to an already-running browser, so no `playwright install`
browser binaries are needed. With --launch the daemon starts its own Chromium
(installed Chrome/Chromium, else Playwright's, downloaded on first use).

Model
-----
  daemon     = ONE browser connection (= one remote-debugging approval). Named.
  namespace  = an isolated state bucket inside a daemon. Named.

  Inside executed code you get:
    browser   playwright Browser (shared by the whole daemon)
    ctx       browser.contexts[0]
    S         dict, persistent, ISOLATED per namespace
    G         dict, persistent, SHARED across all namespaces in the daemon
    out       dict; set out['result'] (or `return ...`) to send a value back
    asyncio

Usage
-----
  tether run <daemon> [code] [-n NS] [target opts]   # auto-creates daemon if absent
  tether ls                                           # list daemons
  tether info <daemon>                                # namespaces + target + health
  tether kill <daemon>
  tether serve <daemon> [target opts]                 # (internal) run the daemon

  code: positional, or omitted/"-" to read from stdin.

Launch instead of attach (daemon owns the browser; killed with it):
  --launch [--headful]          start a fresh Chromium (headless unless --headful)
  --profile NAME                persistent profile ~/.tether/profiles/NAME (default: temp)
  --executable PATH             browser binary (or env TETHER_CHROMIUM)

Target resolution (used when a daemon is created AND on auto-reconnect):
  --cdp-url URL         ws://... or http://host:port   (or env TETHER_CDP_URL)
  --user-data-dir PATH  read PATH/DevToolsActivePort   (or env TETHER_USER_DATA_DIR)
  --browser NAME        known browser key, see BROWSERS (or env TETHER_BROWSER)
  (nothing)             auto-detect: scan known browsers for a live debug port

Note on reconnect: a --browser / --user-data-dir / auto target re-reads
DevToolsActivePort and recovers after the browser restarts (new UUID). A raw
--cdp-url with a fixed UUID cannot be re-resolved, so it won't survive a restart.
"""
import argparse, asyncio, fcntl, json, os, shutil, signal, socket, subprocess, sys, tempfile, time, traceback

HOME = os.path.expanduser("~")
BASE = os.path.join(HOME, ".tether")
PLAT = sys.platform  # 'darwin' | 'linux' | 'win32'

# user-data-dir per browser per platform
BROWSERS = {
    "helium":   {"darwin": "~/Library/Application Support/net.imput.helium",
                 "linux":  "~/.config/net.imput.helium"},
    "chrome":   {"darwin": "~/Library/Application Support/Google/Chrome",
                 "linux":  "~/.config/google-chrome"},
    "chromium": {"darwin": "~/Library/Application Support/Chromium",
                 "linux":  "~/.config/chromium"},
    "brave":    {"darwin": "~/Library/Application Support/BraveSoftware/Brave-Browser",
                 "linux":  "~/.config/BraveSoftware/Brave-Browser"},
    "edge":     {"darwin": "~/Library/Application Support/Microsoft Edge",
                 "linux":  "~/.config/microsoft-edge"},
    "vivaldi":  {"darwin": "~/Library/Application Support/Vivaldi",
                 "linux":  "~/.config/vivaldi"},
    "arc":      {"darwin": "~/Library/Application Support/Arc/User Data"},
    "opera":    {"darwin": "~/Library/Application Support/com.operasoftware.Opera"},
}


# executables tried for --launch, in order (after --executable / TETHER_CHROMIUM)
LAUNCH_CANDIDATES = {
    "darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
               "/Applications/Chromium.app/Contents/MacOS/Chromium",
               "/Applications/Helium.app/Contents/MacOS/Helium",
               "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
               "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
    "linux":  ["google-chrome-stable", "google-chrome", "chromium", "chromium-browser",
               "brave-browser", "microsoft-edge"],
}
PROFILES = os.path.join(BASE, "profiles")


def sock_path(name): return os.path.join(BASE, f"{name}.sock")
def log_path(name):  return os.path.join(BASE, f"{name}.log")
def meta_path(name): return os.path.join(BASE, f"{name}.json")
def lock_path(name): return os.path.join(BASE, f"{name}.lock")


# ---------------------------------------------------------------- target resolve
def ws_from_user_data_dir(path):
    f = os.path.join(os.path.expanduser(path), "DevToolsActivePort")
    if not os.path.exists(f):
        raise RuntimeError(
            f"No DevToolsActivePort in {path!r}. Is the browser running with "
            f"remote debugging enabled (chrome://inspect/#remote-debugging)?")
    lines = open(f).read().splitlines()
    port, devpath = lines[0], lines[1]
    return f"ws://127.0.0.1:{port}{devpath}", int(port)


def port_alive(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def find_executable(explicit=None):
    """Browser binary for --launch; None means 'use Playwright's bundled Chromium'."""
    exe = explicit or os.environ.get("TETHER_CHROMIUM")
    if exe:
        exe = os.path.expanduser(exe)
        p = exe if os.path.isabs(exe) else shutil.which(exe)
        if not p or not os.path.exists(p):
            raise RuntimeError(f"Browser executable not found: {exe!r}")
        return p
    for c in LAUNCH_CANDIDATES.get(PLAT, []):
        p = c if os.path.isabs(c) else shutil.which(c)
        if p and os.path.exists(p):
            return p
    return None


def check_launch(spec):
    """Fail fast in the client for an unusable --launch spec."""
    if spec.get("launch") not in ("headless", "headful"):
        raise RuntimeError("--launch must be 'headless' or 'headful'")
    if spec["launch"] == "headful" and PLAT == "linux" and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise RuntimeError("--headful needs a display (DISPLAY/WAYLAND_DISPLAY); "
                           "drop --headful or run under xvfb-run")
    if spec.get("profile") and not all(ch.isalnum() or ch in "-_." for ch in spec["profile"]):
        raise RuntimeError("--profile must be alphanumeric plus '-', '_', '.'")
    find_executable(spec.get("executable"))


def _die_with_parent():
    """preexec_fn: on Linux, SIGTERM the launched browser if the daemon dies (even -9)."""
    if PLAT == "linux":
        try:
            import ctypes
            ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
        except Exception:
            pass


def resolve(browser=None, user_data_dir=None, cdp_url=None, **_):
    """Resolve an attach target to (cdp_url, human_description). Reads env as fallback."""
    cdp_url = cdp_url or os.environ.get("TETHER_CDP_URL")
    if cdp_url:
        return cdp_url, f"cdp-url={cdp_url}"
    udd = user_data_dir or os.environ.get("TETHER_USER_DATA_DIR")
    if udd:
        ws, _ = ws_from_user_data_dir(udd)
        return ws, f"user-data-dir={udd}"
    name = browser or os.environ.get("TETHER_BROWSER")
    if name:
        entry = BROWSERS.get(name)
        if not entry or PLAT not in entry:
            raise RuntimeError(f"Unknown browser {name!r} for platform {PLAT}.")
        ws, _ = ws_from_user_data_dir(entry[PLAT])
        return ws, f"browser={name}"
    # auto-detect: exactly one debuggable browser wins
    found = []
    for bname, entry in BROWSERS.items():
        p = entry.get(PLAT)
        if not p:
            continue
        f = os.path.join(os.path.expanduser(p), "DevToolsActivePort")
        if not os.path.exists(f):
            continue
        try:
            port = int(open(f).read().splitlines()[0])
        except (ValueError, IndexError, OSError):
            continue
        if port_alive(port):
            ws, _ = ws_from_user_data_dir(p)
            found.append((bname, ws))
    if len(found) == 1:
        return found[0][1], f"auto:{found[0][0]}"
    if not found:
        raise RuntimeError(
            "Auto-detect found no debuggable browser. Enable remote debugging "
            "(chrome://inspect/#remote-debugging) or pass --browser/--cdp-url.")
    names = ", ".join(b for b, _ in found)
    raise RuntimeError(f"Multiple debuggable browsers found ({names}). "
                       f"Pick one with --browser.")


# ---------------------------------------------------------------- daemon
def _is_playwright_obj(v):
    return type(v).__module__.split(".", 1)[0] == "playwright"


def _purge_dead_handles(store, _seen=None):
    """Recursively drop Playwright objects from dicts/lists (post-reconnect)."""
    _seen = _seen if _seen is not None else set()
    if id(store) in _seen:
        return
    _seen.add(id(store))
    if isinstance(store, dict):
        for k in [k for k, v in store.items() if _is_playwright_obj(v)]:
            del store[k]
        for v in store.values():
            if isinstance(v, (dict, list)):
                _purge_dead_handles(v, _seen)
    elif isinstance(store, list):
        store[:] = [v for v in store if not _is_playwright_obj(v)]
        for v in store:
            if isinstance(v, (dict, list)):
                _purge_dead_handles(v, _seen)


class Daemon:
    def __init__(self, name, spec):
        self.name = name
        self.spec = spec          # {"browser","user_data_dir","cdp_url"} as given
        self.cdp_url = None
        self.target_desc = None
        self.browser = None
        self.pw = None
        self.ns = {}              # namespace -> dict (isolated state)
        self.G = {}               # shared across namespaces
        self.started = time.time()
        self.reconnects = 0
        self._lock = asyncio.Lock()
        self.proc = None          # launched browser (--launch only)
        self.udd = None           # its user-data-dir
        self.ephemeral = False    # udd is a temp dir we delete on exit

    def _launch_browser(self, exe):
        """Start (or restart) our own Chromium and return its CDP ws url."""
        if self.udd is None:
            prof = self.spec.get("profile")
            if prof:
                self.udd = os.path.join(PROFILES, prof)
                os.makedirs(self.udd, exist_ok=True)
            else:
                self.udd = tempfile.mkdtemp(prefix=f"tether-{self.name}-")
                self.ephemeral = True
        port_file = os.path.join(self.udd, "DevToolsActivePort")
        try: os.unlink(port_file)
        except OSError: pass
        args = [exe, f"--user-data-dir={self.udd}", "--remote-debugging-port=0",
                "--no-first-run", "--no-default-browser-check"]
        if self.spec["launch"] == "headless":
            args.append("--headless=new")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            args.append("--no-sandbox")
        args.append("about:blank")
        blog = open(os.path.join(BASE, f"{self.name}.browser.log"), "a")
        self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=blog, stderr=blog,
                                     preexec_fn=_die_with_parent)
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"browser exited ({self.proc.returncode}); "
                                   f"see {BASE}/{self.name}.browser.log")
            try:
                return ws_from_user_data_dir(self.udd)[0]
            except (RuntimeError, IndexError, ValueError):
                time.sleep(0.1)   # not written yet / partially written
        raise RuntimeError("launched browser did not expose DevToolsActivePort within 30s")

    def _stop_browser(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(5)
            except subprocess.TimeoutExpired: self.proc.kill()
        if self.ephemeral and self.udd:
            shutil.rmtree(self.udd, ignore_errors=True)

    async def _connect(self):
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        try:
            if self.spec.get("launch"):
                if self.proc and self.proc.poll() is None:
                    self.cdp_url = ws_from_user_data_dir(self.udd)[0]
                else:
                    exe = find_executable(self.spec.get("executable")) or pw.chromium.executable_path
                    if not os.path.exists(exe):
                        await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "playwright",
                                                                 "install", "chromium"], check=True)
                    self.cdp_url = await asyncio.to_thread(self._launch_browser, exe)
                    self.target_desc = (f"launch:{self.spec['launch']} "
                                        f"profile={self.spec.get('profile') or 'ephemeral'} "
                                        f"exe={exe}")
            else:
                self.cdp_url, self.target_desc = resolve(**self.spec)  # may raise if down
        except Exception:
            await pw.stop()
            raise
        try:
            self.browser = await pw.chromium.connect_over_cdp(self.cdp_url)
        except Exception:
            await pw.stop()           # don't leak a started Playwright on failure
            raise
        self.pw = pw

    async def _reconnect(self):
        try:
            await self.pw.stop()
        except Exception:
            pass
        await self._connect()
        # deeply purge dead playwright handles (old pages/contexts) from all state
        for store in (*self.ns.values(), self.G):
            _purge_dead_handles(store)
        self.reconnects += 1

    async def ensure_live(self):
        if self.browser and self.browser.is_connected():
            return
        async with self._lock:
            if self.browser and self.browser.is_connected():
                return
            await self._reconnect()

    async def run(self, code, ns):
        await self.ensure_live()
        S = self.ns.setdefault(ns, {})
        browser = self.browser
        ctx = browser.contexts[0] if browser.contexts else None

        async def new_bg_page(url=None):
            """Open ONE fresh background tab and return it (never steals focus).
            Stateless: call it as many times as you want; you decide where to
            keep the pages. Pass url to navigate, or omit for about:blank."""
            c = browser.contexts[0]
            cdp = await browser.new_browser_cdp_session()
            before = {id(x) for x in c.pages}
            await cdp.send("Target.createTarget", {"url": url or "about:blank", "background": True})
            await asyncio.sleep(0.4)
            new = [x for x in c.pages if id(x) not in before]
            return new[0] if new else c.pages[-1]

        g = {"browser": browser, "ctx": ctx, "S": S, "G": self.G,
             "asyncio": asyncio, "out": {}, "new_bg_page": new_bg_page}
        body = "".join("    " + ln + "\n" for ln in code.splitlines())
        if not body.strip():
            body = "    pass\n"
        loc = {}
        exec("async def __run():\n" + body, g, loc)
        res = await loc["__run"]()
        if res is None:
            res = g["out"].get("result")
        return {"ok": True, "result": res}

    async def handle(self, reader, writer):
        try:
            line = await reader.readline()
            req = json.loads(line.decode())
            op = req.get("op", "run")
            if op == "ping":
                resp = {"ok": True, "result": "pong"}
            elif op == "info":
                connected = bool(self.browser and self.browser.is_connected())
                contexts = len(self.browser.contexts) if connected else 0
                resp = {"ok": True, "result": {
                    "name": self.name, "target": self.target_desc,
                    "cdp_url": self.cdp_url, "connected": connected,
                    "contexts": contexts, "reconnects": self.reconnects,
                    "uptime_s": round(time.time() - self.started, 1),
                    "namespaces": {k: list(v.keys()) for k, v in self.ns.items()},
                    "shared_keys": list(self.G.keys()),
                }}
            elif op == "run":
                resp = await self.run(req["code"], req.get("ns", "default"))
            else:
                resp = {"ok": False, "error": f"unknown op {op!r}"}
        except Exception:
            resp = {"ok": False, "error": traceback.format_exc()}
        try:
            writer.write((json.dumps(resp, default=str) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()

    async def serve(self):
        os.makedirs(BASE, exist_ok=True)
        sp = sock_path(self.name)
        # Single-winner guard: hold an exclusive flock for this daemon name so
        # two racing spawns can't both connect (double approval) and clobber the
        # socket (orphaning a process). Loser exits before connecting.
        self._lockf = open(lock_path(self.name), "w")
        try:
            fcntl.flock(self._lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("LOCKED: another daemon owns this name; exiting", flush=True)
            return
        if os.path.exists(sp):
            os.unlink(sp)
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, task.cancel)  # run the finally below on kill
        try:
            await self._connect()                 # triggers approval (once)
        except BaseException:
            self._stop_browser()
            raise
        server = await asyncio.start_unix_server(self.handle, path=sp)
        os.chmod(sp, 0o600)
        json.dump({"pid": os.getpid(), "target": self.target_desc,
                   "spec": self.spec, "cdp_url": self.cdp_url,
                   "started": self.started}, open(meta_path(self.name), "w"))
        print("READY", flush=True)
        try:
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            self._stop_browser()
            for p in (sp, meta_path(self.name)):
                try: os.unlink(p)
                except OSError: pass
            try: fcntl.flock(self._lockf, fcntl.LOCK_UN); self._lockf.close()
            except OSError: pass


# ---------------------------------------------------------------- client
def send(name, payload, timeout=120):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(sock_path(name))
    s.sendall((json.dumps(payload) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    return json.loads(buf.decode())


def alive(name):
    if not os.path.exists(sock_path(name)):
        return False
    try:
        return send(name, {"op": "ping"}, timeout=3).get("ok") is True
    except OSError:
        try: os.unlink(sock_path(name))   # stale socket, clean it
        except OSError: pass
        return False


def spec_from_args(args):
    return {"browser": args.browser, "user_data_dir": args.user_data_dir,
            "cdp_url": args.cdp_url,
            "launch": ("headful" if args.headful else "headless") if (args.launch or args.headful) else None,
            "profile": args.profile,
            "executable": args.executable}


def target_flags(spec):
    flags = []
    if spec.get("launch"):        flags += ["--launch"] + (["--headful"] if spec["launch"] == "headful" else [])
    if spec.get("profile"):       flags += ["--profile", spec["profile"]]
    if spec.get("executable"):    flags += ["--executable", spec["executable"]]
    if spec.get("cdp_url"):       flags += ["--cdp-url", spec["cdp_url"]]
    if spec.get("user_data_dir"): flags += ["--user-data-dir", spec["user_data_dir"]]
    if spec.get("browser"):       flags += ["--browser", spec["browser"]]
    return flags


def ensure_daemon(name, spec):
    if alive(name):
        return
    os.makedirs(BASE, exist_ok=True)
    if spec.get("launch"):
        check_launch(spec)
    else:
        resolve(**spec)   # fail fast in the client with a clear error
    import subprocess
    cmd = [sys.executable, os.path.abspath(__file__), "serve", name] + target_flags(spec)
    lf = open(log_path(name), "w")
    subprocess.Popen(cmd, stdout=lf, stderr=lf, start_new_session=True)
    deadline = time.time() + 300   # approval dialog, or a first-time Chromium download
    while time.time() < deadline:
        if alive(name):
            return
        time.sleep(0.4)
    raise RuntimeError(f"daemon {name!r} did not become ready; see {log_path(name)}")


def list_daemons():
    if not os.path.isdir(BASE):
        return []
    return [(fn[:-5], alive(fn[:-5]))
            for fn in sorted(os.listdir(BASE)) if fn.endswith(".sock")]


# ---------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(prog="tether")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_target(p):
        p.add_argument("--browser")
        p.add_argument("--user-data-dir")
        p.add_argument("--cdp-url")
        p.add_argument("--launch", action="store_true")
        p.add_argument("--headful", action="store_true")
        p.add_argument("--profile")
        p.add_argument("--executable")

    pr = sub.add_parser("run")
    pr.add_argument("daemon")
    pr.add_argument("code", nargs="?", default="-")
    pr.add_argument("-n", "--ns", default="default")
    add_target(pr)

    ps = sub.add_parser("serve")
    ps.add_argument("daemon")
    add_target(ps)

    sub.add_parser("kill").add_argument("daemon")
    sub.add_parser("info").add_argument("daemon")
    sub.add_parser("ls")

    args = ap.parse_args()

    if args.cmd == "serve":
        asyncio.run(Daemon(args.daemon, spec_from_args(args)).serve())

    elif args.cmd == "ls":
        ds = list_daemons()
        if not ds:
            print("(no daemons)")
        for name, ok in ds:
            meta = {}
            if os.path.exists(meta_path(name)):
                try: meta = json.load(open(meta_path(name)))
                except Exception: pass
            print(f"{'●' if ok else '○'} {name:16} {meta.get('target','')}")

    elif args.cmd == "kill":
        if os.path.exists(meta_path(args.daemon)):
            try:
                pid = json.load(open(meta_path(args.daemon))).get("pid")
                if pid: os.kill(pid, 15)
            except (OSError, ValueError):
                pass
        for p in (sock_path(args.daemon), meta_path(args.daemon)):
            try: os.unlink(p)
            except OSError: pass
        print(f"killed {args.daemon}")

    elif args.cmd == "info":
        print(json.dumps(send(args.daemon, {"op": "info"})["result"],
                         indent=2, ensure_ascii=False))

    elif args.cmd == "run":
        code = sys.stdin.read() if args.code == "-" else args.code
        spec = spec_from_args(args)
        ensure_daemon(args.daemon, spec)
        resp = send(args.daemon, {"op": "run", "code": code, "ns": args.ns})
        if resp.get("ok"):
            r = resp["result"]
            print(r if isinstance(r, str) else json.dumps(r, indent=2, ensure_ascii=False))
        else:
            sys.stderr.write(resp.get("error", "error") + "\n")
            sys.exit(1)


if __name__ == "__main__":
    main()
