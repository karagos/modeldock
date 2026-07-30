# ModelDock — Design Specification

**Date:** 2026-07-30
**Status:** Approved design, pre-implementation
**Owner:** Stefanos Karagos (CAIO Group)
**Location:** `dev_projects/model-dock/`

---

## 1. Purpose

A local Mac app for downloading AI models from Hugging Face onto any drive Stefanos chooses — primarily his 4 TB external SSD — so his internal disk stays free and his model collection is organized, browsable, and ready for inference apps (LM Studio, Ollama, Jan, llama.cpp, MLX tools) and ComfyUI Desktop (image/video models).

The app downloads and organizes models. It does not run models and does not modify other apps' configuration.

## 2. User decisions (locked)

| Decision | Choice |
|---|---|
| Model discovery | Search inside the app (with rich filters) |
| Text-model formats | GGUF + MLX |
| Image/video models | Yes — diffusion models (.safetensors) for ComfyUI Desktop |
| Inference-app integration | None — download cleanly only; folder layout is passively compatible with LM Studio and ComfyUI |
| Hugging Face account | Not supported in v1 (open models only; gated models show a clear notice) |
| Library management | Yes — library tab with sizes, free space, delete, reveal in Finder |
| Tech approach | Zero-install: macOS stock Python, standard library only, no pip/venv/Homebrew |

## 3. User experience

### 3.1 Launch

Double-click `start.command` → server starts on `http://127.0.0.1:8420` → browser opens. No installation, ever. (Port 8420 and explicit `127.0.0.1` chosen per dev_projects port/localhost history.)

### 3.2 Tabs

**Search**
- Search box + filter chips:
  - **Type:** Chat/Text (GGUF · MLX) | Image & Video (ComfyUI)
  - **Company:** Qwen, Meta, Google, Mistral, DeepSeek, Microsoft, OpenAI, Unsloth + free-text publisher
  - **Capability (text):** Vision · Thinking/Reasoning · Agentic/Tool-use · Coding · General chat
  - **Capability (image/video):** Image generation · Video generation · LoRA · Upscaler
  - **Size (parameters):** ≤4B · 7–9B · 12–15B · 20–35B · 70B+ · MoE (own badge + filter)
  - **Quantization:** Q4 · Q5 · Q6 · Q8 · F16 · MLX 4-bit/8-bit — doubles as a persistent "preferred quantization" (pre-highlights the matching file in detail view) and an optional hard filter (when on, detail views show only matching files; models lacking that quant are dimmed in results, not hidden)
  - **Sort:** Most downloaded · Trending · Newest
