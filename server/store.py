"""Single-JSON-file persistence for settings and the download queue."""
import json
import os
import threading

DEFAULT_SETTINGS = {"destination": "", "recent_destinations": [],
                    "preferred_quant": "Q4", "theme": "dark",
                    "ram_override_gb": 0,  # 0 = use this Mac's detected RAM
                    "hf_token": ""}


class Store:
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()
        self.data = {"settings": dict(DEFAULT_SETTINGS), "queue": [], "watchlist": [],
                     "searches": {"recent": [], "saved": []}}
        try:
            with open(path) as f:
                loaded = json.load(f)
            self.data["queue"] = loaded.get("queue", [])
            self.data["watchlist"] = loaded.get("watchlist", [])
            self.data["searches"] = loaded.get("searches", {"recent": [], "saved": []})
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
