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
