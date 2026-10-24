"""Minimal ONVIF support, stdlib only.

Two jobs:
1. WS-Discovery — multicast SOAP Probe; cameras answer with their
   device-service URL and scopes (which often name the maker/model).
2. Stream lookup — GetCapabilities -> Media service -> GetProfiles ->
   GetStreamUri, with WS-UsernameToken digest auth when credentials
   are set. Returns an RTSP (host, port, path) the engine can open.

This is deliberately small: it covers the profile/stream surface the
ingest ladder needs and nothing more.
"""
import base64
import hashlib
import re
import socket
import uuid
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

DISCOVERY_ADDR = ("239.255.255.250", 3702)

_PROBE = """<?xml version="1.0" encoding="utf-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
 xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
<e:Header><w:MessageID>uuid:{mid}</w:MessageID>
<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header>
<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>
</e:Envelope>"""


def parse_probe_matches(xml_text):
    """Extract [{xaddr, scopes}] from a WS-Discovery response."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for match in root.iter():
        if not match.tag.endswith("ProbeMatch"):
            continue
        entry = {"xaddr": "", "scopes": ""}
        for child in match.iter():
            if child.tag.endswith("XAddrs") and child.text:
                entry["xaddr"] = child.text.strip().split()[0]
            elif child.tag.endswith("Scopes") and child.text:
                entry["scopes"] = child.text.strip()
        if entry["xaddr"]:
            out.append(entry)
    return out


def ws_discover(timeout=3.0):
    """Broadcast an ONVIF probe; return a list of match dicts."""
    results = []
    seen = set()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(timeout)
        sock.sendto(_PROBE.format(mid=uuid.uuid4()).encode("utf-8"), DISCOVERY_ADDR)
        while True:
            try:
                data, _addr = sock.recvfrom(65535)
            except socket.timeout:
                break
            for entry in parse_probe_matches(data.decode("utf-8", "replace")):
                if entry["xaddr"] not in seen:
                    seen.add(entry["xaddr"])
                    results.append(entry)
    except OSError:
        pass
    finally:
        sock.close()
    return results


# --- SOAP client ----------------------------------------------------------

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _find_text(root, name):
    for el in root.iter():
        if _local(el.tag) == name and el.text:
            return el.text.strip()
    return ""


def _username_token(username, password):
    if not username:
        return ""
    nonce = uuid.uuid4().bytes
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(
        hashlib.sha1(nonce + created.encode() + password.encode()).digest()
    ).decode()
    return (
        '<s:Header><Security s:mustUnderstand="1" '
        'xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
        '<UsernameToken><Username>%s</Username>'
        '<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">%s</Password>'
        '<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">%s</Nonce>'
        '<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">%s</Created>'
        '</UsernameToken></Security></s:Header>'
        % (username, digest, base64.b64encode(nonce).decode(), created))


def _soap(url, body_inner, username="", password="", timeout=4.0):
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" '
        'xmlns:trt="http://www.onvif.org/ver10/media/wsdl" '
        'xmlns:tt="http://www.onvif.org/ver10/schema">'
        + _username_token(username, password)
        + "<s:Body>" + body_inner + "</s:Body></s:Envelope>")
    req = urllib.request.Request(url, data=envelope.encode("utf-8"), method="POST")
    req.add_header("Content-Type",
                   "application/soap+xml; charset=utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return ET.fromstring(resp.read())


def get_stream_uri(device_xaddr, username="", password="", timeout=4.0):
    """Return an RTSP URL for the first profile, or None.

    The returned URL may carry credentials from the camera's own
    response — treat it as sensitive (never log it).
    """
    try:
        root = _soap(device_xaddr,
                     "<tds:GetCapabilities><tds:Category>Media</tds:Category>"
                     "</tds:GetCapabilities>", username, password, timeout)
        media_xaddr = ""
        for el in root.iter():
            if _local(el.tag) == "Media":
                media_xaddr = _find_text(el, "XAddr")
                break
        if not media_xaddr:
            return None
        root = _soap(media_xaddr, "<trt:GetProfiles/>",
                     username, password, timeout)
        token = ""
        for el in root.iter():
            if _local(el.tag) == "Profiles":
                token = el.get("token", "")
                break
        if not token:
            return None
        root = _soap(media_xaddr,
                     "<trt:GetStreamUri><tt:StreamSetup>"
                     "<tt:Stream>RTP-Unicast</tt:Stream>"
                     "<tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>"
                     "</tt:StreamSetup>"
                     "<trt:ProfileToken>%s</trt:ProfileToken>"
                     "</trt:GetStreamUri>" % token,
                     username, password, timeout)
        uri = _find_text(root, "Uri")
        return uri or None
    except Exception:
        return None


_RTSP_SPLIT = re.compile(r"(?i)^rtsp://([^/]+)(/.*)?$")


def split_rtsp_url(url):
    """'rtsp://[user:pass@]host[:port]/path' -> (host, port, path).
    Credentials in the URL are dropped on purpose: the app attaches
    its own credentials object when it connects."""
    if not url:
        return None
    m = _RTSP_SPLIT.match(url.strip())
    if not m:
        return None
    authority = m.group(1).rsplit("@", 1)[-1]
    path = m.group(2) or "/"
    if ":" in authority:
        host, port = authority.rsplit(":", 1)
        try:
            return host, int(port), path
        except ValueError:
            return authority, 554, path
    return authority, 554, path
