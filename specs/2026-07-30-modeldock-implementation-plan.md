# ModelDock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build ModelDock — a zero-install local Mac app that searches Hugging Face and downloads GGUF/MLX/diffusion models to a switchable destination (external SSD), with resume-safe downloads and a filesystem-truthful library.

**Architecture:** Python 3.9 **standard library only** server (`ThreadingHTTPServer`) on `127.0.0.1:8420` serving a vanilla HTML/CSS/JS frontend and a JSON API. Pure logic isolated in `catalog.py` (fully unit-tested); downloads run in one background worker thread writing `.part` files with HTTP Range resume and atomic rename. State = one JSON file; the Library reads the real filesystem every time.

**Tech Stack:** macOS stock `/usr/bin/python3` (3.9.6), `http.server`, `urllib`, `unittest`. No pip, no venv, no Node, no build step.

**Spec:** `dev_projects/model-dock/SPEC.md` (approved 2026-07-30).

---

## File structure

```
model-dock/
├── start.command            # double-click launcher (delegates to app.py)
├── SPEC.md                  # approved design (exists)
├── README.md                # Task 14
├── specs/                   # this plan
├── server/
│   ├── app.py               # HTTP server, routing, static files, osascript helpers
│   ├── catalog.py           # PURE logic: quants, params/MoE, capabilities, routing, fits
│   ├── hf_api.py            # Hugging Face API client (urllib, injectable opener)
│   ├── store.py             # settings + queue persistence (JSON, atomic writes)
│   ├── library.py           # destination scanning + disk stats
│   └── downloader.py        # queue worker: Range resume, verify, atomic rename
├── data/                    # state.json lives here (gitignored)
├── web/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── tests/
    ├── test_catalog.py
    ├── test_store.py
    ├── test_hf_api.py
    ├── test_library.py
    └── test_downloader.py
```

Run all tests from `model-dock/` with:
`/usr/bin/python3 -m unittest discover -s tests -v`
(`tests/` imports via `sys.path.insert(0, ...server)` in each test file.)

---

### Task 0: Scaffold, git init, launcher, hello server

**Files:**
- Create: `model-dock/.gitignore`, `model-dock/start.command`, `model-dock/server/app.py` (minimal), `model-dock/web/index.html` (placeholder)

- [ ] **Step 1: Create folders and .gitignore, init git**

```bash
cd /Users/karagos/Documents/CAIO-Cowork/dev_projects/model-dock
mkdir -p server web tests data specs
printf 'data/\n__pycache__/\n.DS_Store\n' > .gitignore
git init -b main
git add SPEC.md .gitignore specs/
git commit -m "chore: ModelDock scaffold — approved spec + plan"
```

- [ ] **Step 2: Write minimal `server/app.py`** — static file server + `/api/ping`, port-in-use handling, browser open.

```python
"""ModelDock server. Zero dependencies: macOS stock Python 3.9 stdlib only."""
import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = "127.0.0.1", 8420
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
MIME = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet terminal
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        rel = path.lstrip("/") or "index.html"
        full = os.path.realpath(os.path.join(WEB, rel))
        if not full.startswith(os.path.realpath(WEB)) or not os.path.isfile(full):
            self.send_error(404)
            return
        ext = os.path.splitext(full)[1]
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/ping":
            self._json({"ok": True})
        else:
            self._static(self.path.split("?")[0])


def main():
    url = "http://%s:%s" % (HOST, PORT)
    probe = socket.socket()
    if probe.connect_ex((HOST, PORT)) == 0:  # already running
        probe.close()
        print("ModelDock is already running — opening browser.")
        subprocess.run(["open", url])
        return
    probe.close()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Timer(0.6, lambda: subprocess.run(["open", url])).start()
    print("ModelDock running at %s — close this window to stop." % url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Write `start.command` and make it executable**

```bash
cat > start.command <<'EOF'
#!/bin/zsh
cd "$(dirname "$0")"
exec /usr/bin/python3 server/app.py
EOF
chmod +x start.command
```

- [ ] **Step 4: Placeholder `web/index.html`**

```html
<!doctype html><meta charset="utf-8"><title>ModelDock</title><p>ModelDock booting…</p>
```

- [ ] **Step 5: Verify**

Run: `/usr/bin/python3 server/app.py &` then `curl -s http://127.0.0.1:8420/api/ping`
Expected: `{"ok": true}` — then `curl -s http://127.0.0.1:8420/ | head -1` shows the placeholder HTML. Kill the server (`kill %1`).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: launcher + hello server (port 8420, 127.0.0.1)"
```

---

### Task 1: catalog.py — quantization parsing

**Files:** Create `server/catalog.py`, `tests/test_catalog.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_catalog.py
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import catalog


class TestQuant(unittest.TestCase):
    def test_parse_common_quants(self):
        self.assertEqual(catalog.parse_quant("Llama-3-8B.Q4_K_M.gguf"), "Q4_K_M")
        self.assertEqual(catalog.parse_quant("model-IQ4_XS.gguf"), "IQ4_XS")
        self.assertEqual(catalog.parse_quant("m-Q8_0.gguf"), "Q8_0")
        self.assertEqual(catalog.parse_quant("weights-F16.gguf"), "F16")

    def test_qwen_name_not_a_quant(self):
        self.assertIsNone(catalog.parse_quant("Qwen3-Instruct.gguf"))

    def test_mlx_bits(self):
        self.assertEqual(catalog.parse_quant("mlx-community/Qwen3-14B-4bit"), "MLX-4BIT")
        self.assertEqual(catalog.parse_quant("Model-8bit"), "MLX-8BIT")

    def test_family(self):
        self.assertEqual(catalog.quant_family("Q4_K_M"), "Q4")
        self.assertEqual(catalog.quant_family("IQ4_XS"), "Q4")
        self.assertEqual(catalog.quant_family("F16"), "F16")
        self.assertEqual(catalog.quant_family("MLX-4BIT"), "MLX-4BIT")
        self.assertIsNone(catalog.quant_family(None))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `/usr/bin/python3 -m unittest tests.test_catalog -v` (from `model-dock/`)
Expected: FAIL / ERROR — `No module named 'catalog'`

- [ ] **Step 3: Implement**

```python
# server/catalog.py
"""Pure logic for ModelDock: parsing, filtering, routing. No I/O, no network."""
import re

QUANT_RE = re.compile(r"(?<![A-Za-z0-9])(I?Q\d(?:_[A-Z0-9]+)*|F16|F32|BF16)(?![A-Za-z0-9])")


def parse_quant(name):
    m = QUANT_RE.search(name)
    if m:
        return m.group(1).upper()
    low = name.lower()
    if "8bit" in low or "8-bit" in low:
        return "MLX-8BIT"
    if "4bit" in low or "4-bit" in low:
        return "MLX-4BIT"
    return None


def quant_family(quant):
    if not quant:
        return None
    if quant.startswith("MLX"):
        return quant
    m = re.match(r"I?Q(\d)", quant)
    return "Q%s" % m.group(1) if m else quant
```

- [ ] **Step 4: Run tests — expect PASS**  `/usr/bin/python3 -m unittest tests.test_catalog -v`

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(catalog): quantization parsing"`

---

### Task 2: catalog.py — parameters, MoE, size buckets

**Files:** Modify `server/catalog.py`, `tests/test_catalog.py`

- [ ] **Step 1: Add failing tests**

```python
class TestParams(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(catalog.parse_params("Meta-Llama-3.1-8B-Instruct"),
                         {"total_b": 8.0, "active_b": None, "moe": False})
        self.assertEqual(catalog.parse_params("Qwen3-0.6B")["total_b"], 0.6)

    def test_moe_a_form(self):
        p = catalog.parse_params("Qwen3-30B-A3B-GGUF")
        self.assertEqual((p["total_b"], p["active_b"], p["moe"]), (30.0, 3.0, True))

    def test_moe_x_form(self):
        p = catalog.parse_params("Mixtral-8x7B-v0.1")
        self.assertEqual((p["total_b"], p["active_b"], p["moe"]), (56.0, 7.0, True))

    def test_none(self):
        self.assertIsNone(catalog.parse_params("Phi-model"))

    def test_buckets(self):
        self.assertEqual(catalog.size_bucket(0.6), "<=4B")
        self.assertEqual(catalog.size_bucket(8), "7-9B")
        self.assertEqual(catalog.size_bucket(14), "12-15B")
        self.assertEqual(catalog.size_bucket(30), "20-35B")
        self.assertEqual(catalog.size_bucket(70), "70B+")
        self.assertIsNone(catalog.size_bucket(None))
```

- [ ] **Step 2: Run — expect FAIL** (`parse_params` missing)

