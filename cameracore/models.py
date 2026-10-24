"""Data model. Credentials live in their own object, separate from the
camera's stream description (2026-10-23 audit item 2): the config file
stores paths and templates; URLs are built in memory at connect time.
"""
from dataclasses import dataclass, field, asdict


@dataclass
class Credentials:
    username: str = ""
    password: str = ""

    def has_login(self):
        return bool(self.username)


@dataclass
class CameraSource:
    """The winning ingest result for a camera (what actually plays)."""
    kind: str = ""            # rtsp | mjpeg | snapshot
    path: str = ""            # stream/snapshot path (no credentials)
    port: int = 554
    scheme: str = "rtsp"
    via: str = ""             # which ladder layer won: onvif/template/generic/mjpeg/snapshot

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        if not d:
            return cls()
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


def apply_credentials(cameras, credentials):
    """Give every camera the same login (a fleet that shares one
    password is the common case; per-camera settings can still
    override any camera afterwards). Returns how many were set."""
    count = 0
    for cam in cameras:
        cam.credentials = Credentials(credentials.username, credentials.password)
        count += 1
    return count


@dataclass
class Camera:
    name: str = ""
    host: str = ""
    family: str = "generic"   # template key (cameracore.templates)
    enabled: bool = True
    credentials: Credentials = field(default_factory=Credentials)
    main: CameraSource = field(default_factory=CameraSource)
    sub: CameraSource = field(default_factory=CameraSource)
    notes: str = ""

    def to_dict(self, protect=None):
        """Serialize. ``protect`` (password -> protected string) is
        applied by the store so this module stays platform-free."""
        d = asdict(self)
        if protect is not None:
            d["credentials"]["password"] = protect(self.credentials.password)
        return d

    @classmethod
    def from_dict(cls, d, unprotect=None):
        cam = cls(
            name=d.get("name", ""),
            host=d.get("host", ""),
            family=d.get("family", "generic"),
            enabled=bool(d.get("enabled", True)),
            notes=d.get("notes", ""),
        )
        cred = d.get("credentials") or {}
        pw = cred.get("password", "")
        if unprotect is not None:
            pw = unprotect(pw)
        cam.credentials = Credentials(cred.get("username", ""), pw)
        cam.main = CameraSource.from_dict(d.get("main"))
        cam.sub = CameraSource.from_dict(d.get("sub"))
        return cam
