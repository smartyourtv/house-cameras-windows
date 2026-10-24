"""Headless self-test + diagnostics data.

Runs without any live camera: it exercises config load/repair,
password protection, the ladder (with fake probes), the decode engine
against a synthetic file, snapshot parsing, the updater math, and
crash-report writing. Exit-code friendly: returns (ok, lines).
"""
import os
import sys
import tempfile
import time

from . import APP_NAME, APP_VERSION


def run_self_test():
    lines = []
    failures = []

    def check(name, cond):
        lines.append("%s  %s" % ("PASS" if cond else "FAIL", name))
        if not cond:
            failures.append(name)

    lines.append("%s %s — self-test" % (APP_NAME, APP_VERSION))

    # redaction
    from .util import build_url, redact
    check("log redaction strips credentials",
          "secret" not in redact("rtsp://admin:secret@192.168.1.50/11"))
    check("URL builder keeps path + port",
          build_url("rtsp", "h", 554, "11").endswith("h:554/11"))

    # store: round trip + repair
    from .models import Camera, Credentials
    from .store import load_cameras, protect_password, save_cameras, unprotect_password
    check("password protection round-trips",
          unprotect_password(protect_password("pw-123")) == "pw-123")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cameras.json")
        cam = Camera(name="t", host="127.0.0.1", family="hip2p")
        cam.credentials = Credentials("admin", "pw-123")
        save_cameras([cam], path=path)
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        check("password not stored in plain text", "pw-123" not in raw)
        loaded, repaired = load_cameras(path=path)
        check("config round-trips", loaded and loaded[0].credentials.password == "pw-123"
              and not repaired)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        loaded, repaired = load_cameras(path=path)
        check("corrupt config repaired + verified", repaired and isinstance(loaded, list))

    # templates & paths
    from .paths import GENERIC_RTSP_PATHS
    from .templates import identify_family, template_for
    check("HiP2P template is /11 main, /12 sub",
          template_for("hip2p")["main"].path == "/11"
          and template_for("hip2p")["sub"].path == "/12")
    check("Reolink template present",
          "h264Preview" in template_for("reolink")["main"].path)
    check("generic path library non-empty", len(GENERIC_RTSP_PATHS) >= 10)
    check("family identification", identify_family("Server: ReolinkSrv") == "reolink")

    # ONVIF parsing
    from .onvif import parse_probe_matches, split_rtsp_url
    sample = ('<Envelope xmlns="http://www.w3.org/2003/05/soap-envelope">'
              '<Body><ProbeMatches xmlns="http://schemas.xmlsoap.org/ws/2005/04/discovery">'
              '<ProbeMatch><XAddrs>http://192.168.1.99/onvif/device_service</XAddrs>'
              '<Scopes>onvif://www.onvif.org/name/TestCam</Scopes></ProbeMatch>'
              '</ProbeMatches></Body></Envelope>')
    found = parse_probe_matches(sample)
    check("ONVIF discovery response parses",
          found and found[0]["xaddr"].startswith("http://192.168.1.99"))
    check("RTSP URL split drops credentials",
          split_rtsp_url("rtsp://u:p@h:8554/a/b") == ("h", 8554, "/a/b"))

    # ingest ladder with fake probes
    from .ingest import run_ladder
    cam = Camera(name="fake", host="10.0.0.9", family="hip2p")
    cam.credentials = Credentials("admin", "pw")
    main, _sub, note = run_ladder(
        cam, stream_probe=lambda url: url.endswith("/11"),
        snapshot_probe=lambda *a: False, onvif_lookup=lambda *a: None)
    check("ladder: template layer wins when it verifies",
          main.path == "/11" and main.via == "template")
    main, _sub, note = run_ladder(
        cam, stream_probe=lambda url: False,
        snapshot_probe=lambda *a: True, onvif_lookup=lambda *a: None)
    check("ladder: snapshot is the last resort", main.kind == "snapshot")
    main, _sub, note = run_ladder(
        cam, stream_probe=lambda url: False,
        snapshot_probe=lambda *a: False, onvif_lookup=lambda *a: None)
    check("ladder: honest failure when nothing answers",
          main.kind == "" and "cloud" in note)

    # decode engine against synthetic media
    try:
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "synthetic.mp4")
            writer = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*"mp4v"),
                                     5, (320, 240))
            for i in range(10):
                writer.write(np.full((240, 320, 3), i * 20, dtype="uint8"))
            writer.release()
            from .engine import probe_stream
            check("decode engine reads H.264-class media", probe_stream(video))
    except ImportError:
        lines.append("SKIP  decode engine (opencv not installed here)")

    # JPEG snapshot probe against a local file is covered in unit tests;
    # here: updater math + reports
    from . import updater
    check("version compare",
          updater.is_newer_version("1.0.1", "1.0.0")
          and not updater.is_newer_version("1.0.0", "1.0.0"))
    check("update notice once per version",
          updater.update_notice_wanted({}, "9.9.9")
          and not updater.update_notice_wanted({"dismissed": "9.9.9"}, "9.9.9"))
    from . import reports
    with tempfile.TemporaryDirectory() as tmp:
        try:
            raise ValueError("self-test boom")
        except ValueError:
            etype, evalue, etb = sys.exc_info()
        path = reports.write_crash_report(etype, evalue, etb, dirs=[tmp],
                                          log_tail=["line"])
        text = reports.read_crash_report(path) if path else ""
        check("crash report written + listed + deleted",
              "ValueError: self-test boom" in text
              and any(r["path"] == path for r in reports.list_crash_reports(dirs=[tmp]))
              and reports.delete_crash_report(path))

    lines.append("SELF-TEST %s (%d failure(s))"
                 % ("OK" if not failures else "FAILED", len(failures)))
    return not failures, lines


def diagnostics_lines(cameras=(), workers=None):
    """Plain-language status for the Diagnostics view."""
    import platform
    out = ["%s %s" % (APP_NAME, APP_VERSION),
           "Computer: %s %s" % (platform.system(), platform.release()),
           "Python: %s" % sys.version.split()[0]]
    try:
        import cv2
        out.append("Video engine: OpenCV %s (H.264 / HEVC / MJPEG)" % cv2.__version__)
    except ImportError:
        out.append("Video engine: NOT AVAILABLE — reinstall the app")
    workers = workers or {}
    now = time.time()
    for cam in cameras:
        w = workers.get(cam.name)
        if not cam.enabled:
            out.append("%s: turned off" % cam.name)
        elif w is None:
            out.append("%s (%s): not started" % (cam.name, cam.host or "no address"))
        else:
            state, age = w.status()
            age_txt = ("last picture %ds ago" % int(age)) if age is not None else "no picture yet"
            out.append("%s (%s): %s — %s" % (cam.name, cam.host, state, age_txt))
    return out
