# ModelDock, by CAIO Group

Download AI models from Hugging Face straight to any drive you choose. Built for keeping a large model collection on an external SSD instead of filling your Mac's internal disk.

**Zero installation.** ModelDock runs on what macOS already ships. No Python installs, no packages, no accounts.

## Start

Double-click **`start.command`**. Your browser opens at `http://127.0.0.1:8420`. Close the Terminal window to stop the app.

## First-time setup (once)

1. Open the **Settings** tab.
2. Click **Choose folder…** and pick a folder on your external SSD (e.g. `T7/AI-Models`).
3. Done. The header always shows the current destination and its free space. Previous destinations appear as one-click chips, so switching between drives takes one click.

## The four tabs

- **Search**: search Hugging Face with filters. Type (Chat GGUF, Chat MLX, Image & Video for ComfyUI; select several at once to see merged results with a format badge per model), company, capability (Vision, Thinking, Agentic, Coding, MoE, or Image/Video/LoRA/Upscaler; combine as many as you like), parameter size (≤4B … 70B+), and sort. Click a model to expand its details in place: description, Hugging Face link, and downloadable versions with exact sizes. The colored dot tells you how each file suits your chosen memory size: green runs comfortably, orange is tight, red won't fit. Your preferred quantization (Settings) is pre-highlighted, and versions you already own show "In library ✓".
- **Downloads**: progress, speed, time remaining, Pause / Resume / Cancel. Downloads run one at a time. Interruptions (sleep, network loss, unplugged drive, quitting the app) lose nothing: resume continues from the exact byte where it stopped. Refreshing or closing the browser page never interrupts a download; it runs in the app itself.
- **Library**: everything on the current destination, with sizes, free space, **Reveal in Finder**, and **Delete** (always to the Trash, never permanent).
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

- Gated models (Meta Llama, Google Gemma, Flux dev) need a Hugging Face account. ModelDock shows a clear notice instead of a broken download. Everything open (Qwen, DeepSeek, Mistral, community GGUFs, SDXL ecosystem…) works without any account.
- A file is only given its real name after its size, and when available its checksum, verify. A half-downloaded file can never be mistaken for a working model (it stays `.part`).
- Downloading a version you already have is refused with a clear message. Delete it in the Library first if you really want a fresh copy.
- The Library reads the actual drive every time. Files you move or delete in Finder are reflected immediately; there is no hidden database to go stale.

## Troubleshooting

| Problem | Fix |
|---|---|
| Browser shows nothing | Is the Terminal window still open? Double-click `start.command` again. If the app is already running it just reopens the browser. |
| "Drive not connected" in the header | Plug the SSD in; downloads resume, the Library comes back. |
| A download shows an error | Click Resume. It continues where it stopped. Persistent errors state the reason in plain language. |

## For maintenance sessions

- Tests: `/usr/bin/python3 -m unittest discover -s tests -v` (42 tests, no installs).
- Spec: `SPEC.md` · Plan: `specs/2026-07-30-modeldock-implementation-plan.md`.
- State: `data/state.json` (settings + download queue). Deleting it resets settings; it never contains models.
