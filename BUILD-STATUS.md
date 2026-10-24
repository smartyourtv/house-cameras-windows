# Build status — House Cameras v1.0.0 (2026-10-24)

**BUILT + VERIFIED on a real Windows runner.** GitHub Actions run
40143793241 (`windows-latest`), all steps green:

- Test gate: 18 unit tests + 19 self-test checks passed on Windows —
  including the real DPAPI password round-trip. (The first run,
  40143661605, FAILED here on a genuine DPAPI bytes bug; fixed in
  commit e9c0b9c and re-tagged before anything shipped.)
- PyInstaller single-file exe built; exe smoke test passed
  (`--version` and `--self-test` exit 0).
- Inno Setup compiled the per-user installer.

**Release:** v1.0.0 —
https://github.com/smartyourtv/house-cameras-windows/releases/tag/v1.0.0

| Asset | Size | SHA-256 |
|---|---|---|
| HouseCameras-Setup.exe | 75,301,306 | `0e4e98c12df01af25e4c357490bd403f6b1181b941059a2cc00ea87bb4759087` |
| HouseCameras.exe | 73,881,371 | `351291c851e1bf263eeba868e59d80a57357b10cf58e7c31648c0f2f9d46e5e0` |

The Setup.exe was also downloaded and hash-verified locally — the
checksum matches both GitHub's reported digest and the release's
`.sha256` file. A copy sits in `~/workspace/dist/HouseCameras-Setup.exe`.

**Not yet done (by the owner's sequencing, not by omission):**
- Install on the Dell (192.168.40.100) + on-camera acceptance against
  house-1…6 wait for the remote-viewing relay's live-camera
  verification and coordination through the main chat.
- At install: place `fleet-seed.json` in `%LOCALAPPDATA%\HouseCameras`
  before first launch (prepared, kept with the project files — not in
  this repo), then Shawn enters the camera password in the app, on
  that machine.
- The Reolink front door (house-7) joins when the unit is identified;
  its template ships in v1.0.0.
