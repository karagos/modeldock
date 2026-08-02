"""Hugging Face Hub API client — urllib only, injectable opener for tests."""
import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://huggingface.co"
HEADERS = {"User-Agent": "ModelDock/1.0 (local; CAIO)"}
TIMEOUT = 25
_TOKEN = ""


def set_token(token):
    """Optional Hugging Face access token (unlocks gated models)."""
    global _TOKEN
    _TOKEN = (token or "").strip()


def _headers():
    h = dict(HEADERS)
    if _TOKEN:
        h["Authorization"] = "Bearer " + _TOKEN
    return h
MAX_PAGES = 20


def _get(url, opener=None):
    """Return (parsed JSON body, Link header string)."""
    req = urllib.request.Request(url, headers=_headers())
    op = opener or urllib.request.urlopen
    with op(req, timeout=TIMEOUT) as r:
        link = r.headers.get("Link", "") if hasattr(r, "headers") else ""
        return json.loads(r.read().decode("utf-8")), link or ""


def _get_json(url, opener=None):
    return _get(url, opener)[0]


def _next_url(link_header):
    for part in link_header.split(","):
        if 'rel="next"' in part:
            return part.split(";")[0].strip().strip("<>")
    return None


def search_models(params, opener=None):
    url = "%s/api/models?%s" % (BASE, urllib.parse.urlencode(params))
    return _get_json(url, opener)


def model_info(model_id, opener=None):
    return _get_json("%s/api/models/%s" % (BASE, model_id), opener)


def model_tree(model_id, opener=None):
    """Full file list — follows the Hub's Link-header pagination."""
    url = "%s/api/models/%s/tree/main?recursive=true" % (BASE, model_id)
    files = []
    for _ in range(MAX_PAGES):
        raw, link = _get(url, opener)
        for e in raw:
            if e.get("type") != "file":
                continue
            lfs = e.get("lfs") or {}
            files.append({"path": e["path"], "size": lfs.get("size", e.get("size", 0)),
                          "sha256": lfs.get("oid")})
        url = _next_url(link)
        if not url:
            break
    return files


def model_readme(model_id, opener=None):
    """Raw README markdown, or '' when unavailable (gated, missing, network)."""
    req = urllib.request.Request("%s/%s/raw/main/README.md" % (BASE, model_id),
                                 headers=_headers())
    op = opener or urllib.request.urlopen
    try:
        with op(req, timeout=10) as r:
            return r.read(200000).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return ""


def file_url(model_id, path):
    return "%s/%s/resolve/main/%s" % (BASE, model_id, urllib.parse.quote(path))
