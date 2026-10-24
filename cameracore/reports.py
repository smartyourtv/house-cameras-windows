"""Crash & error reports — standing rule (2026-10-17): every app
captures its crashes TWO ways: an in-app reports view, and a report
FILE in the user's Downloads folder, written synchronously at crash
time. Reports are never auto-uploaded anywhere.
"""
import os
import platform
import sys
import time
import traceback

from . import APP_NAME, APP_VERSION
from .util import LOG, redact

PREFIX = "HouseCameras-crash-"


def crash_report_name(when=None):
    return PREFIX + time.strftime("%Y%m%d-%H%M%S", when or time.localtime()) + ".txt"


def downloads_dir():
    home = os.path.expanduser("~")
    path = os.path.join(home, "Downloads")
    return path if os.path.isdir(path) else home


def report_dirs(extra=None):
    dirs = [downloads_dir()]
    try:
        from .store import data_dir
        dirs.append(data_dir())
    except Exception:
        pass
    return (extra or []) + dirs


def format_report(etype, evalue, etb, log_tail=None):
    lines = [
        "%s hit a problem and caught it." % APP_NAME,
        "Time: %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "App: %s %s" % (APP_NAME, APP_VERSION),
        "Device: %s %s (%s)" % (platform.system(), platform.release(),
                                platform.machine()),
        "Error: %s: %s" % (getattr(etype, "__name__", etype), evalue),
        "",
        "Details:",
    ]
    if etb is not None:
        lines += [redact(l) for l in
                  "".join(traceback.format_exception(etype, evalue, etb)).splitlines()]
    lines += ["", "Recent activity:"]
    lines += log_tail if log_tail is not None else LOG.tail(40)
    return "\n".join(lines) + "\n"


def write_crash_report(etype, evalue, etb, dirs=None, log_tail=None):
    """Write synchronously; return the path or None."""
    text = format_report(etype, evalue, etb, log_tail=log_tail)
    for folder in (dirs or report_dirs()):
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, crash_report_name())
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            return path
        except OSError:
            continue
    return None


def list_crash_reports(dirs=None):
    out = []
    seen = set()
    for folder in (dirs or report_dirs()):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder), reverse=True):
            if name.startswith(PREFIX) and name.endswith(".txt"):
                path = os.path.join(folder, name)
                if path not in seen:
                    seen.add(path)
                    out.append({"name": name, "path": path,
                                "mtime": os.path.getmtime(path)})
    return out


def read_crash_report(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def delete_crash_report(path):
    name = os.path.basename(path or "")
    if not (name.startswith(PREFIX) and name.endswith(".txt")):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def install_excepthook(log=LOG):
    def hook(etype, evalue, etb):
        path = write_crash_report(etype, evalue, etb)
        log("Crash report saved: %s" % (path or "could not be saved"))
        sys.__excepthook__(etype, evalue, etb)
    sys.excepthook = hook
