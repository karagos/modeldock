"""ModelDock server. Zero dependencies: macOS stock Python 3.9 stdlib only."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalog
import hf_api
import library
from downloader import DownloadManager
from store import Store

HOST, PORT = "127.0.0.1", 8420
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
MIME = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}

STORE = Store(os.path.join(ROOT, "data", "state.json"))
MGR = DownloadManager(STORE)


def mac_ram():
    try:
        return int(subprocess.run(["sysctl", "-n", "hw.memsize"],
                                  capture_output=True, text=True).stdout.strip())
    except (ValueError, OSError):
        return 0


RAM = mac_ram()


def effective_ram():
    """Manual override from Settings (for planning around a future Mac), else detected."""
    gb = STORE.data["settings"].get("ram_override_gb") or 0
    return int(gb) * 1024 ** 3 if gb else RAM


def dest():
    return STORE.data["settings"]["destination"]


def inside_models(path):
    d = dest()
    if not d:
        return False
    return os.path.realpath(path).startswith(
        os.path.realpath(os.path.join(d, "Models")) + os.sep)


def make_job_id():
    return "job-%d" % int(time.time() * 1000)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    # ---------- helpers ----------
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n).decode() or "{}")

    def _query(self):
        from urllib.parse import parse_qs, urlparse
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def _static(self, path):
        rel = path.lstrip("/") or "index.html"
        full = os.path.realpath(os.path.join(WEB, rel))
        if not full.startswith(os.path.realpath(WEB) + os.sep) or not os.path.isfile(full):
            self.send_error(404)
            return
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type",
                         MIME.get(os.path.splitext(full)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ---------- GET ----------
    def do_GET(self):
        route = self.path.split("?")[0]
        try:
            if route == "/api/ping":
                self._json({"ok": True})
            elif route == "/api/search":
                self._api_search()
            elif route == "/api/model":
                self._api_model()
            elif route == "/api/downloads":
                self._json({"jobs": MGR.status()})
            elif route == "/api/library":
                d = dest()
                out = library.scan(d)
                out["disk"] = library.disk_stats(d) if out["connected"] else {"free": 0, "total": 0}
                self._json(out)
            elif route == "/api/settings":
                self._json(STORE.data["settings"])
            elif route == "/api/system":
                d = dest()
                connected = bool(d) and os.path.isdir(d)
                self._json({"ram": effective_ram(), "ram_detected": RAM,
                            "ram_source": "manual" if STORE.data["settings"].get("ram_override_gb") else "auto",
                            "destination": d, "connected": connected,
                            "disk": library.disk_stats(d) if connected else {"free": 0, "total": 0}})
            else:
                self._static(route)
        except urllib.error.URLError as e:
            self._json({"error": "Hugging Face is unreachable — check your internet. (%s)"
                        % getattr(e, "reason", e)}, 502)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    # ---------- POST ----------
    def do_POST(self):
        route = self.path.split("?")[0]
        try:
            body = self._body()
            if route == "/api/download":
                self._api_download(body)
            elif route == "/api/downloads/action":
                self._api_action(body)
            elif route == "/api/settings":
                self._api_settings(body)
            elif route == "/api/pick-folder":
                self._api_pick_folder()
            elif route == "/api/library/delete":
                self._api_delete(body)
            elif route == "/api/reveal":
                self._api_reveal(body)
            else:
                self.send_error(404)
        except urllib.error.URLError as e:
            self._json({"error": "Hugging Face is unreachable — check your internet. (%s)"
                        % getattr(e, "reason", e)}, 502)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    # ---------- API implementations ----------
    def _api_search(self):
        q = self._query()
        types = [t for t in q.get("type", "gguf").split(",") if t] or ["gguf"]
        caps = [c for c in q.get("capability", "").split(",") if c]
        want_moe = "moe" in caps
        sort = q.get("sort", "downloads")
        want_bucket = q.get("size", "")
        # Size/MoE filtering happens after the fetch (HF has no param-count
        # filter), so pull a deeper page to avoid false "no results".
        limit = 100 if (want_bucket or want_moe) else 30
        text_caps = [c for c in caps if c in catalog.TEXT_CAPS and c != "moe"]
        image_pipes = [c for c in caps if c in ("image-gen", "video-gen")]
        image_extras = [c for c in caps if c in ("lora", "upscaler")]

        queries = []  # (type, capabilities-for-query)
        for t in types:
            if t in ("gguf", "mlx"):
                queries.append((t, text_caps))
            else:
                # One HF query per selected image pipeline (each can carry only one tag).
                for pipe in (image_pipes or [None]):
                    queries.append((t, ([pipe] if pipe else []) + image_extras))

        per_query = []
        for t, qcaps in queries:
            params = catalog.build_search_params(
                q=q.get("q", ""), mtype=t, company=q.get("company", ""),
                capabilities=qcaps, sort=sort, limit=limit)
            cards = []
            for m in hf_api.search_models(params):
                mid = m.get("id", "")
                p = catalog.parse_params(mid)
                bucket = catalog.size_bucket(p["total_b"]) if p else None
                if want_moe and not (p and p["moe"]):
                    continue
                if want_bucket and bucket != want_bucket:
                    continue
                cards.append({
                    "id": mid, "company": mid.split("/")[0], "mtype": t,
                    "downloads": m.get("downloads", 0), "likes": m.get("likes", 0),
                    "updated": m.get("lastModified", ""), "gated": bool(m.get("gated")),
                    "caps": sorted(catalog.detect_capabilities(mid, m.get("tags", []))),
                    "params": p, "bucket": bucket})
            per_query.append(cards)
        self._json({"results": catalog.merge_cards(per_query, sort)})

    def _api_model(self):
        q = self._query()
        mid, mtype = q["id"], q.get("type", "gguf")
        capability = q.get("capability", "")
        info = hf_api.model_info(mid)
        # Gated repos 401 on the tree endpoint — return the notice without touching it.
        tree = [] if info.get("gated") else hf_api.model_tree(mid)
        d = dest()
        free = library.disk_stats(d)["free"] if d and os.path.isdir(d) else 0
        variants = []
        if mtype == "gguf":
            ggufs = [f for f in tree if f["path"].lower().endswith(".gguf")]
            for g in catalog.group_gguf_files(ggufs):
                variants.append({"label": g["label"], "quant": g["quant"], "size": g["size"],
                                 "files": g["files"], "kind": "text"})
        elif mtype == "mlx":
            files = [f for f in tree
                     if not f["path"].startswith(".") and f["path"] != "README.md"]
            total = sum(f["size"] for f in files)
            variants.append({"label": "Full model (%s)" % (catalog.parse_quant(mid) or "MLX"),
                             "quant": catalog.parse_quant(mid), "size": total,
                             "files": files, "kind": "text"})
        else:  # image
            for f in tree:
                if f["path"].lower().endswith((".safetensors", ".sft")):
                    variants.append({"label": f["path"], "quant": None, "size": f["size"],
                                     "files": [f], "kind": "image",
                                     "subfolder": catalog.comfy_subfolder(
                                         capability, info.get("tags", []), f["path"])})
        for v in variants:
            v["fits"] = catalog.fits_badge(v["size"], effective_ram())
            # Same margin the enqueue check uses, so the button never lies.
            v["will_fit_disk"] = bool(free) and v["size"] * 1.05 + 500 * 1024 * 1024 < free
        card = info.get("cardData") or {}
        p = catalog.parse_params(mid)
        description = "" if info.get("gated") else catalog.readme_excerpt(hf_api.model_readme(mid))
        self._json({
            "id": mid, "company": mid.split("/")[0], "gated": bool(info.get("gated")),
            "description": description,
            "hf_url": "https://huggingface.co/" + mid,
            "downloads": info.get("downloads", 0), "likes": info.get("likes", 0),
            "updated": info.get("lastModified", ""), "license": card.get("license") or "—",
            "params": p,
            "moe_note": ("%.0fB total, %.0fB active — runs like a much smaller model"
                         % (p["total_b"], p["active_b"]))
                        if p and p["moe"] and p["active_b"] else None,
            "caps": sorted(catalog.detect_capabilities(mid, info.get("tags", []))),
            "variants": variants})

    def _api_download(self, body):
        d = dest()
        if not d or not os.path.isdir(d):
            self._json({"error": "No destination folder — choose one in Settings first."}, 400)
            return
        total = sum(f["size"] for f in body["files"])
        free = library.disk_stats(d)["free"]
        if total * 1.05 + 500 * 1024 * 1024 > free:
            self._json({"error": "Not enough free space on the destination "
                                 "(%.1f GB needed, %.1f GB free)."
                                 % (total / 1e9, free / 1e9)}, 400)
            return
        mid = body["model_id"]
        company, _, model = mid.partition("/")
        if body.get("mtype") == "image":
            sub = catalog.comfy_subfolder(body.get("capability", ""), [],
                                          body["files"][0]["path"])
            dest_dir = os.path.join(d, "Models", "comfyui", sub)
        else:
            dest_dir = os.path.join(d, "Models", catalog.sanitize_component(company),
                                    catalog.sanitize_component(model))
        job = {"id": make_job_id(), "model_id": mid,
               "label": "%s — %s" % (mid, body.get("variant_label", "")),
               "dest_dir": dest_dir, "state": "queued", "downloaded_bytes": 0, "error": "",
               "total_bytes": total,
               "files": [{"url": hf_api.file_url(mid, f["path"]),
                          "local_name": catalog.sanitize_component(os.path.basename(f["path"])),
                          "size": f["size"], "sha256": f.get("sha256")}
                         for f in body["files"]]}
        MGR.add_job(job)
        self._json({"ok": True, "id": job["id"]})

    def _api_action(self, body):
        action, jid = body.get("action"), body.get("id")
        if action == "pause":
            MGR.pause(jid)
        elif action == "resume":
            MGR.resume(jid)
        elif action == "cancel":
            MGR.cancel(jid)
        elif action == "clear_done":
            MGR.clear_done()
        self._json({"ok": True})

    def _api_settings(self, body):
        s = STORE.data["settings"]
        if "destination" in body:
            nd = body["destination"]
            if nd and not os.path.isdir(nd):
                self._json({"error": "That folder does not exist or the drive is not connected."}, 400)
                return
            s["destination"] = nd
            if nd:
                STORE.remember_destination(nd)
        for k in ("preferred_quant", "theme"):
            if k in body:
                s[k] = body[k]
        if "ram_override_gb" in body:
            try:
                s["ram_override_gb"] = max(0, int(body["ram_override_gb"]))
            except (TypeError, ValueError):
                pass
        STORE.save()
        self._json(s)

    def _api_pick_folder(self):
        script = 'POSIX path of (choose folder with prompt "Choose where ModelDock saves models")'
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if r.returncode != 0:
            self._json({"canceled": True})
            return
        path = r.stdout.strip().rstrip("/")
        self._json({"path": path})

    def _api_delete(self, body):
        path = body.get("path", "")
        if not inside_models(path) or not os.path.exists(path):
            self._json({"error": "Refusing: path is not inside the models folder."}, 400)
            return
        script = 'tell application "Finder" to delete POSIX file "%s"' % path.replace('"', '\\"')
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if r.returncode != 0:
            self._json({"error": "Could not move to Trash: %s" % r.stderr.strip()}, 500)
            return
        self._json({"ok": True})

    def _api_reveal(self, body):
        path = body.get("path", "")
        if not inside_models(path):
            self._json({"error": "Refusing: path is not inside the models folder."}, 400)
            return
        subprocess.run(["open", "-R", path])
        self._json({"ok": True})


def main():
    url = "http://%s:%s" % (HOST, PORT)
    want_browser = not os.environ.get("MODELDOCK_NO_BROWSER")
    probe = socket.socket()
    if probe.connect_ex((HOST, PORT)) == 0:  # already running
        probe.close()
        print("ModelDock is already running — opening browser.")
        if want_browser:
            subprocess.run(["open", url])
        return
    probe.close()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    if want_browser:
        threading.Timer(0.6, lambda: subprocess.run(["open", url])).start()
    print("ModelDock running at %s — close this window to stop." % url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
