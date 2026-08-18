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
hf_api.set_token(STORE.data["settings"].get("hf_token", ""))

_DISCOVER_CACHE = {"ts": 0, "data": None}
DISCOVER_TTL = 900
LAB_AUTHORS = ("Qwen", "meta-llama", "google", "mistralai", "deepseek-ai", "unsloth")
EXPAND_FIELDS = ["downloads", "downloadsAllTime", "createdAt", "lastModified",
                 "likes", "tags", "gated"]
PERIOD_DAYS = {"6m": 183, "1y": 365}


def make_card(m, mtype):
    mid = m.get("id", "")
    p = catalog.parse_params(mid)
    return {"id": mid, "company": mid.split("/")[0], "mtype": mtype,
            "downloads": m.get("downloads", 0), "likes": m.get("likes", 0),
            "updated": m.get("lastModified", ""), "created": m.get("createdAt", ""),
            "downloads_all": m.get("downloadsAllTime"),
            "gated": bool(m.get("gated")),
            "caps": sorted(catalog.detect_capabilities(mid, m.get("tags", []))),
            "params": p,
            "bucket": catalog.size_bucket(p["total_b"]) if p else None}


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


def variant_dest_dir(d, mid, mtype, capability, first_path):
    """The exact folder a download of this variant would land in."""
    company, _, model = mid.partition("/")
    if mtype == "image":
        sub = catalog.comfy_subfolder(capability, [], first_path)
        return os.path.join(d, "Models", "comfyui", sub)
    return os.path.join(d, "Models", "llm", catalog.sanitize_component(company),
                        catalog.sanitize_component(model))


