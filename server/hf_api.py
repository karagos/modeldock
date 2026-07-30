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
