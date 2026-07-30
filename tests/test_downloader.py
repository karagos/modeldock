import io
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
from downloader import DownloadManager, sha256_file
from store import Store

PAYLOAD = bytes(range(256)) * 40  # 10240 bytes


class RangeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def range_opener(req, timeout=0):
    start = 0
    rng = req.headers.get("Range")
    if rng:
        start = int(rng.split("=")[1].rstrip("-"))
    return RangeResponse(PAYLOAD[start:])


def make_job(dest, name="file.bin"):
    return {"id": "j1", "model_id": "org/repo", "label": name, "dest_dir": dest,
            "files": [{"url": "http://x/file.bin", "local_name": name,
                       "size": len(PAYLOAD), "sha256": None}],
            "state": "queued", "downloaded_bytes": 0, "error": "",
            "total_bytes": len(PAYLOAD)}


class TestDownloader(unittest.TestCase):
    def _run(self, mgr):
        deadline = time.time() + 10
        while time.time() < deadline:
            st = mgr.status()
            if st and st[0]["state"] in ("done", "error"):
                return st[0]
            time.sleep(0.05)
        self.fail("timeout")

    def test_full_download_and_rename(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "s.json"))
            mgr = DownloadManager(store, opener=range_opener)
            mgr.add_job(make_job(d))
            job = self._run(mgr)
            self.assertEqual(job["state"], "done")
            final = os.path.join(d, "file.bin")
            self.assertTrue(os.path.exists(final))
            self.assertFalse(os.path.exists(final + ".part"))
            self.assertEqual(open(final, "rb").read(), PAYLOAD)

    def test_resume_from_partial(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "file.bin.part"), "wb") as f:
                f.write(PAYLOAD[:4000])
            seen = {}

            def spy(req, timeout=0):
                seen["range"] = req.headers.get("Range")
                return range_opener(req, timeout)
            store = Store(os.path.join(d, "s.json"))
            mgr = DownloadManager(store, opener=spy)
            mgr.add_job(make_job(d))
            job = self._run(mgr)
            self.assertEqual(job["state"], "done")
            self.assertEqual(seen["range"], "bytes=4000-")
            self.assertEqual(open(os.path.join(d, "file.bin"), "rb").read(), PAYLOAD)

    def test_cancel_removes_part(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "s.json"))
            mgr = DownloadManager(store, opener=range_opener)
            j = make_job(d)
            mgr.add_job(j)
            mgr.cancel("j1")
            time.sleep(0.3)
            self.assertFalse(os.path.exists(os.path.join(d, "file.bin.part")))
            self.assertEqual(mgr.status(), [])

    def test_sha_mismatch_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "s.json"))
            mgr = DownloadManager(store, opener=range_opener)
            j = make_job(d)
            j["files"][0]["sha256"] = "0" * 64
            mgr.add_job(j)
            job = self._run(mgr)
            self.assertEqual(job["state"], "error")
            self.assertIn("verification", job["error"])


class TestAuditFixes(unittest.TestCase):
    def test_cancel_removes_files_this_job_completed_but_spares_preexisting(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "s.json"))
            mgr = DownloadManager(store, opener=range_opener)
            job = make_job(d)
            job["files"] = [
                {"url": "http://x/a.bin", "local_name": "a.bin", "size": 10, "sha256": None},
                {"url": "http://x/b.bin", "local_name": "b.bin", "size": 10, "sha256": None},
                {"url": "http://x/c.bin", "local_name": "c.bin", "size": 10, "sha256": None},
            ]
            job["state"] = "paused"
            job["completed"] = ["a.bin"]          # downloaded by THIS job
            for name in ("a.bin", "c.bin"):       # c.bin pre-existed (not in completed)
                with open(os.path.join(d, name), "wb") as f:
                    f.write(b"x" * 10)
            with open(os.path.join(d, "b.bin.part"), "wb") as f:
                f.write(b"x" * 5)
            store.data["queue"].append(job)
            mgr.cancel("j1")
            self.assertFalse(os.path.exists(os.path.join(d, "a.bin")))       # cleaned
            self.assertFalse(os.path.exists(os.path.join(d, "b.bin.part")))  # cleaned
            self.assertTrue(os.path.exists(os.path.join(d, "c.bin")))        # spared

    def test_http_4xx_fails_immediately_with_clear_message(self):
        import urllib.error

        def opener_404(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "s.json"))
            mgr = DownloadManager(store, opener=opener_404)
            t0 = time.time()
            mgr.add_job(make_job(d))
            deadline = time.time() + 5
            while time.time() < deadline:
                st = mgr.status()
                if st and st[0]["state"] == "error":
                    break
                time.sleep(0.05)
            self.assertEqual(mgr.status()[0]["state"], "error")
            self.assertIn("404", mgr.status()[0]["error"])
            self.assertLess(time.time() - t0, 3, "4xx must not be retried with backoff")

    def test_size_mismatch_removes_part_so_resume_can_restart(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "s.json"))
            mgr = DownloadManager(store, opener=range_opener)
            j = make_job(d)
            j["files"][0]["size"] = 5000   # server will deliver 10240 bytes
            j["total_bytes"] = 5000
            mgr.add_job(j)
            deadline = time.time() + 5
            while time.time() < deadline:
                st = mgr.status()
                if st and st[0]["state"] == "error":
                    break
                time.sleep(0.05)
            self.assertEqual(mgr.status()[0]["state"], "error")
            self.assertFalse(os.path.exists(os.path.join(d, "file.bin.part")),
                             "oversized .part must be removed or Resume loops forever")


if __name__ == "__main__":
    unittest.main()