def variant_downloaded(d, mid, mtype, capability, files):
    """True when every file of this variant already exists at the destination."""
    if not d or not os.path.isdir(d) or not files:
        return False
    dd = variant_dest_dir(d, mid, mtype, capability, files[0]["path"])
    return all(os.path.exists(os.path.join(
        dd, catalog.sanitize_component(os.path.basename(f["path"])))) for f in files)


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
                for m in out["text_models"]:
                    m["fits"] = catalog.fits_badge(m["size"], effective_ram())
                self._json(out)
            elif route == "/api/discover":
                self._api_discover()
            elif route == "/api/lineage":
                self._api_lineage()
            elif route == "/api/searches":
                self._json(STORE.data["searches"])
            elif route == "/api/watchlist":
                self._json({"watchlist": STORE.data["watchlist"]})
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
            self._json({"error": "Hugging Face is unreachable. Check your internet. (%s)"
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
            elif route == "/api/library/verify":
                self._api_verify(body)
            elif route == "/api/searches/recent":
                self._api_search_recent(body)
            elif route == "/api/searches/save":
                self._api_search_save(body)
            elif route == "/api/searches/delete":
                self._api_search_delete(body)
            elif route == "/api/watchlist":
                self._api_watchlist_add(body)
            elif route == "/api/watchlist/remove":
                self._api_watchlist_remove(body)
            elif route == "/api/reveal":
                self._api_reveal(body)
            else:
                self.send_error(404)
        except urllib.error.URLError as e:
            self._json({"error": "Hugging Face is unreachable. Check your internet. (%s)"
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
        period = q.get("period", "30d") if sort == "downloads" else "30d"
        want_bucket = q.get("size", "")
        # Size/MoE filtering happens after the fetch (HF has no param-count
        # filter), so pull a deeper page to avoid false "no results".
        # Period windows also post-filter, so they need depth too.
        limit = 100 if (want_bucket or want_moe or period != "30d") else 30
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

        cutoff = ""
        if period in PERIOD_DAYS:
            cutoff = time.strftime("%Y-%m-%dT%H:%M:%S",
                                   time.gmtime(time.time() - PERIOD_DAYS[period] * 86400))
        per_query = []
        for t, qcaps in queries:
            params = catalog.build_search_params(
                q=q.get("q", ""), mtype=t, company=q.get("company", ""),
                capabilities=qcaps, sort=sort, limit=limit,
                domain=q.get("domain", ""))
            variants = [params]
            if period == "all":
                # HF cannot sort by all-time downloads. Take a wide candidate
                # pool (30-day top + all-time likes top) and re-rank ourselves.
                for v in variants:
                    v.pop("full", None)
                    v["expand[]"] = EXPAND_FIELDS
                    v["limit"] = "100"
                likes_params = dict(params, sort="likes")
                variants = [params, likes_params]
            cards = []
            for prm in variants:
                for m in hf_api.search_models(prm):
                    card = make_card(m, t)
                    p = card["params"]
                    if want_moe and not (p and p["moe"]):
                        continue
                    if want_bucket and card["bucket"] != want_bucket:
                        continue
                    if cutoff and (card["created"] or "9999") < cutoff:
                        continue
                    cards.append(card)
            per_query.append(cards)
        if q.get("broaden") == "1" and q.get("q", "").strip():
            for term in catalog.broaden_terms(q.get("q", "")):
                t0 = next((t for t in types if t != "image"), types[0])
                prm = catalog.build_search_params(q=term, mtype=t0, company=q.get("company", ""),
                                                  capabilities=[], sort=sort, limit=20)
                cards = []
                for m in hf_api.search_models(prm):
                    card = make_card(m, t0)
                    card["via_term"] = term
                    cards.append(card)
                per_query.append(cards)
        if q.get("q", "").strip():
            ft_cards = []
            for h in hf_api.search_fulltext(q.get("q", "").strip()):
                tags = h["tags"]
                if "gguf" in tags:
                    mt = "gguf"
                elif any("mlx" in t for t in tags):
                    mt = "mlx"
                elif any(t in ("text-to-image", "text-to-video", "diffusers") for t in tags):
                    mt = "image"
                else:
                    mt = next((t for t in types if t != "image"), types[0])
                if mt not in types:
                    continue
                p = catalog.parse_params(h["id"])
                if want_moe and not (p and p["moe"]):
                    continue
                if want_bucket and catalog.size_bucket(p["total_b"] if p else None) != want_bucket:
                    continue
                ft_cards.append({
                    "id": h["id"], "company": h["id"].split("/")[0], "mtype": mt,
                    "downloads": 0, "likes": h["likes"], "updated": "", "created": "",
                    "downloads_all": None, "gated": False, "via_readme": True,
                    "caps": sorted(catalog.detect_capabilities(h["id"], tags)),
                    "params": p,
                    "bucket": catalog.size_bucket(p["total_b"]) if p else None})
            per_query.append(ft_cards[:20])
        results = catalog.merge_cards(per_query, sort)
        if period == "all":
            results.sort(key=lambda c: c.get("downloads_all") or 0, reverse=True)
            results = results[:60]
        self._json({"results": results})

    def _api_discover(self):
        now = time.time()
        if _DISCOVER_CACHE["data"] and now - _DISCOVER_CACHE["ts"] < DISCOVER_TTL:
            self._json(_DISCOVER_CACHE["data"])
            return
        base = {"filter": "gguf", "limit": "8", "direction": "-1", "full": "true"}
        trending = [make_card(m, "gguf") for m in hf_api.search_models(
            dict(base, sort="trendingScore"))]
        top = [make_card(m, "gguf") for m in hf_api.search_models(
            dict(base, sort="downloads"))]
        labs = []
        for author in LAB_AUTHORS:
            labs += [make_card(m, "gguf") for m in hf_api.search_models(
                dict(base, sort="createdAt", limit="2", author=author))]
        labs.sort(key=lambda c: c["created"] or c["updated"], reverse=True)
        data = {"sections": [
            {"title": "Trending right now", "cards": trending},
            {"title": "Fresh from the labs · latest releases", "cards": labs[:8]},
            {"title": "Most downloaded · last 30 days", "cards": top}]}
        _DISCOVER_CACHE.update(ts=now, data=data)
        self._json(data)

    def _api_lineage(self):
        q = self._query()
        mid, rel = q["id"], q.get("rel", "finetune")
        if rel not in ("finetune", "quantized", "adapter", "merge"):
            rel = "finetune"
        raw = hf_api.search_models({"filter": "base_model:%s:%s" % (rel, mid),
                                    "sort": "downloads", "direction": "-1",
                                    "limit": "30", "full": "true"})
        self._json({"results": [make_card(m, catalog.infer_mtype(m.get("tags")))
                                for m in raw]})

    def _api_search_recent(self, body):
        rec = STORE.data["searches"]["recent"]
        entry = body.get("search")
        if entry:
            rec[:] = [r for r in rec if r != entry]
            rec.insert(0, entry)
            del rec[8:]
            STORE.save()
        self._json(STORE.data["searches"])

    def _api_search_save(self, body):
        saved = STORE.data["searches"]["saved"]
        name = (body.get("name") or "").strip()[:60]
        if name and body.get("search"):
            saved[:] = [s for s in saved if s["name"] != name]
            saved.insert(0, {"name": name, "search": body["search"]})
            del saved[20:]
            STORE.save()
        self._json(STORE.data["searches"])

    def _api_search_delete(self, body):
        saved = STORE.data["searches"]["saved"]
        saved[:] = [s for s in saved if s["name"] != body.get("name")]
        STORE.save()
        self._json(STORE.data["searches"])

    def _api_watchlist_add(self, body):
        wl = STORE.data["watchlist"]
        if not any(w["id"] == body["id"] for w in wl):
            wl.insert(0, {"id": body["id"], "mtype": body.get("mtype", "gguf"),
                          "added": int(time.time())})
            STORE.save()
        self._json({"watchlist": wl})

    def _api_watchlist_remove(self, body):
        STORE.data["watchlist"] = [w for w in STORE.data["watchlist"]
                                   if w["id"] != body.get("id")]
        STORE.save()
        self._json({"watchlist": STORE.data["watchlist"]})

    def _api_verify(self, body):
        from downloader import MANIFEST, sha256_file
        path = body.get("path", "")
        if not inside_models(path) or not os.path.isdir(path):
            self._json({"error": "Refusing: path is not inside the models folder."}, 400)
            return
        manifest_path = os.path.join(path, MANIFEST)
        try:
            with open(manifest_path) as fh:
                recorded = json.load(fh).get("files", {})
        except (OSError, ValueError):
            self._json({"no_record": True,
                        "note": "No checksum record for this model (downloaded before "
                                "verification records existed). Re-downloads will have one."})
            return
        results = []
        for name, rec in sorted(recorded.items()):
            fp = os.path.join(path, name)
            if not os.path.exists(fp):
                results.append({"file": name, "status": "missing"})
            elif os.path.getsize(fp) != rec.get("size"):
                results.append({"file": name, "status": "corrupt (wrong size)"})
            elif rec.get("sha256") and sha256_file(fp) != rec["sha256"]:
                results.append({"file": name, "status": "corrupt (checksum mismatch)"})
            else:
                results.append({"file": name, "status": "ok"})
        self._json({"results": results,
                    "healthy": all(r["status"] == "ok" for r in results)})

    def _api_model(self):
        q = self._query()
        mid, mtype = q["id"], q.get("type", "gguf")
        capability = q.get("capability", "")
        info = hf_api.model_info(mid)
        # Gated repos 401 on the tree endpoint for anonymous users. With a token
        # we try anyway; a 401/403 then means the license was not accepted yet.
        gated = bool(info.get("gated"))
        token = STORE.data["settings"].get("hf_token", "")
        tree, gated_reason = [], None
        if not gated or token:
            try:
                tree = hf_api.model_tree(mid)
                gated = False
            except urllib.error.HTTPError as e:
                if e.code in (401, 403) and gated:
                    gated_reason = ("Your Hugging Face token does not have access yet. "
                                    "Open the model page and accept its license first.")
                else:
                    raise
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
        if not variants and tree and mtype != "image":
            files = [f for f in tree
                     if not f["path"].startswith(".") and f["path"] != "README.md"]
            if files:
                variants.append({"label": "Full repository (%d files)" % len(files),
                                 "quant": catalog.parse_quant(mid),
                                 "size": sum(f["size"] for f in files),
                                 "files": files, "kind": "text"})
        for v in variants:
            v["fits"] = catalog.fits_badge(v["size"], effective_ram())
            # Same margin the enqueue check uses, so the button never lies.
            v["will_fit_disk"] = bool(free) and v["size"] * 1.05 + 500 * 1024 * 1024 < free
            v["already"] = variant_downloaded(d, mid, mtype, capability, v["files"])
        card = info.get("cardData") or {}
        p = catalog.parse_params(mid)
        description = "" if gated else catalog.readme_excerpt(hf_api.model_readme(mid))
        self._json({
            "id": mid, "company": mid.split("/")[0], "gated": gated,
            "gated_reason": gated_reason,
            "license_verdict": catalog.license_verdict(card.get("license")),
            "description": description,
            "hf_url": "https://huggingface.co/" + mid,
            "downloads": info.get("downloads", 0), "likes": info.get("likes", 0),
            "updated": info.get("lastModified", ""), "license": card.get("license") or "unknown",
            "params": p,
            "moe_note": ("%.0fB total, %.0fB active. Runs like a much smaller model"
                         % (p["total_b"], p["active_b"]))
                        if p and p["moe"] and p["active_b"] else None,
            "caps": sorted(catalog.detect_capabilities(mid, info.get("tags", []))),
            "bases": catalog.parse_base_models(info.get("tags", [])),
            "variants": variants})

    def _api_download(self, body):
        d = dest()
        if not d or not os.path.isdir(d):
            self._json({"error": "No destination folder. Choose one in Settings first."}, 400)
            return
        total = sum(f["size"] for f in body["files"])
        free = library.disk_stats(d)["free"]
        if total * 1.05 + 500 * 1024 * 1024 > free:
            self._json({"error": "Not enough free space on the destination "
                                 "(%.1f GB needed, %.1f GB free)."
                                 % (total / 1e9, free / 1e9)}, 400)
            return
        mid = body["model_id"]
        if variant_downloaded(d, mid, body.get("mtype", "gguf"),
                              body.get("capability", ""), body["files"]):
            self._json({"error": "This version is already in your library. "
                                 "Delete it there first if you want to download it again."}, 409)
            return
        dest_dir = variant_dest_dir(d, mid, body.get("mtype", "gguf"),
                                    body.get("capability", ""), body["files"][0]["path"])
        job = {"id": make_job_id(), "model_id": mid,
               "label": "%s · %s" % (mid, body.get("variant_label", "")),
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
        if "hf_token" in body:
            s["hf_token"] = str(body["hf_token"]).strip()
            hf_api.set_token(s["hf_token"])
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
        print("ModelDock is already running. Opening browser.")
        if want_browser:
            subprocess.run(["open", url])
        return
    probe.close()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    if want_browser:
        threading.Timer(0.6, lambda: subprocess.run(["open", url])).start()
    print("ModelDock running at %s. Close this window to stop." % url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
