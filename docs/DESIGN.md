# House Cameras (Windows) — Design

Owner order: Sat 2026-10-24 16:30 PDT via main chat ("Make it so").
Spec source: `goals/kitt-van-voice-ai-build/hidden_files/house-camera-rewrite-requirements.md`
(§1 maximum diversity is the governing requirement), plus the HiP2P /
CamHi / Reolink dissections and the 2026-10-23 camera-stack audit.

## What it is

A Windows desktop app that views the house Wi-Fi cameras on the local
network — built to accept as wide a range of camera families as
possible, not fitted to today's fleet. First install target (later,
coordinated): the Dell laptop 192.168.40.100, replacing the vendor
HiP2P Client as the viewing seat. Windows-only; nothing lands on the
ThinkPad.

- Display name: **House Cameras** · exe `HouseCameras.exe` ·
  installer `HouseCameras-Setup.exe` · v1.0.0
- Repo: `smartyourtv/house-cameras-windows` (no credentials, no
  private data in the repo — cameras are configured on the machine)

## Architecture — one core, swappable family templates

Pattern borrowed from the approved DVR-hub design: a stable core, and
each camera family is a *template* behind it. Adding a family = adding
a template file entry, never a rewrite (spec §1.4).

```
house_cameras.py        Tkinter GUI: grid views, single view, add/edit
                        camera, diagnostics view, crash-report view
cameracore/
  models.py             Camera + Credentials (kept as separate objects,
                        per audit item 2: URLs are built, never stored)
  store.py              Config load/save in %LOCALAPPDATA%\HouseCameras,
                        self-repair (corrupt file -> .bad backup + safe
                        defaults, verified by re-read, logged)
  discovery.py          ONVIF WS-Discovery · HiP2P VSCP broadcast ·
                        Reolink identification · plain LAN sweep
  onvif.py              Minimal ONVIF client (SOAP + WS-UsernameToken)
  templates.py          Per-family stream/snapshot path templates:
                        hip2p, reolink, dahua, hikvision, foscam,
                        xmeye, tapo, generic
  paths.py              Generic RTSP known-path library for probing
  ingest.py             The ordered ladder (below); first verified
                        picture wins and is remembered per camera
  engine.py             Frame engine: one thread per camera, latest
                        frame buffer, reconnect with backoff, status
  reports.py            Crash/error reports (in-app + Downloads file)
  updater.py            GitHub release check, one notice per version,
                        hash-verified download, install only on tap
  selftest.py           Diagnostics data + one-tap self-test
```

### Discovery (§1.1) — all methods run, results merged
1. **ONVIF WS-Discovery** — SOAP Probe to 239.255.255.250:3702,
   parses ProbeMatches (device service URL + scopes).
2. **HiP2P-family VSCP LAN search** — UDP broadcast of the exact probe
   string recovered from the vendor SearchLib.dll (`SEARCH * HDS/1.0`);
   any reply is recorded as a HiP2P-family candidate. (Best-effort:
   the vendor binary's port set is not documented; replies are also
   caught opportunistically during the sweep. The fleet's reliable
   path is the sweep + RTSP template — see below.)
3. **Reolink identification** — hosts answering on TCP 9000 or the
   Reolink HTTP API (`/cgi-bin/api.cgi?cmd=GetDevInfo`) are tagged
   Reolink candidates.
4. **LAN sweep** — threaded connect scan of the local subnet on
   554/80/8000/8899/9000, RTSP `OPTIONS` + HTTP banner fingerprinting.
   Unknown hosts are *reported*, never interrogated beyond banners
   (spec §3, the .108 rule).

### Ingest ladder (§1.2) — in order, first verified picture wins
(a) **ONVIF** profiles → stream URI (main + sub).
(b) **Vendor template** for the identified family.
(c) **Generic RTSP** — known-path library probed automatically.
(d) **MJPEG stream**, else **HTTP JPEG snapshot polling** (last resort).
"Verified" means a frame actually decoded (or a JPEG actually
fetched and parsed) — never a port merely being open.

