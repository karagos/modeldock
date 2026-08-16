"""Pure logic for ModelDock: parsing, filtering, routing. No I/O, no network."""
import re

QUANT_RE = re.compile(r"(?<![A-Za-z0-9])(I?Q\d(?:_[A-Z0-9]+)*|F16|F32|BF16)(?![A-Za-z0-9])", re.I)


def parse_quant(name):
    m = QUANT_RE.search(name)
    if m:
        return m.group(1).upper()
    low = name.lower()
    for bits in ("8", "6", "4", "3"):
        if bits + "bit" in low or bits + "-bit" in low:
            return "MLX-%sBIT" % bits
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


TEXT_CAPS = {"vision", "thinking", "agentic", "coding", "moe"}
IMAGE_CAPS = {"image-gen", "video-gen", "lora", "upscaler"}


def merge_cards(lists, sort):
    """Merge per-type search results: dedupe by id; downloads/newest re-sort,
    trending preserves each list's ranking by interleaving."""
    if sort == "trending":
        merged = []
        for i in range(max((len(l) for l in lists), default=0)):
            for l in lists:
                if i < len(l):
                    merged.append(l[i])
    else:
        merged = [m for l in lists for m in l]
    seen, out = set(), []
    for m in merged:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        out.append(m)
    if sort == "downloads":
        out.sort(key=lambda m: m.get("downloads", 0), reverse=True)
    elif sort == "newest":
        out.sort(key=lambda m: m.get("created") or m.get("updated", ""), reverse=True)
    return out


DOMAIN_SEARCH = {"medical": "medical", "legal": "law", "finance": "finance",
                 "math": "math", "science": "science", "translation": "translation",
                 "roleplay": "roleplay"}

SORT_MAP = {"downloads": "downloads", "trending": "trendingScore", "newest": "createdAt"}
CAP_SEARCH_EXTRA = {"thinking": "reasoning", "coding": "coder", "agentic": "tool", "upscaler": "upscale"}
CAP_PIPELINE = {"vision": "image-text-to-text", "image-gen": "text-to-image", "video-gen": "text-to-video"}


def build_search_params(q="", mtype="gguf", company="", capabilities=(), sort="downloads", limit=30, domain=""):
    """Capabilities combine: search terms accumulate, vision sets the pipeline tag.
    'moe' is intentionally NOT a query param — it's a post-fetch filter."""
    caps = set(capabilities)
    p = {"limit": str(limit), "sort": SORT_MAP.get(sort, "downloads"), "direction": "-1", "full": "true"}
    search_terms = [q] if q else []
    for c in sorted(caps & set(CAP_SEARCH_EXTRA)):
        search_terms.append(CAP_SEARCH_EXTRA[c])
    if domain in DOMAIN_SEARCH:
        search_terms.append(DOMAIN_SEARCH[domain])
    if mtype == "gguf":
        p["filter"] = "gguf"
    elif mtype == "mlx":
        p["filter"] = "mlx"
    elif mtype == "image":
        pipe = next((c for c in ("image-gen", "video-gen") if c in caps), None)
        if "lora" in caps:
            p["filter"] = "lora"
        elif "upscaler" in caps:
            pass  # search term only
        else:
            p["pipeline_tag"] = CAP_PIPELINE.get(pipe, "text-to-image")
    if mtype != "image" and "vision" in caps:
        p["pipeline_tag"] = CAP_PIPELINE["vision"]
    if company:
        p["author"] = company
    if search_terms:
        p["search"] = " ".join(search_terms)
    return p


def readme_excerpt(markdown, limit=420):
    """First plain-language paragraph(s) of a model card, markdown noise stripped."""
    if not markdown:
        return ""
    text = re.sub(r"\A---\n.*?\n---\n", "", markdown, flags=re.S)  # YAML frontmatter
    text = re.sub(r"```.*?```", " ", text, flags=re.S)             # code blocks
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)              # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)           # links -> label
    text = re.sub(r"<[^>]+>", " ", text)                           # html tags
    lines = [l.strip() for l in text.splitlines()]
    prose = [l for l in lines
             if l and not l.startswith(("#", "|", ">", "-", "*", "="))]
    out = " ".join(prose)
    out = re.sub(r"[*_`]", "", out)
    out = re.sub(r"\s+", " ", out).strip()
    if len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return out


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


LICENSE_OPEN = {"apache-2.0", "mit", "bsd", "bsd-2-clause", "bsd-3-clause",
                "cc-by-4.0", "cc0-1.0", "unlicense", "isc", "artistic-2.0"}


def license_verdict(lic):
    """Plain-language license bucket for consultants: open / nc / custom / None."""
    if not lic:
        return None
    l = str(lic).lower().strip()
    if l in ("unknown", "n/a"):
        return None
    if l in LICENSE_OPEN:
        return {"level": "open", "text": "Commercial use OK"}
    parts = set(l.replace("_", "-").split("-"))
    if "nc" in parts or "non-commercial" in l or "research" in l:
        return {"level": "nc", "text": "Non-commercial only"}
    return {"level": "custom", "text": "Custom license, review terms"}


BROADEN = {
    "food": ["culinary", "recipe", "chef"], "culinary": ["recipe", "chef", "food"],
    "cooking": ["culinary", "recipe", "chef"], "recipe": ["culinary", "cooking", "chef"],
    "law": ["legal", "lawyer"], "legal": ["law", "lawyer"],
    "medicine": ["medical", "clinical", "health"], "medical": ["clinical", "health", "biomed"],
    "finance": ["financial", "trading", "economics"], "trading": ["finance", "stock"],
    "music": ["audio", "song"], "math": ["mathematics", "reasoning"],
    "coding": ["code", "programming"], "programming": ["code", "coder"],
    "story": ["roleplay", "fiction", "writing"], "writing": ["story", "creative"],
    "translation": ["multilingual", "translate"], "greek": ["hellenic", "el"],
    "astronomy": ["astro", "space"], "biology": ["bio", "genomics"],
    "chemistry": ["chem", "molecular"], "travel": ["tourism"],
    "sailing": ["nautical", "maritime"], "wine": ["sommelier", "vineyard"],
}


def broaden_terms(q, cap=3):
    """Sibling terms for a query, from a curated thesaurus. Never echoes the query."""
    toks = re.findall(r"[a-z]+", (q or "").lower())
    out = []
    for t in toks:
        for syn in BROADEN.get(t, []):
            if syn not in out and syn not in toks:
                out.append(syn)
    return out[:cap]


def parse_base_models(tags):
    """HF lineage tags: base_model:Org/Name (direct) or base_model:<rel>:Org/Name."""
    out = []
    for t in tags or []:
        if not t.startswith("base_model:"):
            continue
        rest = t.split(":", 1)[1]
        if ":" in rest and "/" in rest.split(":", 1)[1]:
            rel, target = rest.split(":", 1)
        else:
            rel, target = "base", rest
        if "/" in target:
            out.append({"rel": rel, "id": target})
    return out


def infer_mtype(tags):
    tl = [str(t).lower() for t in (tags or [])]
    if "gguf" in tl:
        return "gguf"
    if any("mlx" in t for t in tl):
        return "mlx"
    if any(t in ("text-to-image", "text-to-video", "diffusers") for t in tl):
        return "image"
    return "gguf"