- [ ] **Step 3: Implement (append to catalog.py)**

```python
MOE_A_RE = re.compile(r"(?i)(\d+(?:\.\d+)?)B-A(\d+(?:\.\d+)?)B(?![A-Za-z])")
MOE_X_RE = re.compile(r"(?i)(\d+)\s*x\s*(\d+(?:\.\d+)?)B(?![A-Za-z])")
PARAM_RE = re.compile(r"(?i)(?<![\dA-Za-z.])(\d+(?:\.\d+)?)B(?![A-Za-z])")

SIZE_BUCKETS = [("<=4B", 0, 4.5), ("7-9B", 4.5, 10), ("12-15B", 10, 16),
                ("20-35B", 16, 40), ("70B+", 40, float("inf"))]


def parse_params(name):
    m = MOE_A_RE.search(name)
    if m:
        return {"total_b": float(m.group(1)), "active_b": float(m.group(2)), "moe": True}
    m = MOE_X_RE.search(name)
    if m:
        n, per = int(m.group(1)), float(m.group(2))
        return {"total_b": n * per, "active_b": per, "moe": True}
    m = PARAM_RE.search(name)
    if m:
        return {"total_b": float(m.group(1)), "active_b": None, "moe": False}
    return None


def size_bucket(total_b):
    if total_b is None:
        return None
    for label, lo, hi in SIZE_BUCKETS:
        if lo <= total_b < hi:
            return label
    return None
```

- [ ] **Step 4: Run tests — PASS.**  **Step 5: Commit** `git commit -am "feat(catalog): parameter count + MoE detection, size buckets"`

---

### Task 3: catalog.py — capabilities, search-query building

**Files:** Modify `server/catalog.py`, `tests/test_catalog.py`

- [ ] **Step 1: Add failing tests**

```python
class TestCapabilities(unittest.TestCase):
    def test_detect(self):
        self.assertIn("vision", catalog.detect_capabilities("org/Qwen2.5-VL-7B", ["image-text-to-text"]))
        self.assertIn("thinking", catalog.detect_capabilities("org/DeepSeek-R1-Distill", []))
        self.assertIn("thinking", catalog.detect_capabilities("org/QwQ-32B", []))
        self.assertIn("coding", catalog.detect_capabilities("org/Qwen2.5-Coder-14B", []))
        self.assertIn("agentic", catalog.detect_capabilities("org/x", ["function-calling"]))

    def test_search_params_text(self):
        p = catalog.build_search_params(q="qwen", mtype="gguf", company="Qwen",
                                        capability="thinking", sort="downloads")
        self.assertEqual(p["filter"], "gguf")
        self.assertEqual(p["author"], "Qwen")
        self.assertIn("reasoning", p["search"])
        self.assertEqual(p["sort"], "downloads")

    def test_search_params_image(self):
        p = catalog.build_search_params(q="", mtype="image", company="", capability="video-gen", sort="trending")
        self.assertEqual(p["pipeline_tag"], "text-to-video")
        self.assertEqual(p["sort"], "trendingScore")

    def test_search_params_mlx(self):
        p = catalog.build_search_params(q="llama", mtype="mlx", company="", capability="", sort="newest")
        self.assertEqual(p["filter"], "mlx")
        self.assertEqual(p["sort"], "lastModified")
```

- [ ] **Step 2: Run — FAIL.**  **Step 3: Implement (append)**

```python
CAP_NAME_HINTS = {
    "vision": ("-vl", "vl-", "vision", "llava", "-omni"),
    "thinking": ("r1", "qwq", "think", "reason"),
    "coding": ("coder", "-code", "code-", "codestral", "starcoder"),
    "agentic": ("agent", "tool"),
}
CAP_TAG_HINTS = {
    "vision": ("image-text-to-text", "vision", "multimodal"),
    "thinking": ("reasoning",),
    "coding": ("code",),
    "agentic": ("function-calling", "tool-use", "agent"),
}


def detect_capabilities(model_id, tags):
    tags_low = {t.lower() for t in (tags or [])}
    name = model_id.lower()
    caps = set()
    for cap, hints in CAP_NAME_HINTS.items():
        if any(h in name for h in hints):
            caps.add(cap)
    for cap, hints in CAP_TAG_HINTS.items():
        if tags_low & set(hints):
            caps.add(cap)
    return caps


SORT_MAP = {"downloads": "downloads", "trending": "trendingScore", "newest": "lastModified"}
CAP_SEARCH_EXTRA = {"thinking": "reasoning", "coding": "coder", "agentic": "tool", "upscaler": "upscale"}
CAP_PIPELINE = {"vision": "image-text-to-text", "image-gen": "text-to-image", "video-gen": "text-to-video"}


def build_search_params(q="", mtype="gguf", company="", capability="", sort="downloads"):
    p = {"limit": "30", "sort": SORT_MAP.get(sort, "downloads"), "direction": "-1", "full": "true"}
    search_terms = [q] if q else []
    if capability in CAP_SEARCH_EXTRA:
        search_terms.append(CAP_SEARCH_EXTRA[capability])
    if mtype == "gguf":
        p["filter"] = "gguf"
    elif mtype == "mlx":
        p["filter"] = "mlx"
    elif mtype == "image":
        p["pipeline_tag"] = CAP_PIPELINE.get(capability, "text-to-image")
        if capability == "lora":
            p["filter"] = "lora"
            p.pop("pipeline_tag")
        if capability == "upscaler":
            p.pop("pipeline_tag", None)
    if capability in CAP_PIPELINE and mtype != "image":
        p["pipeline_tag"] = CAP_PIPELINE[capability]
    if company:
        p["author"] = company
    if search_terms:
        p["search"] = " ".join(search_terms)
    return p
```

- [ ] **Step 4: Run tests — PASS.**  **Step 5: Commit** `git commit -am "feat(catalog): capability detection + HF search param builder"`

---

### Task 4: catalog.py — sanitizing, ComfyUI routing, fits-your-Mac, GGUF split grouping

**Files:** Modify `server/catalog.py`, `tests/test_catalog.py`

- [ ] **Step 1: Add failing tests**

```python
class TestRoutingAndFits(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(catalog.sanitize_component("meta-llama/Llama:3"), "meta-llama_Llama_3")
        self.assertEqual(catalog.sanitize_component("  .. "), "untitled")

    def test_comfy_routing(self):
        self.assertEqual(catalog.comfy_subfolder("lora", [], "style.safetensors"), "loras")
        self.assertEqual(catalog.comfy_subfolder("", [], "wan_vae.safetensors"), "vae")
        self.assertEqual(catalog.comfy_subfolder("upscaler", [], "x4-esrgan.safetensors"), "upscale_models")
        self.assertEqual(catalog.comfy_subfolder("image-gen", [], "flux1-dev.safetensors"), "checkpoints")

    def test_fits(self):
        gib = 1024 ** 3
        self.assertEqual(catalog.fits_badge(10 * gib, 32 * gib), "green")
        self.assertEqual(catalog.fits_badge(22 * gib, 32 * gib), "orange")
        self.assertEqual(catalog.fits_badge(30 * gib, 32 * gib), "red")
        self.assertEqual(catalog.fits_badge(10 * gib, 0), "unknown")

    def test_split_grouping(self):
        files = [
            {"path": "m-Q4_K_M-00001-of-00002.gguf", "size": 10, "sha256": "a"},
            {"path": "m-Q4_K_M-00002-of-00002.gguf", "size": 7, "sha256": "b"},
            {"path": "m-Q8_0.gguf", "size": 30, "sha256": "c"},
        ]
        groups = catalog.group_gguf_files(files)
        self.assertEqual(len(groups), 2)
        multi = next(g for g in groups if len(g["files"]) == 2)
        self.assertEqual(multi["size"], 17)
        self.assertEqual(multi["quant"], "Q4_K_M")
        self.assertIn("2 parts", multi["label"])
```

- [ ] **Step 2: Run — FAIL.**  **Step 3: Implement (append)**

```python
SPLIT_RE = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$", re.I)


def sanitize_component(name):
    s = re.sub(r"[^\w.\- ]", "_", name).strip(" .")
    return s or "untitled"


def comfy_subfolder(capability, tags, filename):
    t = {x.lower() for x in (tags or [])}
    n = (filename or "").lower()
    if capability == "lora" or "lora" in t or "lora" in n:
        return "loras"
    if capability == "upscaler" or "upscale" in n or "esrgan" in n:
        return "upscale_models"
    if "vae" in t or "vae" in n:
        return "vae"
    return "checkpoints"


def fits_badge(file_bytes, ram_bytes):
    if not ram_bytes:
        return "unknown"
    r = file_bytes / float(ram_bytes)
    if r <= 0.60:
        return "green"
    if r <= 0.85:
        return "orange"
    return "red"


def group_gguf_files(files):
    """Group split GGUF parts into one downloadable entry; singles pass through."""
    groups = {}
    order = []
    for f in files:
        m = SPLIT_RE.match(f["path"])
        key = m.group(1) + ".gguf" if m else f["path"]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(f)
    out = []
    for key in order:
        fs = sorted(groups[key], key=lambda x: x["path"])
        label = key if len(fs) == 1 else "%s (%d parts)" % (key, len(fs))
        out.append({"label": label, "quant": parse_quant(key),
                    "size": sum(x["size"] for x in fs), "files": fs})
    return out
```