- Result cards: model name, company, download count, likes, last updated, capability + MoE badges.
- Model detail view:
  - Plain-language description; context window; release date; license; MoE explanation with active-parameter count (e.g. "30B-A3B = 30B total, 3B active — runs like a much smaller model").
  - File list per variant (GGUF quants / MLX 4-bit-8-bit / safetensors) with exact sizes.
  - **"Fits your Mac" badge** per file: green (runs comfortably) / orange (tight, slow) / red (won't fit), computed from detected Mac RAM vs file size.
  - Free-space check against destination before enabling Download; warning if it won't fit.
  - Gated models: clear "requires a Hugging Face account" notice instead of a download button.

**Downloads**
- Queue, one active download at a time (rest wait). Per item: progress bar, speed, ETA, Pause / Resume / Cancel.
- Survives app restart; interrupted items shown paused and resumable.

**Library**
- Reads the destination's actual folders (no own database) each time it's shown — always truthful.
- Per model: name, format, quant, size on disk, download date; Reveal in Finder; Delete (confirmation dialog states file name + size; nothing deleted silently).
- Header: total space used by models + free space on the destination drive.
- Text models and ComfyUI models shown as separate sections.
- Destination drive not connected → clear message, not an empty list.

**Settings**
- **Choose folder…** → native macOS folder dialog (via `osascript`, same pattern as Markitdown's `/api/pick-folder`).
- Current destination always visible in the app header; recent destinations quick-switch list.
- Preferred quantization; light/dark theme (persisted).

### 3.3 Folder layout on the destination

```
<destination>/Models/
├── <Company>/<Model-Name>/<file.gguf|mlx files>     ← text models (LM Studio-compatible layout)
└── comfyui/
    ├── checkpoints/   ← diffusion checkpoints
    ├── loras/
    ├── vae/
    └── upscale_models/
```

Passively compatible: pointing LM Studio's models folder or ComfyUI's extra-model-paths at these folders makes downloads appear there automatically. The app never edits those apps' settings.

## 4. Architecture

```
model-dock/
├── start.command        # launcher: checks port, starts server, opens browser
├── server/
│   ├── app.py           # stdlib ThreadingHTTPServer: static files + JSON API
│   ├── hf_api.py        # Hugging Face catalog client (urllib): search, model info, file trees
│   ├── downloader.py    # background download thread: .part files, Range resume, verify, rename
│   ├── catalog.py       # pure logic: quant parsing, param-size/MoE detection, capability tags,
│   │                    #   filename sanitizing, ComfyUI subfolder routing, fits-your-Mac calc
│   ├── store.py         # settings + queue persistence (single JSON file in app folder)
│   └── library.py       # scans destination folders; disk free/used via os.statvfs
├── web/                 # vanilla HTML/CSS/JS, no build step, CAIO light+dark theme
├── tests/               # unittest suite for catalog.py + downloader byte-math (stdlib only)
└── SPEC.md
```

- **Zero dependencies:** standard library only (`http.server`, `urllib`, `threading`, `json`, `os`). Runs on macOS stock Python 3.9.
- **HF endpoints used:** `GET /api/models` (search: `search`, `author`, `filter`/tags, `pipeline_tag`, `sort`), `GET /api/models/{id}` (card metadata), `GET /api/models/{id}/tree/main` (files + sizes + checksums), `https://huggingface.co/{id}/resolve/main/{file}` (download, supports Range).
- **Capability filters mapping:** Vision → `pipeline_tag=image-text-to-text` / vision tags; Thinking → reasoning/thinking tags + name heuristics (R1, QwQ, "thinking"); Agentic → tool-use/function-calling tags; Image gen → `text-to-image`; Video gen → `text-to-video` / video tags; LoRA → lora tag; Upscaler → upscaler tags. Heuristics live in `catalog.py` where they're unit-testable and easy to extend.
- **Progress:** frontend polls `GET /api/downloads` once per second (no websockets/SSE needed).
- **RAM detection:** `sysctl hw.memsize` once at startup.
- **Fits-your-Mac rule:** file size vs installed RAM — green ≤ 60% of RAM, orange 60–85%, red > 85%. Stated in the UI as guidance, not a guarantee.

## 5. Download engine

1. Pre-check: free space on destination ≥ file size + 5% margin; otherwise refuse with message.
2. Write to `<final-name>.part` in the final folder.
3. Interruption (sleep, network, unplugged drive, app quit) → `.part` retained; resume issues HTTP Range request from current byte.
4. On completion: verify size matches the catalog's; verify checksum when HF provides one (LFS SHA-256); then atomic rename `.part` → final name. A broken file can never carry a real model's name.
5. Auto-retry on transient network errors with increasing backoff; after repeated failures the item pauses resumably with a plain-language message.
6. During download, destination free space is monitored; drive-full or drive-gone pauses cleanly with a clear message.

## 6. Persistence

One JSON file, `model-dock/data/state.json`: settings (destination, recents, preferred quant, theme) + download queue (including paused/interrupted items). No database. The Library is always computed from the filesystem, never stored.

## 7. Error handling summary

| Situation | Behavior |
|---|---|
| Destination drive not connected | Header warning; downloads pause; Library explains; auto-recovers when reconnected |
| Drive full / would not fit | Pre-check refuses start; mid-download pause with message |
| No internet / HF down | Search shows plain message; downloads auto-retry then pause resumably |
| Gated model | Notice before download ("requires Hugging Face account"), never a cryptic failure |
| App closed mid-download | `.part` retained; reopening shows paused, resumable item |
| Half-downloaded file | Impossible to mistake for complete: `.part` suffix until verified |

## 8. Testing

- `tests/` — Python `unittest`, runnable with stock macOS Python, no installs: quant parsing ("Q4_K_M", "Q8_0", MLX bits), parameter-size + MoE detection ("30B-A3B", "8x7B"), capability-tag mapping, resume byte-math, filename/folder sanitizing, ComfyUI subfolder routing, fits-your-Mac thresholds.
- End-to-end verification before handoff: run the app, search, download a small real model (~100 MB) to a test destination, interrupt + resume it, verify library view, switch destinations, delete flow.

## 9. Out of scope (v1)

- Hugging Face account/token (gated models) — UI shows notice; token field is a known v2 candidate.
- Auto-configuring LM Studio / Ollama / ComfyUI settings; Ollama import automation.
- Running/chatting with models.
- Windows/Linux support (Mac-only launcher; server code is portable in principle).

## 10. Naming

Working name **ModelDock**. Rename is a find-replace in UI strings; folder name `model-dock/` stays unless Stefanos asks otherwise.
