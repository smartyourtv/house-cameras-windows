"""The ingest ladder — spec §1.2, in order, first *verified* picture
wins:

  (a) ONVIF profiles
  (b) the family's vendor template
  (c) generic RTSP — known-path library, auto-probed
  (d) MJPEG stream, then HTTP JPEG snapshot polling (last resort)

If nothing produces a picture, the result says so plainly — for a
closed cloud-only camera there is nothing on the LAN to accept
(spec §1.5), and the app must not promise otherwise.
"""
from . import engine, onvif
from .models import CameraSource
from .paths import GENERIC_MJPEG_PATHS, GENERIC_RTSP_PATHS, GENERIC_SNAPSHOT_PATHS
from .templates import template_for
from .util import LOG, build_url


def _rtsp_url(camera, source):
    cred = camera.credentials
    return build_url("rtsp", camera.host, source.port, source.path,
                     cred.username, cred.password)


def _try_rtsp(camera, source, stream_probe, log):
    if stream_probe(_rtsp_url(camera, source)):
        log("%s: picture verified via %s (%s)"
            % (camera.name, source.via or "rtsp", source.path))
        return CameraSource(kind="rtsp", path=source.path, port=source.port,
                            scheme="rtsp", via=source.via)
    return None


def run_ladder(camera, onvif_xaddr="", stream_probe=None, snapshot_probe=None,
               onvif_lookup=None, log=LOG):
    """Returns (main_source, sub_source or empty, note). Either source
    may be an empty CameraSource when nothing verified."""
    stream_probe = stream_probe or engine.probe_stream
    snapshot_probe = snapshot_probe or engine.probe_snapshot
    onvif_lookup = onvif_lookup or onvif.get_stream_uri
    cred = camera.credentials
    tpl = template_for(camera.family)

    # (a) ONVIF
    if onvif_xaddr:
        uri = onvif_lookup(onvif_xaddr, cred.username, cred.password)
        split = onvif.split_rtsp_url(uri) if uri else None
        if split:
            host, port, path = split
            src = CameraSource(kind="rtsp", path=path, port=port, via="onvif")
            if stream_probe(_rtsp_url(camera, src)):
                log("%s: picture verified via ONVIF (%s)" % (camera.name, path))
                return src, camera.sub, "ONVIF"
    # (b) vendor template
    tried_main = None
    if tpl["main"].path:
        tried_main = _try_rtsp(camera, tpl["main"], stream_probe, log)
        if tried_main:
            sub = _try_rtsp(camera, tpl["sub"], stream_probe, log) or CameraSource()
            return tried_main, sub, tpl["label"]
    # (c) generic RTSP path library
    for path in GENERIC_RTSP_PATHS:
        if tpl["main"].path and path == tpl["main"].path:
            continue
        src = CameraSource(kind="rtsp", path=path, port=554, via="generic")
        hit = _try_rtsp(camera, src, stream_probe, log)
        if hit:
            return hit, camera.sub, "generic RTSP path %s" % path
    # (d1) MJPEG
    for path in GENERIC_MJPEG_PATHS:
        src = CameraSource(kind="mjpeg", path=path, port=80, scheme="http",
                           via="mjpeg")
        url = build_url("http", camera.host, 80, path,
                        cred.username, cred.password)
        if stream_probe(url):
            log("%s: picture verified via MJPEG (%s)" % (camera.name, path))
            return src, camera.sub, "MJPEG"
    # (d2) snapshot polling — last resort
    snap_paths = ([tpl["snapshot"]] if tpl.get("snapshot") else []) \
        + GENERIC_SNAPSHOT_PATHS
    for path in snap_paths:
        if not path:
            continue
        url = build_url("http", camera.host, 80, path)
        if snapshot_probe(url, cred.username, cred.password, camera.host):
            src = CameraSource(kind="snapshot", path=path, port=80,
                               scheme="http", via="snapshot")
            log("%s: picture verified via snapshot polling (%s)"
                % (camera.name, path))
            return src, camera.sub, "snapshot polling"
    log("%s: no local stream could be verified." % camera.name)
    return CameraSource(), CameraSource(), (
        "No local stream answered. If this camera only works through "
        "its maker's cloud app, it cannot be added — it offers nothing "
        "on the local network to view (see Help).")