- [ ] **Step 4: Run full suite — all PASS.** `/usr/bin/python3 -m unittest discover -s tests -v`
- [ ] **Step 5: Commit** `git commit -am "feat(catalog): sanitize, comfy routing, fits badge, split grouping"`

---

### Task 5: store.py — settings + queue persistence

**Files:** Create `server/store.py`, `tests/test_store.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_store.py
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
from store import Store


class TestStore(unittest.TestCase):
    def test_defaults_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "state.json")
            s = Store(p)
            self.assertEqual(s.data["settings"]["preferred_quant"], "Q4")
            s.data["settings"]["destination"] = "/Volumes/SSD"
            s.remember_destination("/Volumes/SSD")
            s.save()
            s2 = Store(p)
            self.assertEqual(s2.data["settings"]["destination"], "/Volumes/SSD")
            self.assertEqual(s2.data["settings"]["recent_destinations"], ["/Volumes/SSD"])

    def test_recents_dedupe_cap(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "s.json"))
            for i in range(8):
                s.remember_destination("/V/%d" % i)
            s.remember_destination("/V/3")
            r = s.data["settings"]["recent_destinations"]
            self.assertEqual(r[0], "/V/3")
            self.assertLessEqual(len(r), 6)

    def test_corrupt_file_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            open(p, "w").write("{broken")
            s = Store(p)
            self.assertIn("settings", s.data)
```

- [ ] **Step 2: Run — FAIL.**  **Step 3: Implement**

```python
# server/store.py
"""Single-JSON-file persistence for settings and the download queue."""
import json
import os
import threading

DEFAULT_SETTINGS = {"destination": "", "recent_destinations": [],
                    "preferred_quant": "Q4", "theme": "dark"}


class Store:
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()
        self.data = {"settings": dict(DEFAULT_SETTINGS), "queue": []}
        try:
            with open(path) as f:
                loaded = json.load(f)
            self.data["queue"] = loaded.get("queue", [])
            merged = dict(DEFAULT_SETTINGS)
            merged.update(loaded.get("settings", {}))
            self.data["settings"] = merged
        except (OSError, ValueError):
            pass

    def save(self):
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, self.path)

    def remember_destination(self, dest):
        r = self.data["settings"]["recent_destinations"]
        if dest in r:
            r.remove(dest)
        r.insert(0, dest)
        del r[6:]
```

- [ ] **Step 4: Run — PASS.**  **Step 5: Commit** `git commit -am "feat(store): JSON persistence with atomic save"`

---

### Task 6: hf_api.py — Hugging Face client

**Files:** Create `server/hf_api.py`, `tests/test_hf_api.py`

- [ ] **Step 1: Failing tests** (mock opener; no network in tests)

```python
# tests/test_hf_api.py
import io, json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import hf_api


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_opener(payload):
    calls = []

    def opener(req, timeout=0):
        calls.append(req.full_url)
        return FakeResponse(json.dumps(payload).encode())
    opener.calls = calls
    return opener


class TestHfApi(unittest.TestCase):
    def test_search_url_and_parse(self):
        op = fake_opener([{"id": "Qwen/Qwen3-14B-GGUF", "downloads": 5, "likes": 2,
                           "tags": ["gguf"], "lastModified": "2026-01-01T00:00:00Z"}])
        out = hf_api.search_models({"filter": "gguf", "search": "qwen"}, opener=op)
        self.assertEqual(out[0]["id"], "Qwen/Qwen3-14B-GGUF")
        self.assertIn("api/models?", op.calls[0])
        self.assertIn("filter=gguf", op.calls[0])

    def test_tree_normalizes_lfs(self):
        op = fake_opener([
            {"type": "file", "path": "m-Q4_K_M.gguf", "size": 99,
             "lfs": {"oid": "abc", "size": 99}},
            {"type": "file", "path": "README.md", "size": 5},
            {"type": "directory", "path": "assets"},
        ])
        files = hf_api.model_tree("org/repo", opener=op)
        self.assertEqual(files, [{"path": "m-Q4_K_M.gguf", "size": 99, "sha256": "abc"},
                                 {"path": "README.md", "size": 5, "sha256": None}])
        self.assertIn("/api/models/org/repo/tree/main?recursive=true", op.calls[0])

    def test_file_url_quotes(self):
        self.assertEqual(hf_api.file_url("org/repo", "a b.gguf"),
                         "https://huggingface.co/org/repo/resolve/main/a%20b.gguf")
```

- [ ] **Step 2: Run — FAIL.**  **Step 3: Implement**

```python
# server/hf_api.py
"""Hugging Face Hub API client — urllib only, injectable opener for tests."""
import json
import urllib.parse
import urllib.request

BASE = "https://huggingface.co"
HEADERS = {"User-Agent": "ModelDock/1.0 (local; CAIO)"}
TIMEOUT = 25


def _get_json(url, opener=None):
    req = urllib.request.Request(url, headers=HEADERS)
    op = opener or urllib.request.urlopen
    with op(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def search_models(params, opener=None):
    url = "%s/api/models?%s" % (BASE, urllib.parse.urlencode(params))
    return _get_json(url, opener)


def model_info(model_id, opener=None):
    return _get_json("%s/api/models/%s" % (BASE, model_id), opener)


def model_tree(model_id, opener=None):
    raw = _get_json("%s/api/models/%s/tree/main?recursive=true" % (BASE, model_id), opener)
    files = []
    for e in raw:
        if e.get("type") != "file":
            continue
        lfs = e.get("lfs") or {}
        files.append({"path": e["path"], "size": lfs.get("size", e.get("size", 0)),
                      "sha256": lfs.get("oid")})
    return files


def file_url(model_id, path):
    return "%s/%s/resolve/main/%s" % (BASE, model_id, urllib.parse.quote(path))
```

- [ ] **Step 4: Run — PASS.**  **Step 5: Commit** `git commit -am "feat(hf_api): search, info, tree, download URLs"`

---

### Task 7: library.py — destination scanning + disk stats

**Files:** Create `server/library.py`, `tests/test_library.py`

- [ ] **Step 1: Failing tests** (build a fake destination in a temp dir)

```python
# tests/test_library.py
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import library


def touch(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * size)


class TestLibrary(unittest.TestCase):
    def test_missing_destination(self):
        out = library.scan("/nonexistent/path/xyz")
        self.assertFalse(out["connected"])

    def test_scan(self):
        with tempfile.TemporaryDirectory() as d:
            touch(os.path.join(d, "Models/Qwen/Qwen3-14B-GGUF/q.Q4_K_M.gguf"), 100)
            touch(os.path.join(d, "Models/Qwen/Qwen3-14B-GGUF/q.Q8_0.gguf"), 200)
            touch(os.path.join(d, "Models/comfyui/loras/style.safetensors"), 50)
            out = library.scan(d)
            self.assertTrue(out["connected"])
            self.assertEqual(len(out["text_models"]), 1)
            m = out["text_models"][0]
            self.assertEqual(m["company"], "Qwen")
            self.assertEqual(m["size"], 300)
            self.assertEqual(sorted(m["quants"]), ["Q4_K_M", "Q8_0"])
            self.assertEqual(out["comfy_models"][0]["subfolder"], "loras")
            self.assertEqual(out["total_bytes"], 350)

    def test_part_files_marked_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            touch(os.path.join(d, "Models/X/M/model.gguf.part"), 10)
            out = library.scan(d)
            self.assertTrue(out["text_models"][0]["incomplete"])
```

- [ ] **Step 2: Run — FAIL.**  **Step 3: Implement**

