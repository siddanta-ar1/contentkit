"""Download songs and clips with yt-dlp, by URL or by search, and keep an index of them.

Every download gets a `.source.json` sidecar (URL, title, uploader, license label) and an
entry in ~/.contentkit/downloads/index.json, so an agent can find "that Resham Firiri
remix" later by title even when the filename is just the video id.
"""
import json
from pathlib import Path

from . import config, ytdlp

ASSETS = Path.home() / ".contentkit" / "downloads"
INDEX = ASSETS / "index.json"


def _index():
    return json.loads(INDEX.read_text()) if INDEX.exists() else []


def _add_to_index(entry):
    items = [e for e in _index() if e.get("file") != entry["file"]]
    items.append(entry)
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(items, indent=2, ensure_ascii=False))


def library(query=None):
    """Downloaded items, optionally filtered by a case-insensitive title/uploader match."""
    items = [e for e in _index() if Path(e["file"]).exists()]
    if query:
        q = query.lower()
        items = [e for e in items if q in (e.get("title") or "").lower() or q in (e.get("uploader") or "").lower()]
    return items


def download(url=None, audio_only=False, out_dir=None, license="", start=None, end=None, search=None,
             browser=None, cookies=None):
    """url, or search="song name artist" (takes YouTube's top result).

    Instagram, Facebook and some TikTok/X posts only download for a logged-in user:
    browser="chrome" (or brave, firefox, edge, chromium) reuses that browser's login on this
    machine; cookies="cookies.txt" uses an exported cookie file instead."""
    if not (url or search):
        raise SystemExit("Give a URL or --search \"song name\"")
    target = url or f"ytsearch1:{search}"
    out_dir = Path(out_dir or ASSETS)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["--no-playlist", "--restrict-filenames", "--print", "after_move:filepath",
           "--write-info-json", "--no-write-playlist-metafiles", "-o", str(out_dir / "%(extractor)s_%(id)s.%(ext)s")]
    if audio_only:
        cmd += ["-x", "--audio-format", "mp3", "--audio-quality", "0"]   # V0 mp3: ~8x smaller than wav
    else:
        # cap both sides (a 3840x1608 film-ratio video passes a height-only cap) and prefer
        # plain https formats: cut sections of m3u8 4K streams can come back without video
        cmd += ["-f", "bv*[height<=1920][width<=1920][protocol^=http]+ba/bv*[height<=1920][width<=1920]+ba"
                "/b[height<=1920][width<=1920]/bv*+ba/b", "--merge-output-format", "mp4"]
    if browser:
        cmd += ["--cookies-from-browser", browser]
    elif cookies:
        cmd += ["--cookies", str(cookies)]
    if start is not None or end is not None:
        cmd += ["--download-sections", f"*{start or 0}-{end or 'inf'}", "--force-keyframes-at-cuts"]
    proc = ytdlp.run(cmd, target)   # self-healing: updates yt-dlp / switches client when YouTube changes
    if proc.returncode != 0 or not proc.stdout.strip():
        msg = proc.error
        if not browser and "--browser" not in msg and any(k in msg.lower() for k in ("login", "cookies", "private", "rate-limit", "sign in")):
            msg += "\n  -> this site wants a login: retry with --browser chrome (or brave/firefox)"
        raise SystemExit(msg)
    path = Path(proc.stdout.strip().splitlines()[-1])
    if not audio_only:
        from . import ff
        if not any(s["codec_type"] == "video" for s in ff.probe(path)["streams"]):
            path.unlink(missing_ok=True)
            raise SystemExit(f"{target}: download has no video stream (try again, or without --section)")

    info_file = path.with_suffix(".info.json")
    info = json.loads(info_file.read_text()) if info_file.exists() else {}
    info_file.unlink(missing_ok=True)
    label = license or info.get("license") or (
        "private use (local only)" if config.private() else "UNKNOWN - reference only until cleared")
    meta = {
        "file": str(path),
        "url": info.get("webpage_url") or url,
        "search": search,
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "duration_s": info.get("duration"),
        "platform_license": info.get("license"),
        "license": label,
    }
    path.with_suffix(".source.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    _add_to_index(meta)
    return path, meta
