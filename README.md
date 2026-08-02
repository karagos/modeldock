# ModelDock, by CAIO Group

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-f5c518)](LICENSE)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-000000?logo=apple&logoColor=white)](#start)
[![Dependencies: zero](https://img.shields.io/badge/Dependencies-zero-2e7a52)](#start)
[![Powered by Hugging Face](https://img.shields.io/badge/Powered%20by-Hugging%20Face-FFD21E?logo=huggingface&logoColor=black)](https://huggingface.co)
[![Made by CAIO Group](https://img.shields.io/badge/Made%20by-CAIO%20Group-D97757)](https://wearecaio.com)
[![GitHub stars](https://img.shields.io/github/stars/karagos/modeldock?style=social)](https://github.com/karagos/modeldock)

</div>

Download AI models from Hugging Face straight to any drive you choose. Built for keeping a large model collection on an external SSD instead of filling your Mac's internal disk.

**Zero installation.** ModelDock runs on what macOS already ships. No Python installs, no packages, no accounts.

## Start

Double-click **`start.command`**. Your browser opens at `http://127.0.0.1:8420`. Close the Terminal window to stop the app.

## First-time setup (once)

1. Open the **Settings** tab.
2. Click **Choose folder…** and pick a folder on your external SSD (e.g. `T7/AI-Models`).
3. Done. The header always shows the current destination and its free space. Previous destinations appear as one-click chips, so switching between drives takes one click.

## The four tabs

- **Search**: opens as a discovery feed (your Watchlist, Trending now, Fresh from the labs, Most downloaded) until you type. Star any model to watch it without downloading. Search Hugging Face with filters. Type (Chat GGUF, Chat MLX, Image & Video for ComfyUI; select several at once to see merged results with a format badge per model), company (major labs plus a dedicated Quantizers row: Unsloth, bartowski, mradermacher, LM Studio, MLX Community, TheBloke, DavidAU), capability (Vision, Thinking, Agentic, Coding, MoE, or Image/Video/LoRA/Upscaler; combine as many as you like), domain for specialist models (Medical, Legal, Finance, Math, Science, Translation, Roleplay & writing), parameter size (≤4B SLM … 70B+), sort, and a Period control for Most downloaded: last 30 days (Hugging Face's native counter), all time (true totals, re-ranked by ModelDock), or only models released in the last 6 or 12 months. Click a model to expand its details in place: description, Hugging Face link, and downloadable versions with exact sizes. The colored dot tells you how each file suits your chosen memory size: green runs comfortably, orange is tight, red won't fit. Your preferred quantization (Settings) is pre-highlighted, and versions you already own show "In library ✓". A license pill translates each model's license to plain language (Commercial use OK / Non-commercial / Custom).
- **Downloads**: progress, speed, time remaining, Pause / Resume / Cancel. Downloads run one at a time. Interruptions (sleep, network loss, unplugged drive, quitting the app) lose nothing: resume continues from the exact byte where it stopped. Refreshing or closing the browser page never interrupts a download; it runs in the app itself.
- **Library**: everything on the current destination with capability badges, fits-dots, sort and filter, **Verify** (re-checks a model against its recorded checksums), **Copy as Markdown** (paste-ready table for docs and posts), **Reveal in Finder**, and **Delete** (always to the Trash, never permanent).
- **Settings**: destination, preferred quantization (Q2 … BF16 and MLX 3/4/6/8-bit), theme, the color legend, and **Memory (RAM)**. The fits-badge normally uses this Mac's detected memory, but you can pick any size (8 GB to 512 GB) to plan downloads for a different machine, for example before buying a new Mac.

## Where files go

```
YourSSD/Models/
├── llm/                                ← chat models (LLMs)
│   └── Qwen/Qwen3-14B-GGUF/…gguf
└── comfyui/                            ← diffusion models (image & video)
    ├── checkpoints/  loras/  vae/  upscale_models/
```

- **LM Studio:** Settings → Models folder → point it at `YourSSD/Models/llm`. Everything ModelDock downloads appears automatically.
- **Ollama:** import a GGUF once with `ollama create <name> -f Modelfile` where the Modelfile contains `FROM /path/to/model.gguf`.
- **ComfyUI Desktop:** add `YourSSD/Models/comfyui` to extra model paths.

## Good to know

- Gated models (Meta Llama, Google Gemma, Flux dev) need a free Hugging Face account: paste a token in Settings and accept the model's license once on its page. Everything open (Qwen, DeepSeek, Mistral, community GGUFs, SDXL ecosystem…) works without any account.
- Every byte of every download is checksummed while it streams in, at any file size. A file is only given its real name after size and checksum verify, and the file is forced to physical disk first, so a power cut can never fake a "finished" model. Connection drops are waited out and resumed from the exact byte; a crash mid-download resumes automatically at next launch (with a safety margin re-downloaded). Checksums are recorded next to the files, so the Library's Verify button can re-prove integrity months later.
- Downloading a version you already have is refused with a clear message. Delete it in the Library first if you really want a fresh copy.
- The Library reads the actual drive every time. Files you move or delete in Finder are reflected immediately; there is no hidden database to go stale.

## Troubleshooting

| Problem | Fix |
|---|---|
| Browser shows nothing | Is the Terminal window still open? Double-click `start.command` again. If the app is already running it just reopens the browser. |
| "Drive not connected" in the header | Plug the SSD in; downloads resume, the Library comes back. |
| A download shows an error | Click Resume. It continues where it stopped. Persistent errors state the reason in plain language. |

## For maintenance sessions

- Tests: `/usr/bin/python3 -m unittest discover -s tests -v` (56 tests, no installs).
- Spec: `SPEC.md` · Plan: `specs/2026-07-30-modeldock-implementation-plan.md`.
- State: `data/state.json` (settings + download queue). Deleting it resets settings; it never contains models.
