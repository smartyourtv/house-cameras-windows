"""Frame engine: one thread per camera, latest-frame buffer.

Decode is OpenCV's FFmpeg backend — H.264, H.265/HEVC and MJPEG all
decode through it (spec §1.3). Snapshot sources are polled over HTTP
with the credentials attached by an auth handler (never in the URL,
never in a command line — there are no child processes at all).

A camera's status is judged by the age of its last good frame
(freshness), never by whether a thread happens to exist.
"""
import os
import threading
import time
import urllib.request

os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;4000000")

from .util import LOG, build_url  # noqa: E402


def _http_opener(username, password, host):
    if not username:
        return urllib.request.build_opener()
    mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    mgr.add_password(None, "http://%s/" % host, username, password)
    return urllib.request.build_opener(
        urllib.request.HTTPBasicAuthHandler(mgr),
        urllib.request.HTTPDigestAuthHandler(mgr))


class CameraWorker:
    def __init__(self, camera, source, log=LOG):
        self.camera = camera
        self.source = source
        self.log = log
        self._frame = None            # BGR numpy array (or JPEG bytes for snapshot)
        self._frame_is_jpeg = False
        self._last_frame_at = 0.0
        self._status = "starting"
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="cam-%s" % self.camera.name)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # -- state ----------------------------------------------------------
    def latest(self):
        with self._lock:
            return self._frame, self._frame_is_jpeg, self._last_frame_at

    def status(self):
        """(state, age_seconds) — state from frame freshness."""
        age = time.time() - self._last_frame_at if self._last_frame_at else None
        if self._last_frame_at and age is not None and age < 10:
            return "live", age
        if self._status == "error":
            return "no signal", age
        return self._status, age

    def _set_frame(self, frame, is_jpeg=False):
        with self._lock:
            self._frame = frame
            self._frame_is_jpeg = is_jpeg
            self._last_frame_at = time.time()
        self._status = "live"

    # -- loops ------------------------------------------------------------
    def _run(self):
        if self.source.kind == "snapshot":
            self._run_snapshot()
        else:
            self._run_stream()

    def _stream_url(self):
        cred = self.camera.credentials
        return build_url(self.source.scheme, self.camera.host,
                         self.source.port, self.source.path,
                         cred.username, cred.password)

    def _run_stream(self):
        import cv2  # local: keeps --self-test importable without cv2
        backoff = 2.0
        while not self._stop.is_set():
            cap = None
            try:
                self._status = "connecting"
                cap = cv2.VideoCapture(self._stream_url(), cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    raise RuntimeError("stream would not open")
                backoff = 2.0
                while not self._stop.is_set():
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        raise RuntimeError("stream ended")
                    self._set_frame(frame)
            except Exception as exc:
                self._status = "error"
                self.log("%s: %s — retrying in %ds"
                         % (self.camera.name, exc, int(backoff)))
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 1.6, 30.0)

    def _run_snapshot(self):
        cred = self.camera.credentials
        opener = _http_opener(cred.username, cred.password, self.camera.host)
        url = build_url("http", self.camera.host, self.source.port or 80,
                        self.source.path)
        while not self._stop.is_set():
            try:
                req = urllib.request.Request(url)
                with opener.open(req, timeout=5) as resp:
                    data = resp.read()
                if data[:2] == b"\xff\xd8":  # JPEG magic
                    self._set_frame(data, is_jpeg=True)
                    self._status = "live"
                else:
                    self._status = "error"
            except Exception:
                self._status = "error"
            self._stop.wait(2.0)


def probe_stream(url, timeout=3.0):
    """True only when a frame actually decodes from ``url``.
    Used by the ingest ladder; ``url`` is sensitive — never log it."""
    import cv2
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    try:
        if not cap.isOpened():
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            ok, frame = cap.read()
            if ok and frame is not None:
                return True
        return False
    finally:
        cap.release()


def probe_snapshot(url, username="", password="", host="", timeout=3.0):
    """True when ``url`` returns a real JPEG."""
    opener = _http_opener(username, password, host)
    try:
        with opener.open(urllib.request.Request(url), timeout=timeout) as resp:
            return resp.read(2) == b"\xff\xd8"
    except Exception:
        return False
