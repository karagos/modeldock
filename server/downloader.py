"""Sequential download worker: .part files, HTTP Range resume, verify, atomic rename."""
import hashlib
import os
import threading
import time
import urllib.error
import urllib.request

CHUNK = 256 * 1024
SPACE_CHECK_EVERY = 200          # chunks (~50 MB)
MIN_FREE = 500 * 1024 * 1024     # pause when destination drops below this
SHA_VERIFY_MAX = 5 * 1024 ** 3   # read-back hash only for files <= 5 GiB
RETRIES = 5
HEADERS = {"User-Agent": "ModelDock/1.0 (local; CAIO)"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class DownloadManager:
    def __init__(self, store, opener=None):
        self.store = store
        self.opener = opener or urllib.request.urlopen
        self._lock = threading.RLock()
        self._worker = None
        self._signals = {}  # job_id -> "pause" | "cancel"
        for job in self.store.data["queue"]:      # recover after restart
            if job["state"] == "active":
                job["state"] = "paused"

    # ---- public API ----
    def add_job(self, job):
        with self._lock:
            self.store.data["queue"].append(job)
            self.store.save()
            self._ensure_worker()

    def pause(self, job_id):
        self._signal(job_id, "pause")

    def cancel(self, job_id):
        self._signal(job_id, "cancel")
        with self._lock:
            job = self._find(job_id)
            if job and job["state"] in ("queued", "paused", "error"):
                self._remove(job)

    def resume(self, job_id):
        with self._lock:
            job = self._find(job_id)
            if job and job["state"] in ("paused", "error"):
                job["state"] = "queued"
                job["error"] = ""
                self.store.save()
                self._ensure_worker()

    def status(self):
        with self._lock:
            return [dict(j) for j in self.store.data["queue"]]

    def clear_done(self):
        with self._lock:
            self.store.data["queue"] = [j for j in self.store.data["queue"]
                                        if j["state"] != "done"]
            self.store.save()

    # ---- internals ----
    def _find(self, job_id):
        return next((j for j in self.store.data["queue"] if j["id"] == job_id), None)

    def _remove(self, job):
        # Delete .part remnants AND files this job itself completed — a cancelled
        # multi-part job must never leave a truncated model that looks finished.
        # Files that pre-existed the job (not in "completed") are spared.
        completed = set(job.get("completed", []))
        for f in job["files"]:
            final = os.path.join(job["dest_dir"], f["local_name"])
            try:
                os.remove(final + ".part")
            except OSError:
                pass
            if f["local_name"] in completed:
                try:
                    os.remove(final)
                except OSError:
                    pass
        if job in self.store.data["queue"]:
            self.store.data["queue"].remove(job)
        self.store.save()

    def _signal(self, job_id, sig):
        with self._lock:
            self._signals[job_id] = sig

    def _ensure_worker(self):
        # Callers hold self._lock; _run clears _worker under the same lock.
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _run(self):
        try:
            while True:
                with self._lock:
                    job = next((j for j in self.store.data["queue"]
                                if j["state"] == "queued"), None)
                    if job is None:
                        # Atomic with the empty-queue observation: any add_job()
                        # after this sees _worker None and spawns a fresh thread.
                        self._worker = None
                        return
                    self._signals.pop(job["id"], None)
                    job["state"] = "active"
                self.store.save()
                try:
                    self._download_job(job)
                except _Interrupted as stop:
                    if stop.kind == "cancel":
                        with self._lock:
                            self._remove(job)
                    else:
                        job["state"] = "paused"
                        self.store.save()
                except Exception as e:  # network exhausted, disk gone, etc.
                    job["state"] = "error"
                    job["error"] = str(e)
                    self.store.save()
        finally:
            with self._lock:
                if self._worker is threading.current_thread():
                    self._worker = None

    def _download_job(self, job):
        os.makedirs(job["dest_dir"], exist_ok=True)
        done_bytes = 0
        for f in job["files"]:
            final = os.path.join(job["dest_dir"], f["local_name"])
            if os.path.exists(final):
                done_bytes += f["size"]
                job["downloaded_bytes"] = done_bytes
                continue
            self._download_file(job, f, final, done_bytes)
            self._verify(final + ".part", f)
            os.replace(final + ".part", final)
            job.setdefault("completed", []).append(f["local_name"])
            done_bytes += f["size"]
            job["downloaded_bytes"] = done_bytes
            self.store.save()
        job["state"] = "done"
        self.store.save()

    def _download_file(self, job, f, final, done_bytes):
        part = final + ".part"
        attempts = 0
        while True:
            pos = os.path.getsize(part) if os.path.exists(part) else 0
            if pos >= f["size"]:
                return
            try:
                req = urllib.request.Request(f["url"], headers=dict(HEADERS))
                if pos:
                    req.add_header("Range", "bytes=%d-" % pos)
                with self.opener(req, timeout=30) as resp, open(part, "ab") as out:
                    chunks = 0
                    while True:
                        self._check_signal(job)
                        block = resp.read(CHUNK)
                        if not block:
                            break
                        out.write(block)
                        pos += len(block)
                        job["downloaded_bytes"] = done_bytes + pos
                        chunks += 1
                        if chunks % SPACE_CHECK_EVERY == 0:
                            self._check_space(job)
                if pos >= f["size"]:
                    return
                attempts += 1  # server closed early — retry/resume
            except _Interrupted:
                raise
            except urllib.error.HTTPError as e:
                if 400 <= e.code < 500:
                    # Permanent: file removed, gated, bad range. Retrying is pointless.
                    raise RuntimeError(
                        "Download refused (HTTP %d). The file may have been removed "
                        "or requires a Hugging Face account." % e.code) from e
                attempts += 1
                if attempts > RETRIES:
                    raise RuntimeError("Network failed after %d retries: %s" % (RETRIES, e)) from e
                time.sleep(min(2 ** attempts, 30))
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
                if isinstance(e, OSError) and not os.path.isdir(job["dest_dir"]):
                    raise RuntimeError("Destination drive is not available") from e
                attempts += 1
                if attempts > RETRIES:
                    raise RuntimeError("Network failed after %d retries: %s" % (RETRIES, e)) from e
                time.sleep(min(2 ** attempts, 30))

    def _check_signal(self, job):
        sig = self._signals.get(job["id"])
        if sig:
            raise _Interrupted(sig)

    def _check_space(self, job):
        try:
            st = os.statvfs(job["dest_dir"])
            if st.f_bavail * st.f_frsize < MIN_FREE:
                job["error"] = "Destination drive is almost full. Download paused."
                raise _Interrupted("pause")
        except OSError:
            raise RuntimeError("Destination drive is not available")

    def _verify(self, part_path, f):
        actual = os.path.getsize(part_path)
        if actual != f["size"]:
            # Remove the bad .part or Resume would see pos >= size and loop forever.
            os.remove(part_path)
            raise RuntimeError("verification failed: size %d != expected %d "
                               "(bad download removed; Resume restarts this file)"
                               % (actual, f["size"]))
        if f.get("sha256") and f["size"] <= SHA_VERIFY_MAX:
            if sha256_file(part_path) != f["sha256"]:
                os.remove(part_path)
                raise RuntimeError("verification failed: checksum mismatch (corrupt download removed)")


class _Interrupted(Exception):
    def __init__(self, kind):
        self.kind = kind
