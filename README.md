# House Cameras (Windows)

A Windows app for viewing the house Wi-Fi cameras on the home
network — built to accept as wide a range of camera families as
possible, not just today's fleet.

## Install

1. Download **HouseCameras-Setup.exe** from the
   [latest release](https://github.com/smartyourtv/house-cameras-windows/releases/latest).
2. Double-click it. No administrator rights and no Python are needed;
   it installs for your user account only, with a Start Menu and
   Desktop shortcut, and uninstalls from Settings → Apps.
3. **SmartScreen note:** the installer is unsigned, so Windows may
   show "Windows protected your PC" the first time. Click
   **More info → Run anyway**. That step is expected until a code
   signing certificate exists.

## Using it

- The grid shows every camera, each picture as large as its box
  allows in its true shape (never stretched or cropped).
  Double-click a camera to see it full-window.
- **Find cameras** searches the home network four ways — ONVIF
  WS-Discovery, the HiP2P-family VSCP search, Reolink identification,
  and a plain LAN sweep — and lists what answers.
- **Add a camera** (or pick one from Find cameras): the app tries, in
  order, the camera's ONVIF settings, its family recipe (HiP2P,
  Reolink, Dahua/Amcrest, Hikvision, Foscam, XMEye, Tapo), a library
  of common stream addresses, and finally still pictures — and keeps
  the first that actually shows a picture. H.264, H.265/HEVC and
  MJPEG all play.
- Camera passwords are typed into the app on this PC. They are kept
  protected (Windows DPAPI) in the app's own settings folder, are
  never logged, and never leave this computer.
- New camera families are added as a small template in the code —
  the app itself never needs a rewrite for a new family.

**An honest limit:** cameras that only work through their maker's
cloud app (Ring, Blink, Wyze on its original software, Nest) offer
nothing on the home network to view, so they cannot be added. If a
camera offers RTSP, ONVIF, or any local stream, this app will find
a way to show it.

## Diagnostics, reports, updates

- **Diagnostics** shows each camera's state and the age of its last
  picture, plus a one-tap self-test that needs no cameras.
- If the app crashes, a plain-language report is written to your
  Downloads folder (`HouseCameras-crash-<date>-<time>.txt`) and
  listed under **Reports** in the app. Reports are never sent
  anywhere.
- The app checks GitHub for a new version about once a day and shows
  a small note when one exists. Nothing installs unless you tap
  Update, and the download is verified (size + SHA-256) before it
  runs.

## For developers

- Design: `docs/DESIGN.md` · Audits: `docs/AUDITS.md`
- Run from source: `pip install -r requirements.txt`, then
  `python house_cameras.py` (headless check: `--self-test`).
- Tests: `python -m unittest discover -s tests`
- Build the installer: `packaging/build-installer.ps1` on Windows,
  or push a `v*` tag / run the *Build Windows installer* workflow —
  CI builds on a real Windows runner (`windows-latest`).
- Packaging validation without Windows:
  `python packaging/validate_packaging.py`
