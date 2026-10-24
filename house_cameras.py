"""House Cameras — Windows viewer for the house Wi-Fi cameras.

Views as wide a range of Wi-Fi camera families as possible: discovery
runs ONVIF, the HiP2P-family VSCP search, Reolink identification and a
plain LAN sweep; each camera is connected through an ordered ladder
(ONVIF -> family template -> generic RTSP probing -> MJPEG/snapshot),
and the first layer that produces a verified picture is the one used.

Credentials are typed into this app on this machine only. They are
stored DPAPI-protected in the app's own settings folder, never logged,
never shown in a stream address.

Run `python house_cameras.py --self-test` for a headless check.
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cameracore import APP_NAME, APP_VERSION  # noqa: E402
from cameracore.util import LOG  # noqa: E402


def app_dir():
    """Folder for user data: next to the exe when frozen (PyInstaller
    unpacks __file__ into a temp dir that vanishes), else the
    platform app-data folder via cameracore.store."""
    from cameracore.store import data_dir
    return data_dir()


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

def launch_gui():
    import tkinter as tk
    from tkinter import messagebox, ttk

    import cv2
    import numpy as np
    from PIL import Image, ImageTk

    from cameracore import discovery, engine, ingest, reports, store, updater
    from cameracore.models import Camera, Credentials
    from cameracore.selftest import diagnostics_lines, run_self_test
    from cameracore.templates import TEMPLATES

    reports.install_excepthook()

    cameras, _repaired = store.load_cameras()
    workers = {}   # name -> CameraWorker (the source currently shown)
    worker_pref = {}  # name -> "sub"|"main" currently in use

    root = tk.Tk()
    root.title("%s — house cameras" % APP_NAME)
    root.geometry("1180x760")
    root.minsize(800, 520)

    def report_callback_exception(etype, evalue, etb):
        path = reports.write_crash_report(etype, evalue, etb)
        messagebox.showerror(
            APP_NAME,
            "Something went wrong in the window, but the app is still "
            "running.\n\nA crash report was saved%s.\nReports are never "
            "sent anywhere — they stay on this computer."
            % ((" to your Downloads folder:\n%s" % path) if path else ""))
    root.report_callback_exception = report_callback_exception

    # -- workers ------------------------------------------------------
    def want_source(cam, mode):
        if mode == "main":
            return cam.main if cam.main.kind else cam.sub
        return cam.sub if cam.sub.kind else cam.main

    def start_worker(cam, mode="sub"):
        src = want_source(cam, mode)
        if not src.kind:
            return
        key = cam.name
        old = workers.get(key)
        if old and worker_pref.get(key) == mode and old.source == src:
            return
        if old:
            old.stop()
        w = engine.CameraWorker(cam, src)
        workers[key] = w
        worker_pref[key] = mode
        w.start()

    resolving = set()

    def resolve_camera(cam):
        """Run the ingest ladder in the background; save what wins."""
        if cam.name in resolving:
            return
        resolving.add(cam.name)

        def job():
            try:
                _resolve_job(cam)
            finally:
                resolving.discard(cam.name)

        threading.Thread(target=job, daemon=True).start()

    def _resolve_job(cam):
        main, sub, note = ingest.run_ladder(cam)
        if main.kind:
            cam.main = main
            if sub.kind:
                cam.sub = sub
            store.save_cameras(cameras)
            root.after(0, lambda: start_worker(cam, view_mode["mode"]))
            root.after(0, lambda: status_var.set(
                "%s connected — %s" % (cam.name, note)))
        else:
            root.after(0, lambda: status_var.set("%s: %s" % (cam.name, note)))

    # -- layout ---------------------------------------------------------
    top = tk.Frame(root)
    top.pack(fill="x", padx=8, pady=6)
    tk.Label(top, text="House Cameras", font=("Segoe UI", 15, "bold")).pack(side="left")
    update_btn = tk.Button(top, text="", relief="flat", fg="#2050a0")
    view_mode = {"mode": "grid", "single": None}

    stage = tk.Frame(root, bg="#101010")
    stage.pack(fill="both", expand=True, padx=8)
    tiles = {}  # name -> (label_widget, caption_var)

    bottom = tk.Frame(root)
    bottom.pack(fill="x", padx=8, pady=6)
    status_var = tk.StringVar(value="Starting…")
    tk.Label(bottom, textvariable=status_var, anchor="w").pack(side="left", fill="x", expand=True)

    def clear_stage():
        for child in stage.winfo_children():
            child.destroy()
        tiles.clear()

    def build_stage():
        clear_stage()
        shown = [c for c in cameras if c.enabled] if view_mode["mode"] == "grid" \
            else [c for c in cameras if c.name == view_mode["single"]]
        shown = [c for c in shown if c is not None]
        if not shown:
            tk.Label(stage, text="No cameras yet — use “Find cameras” or “Add a camera”.",
                     fg="white", bg="#101010", font=("Segoe UI", 12)).pack(expand=True)
            return
        cols = 1 if len(shown) == 1 else (2 if len(shown) <= 4 else 3)
        rows = (len(shown) + cols - 1) // cols
        for r in range(rows):
            stage.rowconfigure(r, weight=1)
        for c in range(cols):
            stage.columnconfigure(c, weight=1)
        for i, cam in enumerate(shown):
            cell = tk.Frame(stage, bg="#101010")
            cell.grid(row=i // cols, column=i % cols, sticky="nsew", padx=3, pady=3)
            img = tk.Label(cell, bg="black", fg="white",
                           text="%s\nwaiting for picture…" % cam.name)
            img.pack(fill="both", expand=True)
            img.bind("<Double-Button-1>", lambda _e, n=cam.name: show_single(n))
            cap = tk.StringVar(value=cam.name)
            tk.Label(cell, textvariable=cap, fg="white", bg="#101010",
                     font=("Segoe UI", 10)).pack(fill="x")
            tiles[cam.name] = (img, cap)
            start_worker(cam, "main" if view_mode["mode"] == "single" else "sub")
            if not want_source(cam, "sub").kind and cam.host:
                resolve_camera(cam)

    def show_single(name):
        view_mode["mode"] = "single"
        view_mode["single"] = name
        build_stage()

    def show_grid():
        view_mode["mode"] = "grid"
        view_mode["single"] = None
        for cam in cameras:
            if cam.enabled and cam.name in workers:
                start_worker(cam, "sub")
        build_stage()

    # -- frame pump -----------------------------------------------------
    def letterbox(frame_bgr, box_w, box_h):
        h, w = frame_bgr.shape[:2]
        if w <= 0 or h <= 0 or box_w <= 0 or box_h <= 0:
            return None
        scale = min(box_w / w, box_h / h)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        resized = cv2.resize(frame_bgr, (nw, nh), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)

    def pump():
        for name, (label, cap) in list(tiles.items()):
            w = workers.get(name)
            cam = next((c for c in cameras if c.name == name), None)
            if w is None or cam is None:
                continue
            frame, is_jpeg, _at = w.latest()
            state, age = w.status()
            age_txt = "" if age is None else " · picture %ds old" % int(age)
            cap.set("%s — %s%s" % (name, state, age_txt))
            bw, bh = label.winfo_width(), label.winfo_height()
            if frame is None or bw < 40 or bh < 40:
                continue
            try:
                if is_jpeg:
                    import io
                    img = Image.open(io.BytesIO(frame)).convert("RGB")
                    iw, ih = img.size
                    scale = min(bw / iw, bh / ih)
                    img = img.resize((max(1, int(iw * scale)), max(1, int(ih * scale))))
                else:
                    img = letterbox(np.asarray(frame), bw, bh)
                if img is None:
                    continue
                photo = ImageTk.PhotoImage(img)
                label.configure(image=photo, text="")
                label.image = photo
            except Exception:
                pass
        root.after(120, pump)

    # -- dialogs ----------------------------------------------------------
    def open_diagnostics():
        win = tk.Toplevel(root)
        win.title("Diagnostics — House Cameras")
        win.geometry("720x520")
        text = tk.Text(win, font=("Consolas", 10), wrap="word")
        text.pack(fill="both", expand=True)

        def refresh(extra=()):
            text.delete("1.0", "end")
            lines = diagnostics_lines(cameras, workers) + [""] \
                + list(extra) + ["", "Recent activity:"] + LOG.tail(60)
            text.insert("1.0", "\n".join(lines))
        refresh()

        def self_test():
            def job():
                ok, lines = run_self_test()
                root.after(0, lambda: refresh(lines))
                root.after(0, lambda: status_var.set(
                    "Self-test %s" % ("passed" if ok else "found a problem — see Diagnostics")))
            threading.Thread(target=job, daemon=True).start()
        tk.Button(win, text="Run the self-test", command=self_test).pack(pady=6)

    def open_reports():
        win = tk.Toplevel(root)
        win.title("Crash & error reports")
        win.geometry("720x520")
        tk.Label(win, text="Reports stay on this computer. They are never sent anywhere.",
                 wraplength=680).pack(padx=10, pady=6, anchor="w")
        listing = tk.Listbox(win, font=("Consolas", 10))
        listing.pack(fill="both", expand=True, padx=10)
        items = {"rows": []}

        def refresh():
            listing.delete(0, "end")
            items["rows"] = reports.list_crash_reports()
            for r in items["rows"]:
                listing.insert("end", "%s   (%s)" % (
                    r["name"], time.strftime("%Y-%m-%d %H:%M", time.localtime(r["mtime"]))))
            if not items["rows"]:
                listing.insert("end", "No crash reports saved.")
        refresh()

        def selected():
            sel = listing.curselection()
            return items["rows"][sel[0]] if sel and items["rows"] else None

        def view():
            r = selected()
            if r:
                top2 = tk.Toplevel(win)
                top2.title(r["name"])
                t = tk.Text(top2, font=("Consolas", 10), wrap="word")
                t.pack(fill="both", expand=True)
                t.insert("1.0", reports.read_crash_report(r["path"]))

        btns = tk.Frame(win)
        btns.pack(pady=6)
        tk.Button(btns, text="Read", command=view).pack(side="left", padx=4)
        tk.Button(btns, text="Delete", command=lambda: (
            reports.delete_crash_report(selected()["path"]), refresh())
            if selected() else None).pack(side="left", padx=4)
        tk.Button(btns, text="Open Downloads folder",
                  command=lambda: os.startfile(reports.downloads_dir())
                  if hasattr(os, "startfile") else None).pack(side="left", padx=4)

    def open_help():
        win = tk.Toplevel(root)
        win.title("Help — House Cameras")
        win.geometry("640x460")
        t = tk.Text(win, font=("Segoe UI", 11), wrap="word")
        t.pack(fill="both", expand=True, padx=10, pady=10)
        t.insert("1.0",
                 "Watching a camera\n"
                 "• The grid shows all cameras. Double-click one to see it big; "
                 "“All cameras” brings the grid back.\n"
                 "• Each picture is shown as large as its box allows, in its true "
                 "shape — never stretched or cropped.\n\n"
                 "Adding a camera\n"
                 "• “Find cameras” searches the home network four ways (ONVIF, the "
                 "HiP2P family search, Reolink, and a plain sweep) and lists what "
                 "answers. Pick one and add it — the app then tries, in order: the "
                 "camera's ONVIF settings, its family recipe, a library of common "
                 "stream addresses, and finally still pictures — and keeps the "
                 "first that actually shows a picture.\n"
                 "• Type the camera's password here, on this computer. It is kept "
                 "protected in the app's own settings and never leaves this PC.\n\n"
                 "A camera that cannot be added\n"
                 "• Some cameras only work through their maker's cloud app "
                 "(Ring, Blink, Wyze on its original software, Nest). Those offer "
                 "nothing on the home network to view, so no app can show them "
                 "directly. If a camera offers RTSP, ONVIF or a local stream of "
                 "any kind, this app will find a way to show it.\n\n"
                 "Problems\n"
                 "• Diagnostics shows each camera's state and the age of its last "
                 "picture, and has a self-test that needs no cameras at all.\n"
                 "• If the app ever crashes, a plain-language report is saved in "
                 "your Downloads folder and listed under Reports. Reports are "
                 "never sent anywhere.\n\n"
                 "Updating\n"
                 "• The app checks for a new version about once a day and shows a "
                 "small note here. Nothing ever installs unless you tap Update.\n")
        t.configure(state="disabled")

    def edit_camera(cam=None):
        is_new = cam is None
        cam = cam or Camera(name="", host="", family="generic")
        win = tk.Toplevel(root)
        win.title("Add a camera" if is_new else "Camera settings")
        win.geometry("440x380")
        fields = {}

        def row(label, key, initial, show=None, widget="entry"):
            tk.Label(win, text=label).pack(anchor="w", padx=12, pady=(8, 0))
            if widget == "combo":
                var = tk.StringVar(value=initial)
                ttk.Combobox(win, textvariable=var, state="readonly",
                             values=sorted(TEMPLATES.keys())).pack(fill="x", padx=12)
                fields[key] = var
            else:
                var = tk.StringVar(value=initial)
                tk.Entry(win, textvariable=var, show=show or "").pack(fill="x", padx=12)
                fields[key] = var
        row("Name", "name", cam.name)
        row("Network address (e.g. 192.168.1.50)", "host", cam.host)
        row("Camera family", "family", cam.family, widget="combo")
        row("Camera user name", "username", cam.credentials.username)
        row("Camera password (kept only on this PC)", "password",
            cam.credentials.password, show="•")
        enabled = tk.BooleanVar(value=cam.enabled)
        tk.Checkbutton(win, text="Show this camera", variable=enabled).pack(
            anchor="w", padx=12, pady=8)

        def save():
            cam.name = fields["name"].get().strip() or cam.name or "camera"
            cam.host = fields["host"].get().strip()
            cam.family = fields["family"].get()
            cam.credentials = Credentials(fields["username"].get().strip(),
                                          fields["password"].get())
            cam.enabled = enabled.get()
            if is_new:
                cameras.append(cam)
            cam.main, cam.sub = cam.main.__class__(), cam.sub.__class__()
            store.save_cameras(cameras)
            win.destroy()
            build_stage()
            if cam.enabled and cam.host:
                resolve_camera(cam)
        tk.Button(win, text="Save", command=save).pack(pady=6)

    def find_cameras():
        win = tk.Toplevel(root)
        win.title("Find cameras")
        win.geometry("680x440")
        status = tk.StringVar(value="Searching the home network — this takes a few seconds…")
        tk.Label(win, textvariable=status, wraplength=640).pack(padx=10, pady=8, anchor="w")
        listing = tk.Listbox(win, font=("Consolas", 10))
        listing.pack(fill="both", expand=True, padx=10)
        found = {"rows": []}

        def job():
            rows = discovery.discover()
            found["rows"] = rows

            def fill():
                listing.delete(0, "end")
                known = {c.host for c in cameras}
                for r in rows:
                    tag = " (already added)" if r["host"] in known else ""
                    listing.insert("end", "%s  %s%s  %s" % (
                        r["host"], r.get("family") or "unknown family", tag,
                        (r.get("detail") or "")[:60]))
                status.set("Found %d device(s). Cameras that only work through a "
                           "maker's cloud app will not appear — they offer nothing "
                           "on the home network." % len(rows))
            root.after(0, fill)
        threading.Thread(target=job, daemon=True).start()

        def add_selected():
            sel = listing.curselection()
            if not sel:
                return
            r = found["rows"][sel[0]]
            cam = Camera(name="camera-%s" % r["host"].split(".")[-1],
                         host=r["host"], family=r.get("family") or "generic")
            win.destroy()
            cameras.append(cam)
            store.save_cameras(cameras)
            build_stage()
            resolve_camera(cam)
        tk.Button(win, text="Add the selected camera", command=add_selected).pack(pady=6)

    # -- updater ---------------------------------------------------------
    def check_updates(manual=False):
        def job():
            state = updater.load_state()
            if not manual and not updater.update_check_due(state):
                return
            try:
                release = updater.check_latest()
            except Exception:
                if manual:
                    root.after(0, lambda: status_var.set("Could not check for updates."))
                return
            updater.record_update_check(state)
            state = updater.load_state()
            if updater.update_notice_wanted(state, release["version"]):
                def offer():
                    update_btn.configure(
                        text="Version %s is available — tap to update" % release["version"],
                        command=lambda: apply_update(release))
                    update_btn.pack(side="right")
                root.after(0, offer)
            elif manual:
                root.after(0, lambda: status_var.set("You have the latest version."))
        threading.Thread(target=job, daemon=True).start()

    def apply_update(release):
        def job():
            import tempfile
            dest_dir = tempfile.mkdtemp(prefix="HouseCameras-update-")
            path, err = updater.download_update(release, dest_dir)
            if err:
                root.after(0, lambda: status_var.set("Update download failed: %s" % err))
                return
            ok, why = updater.verify_download(
                path, release["setup"]["size"], release["setup"]["sha256"])
            if not ok:
                root.after(0, lambda: status_var.set(
                    "Update was NOT installed — it failed its safety check (%s)." % why))
                return
            updater.dismiss_update_notice(updater.load_state(), release["version"])
            if hasattr(os, "startfile"):
                os.startfile(path)  # noqa: S606 — verified installer, user tapped
            root.after(0, lambda: status_var.set("Update downloaded — follow the installer."))
        threading.Thread(target=job, daemon=True).start()

    # -- buttons -----------------------------------------------------------
    buttons = tk.Frame(root)
    buttons.pack(fill="x", padx=8, pady=(0, 4))
    tk.Button(buttons, text="All cameras", command=show_grid).pack(side="left", padx=3)
    tk.Button(buttons, text="Find cameras", command=find_cameras).pack(side="left", padx=3)
    tk.Button(buttons, text="Add a camera", command=lambda: edit_camera()).pack(side="left", padx=3)
    tk.Button(buttons, text="Camera settings", command=lambda: (
        edit_camera(next((c for c in cameras if c.name == view_mode["single"]), cameras[0] if cameras else None))
        if cameras else None)).pack(side="left", padx=3)
    tk.Button(buttons, text="Diagnostics", command=open_diagnostics).pack(side="left", padx=3)
    tk.Button(buttons, text="Reports", command=open_reports).pack(side="left", padx=3)
    tk.Button(buttons, text="Check for updates",
              command=lambda: check_updates(manual=True)).pack(side="left", padx=3)
    tk.Button(buttons, text="Help", command=open_help).pack(side="left", padx=3)

    build_stage()
    pump()
    status_var.set("Ready — %d camera(s) configured." % len([c for c in cameras if c.enabled]))
    threading.Thread(target=lambda: check_updates(manual=False), daemon=True).start()
    root.mainloop()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--version" in argv:
        print("%s %s" % (APP_NAME, APP_VERSION))
        return 0
    if "--self-test" in argv:
        from cameracore.selftest import run_self_test
        ok, lines = run_self_test()
        for line in lines:
            print(line)
        return 0 if ok else 1
    launch_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
