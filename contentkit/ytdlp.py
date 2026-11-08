"""A yt-dlp that keeps working when YouTube changes.

YouTube changes its player every few weeks, and each change breaks yt-dlp until a fix ships,
usually within days. Distro packages lag months behind, so contentkit keeps its own yt-dlp in
~/.contentkit/tools/yt-dlp (a private venv: no sudo, does not touch system Python) and:

  1. refreshes it in the background of normal use when it is older than MAX_AGE;
  2. when a run fails the way an outdated yt-dlp fails, updates to the nightly build
     (where YouTube fixes land first) and retries;
  3. if YouTube still refuses, retries with other YouTube player clients;
  4. otherwise reports the real error with the next step (usually: use a browser login).

CONTENTKIT_YTDLP=/path/to/yt-dlp pins a specific binary and turns all of this off.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

TOOL = Path.home() / ".contentkit" / "tools" / "yt-dlp"
BIN = TOOL / "bin" / "yt-dlp"
PY = TOOL / "bin" / "python"
STAMP = TOOL / ".last-update"
MAX_AGE = 3 * 86400          # routine refresh
RETRY_GAP = 3600             # do not re-download on every failure in a loop

# what an outdated yt-dlp says when YouTube has changed underneath it
STALE = ("precondition check failed", "no video formats found", "unable to extract",
         "nsig", "signature", "challenge", "requested format is not available",
         "http error 403", "http error 400", "latest version", "please report this issue",
         "no such option")
# what YouTube says when it wants proof of a real user; a different client or a login helps
BOT = ("sign in to confirm", "not a bot", "po token", "rate-limit", "rate limit")
# other player clients to try, most reliable first (unknown names are skipped by yt-dlp)
CLIENTS = ("tv,web_safari", "mweb", "android_vr")


def _log(msg):
    print(f"[contentkit] {msg}", file=sys.stderr)


def _age():
    return time.time() - STAMP.stat().st_mtime if STAMP.exists() else float("inf")


def update(nightly=False):
    """Create or upgrade the managed yt-dlp. Returns True when it is usable afterwards."""
    try:
        if not PY.exists():
            _log("setting up a private, up-to-date yt-dlp (one time)...")
            TOOL.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([sys.executable, "-m", "venv", str(TOOL)], check=True, capture_output=True)
        cmd = [str(PY), "-m", "pip", "install", "-q", "-U", "yt-dlp[default]"]
        if nightly:
            cmd.insert(5, "--pre")   # yt-dlp publishes nightlies to PyPI as pre-releases
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
        STAMP.touch()
        _supported.clear()
        return True
    except (subprocess.SubprocessError, OSError) as e:
        STAMP.parent.mkdir(parents=True, exist_ok=True)
        STAMP.touch()            # offline or no venv support: don't retry on every call
        err = getattr(e, "stderr", b"") or b""
        _log(f"could not update yt-dlp ({(err.decode(errors='replace').strip().splitlines() or [e])[-1]})")
        return BIN.exists()


def binary():
    """Path of the yt-dlp to use, refreshing the managed copy when it is stale."""
    pinned = os.environ.get("CONTENTKIT_YTDLP")
    if pinned:
        return pinned
    if not BIN.exists() or _age() > MAX_AGE:
        update()
    if BIN.exists():
        return str(BIN)
    # managed copy impossible (no venv module, offline first run): fall back
    local = Path(sys.executable).with_name("yt-dlp")
    found = str(local) if local.exists() else shutil.which("yt-dlp")
    if not found:
        raise SystemExit("yt-dlp unavailable: install python3-venv (or pip install -U yt-dlp) and retry")
    return found


_supported = {}


def supports(ytdlp, flag):
    """Whether this yt-dlp knows a command-line flag (old builds die on unknown ones)."""
    if (ytdlp, flag) not in _supported:
        out = subprocess.run([ytdlp, "--help"], capture_output=True, text=True).stdout
        _supported[(ytdlp, flag)] = flag in out
    return _supported[(ytdlp, flag)]


def base_args(ytdlp):
    args = []
    # YouTube needs a JavaScript runtime for its player challenge; yt-dlp only looks for deno
    # by default, so hand it node when that's what is installed
    if not shutil.which("deno") and shutil.which("node") and supports(ytdlp, "--js-runtimes"):
        args += ["--js-runtimes", f"node:{shutil.which('node')}"]
    return args


def _error(proc):
    lines = proc.stderr.strip().splitlines()
    errors = [l for l in lines if l.startswith("ERROR") or "error:" in l]
    return (errors or lines or ["yt-dlp found nothing"])[-1]


def _ok(proc):
    return proc.returncode == 0 and proc.stdout.strip()


def run(args, target):
    """Run yt-dlp with self-healing. Returns the CompletedProcess of the last attempt;
    on failure its .error attribute holds the most useful error line."""
    ytdlp = binary()
    attempt = lambda exe, extra=(): subprocess.run(
        [exe, *base_args(exe), *args, *extra, target], capture_output=True, text=True)

    proc = attempt(ytdlp)
    if _ok(proc):
        return proc
    msg = _error(proc).lower()
    managed = ytdlp == str(BIN) and not os.environ.get("CONTENTKIT_YTDLP")

    if managed and any(k in msg for k in STALE) and _age() > RETRY_GAP:
        _log("yt-dlp looks out of date for this site; updating to the nightly build and retrying...")
        if update(nightly=True):
            proc = attempt(ytdlp)
            if _ok(proc):
                return proc
            msg = _error(proc).lower()

    youtube = "youtu" in target or target.startswith("ytsearch")
    if youtube and any(k in msg for k in STALE + BOT):
        for clients in CLIENTS:
            _log(f"retrying with YouTube player client(s) {clients}...")
            retry = attempt(ytdlp, ["--extractor-args", f"youtube:player_client={clients}"])
            if _ok(retry):
                return retry
        proc.error = _error(proc)
        if os.environ.get("CONTENTKIT_YTDLP") and any(k in msg for k in STALE):
            proc.error += "\n  -> the pinned CONTENTKIT_YTDLP looks outdated: unset it so contentkit manages yt-dlp"
        if any(k in msg for k in BOT):
            proc.error += "\n  -> YouTube wants a signed-in user: retry with --browser chrome (or firefox)"
        return proc

    proc.error = _error(proc)
    return proc


def status():
    """One-line health report for `contentkit fetch --doctor`."""
    try:
        exe = binary()
        ver = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.strip()
    except SystemExit as e:
        return str(e)
    age = _age()
    js = "deno" if shutil.which("deno") else ("node" if shutil.which("node") else "NONE (install node or deno)")
    when = "never" if age == float("inf") else f"{age / 86400:.1f} days ago"
    return f"yt-dlp {ver} at {exe}\n  last update check: {when}\n  JavaScript runtime: {js}"