### Codecs (§1.3)
Decode via OpenCV's FFmpeg backend: **H.264, H.265/HEVC, MJPEG**.
(house-4's main stream is HEVC 2304×1296 — covered.)

### Honest limit (§1.5) — stated in the app, not papered over
Closed cloud-only cameras (Ring, Blink, stock Wyze, Nest) expose no
local stream and cannot be added. If discovery/ingest fails for a
device, the app says plainly that it offers no local stream we can
use, instead of promising a path that doesn't exist.

## Viewing
- Grids: All cameras, 4-up, single view. Each picture is drawn **as
  large as its box allows with its true shape kept — no stretch, no
  crop** (owner's standing camera rule; letterboxing accepted).
- Grid shows the sub-stream (lighter); single view uses the main
  stream. Per-camera status line: Live / Connecting / No signal,
  with the age of the last good frame (freshness, not process state).
- The shipped app starts with an **empty** camera list: no owner's
  addresses or house layout ever live in the repo. At install time a
  `fleet-seed.json` (same schema as the config, addresses + names
  only, still no credentials) is placed in the app's data folder on
  the target machine and adopted on first run — the acceptance fleet
  from the 2026-10-24 census (house-1…6 HiP2P + disabled house-7
  Reolink placeholder) is prepared that way, kept with the project
  files, never committed. Discovery is the normal path for everyone
  else.

## Credentials & security (from the 2026-10-23 audit)
- Entered **on the machine, in the app** — never in chat, never in
  the repo, never in this design.
- Stored as a separate credentials object, protected with Windows
  DPAPI (`CryptProtectData`, current-user scope) inside the local
  config file. Stream URLs are built in memory at connect time.
- **Never logged**: log lines and crash reports carry host + path
  only; URLs are redacted before any string reaches disk.
- Credentials are never put in a child-process command line (the
  engine is in-process OpenCV; there is no ffmpeg argv).

## Standing build laws — how each is met
- **One per-user `HouseCameras-Setup.exe`**: PyInstaller single-file +
  Inno Setup template (same proven packaging as Windows Health &
  Repair), built on GitHub Actions `windows-latest` — never faked
  from Linux. Start Menu + Desktop shortcut, uninstaller, no Python
  prerequisite. README documents SmartScreen "More info → Run anyway".
- **Diagnostics/status view + one-tap self-test**: engine versions,
  per-camera state, last-frame ages, config health, log tail; the
  self-test exercises config repair, discovery sockets, and the decode
  engine against a synthetic stream — no live camera needed.
- **Crash/error reports**: in-app viewer (list/read/share/delete) AND
  `HouseCameras-crash-<YYYYMMDD-HHMMSS>.txt` in Downloads, written
  synchronously at crash time. Never auto-uploaded.
- **Self-repair**: corrupt config → backup + defaults (verified);
  stale per-camera state → re-run the ingest ladder; dead engine
  thread → restart with backoff. Conservative, verified, logged.
- **Updater**: checks GitHub releases (24 h throttle), ONE subtle
  notice per version, user taps to apply; download verified by size +
  SHA-256 before launch. Never forced, never silent.
- **No on-screen keyboard** (there is none). Plain-language UI.

## Coordination & sequencing
- A sibling remote-viewing relay (Enterprise Security lane) verifies
  against the live cameras FIRST today. This app's on-camera
  acceptance runs AFTER that, coordinated through main — no live
  camera load from this lane until main clears it.
- The cameras' internet block flips only in the post-stack camera
  pass; this app being verified is one of its gates. The app itself
  is LAN-only by design, so the block does not affect it.
- v1 acceptance without live cameras: unit tests, self-test,
  synthetic-stream decode test, installer built on a real Windows
  runner and smoke-tested there (`--version`, `--self-test`).

## Out of scope for v1
Recording/DVR, PTZ controls (templates reserve the fields), two-way
talk, remote (off-LAN) viewing — the relay lane owns remote viewing.
PPPP/PPCS LAN-direct leg: only if the queued ThinkPad-side test ever
proves the house cameras speak it (spec §3).
