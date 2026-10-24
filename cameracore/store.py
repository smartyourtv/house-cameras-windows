"""Config storage with conservative, verified, logged self-repair.

Location: %LOCALAPPDATA%\\HouseCameras\\cameras.json (per-user).
Passwords are protected with Windows DPAPI (current-user scope) when
running on Windows; elsewhere a clearly-marked plain fallback is used
so tests/dev on other platforms still work — the shipped app always
runs on Windows, where DPAPI applies.

Self-repair rules (standing, 2026-10-17): if the config is unreadable
or malformed, keep the broken file as ``cameras.json.bad-<stamp>``,
restore the last known-good backup if one verifies, else fall back to
the seeded defaults; re-read after repair and only claim success if
the re-read parses. Every repair (and failed repair) is logged.
"""
import base64
import ctypes
import json
import os
import sys
import time

from .models import Camera
from .util import LOG

_DPAPI_PREFIX = "dpapi:"
_PLAIN_PREFIX = "plain:"


def data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "HouseCameras")
    os.makedirs(path, exist_ok=True)
    return path


def config_path(base=None):
    return os.path.join(base or data_dir(), "cameras.json")


# --- password protection -------------------------------------------------

class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


_CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _dpapi(data_bytes, protect=True):
    """Bytes in, bytes out. (A str round-trip through latin-1/utf-8
    corrupted cipher bytes >= 0x80 and silently broke unprotect on
    Windows — caught by the CI test gate on the first v1.0.0 build.)"""
    if sys.platform != "win32":
        return None
    buf = ctypes.create_string_buffer(data_bytes, len(data_bytes))
    blob_in = _DataBlob(len(data_bytes),
                        ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    blob_out = _DataBlob()
    fn = (ctypes.windll.crypt32.CryptProtectData if protect
          else ctypes.windll.crypt32.CryptUnprotectData)
    if not fn(ctypes.byref(blob_in), None, None, None, None,
              _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)):
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def protect_password(password):
    if not password:
        return ""
    out = _dpapi(password.encode("utf-8"), protect=True)
    if out is not None:
        return _DPAPI_PREFIX + base64.b64encode(out).decode("ascii")
    return _PLAIN_PREFIX + base64.b64encode(password.encode("utf-8")).decode("ascii")


def unprotect_password(stored):
    if not stored:
        return ""
    try:
        if stored.startswith(_DPAPI_PREFIX):
            raw = base64.b64decode(stored[len(_DPAPI_PREFIX):])
            out = _dpapi(raw, protect=False)
            return out.decode("utf-8") if out is not None else ""
        if stored.startswith(_PLAIN_PREFIX):
            return base64.b64decode(stored[len(_PLAIN_PREFIX):]).decode("utf-8")
    except Exception:
        return ""
    return ""


# --- starter list ------------------------------------------------------------
# The shipped app starts EMPTY on purpose: no owner's camera addresses
# or layout ever live in the repo. A machine may carry an optional
# ``fleet-seed.json`` (same schema as cameras.json) in its data folder,
# placed there at install time by whoever sets the machine up; when no
# config exists yet, the seed becomes the starting list. Discovery is
# the normal way cameras are added.

def seed_path(base=None):
    return os.path.join(base or data_dir(), "fleet-seed.json")


def default_cameras(base=None):
    path = seed_path(base)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return _parse(fh.read())
        except Exception:
            pass
    return []


# --- load / save with repair ----------------------------------------------

def _parse(text):
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("cameras"), list):
        raise ValueError("config shape not recognized")
    return [Camera.from_dict(c, unprotect=unprotect_password) for c in data["cameras"]]


def load_cameras(path=None, log=LOG):
    """Returns (cameras, repaired: bool). Repairs in place when needed."""
    path = path or config_path()
    if not os.path.exists(path):
        cams = default_cameras(os.path.dirname(path) or None)
        save_cameras(cams, path=path)
        log("No config found — seeded the starter camera list (no passwords).")
        return cams, False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return _parse(fh.read()), False
    except Exception as exc:
        log("Config could not be read (%s) — repairing." % exc)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bad = "%s.bad-%s" % (path, stamp)
    try:
        os.replace(path, bad)
        log("Kept the broken config as %s" % os.path.basename(bad))
    except OSError:
        pass
    backup = path + ".bak"
    if os.path.exists(backup):
        try:
            with open(backup, "r", encoding="utf-8") as fh:
                cams = _parse(fh.read())
            save_cameras(cams, path=path)
            with open(path, "r", encoding="utf-8") as fh:  # verify repair
                _parse(fh.read())
            log("Config repaired from the last good backup and verified.")
            return cams, True
        except Exception as exc:
            log("Backup repair failed (%s) — falling back to defaults." % exc)
    cams = default_cameras(os.path.dirname(path) or None)
    save_cameras(cams, path=path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            _parse(fh.read())
        log("Config repaired with the starter camera list and verified.")
    except Exception as exc:
        log("Config repair FAILED verification (%s)." % exc)
    return cams, True


def save_cameras(cameras, path=None):
    path = path or config_path()
    payload = {"version": 1,
               "cameras": [c.to_dict(protect=protect_password) for c in cameras]}
    text = json.dumps(payload, indent=2)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                previous = fh.read()
            _parse(previous)  # only a good file becomes the backup
            with open(path + ".bak", "w", encoding="utf-8") as fh:
                fh.write(previous)
        except Exception:
            pass  # never back up a broken file over a good backup
    os.replace(tmp, path)
