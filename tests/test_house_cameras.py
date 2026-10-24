import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cameracore import ingest, onvif, reports, store, updater  # noqa: E402
from cameracore.models import Camera, CameraSource, Credentials  # noqa: E402
from cameracore.selftest import run_self_test  # noqa: E402
from cameracore.templates import identify_family, template_for  # noqa: E402
from cameracore.util import build_url, redact  # noqa: E402


class TestUtil(unittest.TestCase):
    def test_redact(self):
        self.assertNotIn("secret", redact("rtsp://admin:secret@h/11"))
        self.assertIn("***@", redact("rtsp://admin:secret@h/11"))

    def test_build_url(self):
        self.assertEqual(build_url("rtsp", "h", 554, "11"), "rtsp://h:554/11")


class TestStore(unittest.TestCase):
    def test_round_trip_and_repair(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cameras.json")
            cam = Camera(name="a", host="127.0.0.1", family="hip2p")
            cam.credentials = Credentials("admin", "pw-123")
            store.save_cameras([cam], path=path)
            store.save_cameras([cam], path=path)  # second save leaves a .bak
            with open(path) as fh:
                self.assertNotIn("pw-123", fh.read())
            loaded, repaired = store.load_cameras(path=path)
            self.assertFalse(repaired)
            self.assertEqual(loaded[0].credentials.password, "pw-123")
            with open(path, "w") as fh:
                fh.write("broken")
            loaded, repaired = store.load_cameras(path=path)
            self.assertTrue(repaired)
            self.assertEqual([c.name for c in loaded], ["a"])  # restored from backup

    def test_defaults_empty_without_seed(self):
        # No owner's fleet ships in the repo: no seed file, no cameras.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(store.default_cameras(tmp), [])

    def test_seed_file_becomes_starting_list(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            seed = {"version": 1, "cameras": [
                {"name": "house-1", "host": "192.0.2.1", "family": "hip2p",
                 "enabled": True, "credentials": {"username": "", "password": ""},
                 "main": {}, "sub": {}, "notes": ""}]}
            with open(os.path.join(tmp, "fleet-seed.json"), "w") as fh:
                json.dump(seed, fh)
            cams = store.default_cameras(tmp)
            self.assertEqual([c.name for c in cams], ["house-1"])
            self.assertEqual(cams[0].credentials.password, "")


class TestTemplates(unittest.TestCase):
    def test_hip2p_paths(self):
        tpl = template_for("hip2p")
        self.assertEqual((tpl["main"].path, tpl["sub"].path), ("/11", "/12"))

    def test_identify(self):
        self.assertEqual(identify_family("reolink"), "reolink")
        self.assertIsNone(identify_family("some other server"))


class TestOnvif(unittest.TestCase):
    def test_split(self):
        self.assertEqual(onvif.split_rtsp_url("rtsp://u:p@h:8554/x"),
                         ("h", 8554, "/x"))
        self.assertIsNone(onvif.split_rtsp_url("http://h/x"))


class TestLadder(unittest.TestCase):
    def _cam(self):
        cam = Camera(name="t", host="10.0.0.9", family="hip2p")
        cam.credentials = Credentials("a", "b")
        return cam

    def test_template_wins(self):
        main, sub, _ = ingest.run_ladder(
            self._cam(), stream_probe=lambda u: u.endswith("/11") or u.endswith("/12"),
            snapshot_probe=lambda *a: False, onvif_lookup=lambda *a: None)
        self.assertEqual(main.path, "/11")
        self.assertEqual(sub.path, "/12")

    def test_onvif_first(self):
        main, _, note = ingest.run_ladder(
            self._cam(), onvif_xaddr="http://10.0.0.9/onvif/device_service",
            stream_probe=lambda u: True, snapshot_probe=lambda *a: False,
            onvif_lookup=lambda *a: "rtsp://u:p@10.0.0.9:554/onvif-stream")
        self.assertEqual(main.via, "onvif")

    def test_snapshot_last_resort(self):
        main, _, _ = ingest.run_ladder(
            self._cam(), stream_probe=lambda u: False,
            snapshot_probe=lambda *a: True, onvif_lookup=lambda *a: None)
        self.assertEqual(main.kind, "snapshot")

    def test_honest_failure(self):
        main, _, note = ingest.run_ladder(
            self._cam(), stream_probe=lambda u: False,
            snapshot_probe=lambda *a: False, onvif_lookup=lambda *a: None)
        self.assertEqual(main, CameraSource())
        self.assertIn("cloud", note)


class TestUpdater(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(updater.is_newer_version("1.1", "1.0.9"))
        self.assertFalse(updater.is_newer_version("1.0", "1.0"))
        self.assertIsNone(updater.parse_version("soon"))

    def test_notice_once(self):
        self.assertTrue(updater.update_notice_wanted({}, "2.0"))
        self.assertFalse(updater.update_notice_wanted({"dismissed": "2.0"}, "2.0"))

    def test_release_parse(self):
        rel = updater.parse_release({
            "tag_name": "v3.0", "html_url": "https://example.invalid/r",
            "assets": [{"name": updater.UPDATE_SETUP_NAME, "size": 5,
                        "browser_download_url": "https://example.invalid/s",
                        "digest": "sha256:" + "a" * 64}]})
        self.assertEqual(rel["version"], "3.0")
        self.assertEqual(rel["setup"]["sha256"], "a" * 64)


class TestReports(unittest.TestCase):
    def test_name(self):
        import time
        name = reports.crash_report_name(time.localtime(0))
        self.assertTrue(name.startswith("HouseCameras-crash-"))
        self.assertTrue(name.endswith(".txt"))

    def test_delete_guard(self):
        self.assertFalse(reports.delete_crash_report("/tmp/not-a-report.txt"))


class TestSelfTest(unittest.TestCase):
    def test_self_test_passes(self):
        ok, lines = run_self_test()
        self.assertTrue(ok, "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