```python
# server/library.py
"""Reads the destination's real folders. No cache, no database — always truthful."""
import os

import catalog


def disk_stats(dest):
    try:
        st = os.statvfs(dest)
        return {"free": st.f_bavail * st.f_frsize, "total": st.f_blocks * st.f_frsize}
    except OSError:
        return {"free": 0, "total": 0}


def _entry_files(folder):
    out = []
    for base, _dirs, names in os.walk(folder):
        for n in names:
            if n == ".DS_Store":
                continue
            p = os.path.join(base, n)
            try:
                out.append((n, os.path.getsize(p), os.path.getmtime(p)))
            except OSError:
                pass
    return out


def scan(dest):
    root = os.path.join(dest, "Models") if dest else ""
    if not dest or not os.path.isdir(dest):
        return {"connected": False, "text_models": [], "comfy_models": [], "total_bytes": 0}
    result = {"connected": True, "text_models": [], "comfy_models": [], "total_bytes": 0}
    if not os.path.isdir(root):
        return result
    for company in sorted(os.listdir(root)):
        cpath = os.path.join(root, company)
        if not os.path.isdir(cpath) or company.startswith("."):
            continue
        if company == "comfyui":
            for sub in sorted(os.listdir(cpath)):
                spath = os.path.join(cpath, sub)
                if not os.path.isdir(spath):
                    continue
                for name, size, mtime in _entry_files(spath):
                    result["comfy_models"].append({
                        "name": name, "subfolder": sub, "size": size, "mtime": mtime,
                        "path": os.path.join(spath, name),
                        "incomplete": name.endswith(".part")})
                    result["total_bytes"] += size
            continue
        for model in sorted(os.listdir(cpath)):
            mpath = os.path.join(cpath, model)
            if not os.path.isdir(mpath):
                continue
            files = _entry_files(mpath)
            if not files:
                continue
            size = sum(f[1] for f in files)
            quants = sorted({q for q in (catalog.parse_quant(f[0]) for f in files) if q})
            fmt = "GGUF" if any(f[0].lower().endswith((".gguf", ".gguf.part")) for f in files) else "MLX"
            result["text_models"].append({
                "company": company, "model": model, "path": mpath, "size": size,
                "mtime": max(f[2] for f in files), "quants": quants, "format": fmt,
                "incomplete": any(f[0].endswith(".part") for f in files)})
            result["total_bytes"] += size
    return result
```

- [ ] **Step 4: Run — PASS.**  **Step 5: Commit** `git commit -am "feat(library): filesystem-truthful scanning + disk stats"`

---

### Task 8: downloader.py — resume-safe download engine

**Files:** Create `server/downloader.py`, `tests/test_downloader.py`

- [ ] **Step 1: Failing tests** — fake opener serves a byte buffer honoring `Range`.

```python
# tests/test_downloader.py
import io, os, sys, tempfile, threading, time, unittest
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
            "state": "queued", "downloaded_bytes": 0, "error": ""}


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
```

- [ ] **Step 2: Run — FAIL.**  **Step 3: Implement**

```python
# server/downloader.py
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
        for f in job["files"]:
            part = os.path.join(job["dest_dir"], f["local_name"] + ".part")
            try:
                os.remove(part)
            except OSError:
                pass
        self.store.data["queue"].remove(job)
        self.store.save()

    def _signal(self, job_id, sig):
        with self._lock:
            self._signals[job_id] = sig

    def _ensure_worker(self):
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _next_queued(self):
        with self._lock:
            return next((j for j in self.store.data["queue"] if j["state"] == "queued"), None)

    def _run(self):
        while True:
            job = self._next_queued()
            if job is None:
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
                job["error"] = "Destination drive is almost full — download paused."
                raise _Interrupted("pause")
        except OSError:
            raise RuntimeError("Destination drive is not available")

    def _verify(self, part_path, f):
        actual = os.path.getsize(part_path)
        if actual != f["size"]:
            raise RuntimeError("verification failed: size %d != expected %d" % (actual, f["size"]))
        if f.get("sha256") and f["size"] <= SHA_VERIFY_MAX:
            if sha256_file(part_path) != f["sha256"]:
                os.remove(part_path)
                raise RuntimeError("verification failed: checksum mismatch (corrupt download removed)")


class _Interrupted(Exception):
    def __init__(self, kind):
        self.kind = kind
```

- [ ] **Step 4: Run — all downloader tests PASS**, then full suite.
- [ ] **Step 5: Commit** `git commit -am "feat(downloader): resume-safe engine with verify + atomic rename"`

---

### Task 9: app.py — full API wiring

**Files:** Modify `server/app.py` (replace minimal version)

Endpoints (all JSON):

