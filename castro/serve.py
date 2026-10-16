#!/usr/bin/env python3
"""Serves the extraction review page for the Castro project.

Usage:
    python3 serve.py [port]            # default port 8051
    # opens http://127.0.0.1:8051

Reads ./data/shows.json and injects it into viewer/index.html as
window.SHOWS, so the page always reflects the latest extraction.
(Independent uses 8050.)
"""
import os, sys, json, http.server, socketserver, webbrowser, threading

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8051

def build_index():
    tpl = open(os.path.join(ROOT, "viewer", "index.html")).read()
    data = open(os.path.join(ROOT, "data", "shows.json")).read()
    return tpl.replace("/*__SHOWS_PAYLOAD__*/", "window.SHOWS=" + data + ";")

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = build_index().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/shows.json":
            body = open(os.path.join(ROOT, "data", "shows.json"), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()
    def log_message(self, *a): pass

if __name__ == "__main__":
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), H) as httpd:
        url = f"http://127.0.0.1:{PORT}/"
        print(f"Review server running at {url}  (Ctrl+C to stop)")
        try:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")
