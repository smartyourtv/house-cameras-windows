"""Generic RTSP known-path library (ingest ladder layer c).

Paths seen across common camera families. ``{ch}`` is the channel
(1-based). Probing tries these in order; a path only counts when a
frame actually decodes (see ingest.py) — never on a 200 alone.
"""

GENERIC_RTSP_PATHS = [
    "/11", "/12",                                   # HiP2P / generic CN family
    "/onvif1", "/onvif2",
    "/stream1", "/stream2", "/stream_0", "/stream_1",
    "/live/ch00_0", "/live/ch00_1",
    "/ch0_0.264", "/ch0_1.264",
    "/Streaming/Channels/101", "/Streaming/Channels/102",   # Hikvision
    "/cam/realmonitor?channel=1&subtype=0",                  # Dahua
    "/cam/realmonitor?channel=1&subtype=1",
    "/h264/ch1/main/av_stream", "/h264/ch1/sub/av_stream",
    "/video1", "/video2", "/live", "/rtsp", "/1", "/0",
    "/user=admin_password=_channel=1_stream=0.sdp",          # legacy CN
]

GENERIC_SNAPSHOT_PATHS = [
    "/snapshot.jpg", "/snapshot.cgi", "/snap.jpg", "/image.jpg",
    "/jpg/image.jpg", "/cgi-bin/snapshot.cgi",
    "/webcapture.jpg?command=snap&channel=1",
    "/ISAPI/Streaming/channels/101/picture",                 # Hikvision
    "/cgi-bin/api.cgi?cmd=Snap&channel=0",                   # Reolink
]

GENERIC_MJPEG_PATHS = [
    "/video.mjpg", "/mjpg/video.mjpg", "/videostream.cgi",
    "/cgi-bin/mjpeg", "/axis-cgi/mjpg/video.cgi",
]


def expand(paths, channel=1):
    return [p.replace("{ch}", str(channel)) for p in paths]
