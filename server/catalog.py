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