| Method+Path | Behavior |
|---|---|
| `GET /api/search?q&type&company&capability&size&sort` | `catalog.build_search_params` → `hf_api.search_models` → cards (id, company=id-prefix, downloads, likes, lastModified, gated, caps via `detect_capabilities`, params via `parse_params`, size_bucket; server-side size-bucket filter applied here since HF can't) |
| `GET /api/model?id=` | `model_info` + `model_tree` → detail: for gguf → `group_gguf_files` of `.gguf` files; for mlx → one variant "Full model" with all non-dot files; for image → each `.safetensors`/`.sft` file with suggested `comfy_subfolder`; every variant gets `fits` badge + free-space `will_fit` flag; license/gated/context (best effort from `cardData`) |
| `POST /api/download` | body `{model_id, variant_label, files:[{path,size,sha256}], mtype, capability}` → dest check → free-space pre-check (total×1.05 + 500 MB) → build job (text: `Models/<Company>/<Model>`; image: `Models/comfyui/<subfolder>`) → `mgr.add_job` |
| `GET /api/downloads` | `mgr.status()` |
| `POST /api/downloads/action` | `{id, action: pause\|resume\|cancel\|clear_done}` |
| `GET /api/library` | `library.scan(dest)` + `disk_stats` |
| `POST /api/library/delete` | `{path}` — realpath must be inside `<dest>/Models`; moves to Trash via Finder osascript (never permanent delete) |
| `POST /api/reveal` | `{path}` → `open -R` (same containment check) |
| `GET/POST /api/settings` | read / merge-write settings (destination validated `os.path.isdir`), `remember_destination` |
| `POST /api/pick-folder` | osascript `choose folder` → path or `{canceled: true}` |
| `GET /api/system` | RAM (`sysctl -n hw.memsize`), destination, connected, disk stats |

- [ ] **Step 1: Replace `server/app.py`**

```python
"""ModelDock server. Zero dependencies: macOS stock Python 3.9 stdlib only."""
import json
import os
import socket
import subprocess
import sys
import threading
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


def dest():
    return STORE.data["settings"]["destination"]


def inside_models(path):
    d = dest()
    if not d:
        return False
    return os.path.realpath(path).startswith(os.path.realpath(os.path.join(d, "Models")) + os.sep)


def make_job_id():
    import time
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
        if not full.startswith(os.path.realpath(WEB)) or not os.path.isfile(full):
            self.send_error(404)
            return
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(os.path.splitext(full)[1], "application/octet-stream"))
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
                self._json({"ram": RAM, "destination": d, "connected": connected,
                            "disk": library.disk_stats(d) if connected else {"free": 0, "total": 0}})
            else:
                self._static(route)
        except urllib.error.URLError as e:
            self._json({"error": "Hugging Face is unreachable — check your internet. (%s)" % e.reason}, 502)
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
            self._json({"error": "Hugging Face is unreachable — check your internet. (%s)" % e.reason}, 502)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    # ---------- API implementations ----------
    def _api_search(self):
        q = self._query()
        params = catalog.build_search_params(
            q=q.get("q", ""), mtype=q.get("type", "gguf"), company=q.get("company", ""),
            capability=q.get("capability", ""), sort=q.get("sort", "downloads"))
        raw = hf_api.search_models(params)
        want_bucket = q.get("size", "")
        cards = []
        for m in raw:
            mid = m.get("id", "")
            p = catalog.parse_params(mid)
            bucket = catalog.size_bucket(p["total_b"]) if p else None
            if want_bucket == "moe":
                if not (p and p["moe"]):
                    continue
            elif want_bucket and bucket != want_bucket:
                continue
            cards.append({
                "id": mid, "company": mid.split("/")[0],
                "downloads": m.get("downloads", 0), "likes": m.get("likes", 0),
                "updated": m.get("lastModified", ""), "gated": bool(m.get("gated")),
                "caps": sorted(catalog.detect_capabilities(mid, m.get("tags", []))),
                "params": p, "bucket": bucket})
        self._json({"results": cards})

    def _api_model(self):
        q = self._query()
        mid, mtype = q["id"], q.get("type", "gguf")
        capability = q.get("capability", "")
        info = hf_api.model_info(mid)
        tree = hf_api.model_tree(mid)
        d = dest()
        free = library.disk_stats(d)["free"] if d and os.path.isdir(d) else 0
        variants = []
        if mtype == "gguf":
            ggufs = [f for f in tree if f["path"].lower().endswith(".gguf")]
            for g in catalog.group_gguf_files(ggufs):
                variants.append({"label": g["label"], "quant": g["quant"], "size": g["size"],
                                 "files": g["files"], "kind": "text"})
        elif mtype == "mlx":
            files = [f for f in tree if not f["path"].startswith(".") and f["path"] != "README.md"]
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
            v["fits"] = catalog.fits_badge(v["size"], RAM)
            v["will_fit_disk"] = bool(free) and v["size"] * 1.05 < free
        card = info.get("cardData") or {}
        p = catalog.parse_params(mid)
        self._json({
            "id": mid, "company": mid.split("/")[0], "gated": bool(info.get("gated")),
            "downloads": info.get("downloads", 0), "likes": info.get("likes", 0),
            "updated": info.get("lastModified", ""), "license": card.get("license") or "—",
            "params": p, "moe_note": ("%.0fB total, %.0fB active — runs like a much "
                                      "smaller model" % (p["total_b"], p["active_b"]))
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
            sub = catalog.comfy_subfolder(body.get("capability", ""), [], body["files"][0]["path"])
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
    probe = socket.socket()
    if probe.connect_ex((HOST, PORT)) == 0:
        probe.close()
        print("ModelDock is already running — opening browser.")
        subprocess.run(["open", url])
        return
    probe.close()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Timer(0.6, lambda: subprocess.run(["open", url])).start()
    print("ModelDock running at %s — close this window to stop." % url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify with real network (server running in background)**

```bash
/usr/bin/python3 server/app.py &
curl -s 'http://127.0.0.1:8420/api/search?q=qwen&type=gguf&sort=downloads' | /usr/bin/python3 -m json.tool | head -30
curl -s 'http://127.0.0.1:8420/api/model?id=Qwen/Qwen3-4B-GGUF&type=gguf' | /usr/bin/python3 -m json.tool | head -40
curl -s http://127.0.0.1:8420/api/system | /usr/bin/python3 -m json.tool
```
Expected: search returns result cards; model returns grouped quant variants with `fits` badges; system shows real RAM. Then `kill %1`.

- [ ] **Step 3: Run full test suite — still all PASS.**
- [ ] **Step 4: Commit** `git commit -am "feat(app): full JSON API — search, detail, downloads, library, settings"`

---

### Task 10: Web UI — shell, theme, header, Settings tab

**Files:** Replace `web/index.html`, create `web/style.css`, create `web/app.js`

The full content of the three files is written in this task and Tasks 11–12 extend `app.js` with the renderers. The UI follows CAIO conventions from Markitdown v2: light+dark themes (persisted via settings), coral accent `#D97757`, system font stack, no external fonts/CDNs (fully offline-capable shell).

- [ ] **Step 1: `web/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ModelDock</title>
<link rel="stylesheet" href="style.css">
</head>
<body data-theme="dark">
<header>
  <div class="brand"><span class="logo">▣</span> ModelDock <span class="by">by CAIO</span></div>
  <div class="dest" id="destPill" title="Current destination — change in Settings">
    <span id="destPath">No destination</span>
    <span id="destFree"></span>
  </div>
  <button id="themeBtn" title="Toggle theme">◐</button>
</header>
<nav>
  <button class="tab active" data-tab="search">Search</button>
  <button class="tab" data-tab="downloads">Downloads <span id="dlBadge" class="badge" hidden></span></button>
  <button class="tab" data-tab="library">Library</button>
  <button class="tab" data-tab="settings">Settings</button>
</nav>
<main>
  <section id="tab-search" class="pane active">
    <div class="searchbar">
      <input id="q" type="search" placeholder="Search models — e.g. qwen 3, flux, whisper…">
      <button id="goBtn" class="primary">Search</button>
    </div>
    <div class="filters" id="filters">
      <div class="chiprow" data-group="type">
        <span class="lbl">Type</span>
        <button class="chip active" data-v="gguf">Chat · GGUF</button>
        <button class="chip" data-v="mlx">Chat · MLX</button>
        <button class="chip" data-v="image">Image & Video (ComfyUI)</button>
      </div>
      <div class="chiprow" data-group="company">
        <span class="lbl">Company</span>
        <button class="chip" data-v="Qwen">Qwen</button>
        <button class="chip" data-v="meta-llama">Meta</button>
        <button class="chip" data-v="google">Google</button>
        <button class="chip" data-v="mistralai">Mistral</button>
        <button class="chip" data-v="deepseek-ai">DeepSeek</button>
        <button class="chip" data-v="microsoft">Microsoft</button>
        <button class="chip" data-v="openai">OpenAI</button>
        <button class="chip" data-v="unsloth">Unsloth</button>
        <input id="companyFree" placeholder="other…">
      </div>
      <div class="chiprow" data-group="capability" id="capText">
        <span class="lbl">Capability</span>
        <button class="chip" data-v="vision">Vision</button>
        <button class="chip" data-v="thinking">Thinking</button>
        <button class="chip" data-v="agentic">Agentic</button>
        <button class="chip" data-v="coding">Coding</button>
      </div>
      <div class="chiprow" data-group="capability" id="capImage" hidden>
        <span class="lbl">Capability</span>
        <button class="chip" data-v="image-gen">Image generation</button>
        <button class="chip" data-v="video-gen">Video generation</button>
        <button class="chip" data-v="lora">LoRA</button>
        <button class="chip" data-v="upscaler">Upscaler</button>
      </div>
      <div class="chiprow" data-group="size" id="sizeRow">
        <span class="lbl">Size</span>
        <button class="chip" data-v="<=4B">≤4B</button>
        <button class="chip" data-v="7-9B">7–9B</button>
        <button class="chip" data-v="12-15B">12–15B</button>
        <button class="chip" data-v="20-35B">20–35B</button>
        <button class="chip" data-v="70B+">70B+</button>
        <button class="chip" data-v="moe">MoE</button>
      </div>
      <div class="chiprow" data-group="sort">
        <span class="lbl">Sort</span>
        <button class="chip active" data-v="downloads">Most downloaded</button>
        <button class="chip" data-v="trending">Trending</button>
        <button class="chip" data-v="newest">Newest</button>
      </div>
    </div>
    <div id="results" class="cards"></div>
    <div id="detail" hidden></div>
  </section>

  <section id="tab-downloads" class="pane">
    <div class="pane-head"><h2>Downloads</h2><button id="clearDone" class="ghost">Clear finished</button></div>
    <div id="dlList"></div>
  </section>

  <section id="tab-library" class="pane">
    <div class="pane-head"><h2>Library</h2><div id="libStats"></div></div>
    <div id="libList"></div>
  </section>

  <section id="tab-settings" class="pane">
    <h2>Settings</h2>
    <div class="setting">
      <h3>Destination</h3>
      <p class="hint">Where downloaded models are stored. Point this at your external SSD.</p>
      <div class="row"><code id="setDest">—</code><button id="pickBtn" class="primary">Choose folder…</button></div>
      <div id="recents"></div>
    </div>
    <div class="setting">
      <h3>Preferred quantization</h3>
      <p class="hint">Pre-highlighted in every model. Q4 = best size/quality balance for most Macs.</p>
      <div class="chiprow" id="quantPref">
        <button class="chip" data-v="Q4">Q4</button><button class="chip" data-v="Q5">Q5</button>
        <button class="chip" data-v="Q6">Q6</button><button class="chip" data-v="Q8">Q8</button>
        <button class="chip" data-v="F16">F16</button>
        <button class="chip" data-v="MLX-4BIT">MLX 4-bit</button>
        <button class="chip" data-v="MLX-8BIT">MLX 8-bit</button>
      </div>
    </div>
    <div class="setting"><h3>About</h3>
      <p class="hint">ModelDock v1.0 — downloads AI models from Hugging Face to any drive.
      Zero dependencies. Models stay in plain folders you own. <br>Mac RAM detected: <span id="ramInfo">—</span></p>
    </div>
  </section>
</main>
<div id="toast" hidden></div>
<script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: `web/style.css`** — complete stylesheet:

```css
:root {
  --accent: #D97757; --accent-soft: #d9775722;
  --green: #3f9d6b; --orange: #d99a3d; --red: #cc5449;
}
[data-theme="dark"] {
  --bg: #17171c; --bg2: #1f1f26; --bg3: #2a2a33; --text: #ececf1;
  --muted: #9c9ca8; --line: #33333e;
}
[data-theme="light"] {
  --bg: #faf9f5; --bg2: #ffffff; --bg3: #f0efe9; --text: #1f1e1d;
  --muted: #6e6d66; --line: #e3e1d9;
}
* { box-sizing: border-box; margin: 0; }
body {
  font: 15px/1.5 -apple-system, "SF Pro Text", Helvetica, Arial, sans-serif;
  background: var(--bg); color: var(--text);
}
header {
  display: flex; align-items: center; gap: 16px; padding: 14px 22px;
  border-bottom: 1px solid var(--line); background: var(--bg2);
  position: sticky; top: 0; z-index: 5;
}
.brand { font-weight: 700; font-size: 18px; }
.logo { color: var(--accent); }
.by { font-weight: 400; font-size: 12px; color: var(--muted); }
.dest {
  margin-left: auto; background: var(--bg3); border: 1px solid var(--line);
  border-radius: 20px; padding: 5px 14px; font-size: 13px; display: flex; gap: 10px;
  max-width: 46vw; overflow: hidden; white-space: nowrap;
}
#destPath { overflow: hidden; text-overflow: ellipsis; }
#destFree { color: var(--muted); flex-shrink: 0; }
.dest.warn { border-color: var(--red); color: var(--red); }
#themeBtn { background: none; border: none; color: var(--text); font-size: 18px; cursor: pointer; }
nav { display: flex; gap: 4px; padding: 10px 22px 0; border-bottom: 1px solid var(--line); }
.tab {
  background: none; border: none; color: var(--muted); font-size: 15px; font-weight: 600;
  padding: 8px 14px 12px; cursor: pointer; border-bottom: 2px solid transparent;
}
.tab.active { color: var(--text); border-bottom-color: var(--accent); }
.badge {
  background: var(--accent); color: #fff; border-radius: 10px;
  font-size: 11px; padding: 1px 7px; margin-left: 4px;
}
main { padding: 20px 22px 60px; max-width: 1060px; margin: 0 auto; }
.pane { display: none; }
.pane.active { display: block; }
.pane-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.searchbar { display: flex; gap: 10px; margin-bottom: 14px; }
#q {
  flex: 1; padding: 12px 16px; font-size: 16px; border: 1px solid var(--line);
  border-radius: 10px; background: var(--bg2); color: var(--text);
}
button.primary {
  background: var(--accent); color: #fff; border: none; border-radius: 10px;
  padding: 10px 22px; font-size: 15px; font-weight: 600; cursor: pointer;
}
button.ghost {
  background: none; border: 1px solid var(--line); color: var(--muted);
  border-radius: 8px; padding: 6px 14px; cursor: pointer;
}
.chiprow { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.lbl { color: var(--muted); font-size: 12px; width: 74px; flex-shrink: 0; text-transform: uppercase; letter-spacing: .4px; }
.chip {
  background: var(--bg2); border: 1px solid var(--line); color: var(--text);
  border-radius: 16px; padding: 4px 13px; font-size: 13px; cursor: pointer;
}
.chip.active { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); font-weight: 600; }
#companyFree {
  width: 110px; background: var(--bg2); border: 1px solid var(--line);
  border-radius: 16px; padding: 4px 12px; font-size: 13px; color: var(--text);
}
.cards { display: grid; gap: 10px; margin-top: 18px; }
.card {
  background: var(--bg2); border: 1px solid var(--line); border-radius: 12px;
  padding: 14px 18px; cursor: pointer; display: flex; gap: 14px; align-items: baseline;
}
.card:hover { border-color: var(--accent); }
.card .name { font-weight: 650; }
.card .meta { color: var(--muted); font-size: 13px; margin-left: auto; flex-shrink: 0; }
.pill {
  font-size: 11px; border-radius: 9px; padding: 1px 8px;
  background: var(--bg3); color: var(--muted); margin-left: 6px;
}
.pill.moe { background: var(--accent-soft); color: var(--accent); }
.pill.gated { background: #cc544922; color: var(--red); }
#detail { background: var(--bg2); border: 1px solid var(--line); border-radius: 14px; padding: 22px; margin-top: 16px; }
#detail h2 { margin-bottom: 4px; }
.dmeta { color: var(--muted); font-size: 13px; margin-bottom: 14px; }
.variant {
  display: flex; align-items: center; gap: 12px; padding: 10px 12px;
  border: 1px solid var(--line); border-radius: 10px; margin-bottom: 8px;
}
.variant.preferred { border-color: var(--accent); background: var(--accent-soft); }
.variant .vname { font-family: ui-monospace, monospace; font-size: 13px; overflow: hidden; text-overflow: ellipsis; }
.variant .vsize { margin-left: auto; color: var(--muted); font-size: 13px; flex-shrink: 0; }
.fit { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.fit.green { background: var(--green); } .fit.orange { background: var(--orange); }
.fit.red { background: var(--red); } .fit.unknown { background: var(--muted); }
.dl-item { background: var(--bg2); border: 1px solid var(--line); border-radius: 12px; padding: 14px 18px; margin-bottom: 10px; }
.dl-top { display: flex; align-items: center; gap: 10px; }
.dl-label { font-weight: 600; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dl-stats { margin-left: auto; color: var(--muted); font-size: 13px; flex-shrink: 0; }
.bar { height: 6px; background: var(--bg3); border-radius: 3px; margin-top: 10px; overflow: hidden; }
.bar > div { height: 100%; background: var(--accent); border-radius: 3px; transition: width .4s; }
.dl-err { color: var(--red); font-size: 13px; margin-top: 6px; }
.lib-group h3 { margin: 18px 0 8px; font-size: 14px; color: var(--muted); text-transform: uppercase; letter-spacing: .4px; }
.lib-item {
  display: flex; align-items: center; gap: 12px; background: var(--bg2);
  border: 1px solid var(--line); border-radius: 10px; padding: 10px 16px; margin-bottom: 6px;
}
.lib-item .meta { color: var(--muted); font-size: 13px; margin-left: auto; flex-shrink: 0; }
.lib-item button { margin-left: 6px; }
.setting { background: var(--bg2); border: 1px solid var(--line); border-radius: 12px; padding: 18px 20px; margin-bottom: 14px; }
.setting h3 { margin-bottom: 4px; }
.hint { color: var(--muted); font-size: 13px; margin-bottom: 10px; }
.row { display: flex; gap: 12px; align-items: center; }
.row code {
  flex: 1; background: var(--bg3); padding: 8px 12px; border-radius: 8px;
  font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
#recents { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
.msg { color: var(--muted); padding: 30px 0; text-align: center; }
#toast {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
  background: var(--bg3); border: 1px solid var(--line); color: var(--text);
  padding: 10px 20px; border-radius: 10px; font-size: 14px; z-index: 20; max-width: 80vw;
}
#toast.err { border-color: var(--red); color: var(--red); }
```

- [ ] **Step 3: `web/app.js`** — core state, helpers, tabs, header, Settings (search/downloads/library renderers arrive in Tasks 11–12; define the function stubs `renderResults`, `renderDetail`, `renderDownloads`, `renderLibrary` as empty functions here so the file runs):

```javascript
"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const state = {
  filters: { type: "gguf", company: "", capability: "", size: "", sort: "downloads" },
  settings: {}, system: {}, results: [], detail: null, pollTimer: null,
};

async function api(path, opts) {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ("Request failed (" + r.status + ")"));
  return data;
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

function toast(msg, isErr) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  t.className = isErr ? "err" : "";
  clearTimeout(t._h); t._h = setTimeout(() => (t.hidden = true), 4000);
}

function fmtBytes(n) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0; while (n >= 1000 && i < 4) { n /= 1000; i++; }
  return n.toFixed(n >= 100 || i === 0 ? 0 : 1) + " " + u[i];
}
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

