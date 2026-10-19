#!/usr/bin/env python3
"""Headliners — unified reviewer server.

Serves ONE entry page (theater picker) that links into each venue's
individual reviewer. This replaces running the two venues on separate ports:

    python3 serve.py [port]           # default 8050

Routes:
    /                  -> picker (viewer/index.html)
    /independent/      -> The Independent reviewer   (independent/)
    /castro/           -> The Castro reviewer        (castro/)
    /fillmore/         -> The Fillmore reviewer      (fillmore/)
    /<venue>/shows.json, /<venue>/<file>  (static)

Run this instead of the per-venue serve.py scripts (those still work, on
8050/8051, if you want them standalone).
"""
import os, sys, json, http.server, socketserver, urllib.parse, webbrowser, threading

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8050

VENUES = {
    "independent": {"name": "The Independent", "city": "San Francisco, CA",
                    "venue_dir": os.path.join(ROOT, "independent")},
    "castro":      {"name": "The Castro Theatre", "city": "San Francisco, CA",
                    "venue_dir": os.path.join(ROOT, "castro")},
    "fillmore":    {"name": "The Fillmore", "city": "San Francisco, CA",
                    "venue_dir": os.path.join(ROOT, "fillmore")},
    "gamh":        {"name": "Great American Music Hall", "city": "San Francisco, CA",
                    "venue_dir": os.path.join(ROOT, "gamh")},
    "regency":     {"name": "The Regency Ballroom", "city": "San Francisco, CA",
                    "venue_dir": os.path.join(ROOT, "regency")},
    "augusthall":  {"name": "August Hall", "city": "San Francisco, CA",
                    "venue_dir": os.path.join(ROOT, "augusthall")},
    "warfield":    {"name": "The Warfield Theatre", "city": "San Francisco, CA",
                    "venue_dir": os.path.join(ROOT, "warfield")},
    "cafedunord":  {"name": "Cafe du Nord", "city": "San Francisco, CA",
                    "venue_dir": os.path.join(ROOT, "cafedunord")},
    "foxoakland":  {"name": "Fox Theater", "city": "Oakland, CA",
                    "venue_dir": os.path.join(ROOT, "foxoakland")},
    "greek":       {"name": "Greek Theatre", "city": "Berkeley, CA",
                    "venue_dir": os.path.join(ROOT, "greek")},
    "brickandmortar": {"name": "Brick & Mortar", "city": "San Francisco, CA",
                        "venue_dir": os.path.join(ROOT, "brickandmortar")},
    "frost":       {"name": "Frost Amphitheater", "city": "Stanford, CA",
                    "venue_dir": os.path.join(ROOT, "frost")},
}

def venue_pills(key, data):
    """Human stat pills per venue, derived from its data/shows.json."""
    pills = []
    st = data.get("stats") or {}
    et = st.get("event_types")
    if et:  # category breakdown (e.g. Castro: music/film/comedy/other)
        for cat in ("music", "film", "comedy", "other"):
            if et.get(cat):
                pills.append(f"{cat} <b>{et[cat]}</b>")
    am = st.get("apple_music")
    if am:  # Apple Music match breakdown (e.g. Independent)
        pills.append(f"Apple Music <b>{am.get('exact', 0)}</b> exact / {am.get('close', 0)} close")
        if am.get("needs_review"):
            pills.append(f"<b>{am['needs_review']}</b> needs review")
    return pills


def build_picker():
    tpl = open(os.path.join(ROOT, "viewer", "index.html")).read()
    venues = []
    for key, v in VENUES.items():
        path = os.path.join(v["venue_dir"], "data", "shows.json")
        entry = {"key": key, "name": v["name"], "city": v["city"],
                 "path": f"/{key}/", "count": 0, "stat_pills": []}
        try:
            data = json.load(open(path))
            entry["count"] = data.get("count", len(data.get("shows", [])))
            entry["stat_pills"] = venue_pills(key, data)
        except (OSError, json.JSONDecodeError) as e:
            entry["stat_pills"] = [f"no data ({e.__class__.__name__})"]
        venues.append(entry)
    return tpl.replace("/*__VENUES_PAYLOAD__*/", "window.VENUES=" + json.dumps(venues) + ";")


def venue_viewer(key):
    # ONE shared viewer for every venue (common/); the venue's JSON is
    # injected, and the page adapts to whatever fields that venue carries.
    tpl = open(os.path.join(ROOT, "common", "viewer", "index.html")).read()
    data = open(os.path.join(VENUES[key]["venue_dir"], "data", "shows.json")).read()
    return tpl.replace("/*__SHOWS_PAYLOAD__*/", "window.SHOWS=" + data + ";")


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def _send(self, body, ctype, status=200):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        # Block traversal: super() (SimpleHTTPRequestHandler) does not
        # collapse "..", and we don't want /independent/../.git to work.
        if ".." in p.split("/") or ".git" in p.split("/"):
            return self._send("forbidden", "text/plain", 403)
        if p == "/":
            return self._send(build_picker(), "text/html; charset=utf-8")
        # /<venue>/...
        parts = p.strip("/").split("/")
        if parts and parts[0] in VENUES:
            v = VENUES[parts[0]]
            rest = "/".join(parts[1:])
            if rest in ("", "index.html"):
                try:
                    return self._send(venue_viewer(parts[0]), "text/html; charset=utf-8")
                except OSError as e:
                    return self._send(f"<h1>no data yet for {parts[0]}</h1><p>{e}</p>",
                                      "text/html; charset=utf-8", 503)
            if rest == "shows.json":
                try:
                    return self._send(open(os.path.join(v["venue_dir"], "data", "shows.json"), "rb").read(),
                                      "application/json")
                except OSError as e:
                    return self._send(f'{{"error":"{e}"}}', "application/json", 503)
            # static file under the venue (viewer assets, etc.)
            fp = os.path.realpath(os.path.join(v["venue_dir"], rest))
            if not fp.startswith(os.path.realpath(v["venue_dir"])) or not os.path.isfile(fp):
                return self._send("not found", "text/plain", 404)
            ct = "text/html; charset=utf-8" if fp.endswith(".html") else self.guess_type(fp)
            return self._send(open(fp, "rb").read(), ct)
        return super().do_GET()

    def log_message(self, format: str, *args: object) -> None:
        pass


if __name__ == "__main__":
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), H) as httpd:
        url = f"http://127.0.0.1:{PORT}/"
        print(f"Headliners reviewer running at {url}  (Ctrl+C to stop)")
        for key, v in VENUES.items():
            print(f"  {url}{key}/  {v['name']}")
        try:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        except Exception:
            pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")
