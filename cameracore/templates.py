"""Per-family camera templates (ingest ladder layer b).

A template says: which ports the family usually answers on, its RTSP
main/sub stream paths, a snapshot path, and how to recognize the
family during discovery. Adding a new camera family = adding one
entry here; the ladder, engine, and UI never change (spec §1.4).
"""
from .models import CameraSource

TEMPLATES = {
    "hip2p": {
        "label": "HiP2P / CamHi family",
        "ports": [554, 80],
        "main": CameraSource(kind="rtsp", path="/11", port=554, via="template"),
        "sub": CameraSource(kind="rtsp", path="/12", port=554, via="template"),
        "snapshot": "/snapshot.jpg",
        "match": ["hichip", "hip2p", "camhi"],
    },
    "reolink": {
        "label": "Reolink",
        "ports": [554, 80, 9000],
        "main": CameraSource(kind="rtsp",
                             path="/h264Preview_01_main", port=554, via="template"),
        "sub": CameraSource(kind="rtsp",
                            path="/h264Preview_01_sub", port=554, via="template"),
        "snapshot": "/cgi-bin/api.cgi?cmd=Snap&channel=0",
        "match": ["reolink"],
    },
    "dahua": {
        "label": "Dahua / Amcrest",
        "ports": [554, 80],
        "main": CameraSource(kind="rtsp",
                             path="/cam/realmonitor?channel=1&subtype=0",
                             port=554, via="template"),
        "sub": CameraSource(kind="rtsp",
                            path="/cam/realmonitor?channel=1&subtype=1",
                            port=554, via="template"),
        "snapshot": "/cgi-bin/snapshot.cgi",
        "match": ["dahua", "amcrest"],
    },
    "hikvision": {
        "label": "Hikvision",
        "ports": [554, 80, 8000],
        "main": CameraSource(kind="rtsp", path="/Streaming/Channels/101",
                             port=554, via="template"),
        "sub": CameraSource(kind="rtsp", path="/Streaming/Channels/102",
                            port=554, via="template"),
        "snapshot": "/ISAPI/Streaming/channels/101/picture",
        "match": ["hikvision"],
    },
    "foscam": {
        "label": "Foscam",
        "ports": [88, 554],
        "main": CameraSource(kind="rtsp", path="/videoMain", port=554, via="template"),
        "sub": CameraSource(kind="rtsp", path="/videoSub", port=554, via="template"),
        "snapshot": "/cgi-bin/CGIProxy.fcgi?cmd=snapPicture2",
        "match": ["foscam"],
    },
    "xmeye": {
        "label": "XMEye family",
        "ports": [554, 80, 34567],
        "main": CameraSource(kind="rtsp", path="/user=admin_password=_channel=1_stream=0.sdp",
                             port=554, via="template"),
        "sub": CameraSource(kind="rtsp", path="/user=admin_password=_channel=1_stream=1.sdp",
                            port=554, via="template"),
        "snapshot": "/snapshot.jpg",
        "match": ["xmeye", "xm "],
    },
    "tapo": {
        "label": "TP-Link Tapo (RTSP must be enabled in the Tapo app)",
        "ports": [554],
        "main": CameraSource(kind="rtsp", path="/stream1", port=554, via="template"),
        "sub": CameraSource(kind="rtsp", path="/stream2", port=554, via="template"),
        "snapshot": "",
        "match": ["tapo"],
    },
    "generic": {
        "label": "Generic / unknown",
        "ports": [554, 80],
        "main": CameraSource(kind="rtsp", path="", port=554, via="generic"),
        "sub": CameraSource(kind="rtsp", path="", port=554, via="generic"),
        "snapshot": "",
        "match": [],
    },
}


def template_for(family):
    return TEMPLATES.get(family or "generic", TEMPLATES["generic"])


def identify_family(banner_text):
    """Map discovery banner text to a family key, or None."""
    text = (banner_text or "").lower()
    for key, tpl in TEMPLATES.items():
        if key == "generic":
            continue
        for needle in tpl["match"]:
            if needle in text:
                return key
    return None
