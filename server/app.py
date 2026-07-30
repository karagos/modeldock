"""ModelDock server. Zero dependencies: macOS stock Python 3.9 stdlib only."""
import json
import os
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = "127.0.0.1", 8420
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
MIME = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
        ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet terminal
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        rel = path.lstrip("/") or "index.html"
        full = os.path.realpath(os.path.join(WEB, rel))
        if not full.startswith(os.path.realpath(WEB)) or not os.path.isfile(full):
            self.send_error(404)
            return
        ext = os.path.splitext(full)[1]
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/ping":
            self._json({"ok": True})
        else:
            self._static(self.path.split("?")[0])


def main():
    url = "http://%s:%s" % (HOST, PORT)
    want_browser = not os.environ.get("MODELDOCK_NO_BROWSER")
    probe = socket.socket()
    if probe.connect_ex((HOST, PORT)) == 0:  # already running
        probe.close()
        print("ModelDock is already running — opening browser.")
        if want_browser:
            subprocess.run(["open", url])
        return
    probe.close()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    if want_browser:
        threading.Timer(0.6, lambda: subprocess.run(["open", url])).start()
    print("ModelDock running at %s — close this window to stop." % url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
