"""Small shared helpers: credential-safe logging above all.

Rule (2026-10-23 camera-stack audit): a URL carrying credentials must
never reach a log file, a crash report, or the screen. Every string
that might contain one goes through :func:`redact` first.
"""
import re
import threading
import time

_URL_CRED_RE = re.compile(r"(?i)\b(rtsp|rtsps|http|https)://([^/@\s:]+)(:[^/@\s]*)?@")


def redact(text):
    """Replace ``scheme://user:pass@`` with ``scheme://***@`` in text."""
    if text is None:
        return ""
    return _URL_CRED_RE.sub(lambda m: "%s://***@" % m.group(1), str(text))


def build_url(scheme, host, port, path, username="", password=""):
    """Build a stream URL in memory. The result is sensitive: use it to
    connect, never to log or store (audit item 2 — URLs are built at
    connect time from a separate credentials object, never stored)."""
    if not path.startswith("/"):
        path = "/" + path
    auth = ""
    if username:
        from urllib.parse import quote
        auth = quote(username, safe="")
        if password:
            auth += ":" + quote(password, safe="")
        auth += "@"
    if port:
        return "%s://%s%s:%d%s" % (scheme, auth, host, int(port), path)
    return "%s://%s%s%s" % (scheme, auth, host, path)


class Log:
    """Thread-safe in-memory log with redaction; keeps a tail for the
    diagnostics view and crash reports."""

    def __init__(self, keep=400):
        self._lines = []
        self._keep = keep
        self._lock = threading.Lock()

    def __call__(self, message):
        line = "%s  %s" % (time.strftime("%H:%M:%S"), redact(message))
        with self._lock:
            self._lines.append(line)
            if len(self._lines) > self._keep:
                del self._lines[: len(self._lines) - self._keep]

    def tail(self, n=80):
        with self._lock:
            return list(self._lines[-n:])


LOG = Log()
