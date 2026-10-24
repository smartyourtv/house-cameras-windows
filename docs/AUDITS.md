# Audits — House Cameras (Windows)

## Change-impact audit (2026-10-24, before implementing)

1. **Blast radius** — Brand-new standalone app in a new repo
   (`smartyourtv/house-cameras-windows`). Touches no existing code,
   no ThinkPad files, no panel, no other app. The only shared inputs
   are read-only: requirements doc, dissection reports, census.
2. **Regression risk** — None to existing builds: no shared code is
   modified. The packaging template is *copied* from Windows Health
   & Repair, not edited in place.
3. **Cross-build effects** — None. Windows-only; the Android and
   laptop builds are untouched.
4. **Data & compatibility** — Creates one new local data location
   (`%LOCALAPPDATA%\HouseCameras`). No existing data is read or
   migrated. The seeded camera list carries addresses only — no
   credentials — and is stored as ordinary editable config.
5. **Permissions & security** — No admin needed (per-user install).
   Network: LAN discovery broadcasts + user-initiated RTSP/HTTP to
   cameras on the local subnet only. No cloud contact except the
   updater's GitHub release check (owner's standing updater rule).
   Credentials: DPAPI-protected at rest, never logged, never in argv,
   never in the repo. Discovery sweep reports unknown hosts without
   interrogating them (requirements §3).
6. **Behavior changes** — Nothing existing changes. On the Dell
   (later, coordinated) the app sits beside the vendor HiP2P client;
   it does not uninstall or reconfigure it.
7. **Performance** — Sub-streams in grid view keep decode load low;
   one thread per camera with backoff; snapshot-polling fallback is
   rate-limited. No work on battery/thermal budgets (mains desktop
   class target), but the engine idles cleanly when hidden.
8. **Rollback** — Uninstall via Settings → Apps removes the program;
   the config folder remains for a reinstall and can be deleted by
   hand. Nothing else on the machine is changed, so rollback is
   total.
9. **Test plan** — Unit tests for the ladder, templates, store
   repair, updater, reports; self-test on synthetic media (no live
   cameras); CI smoke test of the built exe on windows-latest.
   Live-camera acceptance is a separate, coordinated step AFTER the
   sibling relay's verification (owner's sequencing rule).

## Pre-build audit (2026-10-24, before the CI build)

1. **Permissions** — No admin, no special permissions: per-user
   install, LAN sockets + GitHub HTTPS (updater) only. Every network
   call is user-initiated (Find cameras, ladder on add/start) except
   the throttled (24 h) update check from the standing updater rule.
2. **Null-safety / error handling** — Ladder probes, discovery and
   engine loops all fail closed per camera; a dead camera never
   blocks others; GUI callback exceptions route to crash reports.
   Unit tests cover the failure paths (honest-failure ladder test).
3. **API misuse** — Tkinter touched only on the UI thread (worker
   results marshal via `root.after`); OpenCV captures are created and
   released on their own worker threads; no shell, no subprocess —
   credentials can never appear in a child-process command line.
4. **Protocol contracts** — ONVIF SOAP shapes tested against a
   recorded ProbeMatch; RTSP URL split drops embedded credentials;
   config schema versioned (`"version": 1`) with a tolerant reader
   (unknown fields ignored, missing fields defaulted).
5. **Security** — Grep-verified: no credential value is logged
   (`redact()` on every log line; engine/ingest log host+path only);
   passwords DPAPI-protected at rest and absent from the repo (the
   shipped app starts with an empty list — the owner's fleet rides a
   machine-local seed file placed at install, credentials entered
   on the machine); updater downloads verified by size + SHA-256
   before launch; crash reports pass through redaction.
6. **Dependency/version check** — Python 3.12 (CI), OpenCV headless
   (FFmpeg backend: H.264/HEVC/MJPEG), NumPy, Pillow pinned by floor
   versions in requirements.txt; PyInstaller 6.x per template.
   `python packaging/validate_packaging.py`: **42 passed, 0 failed**
   (config/GUID/naming/version agreement, per-user Inno contract,
   workflow shape). Unit tests: **18 passed**. Self-test: **19/19
   checks PASS**, including a synthetic-media decode through the
   real engine path.
