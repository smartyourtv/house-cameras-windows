"""In-app updater — standing rule (2026-10-15): check GitHub, show
ONE subtle notice per version (dismissed = never again for that
version), install only when the user taps. The downloaded installer
is verified (size + SHA-256) before it is launched; a failed
verification means nothing runs.
"""
import hashlib
import json
import os
import time
import urllib.request

from . import APP_VERSION

UPDATE_REPO = "smartyourtv/house-cameras-windows"
UPDATE_API_LATEST = "https://api.github.com/repos/%s/releases/latest" % UPDATE_REPO
UPDATE_RELEASES_PAGE = "https://github.com/%s/releases" % UPDATE_REPO
UPDATE_SETUP_NAME = "HouseCameras-Setup.exe"   # == packaging/app-config.json
UPDATE_CHECKSUM_NAME = UPDATE_SETUP_NAME + ".sha256"
CHECK_INTERVAL_HOURS = 24


def parse_version(text):
    if not text:
        return None
    text = str(text).strip().lstrip("vV")
    parts = []
    for piece in text.split("."):
        if not piece.isdigit():
            return None
        parts.append(int(piece))
    return tuple(parts) if parts else None


def is_newer_version(candidate, current=APP_VERSION):
    c, cur = parse_version(candidate), parse_version(current)
    if c is None or cur is None:
        return False
    width = max(len(c), len(cur))
    return c + (0,) * (width - len(c)) > cur + (0,) * (width - len(cur))


def parse_release(payload):
    assets = {a.get("name"): a for a in payload.get("assets", [])}
    setup = assets.get(UPDATE_SETUP_NAME) or {}
    digest = setup.get("digest") or ""
    sha = digest.split(":", 1)[1] if digest.startswith("sha256:") else None
    checksum = assets.get(UPDATE_CHECKSUM_NAME) or {}
    return {"version": (payload.get("tag_name") or "").lstrip("vV"),
            "page": payload.get("html_url", UPDATE_RELEASES_PAGE),
            "setup": {"url": setup.get("browser_download_url"),
                      "size": setup.get("size"), "sha256": sha},
            "checksum_url": checksum.get("browser_download_url")}


def parse_checksum_text(text):
    for token in (text or "").split():
        if len(token) == 64 and all(c in "0123456789abcdef" for c in token.lower()):
            return token.lower()
    return None


# --- notice state (one subtle notice per version) --------------------------

def _state_path():
    from .store import data_dir
    return os.path.join(data_dir(), "update-state.json")


def load_state(path=None):
    try:
        with open(path or _state_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state, path=None):
    try:
        with open(path or _state_path(), "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError:
        pass


def update_notice_wanted(state, version):
    return bool(version) and is_newer_version(version) \
        and state.get("dismissed") != version


def dismiss_update_notice(state, version, path=None):
    state = dict(state)
    state["dismissed"] = version
    save_state(state, path=path)
    return state


def update_check_due(state):
    last = state.get("last_check")
    if not last:
        return True
    try:
        then = time.mktime(time.strptime(last, "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return True
    return (time.time() - then) > CHECK_INTERVAL_HOURS * 3600


def record_update_check(state, path=None):
    state = dict(state)
    state["last_check"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_state(state, path=path)
    return state


# --- network ----------------------------------------------------------------

def check_latest(opener=None, timeout=10):
    req = urllib.request.Request(UPDATE_API_LATEST)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "HouseCameras/%s" % APP_VERSION)
    open_fn = opener or (lambda r, timeout=None: urllib.request.urlopen(r, timeout=timeout))
    with open_fn(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return parse_release(payload)


def verify_download(path, size=None, sha256=None):
    try:
        if size is not None and os.path.getsize(path) != int(size):
            return False, "downloaded file is the wrong size"
        if sha256:
            h = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest().lower() != str(sha256).lower():
                return False, "downloaded file failed its safety check"
        return True, ""
    except OSError as exc:
        return False, str(exc)


def download_update(release, dest_dir, opener=None):
    url = (release.get("setup") or {}).get("url")
    if not url:
        return None, "the release has no installer attached"
    open_fn = opener or (lambda r, timeout=None: urllib.request.urlopen(r, timeout=timeout))
    dest = os.path.join(dest_dir, UPDATE_SETUP_NAME)
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "HouseCameras/%s" % APP_VERSION)
        with open_fn(req, timeout=60) as resp, open(dest, "wb") as fh:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
        return dest, None
    except Exception as exc:
        return None, str(exc)
