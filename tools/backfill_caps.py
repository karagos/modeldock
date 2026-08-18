#!/usr/bin/env python3
"""Backfill Hugging Face tags into the manifests of models already on disk.

ModelDock now records the Hub's tags at download time, so capabilities come from
the model rather than from guessing at its folder name. Anything downloaded
before that change has no tags recorded. This walks the library, asks the Hub
about each model once, and writes the answer into its .modeldock.json.

Run once:  /usr/bin/python3 tools/backfill_caps.py
Dry run:   /usr/bin/python3 tools/backfill_caps.py --dry-run
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

import catalog                                    # noqa: E402
import hf_api                                     # noqa: E402
import library                                    # noqa: E402
from store import Store                           # noqa: E402

DRY = "--dry-run" in sys.argv


def destination():
    st = Store(os.path.join(ROOT, "data", "state.json"))
    hf_api.set_token(st.data["settings"].get("hf_token", ""))
    return st.data["settings"]["destination"]


def write_tags(folder, model_id, tags):
    path = os.path.join(folder, library.MANIFEST)
    data = {}
    try:
        with io.open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        pass
    data["tags"] = list(tags)
    data.setdefault("model_id", model_id)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)


def main():
    dest = destination()
    if not dest or not os.path.isdir(dest):
        sys.exit("No destination set, or the drive is not mounted.")

    scan = library.scan(dest)
    if not scan["connected"]:
        sys.exit("Destination not reachable.")

    updated, unchanged, missing = [], [], []
    for m in scan["text_models"]:
        model_id = "%s/%s" % (m["company"], m["model"])
        if library.manifest_tags(m["path"]):
            unchanged.append(model_id)
            continue
        try:
            tags = hf_api.model_info(model_id).get("tags", []) or []
        except Exception as e:                     # 404, gated, offline
            missing.append((model_id, type(e).__name__))
            continue
        if not tags:
            missing.append((model_id, "no tags on the Hub"))
            continue
        caps = sorted(catalog.detect_capabilities(model_id, tags))
        if not DRY:
            write_tags(m["path"], model_id, tags)
        updated.append((model_id, m["caps"], caps))

    prefix = "DRY RUN: " if DRY else ""
    print("%sBackfill over %d models" % (prefix, len(scan["text_models"])))
    print()
    if updated:
        print("Updated (%d):" % len(updated))
        for mid, was, now in updated:
            gained = sorted(set(now) - set(was))
            note = "  +%s" % ", ".join(gained) if gained else "  (no capability change)"
            print("  %-70s %s -> %s%s" % (mid, was or "[]", now or "[]", note))
        print()
    if unchanged:
        print("Already had tags (%d): %s" % (len(unchanged), ", ".join(unchanged)))
        print()
    if missing:
        print("Could not resolve (%d), left as-is:" % len(missing))
        for mid, why in missing:
            print("  %-70s %s" % (mid, why))


if __name__ == "__main__":
    main()