// ---- tabs ----
$$(".tab").forEach((b) => b.addEventListener("click", () => {
  $$(".tab").forEach((x) => x.classList.toggle("active", x === b));
  $$(".pane").forEach((p) => p.classList.toggle("active", p.id === "tab-" + b.dataset.tab));
  if (b.dataset.tab === "library") loadLibrary();
  if (b.dataset.tab === "downloads") pollDownloads();
}));

// ---- theme ----
$("#themeBtn").addEventListener("click", () => {
  const next = document.body.dataset.theme === "dark" ? "light" : "dark";
  document.body.dataset.theme = next;
  post("/api/settings", { theme: next }).catch(() => {});
});

// ---- header / system ----
async function refreshSystem() {
  try {
    state.system = await api("/api/system");
    const pill = $("#destPill");
    if (!state.system.destination) {
      $("#destPath").textContent = "No destination — choose in Settings";
      $("#destFree").textContent = ""; pill.classList.add("warn");
    } else if (!state.system.connected) {
      $("#destPath").textContent = state.system.destination;
      $("#destFree").textContent = "drive not connected"; pill.classList.add("warn");
    } else {
      $("#destPath").textContent = state.system.destination;
      $("#destFree").textContent = fmtBytes(state.system.disk.free) + " free";
      pill.classList.remove("warn");
    }
    $("#ramInfo").textContent = fmtBytes(state.system.ram);
  } catch (e) { /* server briefly busy — retried by caller */ }
}

