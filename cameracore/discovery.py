"""Discovery — spec §1.1: every method runs, results merge.

Methods: ONVIF WS-Discovery, HiP2P-family VSCP broadcast, Reolink
identification, plain LAN sweep with banner fingerprinting.
Unknown hosts are reported, never interrogated beyond banners.
"""
import concurrent.futures
import http.client
import ipaddress
import socket
import urllib.request

from . import onvif
from .templates import identify_family
from .util import LOG

SCAN_PORTS = [554, 80, 8000, 8899, 9000]
# VSCP search string recovered from the vendor SearchLib.dll
# (hip2p-analysis/DISSECTION.md). The DLL's port set is undocumented;
# these are the candidate ports the family's tools are known to use.
VSCP_PROBE = b"SEARCH * HDS/1.0\r\n\r\n"
VSCP_PORTS = [8000, 8899, 34567]


def local_subnet():
    """The /24 this machine sits on, as a list of host strings."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        net = ipaddress.ip_network(ip + "/24", strict=False)
        return [str(h) for h in net.hosts()]
    except OSError:
        return []


def _tcp_open(host, port, timeout=0.45):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def rtsp_options(host, port=554, timeout=2.0):
    """One RTSP OPTIONS request; returns the response text or ''.
    No credentials are sent — this only reads the banner."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(b"OPTIONS rtsp://%s:%d/ RTSP/1.0\r\nCSeq: 1\r\n\r\n"
                      % (host.encode(), port))
            data = s.recv(2048)
            return data.decode("utf-8", "replace")
    except OSError:
        return ""


def http_banner(host, port=80, timeout=2.0):
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("HEAD", "/")
        resp = conn.getresponse()
        parts = ["%s %s" % (resp.status, resp.reason or "")]
        for k, v in resp.getheaders():
            parts.append("%s: %s" % (k, v))
        conn.close()
        return "\n".join(parts)
    except OSError:
        return ""


def reolink_probe(host, timeout=2.0):
    """True when the host answers like a Reolink (HTTP API shape)."""
    for path in ("/cgi-bin/api.cgi?cmd=GetDevInfo", "/api.cgi?cmd=GetDevInfo"):
        try:
            req = urllib.request.Request("http://%s%s" % (host, path))
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(2048).decode("utf-8", "replace")
                if "GetDevInfo" in body or '"cmd"' in body:
                    return True
        except Exception:
            continue
    return False


def vscp_search(timeout=2.0, log=LOG):
    """HiP2P-family VSCP LAN search: broadcast the vendor probe and
    collect anything that answers. Best-effort by design (see
    DESIGN.md) — replies become HiP2P-family candidates."""
    found = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        for port in VSCP_PORTS:
            try:
                sock.sendto(VSCP_PROBE, ("255.255.255.255", port))
            except OSError:
                pass
        while True:
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                break
            found.append({"host": addr[0], "via": "vscp",
                          "family": "hip2p",
                          "detail": data[:120].decode("utf-8", "replace")})
    except OSError as exc:
        log("VSCP search could not run (%s)." % exc)
    finally:
        sock.close()
    return found


def sweep(hosts=None, log=LOG, max_workers=48):
    """TCP sweep + banner fingerprinting. Returns candidate dicts:
    {host, open_ports, family (or None), via, detail}."""
    hosts = hosts if hosts is not None else local_subnet()
    live = []

    def check(host):
        open_ports = [p for p in SCAN_PORTS if _tcp_open(host, p)]
        if not open_ports:
            return None
        detail = ""
        family = None
        if 554 in open_ports:
            banner = rtsp_options(host)
            detail += banner.split("\r\n")[0] if banner else ""
            family = identify_family(banner)
        if 80 in open_ports:
            banner = http_banner(host)
            if not family:
                family = identify_family(banner)
            detail += (" " + banner.split("\n")[0]) if banner else ""
        if not family and (9000 in open_ports or 80 in open_ports):
            if reolink_probe(host):
                family = "reolink"
                detail += " Reolink API answered"
        return {"host": host, "open_ports": open_ports, "family": family,
                "via": "sweep", "detail": detail.strip()[:200]}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for result in pool.map(check, hosts):
            if result:
                live.append(result)
    live.sort(key=lambda r: r["host"])
    return live


def discover(log=LOG):
    """Run every discovery method and merge by host."""
    merged = {}

    def add(entry):
        key = entry["host"]
        if key in merged:
            cur = merged[key]
            cur.setdefault("via_all", [cur.get("via", "")]).append(entry.get("via", ""))
            if not cur.get("family") and entry.get("family"):
                cur["family"] = entry["family"]
            if entry.get("open_ports"):
                cur["open_ports"] = sorted(set(cur.get("open_ports", []))
                                           | set(entry["open_ports"]))
        else:
            merged[key] = dict(entry)

    for entry in onvif.ws_discover():
        host = entry["xaddr"].split("://", 1)[-1].split(":")[0].split("/")[0]
        add({"host": host, "via": "onvif", "family": identify_family(entry["scopes"]),
             "detail": entry["scopes"][:200], "onvif_xaddr": entry["xaddr"]})
    for entry in vscp_search(log=log):
        add(entry)
    for entry in sweep(log=log):
        add(entry)
    results = sorted(merged.values(), key=lambda r: r["host"])
    log("Discovery finished: %d device(s) answered." % len(results))
    return results