// ---- settings ----
async function loadSettings() {
  state.settings = await api("/api/settings");
  document.body.dataset.theme = state.settings.theme || "dark";
  $("#setDest").textContent = state.settings.destination || "— none chosen —";
  const rec = $("#recents"); rec.replaceChildren();
  (state.settings.recent_destinations || []).forEach((p) => {
    if (p === state.settings.destination) return;
    const b = el("button", "chip", p);
    b.addEventListener("click", () => saveSettings({ destination: p }));
    rec.append(b);
  });
  $$("#quantPref .chip").forEach((c) =>
    c.classList.toggle("active", c.dataset.v === state.settings.preferred_quant));
}
async function saveSettings(patch) {
  try {
    await post("/api/settings", patch);
    await loadSettings(); await refreshSystem();
    toast("Settings saved");
  } catch (e) { toast(e.message, true); }
}
$("#pickBtn").addEventListener("click", async () => {
  try {
    const r = await post("/api/pick-folder");
    if (!r.canceled && r.path) await saveSettings({ destination: r.path });
  } catch (e) { toast(e.message, true); }
});
$("#quantPref").addEventListener("click", (ev) => {
  const c = ev.target.closest(".chip");
  if (c) saveSettings({ preferred_quant: c.dataset.v });
});

// ---- filter chips (single-select per row, click again to clear) ----
$("#filters").addEventListener("click", (ev) => {
  const chip = ev.target.closest(".chip");
  if (!chip) return;
  const row = chip.parentElement, group = row.dataset.group;
  const wasActive = chip.classList.contains("active");
  row.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
  if (!wasActive || group === "type" || group === "sort") chip.classList.add("active");
  state.filters[group] = row.querySelector(".chip.active")?.dataset.v || "";
  if (group === "type") {
    const img = state.filters.type === "image";
    $("#capText").hidden = img; $("#capImage").hidden = !img; $("#sizeRow").hidden = img;
    state.filters.capability = ""; state.filters.size = "";
    $$("#capText .chip, #capImage .chip, #sizeRow .chip").forEach((c) => c.classList.remove("active"));
  }
  if (group === "company") $("#companyFree").value = "";
  runSearch();
});
$("#companyFree").addEventListener("change", () => {
  $$('[data-group="company"] .chip').forEach((c) => c.classList.remove("active"));
  state.filters.company = $("#companyFree").value.trim();
  runSearch();
});
$("#goBtn").addEventListener("click", runSearch);
$("#q").addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); });

// Defined fully in Tasks 11–12:
function runSearch() {}
function renderResults() {}
function openDetail() {}
function pollDownloads() {}
function loadLibrary() {}

// ---- boot ----
(async function boot() {
  await loadSettings();
  await refreshSystem();
  setInterval(refreshSystem, 5000);
})();
```

- [ ] **Step 4: Verify** — start server, open `http://127.0.0.1:8420` in the Browser pane: header, tabs, filters render; theme toggle works; Settings shows destination controls; **Choose folder…** opens the native dialog (verify manually later — in automated check just confirm no console errors).

- [ ] **Step 5: Commit** `git commit -am "feat(web): app shell, theme, header, settings tab"`

---

### Task 11: Web UI — search results + model detail

**Files:** Modify `web/app.js` — replace the `runSearch`, `renderResults`, `openDetail` stubs:

- [ ] **Step 1: Implement**

```javascript
const CAP_LABELS = { vision: "Vision", thinking: "Thinking", agentic: "Agentic", coding: "Coding" };

async function runSearch() {
  const f = state.filters;
  const qs = new URLSearchParams({ q: $("#q").value.trim(), type: f.type,
    company: f.company, capability: f.capability, size: f.size, sort: f.sort });
  $("#detail").hidden = true;
  $("#results").replaceChildren(el("div", "msg", "Searching Hugging Face…"));
  try {
    const data = await api("/api/search?" + qs);
    state.results = data.results;
    renderResults();
  } catch (e) {
    $("#results").replaceChildren(el("div", "msg", e.message));
  }
}

function renderResults() {
  const box = $("#results"); box.replaceChildren();
  if (!state.results.length) {
    box.append(el("div", "msg", "No models found — try fewer filters or another search term."));
    return;
  }
  state.results.forEach((m) => {
    const c = el("div", "card");
    const name = el("span", "name", m.id);
    if (m.params && m.params.moe) name.append(el("span", "pill moe", "MoE"));
    if (m.bucket) name.append(el("span", "pill", m.bucket.replace("<=", "≤")));
    (m.caps || []).forEach((cap) => CAP_LABELS[cap] && name.append(el("span", "pill", CAP_LABELS[cap])));
    if (m.gated) name.append(el("span", "pill gated", "requires HF account"));
    const meta = el("span", "meta",
      m.downloads.toLocaleString() + " downloads · " + m.likes + " ♥ · " + (m.updated || "").slice(0, 10));
    c.append(name, meta);
    c.addEventListener("click", () => openDetail(m));
    box.append(c);
  });
}

async function openDetail(card) {
  const d = $("#detail");
  d.hidden = false;
  d.replaceChildren(el("div", "msg", "Loading " + card.id + "…"));
  d.scrollIntoView({ behavior: "smooth" });
  try {
    const qs = new URLSearchParams({ id: card.id, type: state.filters.type,
      capability: state.filters.capability });
    const m = await api("/api/model?" + qs);
    d.replaceChildren();
    const back = el("button", "ghost", "← back to results");
    back.addEventListener("click", () => { d.hidden = true; });
    d.append(back, el("h2", "", m.id));
    let metaTxt = m.downloads.toLocaleString() + " downloads · license: " + m.license +
      " · updated " + (m.updated || "").slice(0, 10);
    if (m.params) metaTxt += " · " + m.params.total_b + "B parameters";
    d.append(el("div", "dmeta", metaTxt));
    if (m.moe_note) d.append(el("div", "dmeta", "Mixture-of-Experts: " + m.moe_note));
    if (m.gated) {
      d.append(el("div", "msg",
        "This model requires a free Hugging Face account and license acceptance on huggingface.co. " +
        "ModelDock v1 supports open models only — pick a non-gated alternative."));
      return;
    }
    if (!m.variants.length) {
      d.append(el("div", "msg", "No downloadable files of this type found in this repository."));
      return;
    }
    const prefFam = state.settings.preferred_quant || "";
    m.variants.forEach((v) => {
      const row = el("div", "variant");
      const famOf = (q) => (q ? (q.startsWith("MLX") ? q : "Q" + (q.match(/\d/) || [""])[0]) : "");
      if (prefFam && famOf(v.quant) === prefFam) row.classList.add("preferred");
      row.append(el("span", "fit " + v.fits));
      row.title = { green: "Runs comfortably on this Mac", orange: "Tight — will be slow",
        red: "Won't fit in this Mac's memory", unknown: "RAM unknown" }[v.fits];
      row.append(el("span", "vname", v.label + (v.subfolder ? "  → comfyui/" + v.subfolder : "")));
      row.append(el("span", "vsize", fmtBytes(v.size)));
      const btn = el("button", "primary", "Download");
      if (!v.will_fit_disk) { btn.disabled = true; btn.textContent = "Won't fit on drive"; }
      btn.addEventListener("click", async () => {
        try {
          await post("/api/download", { model_id: m.id, variant_label: v.label,
            files: v.files, mtype: state.filters.type, capability: state.filters.capability });
          toast("Added to downloads: " + v.label);
          $('[data-tab="downloads"]').click();
        } catch (e) { toast(e.message, true); }
      });
      row.append(btn);
      d.append(row);
    });
  } catch (e) {
    d.replaceChildren(el("div", "msg", e.message));
  }
}
```

- [ ] **Step 2: Verify in browser** — search "qwen", results render with pills; click a GGUF repo → quant list with sizes, fits dots, preferred highlight; switch type to Image & Video → capability chips swap; a gated model shows the notice.
- [ ] **Step 3: Commit** `git commit -am "feat(web): search results + model detail with fits badges"`

---

### Task 12: Web UI — downloads queue + library

**Files:** Modify `web/app.js` — replace `pollDownloads`, `loadLibrary` stubs:

- [ ] **Step 1: Implement**

```javascript
const speedTrack = {}; // job_id -> {bytes, t}

function renderDownloads(jobs) {
  const box = $("#dlList"); box.replaceChildren();
  const active = jobs.filter((j) => j.state === "active" || j.state === "queued").length;
  const badge = $("#dlBadge");
  badge.hidden = !active; badge.textContent = active;
  if (!jobs.length) { box.append(el("div", "msg", "No downloads yet — find a model in Search.")); return; }
  jobs.forEach((j) => {
    const item = el("div", "dl-item");
    const top = el("div", "dl-top");
    top.append(el("span", "dl-label", j.label));
    let stats = j.state;
    if (j.state === "active") {
      const prev = speedTrack[j.id], now = Date.now();
      let speed = 0;
      if (prev) speed = Math.max(0, (j.downloaded_bytes - prev.bytes) / ((now - prev.t) / 1000));
      speedTrack[j.id] = { bytes: j.downloaded_bytes, t: now };
      const remain = speed > 0 ? (j.total_bytes - j.downloaded_bytes) / speed : 0;
      stats = fmtBytes(j.downloaded_bytes) + " / " + fmtBytes(j.total_bytes) +
        (speed ? " · " + fmtBytes(speed) + "/s" : "") +
        (remain ? " · ~" + (remain > 90 ? Math.round(remain / 60) + " min" : Math.round(remain) + " s") + " left" : "");
    } else if (j.state === "done") {
      stats = "done · " + fmtBytes(j.total_bytes);
    }
    top.append(el("span", "dl-stats", stats));
    const mk = (label, action) => {
      const b = el("button", "ghost", label);
      b.addEventListener("click", async () => {
        await post("/api/downloads/action", { id: j.id, action });
        pollDownloads();
      });
      return b;
    };
    if (j.state === "active") top.append(mk("Pause", "pause"));
    if (j.state === "paused" || j.state === "error") top.append(mk("Resume", "resume"));
    if (j.state !== "done") top.append(mk("Cancel", "cancel"));
    item.append(top);
    const bar = el("div", "bar"); const fill = el("div");
    fill.style.width = (j.total_bytes ? (100 * j.downloaded_bytes / j.total_bytes) : 0) + "%";
    bar.append(fill); item.append(bar);
    if (j.error) item.append(el("div", "dl-err", j.error));
    box.append(item);
  });
}

async function pollDownloads() {
  clearTimeout(state.pollTimer);
  try {
    const data = await api("/api/downloads");
    renderDownloads(data.jobs);
    if (data.jobs.some((j) => j.state === "active" || j.state === "queued")) {
      state.pollTimer = setTimeout(pollDownloads, 1000);
    }
  } catch (e) { /* transient */ }
}
$("#clearDone").addEventListener("click", async () => {
  await post("/api/downloads/action", { action: "clear_done" });
  pollDownloads();
});

async function loadLibrary() {
  const box = $("#libList"); box.replaceChildren(el("div", "msg", "Reading destination…"));
  try {
    const lib = await api("/api/library");
    box.replaceChildren();
    if (!lib.connected) {
      $("#libStats").textContent = "";
      box.append(el("div", "msg", "Destination drive is not connected (or no destination chosen in Settings)."));
      return;
    }
    $("#libStats").textContent = "Models: " + fmtBytes(lib.total_bytes) +
      " · Free on drive: " + fmtBytes(lib.disk.free);
    const mkActions = (path) => {
      const rev = el("button", "ghost", "Reveal");
      rev.addEventListener("click", () => post("/api/reveal", { path }));
      const del = el("button", "ghost", "Delete");
      del.addEventListener("click", async () => {
        if (!confirm("Move to Trash?\n\n" + path)) return;
        try { await post("/api/library/delete", { path }); toast("Moved to Trash"); loadLibrary(); }
        catch (e) { toast(e.message, true); }
      });
      return [rev, del];
    };
    if (lib.text_models.length) {
      const g = el("div", "lib-group"); g.append(el("h3", "", "Chat & text models"));
      lib.text_models.forEach((m) => {
        const it = el("div", "lib-item");
        const nm = el("span", "", m.company + " / " + m.model);
        if (m.incomplete) nm.append(el("span", "pill gated", "incomplete"));
        it.append(nm, el("span", "meta", m.format + " · " + (m.quants.join(", ") || "—") +
          " · " + fmtBytes(m.size) + " · " + new Date(m.mtime * 1000).toLocaleDateString()));
        it.append(...mkActions(m.path));
        g.append(it);
      });
      box.append(g);
    }
    if (lib.comfy_models.length) {
      const g = el("div", "lib-group"); g.append(el("h3", "", "Image & video models (ComfyUI)"));
      lib.comfy_models.forEach((m) => {
        const it = el("div", "lib-item");
        it.append(el("span", "", m.name),
          el("span", "meta", m.subfolder + " · " + fmtBytes(m.size)));
        it.append(...mkActions(m.path));
        g.append(it);
      });
      box.append(g);
    }
    if (!lib.text_models.length && !lib.comfy_models.length) {
      box.append(el("div", "msg", "Nothing downloaded yet to this destination."));
    }
  } catch (e) {
    box.replaceChildren(el("div", "msg", e.message));
  }
}
```

- [ ] **Step 2: Verify in browser** — Downloads tab shows queue empty message; Library shows "no destination" or scans a chosen folder.
- [ ] **Step 3: Commit** `git commit -am "feat(web): downloads queue with speed/ETA + library tab"`

---

### Task 13: End-to-end verification

No new files — this task proves the whole system with a real download.

- [ ] **Step 1: Full test suite** — `/usr/bin/python3 -m unittest discover -s tests -v` → all pass.
- [ ] **Step 2: Real E2E via API** (small model, ~100–300 MB; destination = a scratch folder):

```bash
mkdir -p /tmp/modeldock-e2e-dest
/usr/bin/python3 server/app.py &
sleep 1
curl -s -X POST http://127.0.0.1:8420/api/settings -d '{"destination": "/tmp/modeldock-e2e-dest"}'
# search + pick smallest quant of a tiny model, e.g. Qwen/Qwen3-0.6B-GGUF Q8_0 (~600MB) or unsloth/Qwen3-0.6B-GGUF Q4:
curl -s 'http://127.0.0.1:8420/api/model?id=unsloth/Qwen3-0.6B-GGUF&type=gguf' | /usr/bin/python3 -m json.tool
# POST /api/download with the smallest variant's files; poll /api/downloads until done
```
Verify: progress advances; **pause + resume mid-download** works (`.part` grows from where it stopped); finished file exists at `Models/unsloth/Qwen3-0.6B-GGUF/…gguf` with correct size; `/api/library` lists it; delete moves it to Trash.

- [ ] **Step 3: Browser walkthrough** — via Browser pane: search → filters → detail → download → watch progress → library. Screenshot for Stefanos. (If the pane can't reach the app's files due to TCC, run the server from this session's Bash — it inherits Documents access — and only *view* via the pane at `http://127.0.0.1:8420`.)
- [ ] **Step 4: Fix anything found, re-run suite, commit** — `git commit -am "test: end-to-end verified with real download"`

---

### Task 14: README, memory updates, handoff

**Files:** Create `model-dock/README.md`; modify `dev_projects/memory.md`

- [ ] **Step 1: README.md** — plain-language: what it is, double-click `start.command`, the four tabs, where files go, LM Studio/ComfyUI pointing instructions, troubleshooting (port busy, drive not connected).
- [ ] **Step 2: Add ModelDock section to `dev_projects/memory.md`** following the existing format: what it does, location, architecture table (zero-dep stdlib), how to start, port **8420**, URL `http://127.0.0.1:8420`, key files, tests command, notes (no database file; `data/state.json` holds settings+queue; safe to edit; never delete files under user destinations).
- [ ] **Step 3: Final commit** `git add -A && git commit -m "docs: README + operational notes"`

---

## Self-review (done at plan time)

- **Spec coverage:** search+filters (T3, T9, T11 — incl. size buckets, MoE, quant preference, company free-text), GGUF+MLX+image variants (T9), fits badge (T4, T9, T11), free-space pre-check + mid-download monitor (T8, T9), resume/pause/cancel + atomic rename + verify (T8), library truthful scan + delete-to-Trash + reveal (T7, T9, T12), destination picker + recents (T5, T9, T10), gated notice (T11), one-at-a-time queue (T8 worker), port/localhost rules (T0), zero deps (all).
- **Placeholders:** none — all code inline. README/memory content described by outline (docs, not code).
- **Type consistency:** job dict fields (`id/model_id/label/dest_dir/files/state/downloaded_bytes/total_bytes/error`) consistent across T8/T9/T12; file dicts `{path,size,sha256}` from hf_api → catalog grouping → `{url,local_name,size,sha256}` in jobs (T9 maps them); `catalog.group_gguf_files` name consistent in T4/T9.
- **Known deltas from spec:** context-window display is best-effort (HF API rarely exposes it for GGUF repos) — detail shows license/params/dates always, context only when derivable. Delete uses **Trash**, exceeding the spec's confirm-only requirement (safer).
