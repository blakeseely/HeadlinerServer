"""venue_images.py — find, verify and store one representative photo per venue.

Stores <venue_id>.jpg in BOTH the pipeline venue folder and the data-repo
venue folder (what gets pushed to HeadlinerListings). Rules:
  - source priority: Wikimedia Commons first (free-licensed, so the feed repo
    may redistribute), then open-licensed web sources; never scrape a venue's
    own site or arbitrary blog photos.
  - minimum 750x750 pixels (both dimensions); any aspect ratio allowed.
  - must be converted to JPEG (transparency flattened on white).
  - the SUBJECT may be a stage mid-set — a venue's identity must be certain,
    the frame need not be an empty-room exterior.
  - a venue with no qualifying image gets NOTHING saved and appears in the
    report for manual review.

Usage (Pillow lives in .venv-images/ — create with
`python3 -m venv .venv-images && .venv-images/bin/pip install pillow`):
  .venv-images/bin/python common/venue_images.py find [--only a,b]
      # write proposals + a candidates report (Commons-only; ~1 min/venue)
  .venv-images/bin/python common/venue_images.py apply
      # download approved proposals, re-verify license + size, save jpgs
  .venv-images/bin/python common/venue_images.py audit
      # re-verify stored jpgs meet the rules

Approvals live in common/venue_images.json (committed):
  {"<venue_id>": {"file": "File:...", "approved": true, ...}}
`find` auto-proposes only venue-certain candidates (venue-named Commons
category, or geotag at the building + venue-named filename); everything else
appears in common/venue_images_report.md — set `file` (and optionally
`approved`) by hand, then run `apply`. `apply` re-verifies the license at
download time and writes a CREDITS.json attribution sidecar beside each jpg.
If Commons still throttles a run, raise the pacing floor:
VENUE_API_INTERVAL=2 ... (seconds between API calls; default 1.2).
"""

import argparse
import concurrent.futures
import io
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# KAGI_API_KEY lives in the repo-root .env (gitignored), the same place the
# rest of the pipeline keeps its secrets — load it without a shell wrapper.
_dotenv = os.path.join(ROOT, ".env")
if os.path.isfile(_dotenv):
    for _line in open(_dotenv):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k, _v)
from common import venues as venues_mod  # noqa: E402

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
UA = "HeadlinerListings-venue-image-tool/1.0 (contact: repo owner)"

MIN_PX = 750                 # required short-side minimum
TARGET_PX = 1200             # resize width/height cap when the original is huge
MAX_ORIGINAL_MB = 120        # download ceiling for originals (they get
                             # downscaled to TARGET_PX; show photos from
                             # modern DSLRs run 40-80 MB originals)

PROPOSALS_PATH = os.path.join(ROOT, "common", "venue_images.json")
REPORT_PATH = os.path.join(ROOT, "common", "venue_images_report.md")

# Manual override when the venue name alone is ambiguous (e.g. several "Fox").
FALLBACK_QUERY = {
    "foxoakland": "Fox Theater Oakland",
    "greek": "Greek Theatre Berkeley",
    "frost": "Frost Amphitheater Stanford",
    "bellyup": "Belly Up Tavern Solana Beach",
    "thesound": "The Sound (venue) Del Mar",
    "musicbox": "Music Box Tavern San Diego",
    "pappy": "Pappy and Harriet's Pioneertown Palace",
}

# Commons categories that are known to be exactly about the venue, where the
# name-category probe fails (ambiguous name, or Commons names the category
# differently). Curated, like the coordinates in venues.py.
STRONG_FALLBACK = {
    # Curated after manual verification (Nov 2026): each category contains
    # this exact venue's files and nothing misleading.
    "warfield": ["Warfield Theatre"],
    "paramount": ["Paramount Theatre (Seattle)"],
    "showboxsodo": ["Showbox SoDo"],
}

SKIP_FILE_PREFIXES = ("Map:", "Symbol:", "Logo:", "Coat of arms:")

# Kagi Search API (key in .env): web image search for venues Commons lacks.
# Rank 4 — below every Commons source; identity is judged by filename/page
# relevance to name+city, licensing by the human review pass (apply fetches
# full-size, the report records source page + license note).
KAGI_URL = "https://kagi.com/api/v1/search"
KAGI_KEY = os.environ.get("KAGI_API_KEY", "")


def _kagi_images(query, limit=10):
    """Web image results: [{image_url, page_url, title, width, height}]."""
    if not KAGI_KEY:
        return []
    body = json.dumps({"query": query, "workflow": "images",
                       "limit": limit}).encode()
    req = urllib.request.Request(
        KAGI_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {KAGI_KEY}",
                 "Content-Type": "application/json",
                 "User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(4 * (attempt + 1))
                continue
            return []
        except Exception:
            return []
    out = []
    for r in data.get("data", {}).get("image", []):
        im = r.get("image") or {}
        if im.get("url"):
            out.append({"image_url": im["url"], "page_url": r.get("url"),
                        "title": r.get("title") or "",
                        "width": im.get("width"), "height": im.get("height")})
    return out


def _probe_web_image(rec):
    """Download a web candidate and confirm it decodes at >= a real size.
    Returns {width,height,mime,bytes} or None. Never stores anything."""
    if not rec.get("image_url"):
        return None
    try:
        from PIL import Image
        raw = _fetch_image(rec["image_url"])
        if not raw or len(raw) > MAX_ORIGINAL_MB * 1024 * 1024:
            return None
        im = Image.open(io.BytesIO(raw))
        im.load()
        return {"width": im.width, "height": im.height,
                "mime": (im.format or "unknown").lower(), "bytes": len(raw)}
    except Exception:
        return None


def _fetch_image(url, timeout=90):
    """Bytes for an arbitrary web image URL."""
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/126.0 Safari/537.36"),
        "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


_rate_lock = threading.Lock()
_last_call = [0.0]
# Minimum spacing between Commons API calls. Commons throttles anonymous
# bursty traffic; if a run still gets throttled, re-run with a slower floor,
# e.g. VENUE_API_INTERVAL=2.
API_INTERVAL = float(os.environ.get("VENUE_API_INTERVAL", "1.2"))


def _api(params):
    global API_INTERVAL
    params = dict(params, action="query", format="json")
    # urlencode duplicates repeated keys (titles=...&titles=...), the form the
    # MediaWiki API expects for list-valued params.
    url = COMMONS_API + "?" + urllib.parse.urlencode(params, doseq=True)
    for attempt in range(5):
        # Paced globally: anonymous Commons calls get 429'd easily.
        with _rate_lock:
            wait = _last_call[0] + API_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last_call[0] = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", "replace")
            try:
                return json.loads(body)
            except ValueError:
                raise RuntimeError(f"non-JSON API reply: {body[:120]!r}")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            # Commons rate-limits anonymous bursty traffic ("too many
            # requests"), sometimes as a 4xx with a JSON error payload.
            throttled = e.code == 429 or "too many requests" in body.lower()
            if throttled and attempt < 4:
                delay = int(e.headers.get("Retry-After") or 0) or (5 * (attempt + 1))
                # A throttle signal means the window is hot: slow every
                # subsequent call, not just this one.
                with _rate_lock:
                    _last_call[0] = max(_last_call[0], time.monotonic())
                    API_INTERVAL = min(API_INTERVAL * 1.5, 6.0)
                time.sleep(delay)
                continue
            detail = body[:160] or str(e.reason)
            raise RuntimeError(f"API HTTP {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == 4:
                raise RuntimeError(f"API network error: {e}")
            time.sleep(3 * (attempt + 1))


def _search_files(query, limit=12):
    """Full-text File-namespace search, ranked by relevance. Noisy: it matches
    prose on description pages, so it is a last-resort source."""
    data = _api({"list": "search", "srsearch": query, "srnamespace": 6,
                 "srlimit": limit, "srprop": ""})
    return [hit["title"] for hit in data.get("query", {}).get("search", [])
            if hit.get("ns") == 6]


def _search_images(query, limit=16):
    """Commons' `queryimages` generator: image-oriented search with a ranking
    model tuned for finding photos of things — far more precise than the
    generic full-text search."""
    try:
        data = _api({"generator": "search", "gsrsearch": f"filetype:bitmap {query}",
                     "gsrnamespace": 6, "gsrlimit": limit,
                     "prop": "info"})
    except Exception:
        return []
    pages = data.get("query", {}).get("pages", {})
    ordered = sorted(pages.values(), key=lambda p: p.get("index", 999))
    return [p["title"] for p in ordered if p.get("ns") == 6]


def _category_members(cat, limit=30):
    data = _api({"list": "categorymembers", "cmtitle": "Category:" + cat,
                 "cmtype": "file", "cmlimit": limit})
    return [m["title"] for m in data.get("query", {}).get("categorymembers", [])]


def _category_exists(cat):
    """True when the category actually exists AND holds content. A red-link
    category page answers prop=info as if present, so existence is decided by
    an actual member listing (files or subcategories)."""
    try:
        data = _api({"list": "categorymembers", "cmtitle": "Category:" + cat,
                     "cmlimit": 1})
    except Exception:
        return False
    members = data.get("query", {}).get("categorymembers", [])
    return bool(members)


# Category-existence answers repeat across venues (e.g. "(San Francisco)"
# suffix probes); cache them process-wide, and drop a negative marker so the
# first search query is never skipped.
_cat_cache = {}
_cat_cache_lock = threading.Lock()


def _category_exists_cached(cat):
    with _cat_cache_lock:
        if cat in _cat_cache:
            return _cat_cache[cat]
    ok = _category_exists(cat)
    with _cat_cache_lock:
        _cat_cache[cat] = ok
    return ok


def _imageinfo(titles):
    """imageinfo for up to 20 titles per request -> {title: info}.

    NOT 50: Commons drops entire 50-title batches whose URL exceeds ~2 KB,
    returning an empty/partial reply while still answering HTTP 200. It also
    reports a wrong-case title as `missing`, so querying a title's .png/.jpg
    twin masks the real title."""
    out = {}
    titles = [t for t in dict.fromkeys(t for t in titles if t)]
    def fetch(batch):
        data = _api({"titles": batch, "prop": "imageinfo",
                     # "coordinates" is only valid on prop=coordinates — asking
                     # imageinfo for it made MediaWiki drop the whole property.
                     "iiprop": "url|size|mime|extmetadata",
                     "iiextmetadatafilter": "LicenseShortName|UsageByOtherProjects|Artist"})
        ok = 0
        for p in data.get("query", {}).get("pages", {}).values():
            ii = (p.get("imageinfo") or [None])[0]
            if ii and p.get("title"):
                out[p["title"]] = ii
                ok += 1
        # Commons answers 200-but-empty when the batch URL exceeds its
        # length budget (~50 long File: titles) — treat that as a chunk
        # failure and split, instead of silently losing the titles.
        return ok
    def robust(chunk):
        # One request per title: Commons mis-answers mixed batches — any
        # absent title (the format twins are usually absent) or any
        # ampersand/unicode title can make the WHOLE reply 200-but-empty,
        # silently destroying valid titles sitting next to it. Singles are
        # ~1.2 s each under the rate limiter; a few seconds per venue buys
        # correctness.
        for t in chunk:
            try:
                fetch([t])
            except Exception:
                pass
    for i in range(0, len(titles), 20):
        robust(titles[i:i + 20])
    return out


def _geo_of(titles):
    """{file title: primary geo} via prop=coordinates (an imageinfo iiprop
    value would be invalid there)."""
    out = {}
    titles = list(dict.fromkeys(t for t in titles if t))
    for i in range(0, len(titles), 20):
        try:
            data = _api({"titles": titles[i:i + 20], "prop": "coordinates",
                         "collimit": 1})
        except Exception:
            continue
        for p in data.get("query", {}).get("pages", {}).values():
            coords = p.get("coordinates") or []
            if coords and p.get("title"):
                out[p["title"]] = coords[0]
    return out


def _strip_markup(s):
    s = re.sub(r"{{([^|}]*)\|[^}]*}}", r"\1", s or "")
    s = re.sub(r"\{\{|\}\}", "", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def _categories_of(title):
    """Commons categories a File is a member of (maintenance cats excluded)."""
    try:
        data = _api({"prop": "categories", "titles": title, "cllimit": 50,
                     "clshow": "!hidden"})
    except Exception:
        return []
    out = []
    for p in data.get("query", {}).get("pages", {}).values():
        out += [c["title"].split(":", 1)[1] for c in p.get("categories", [])]
    return out




def _license(info):
    md = info.get("extmetadata") or {}
    return _strip_markup(md.get("LicenseShortName", {}).get("value", "")) or "unknown"




FREE_RE = re.compile(r"(cc (?:by|0)|cc-by|cc-pd|public domain|pd|public domain mark|"
                     r"gnu fdl|mit/x11)", re.I)
NONFREE_RE = re.compile(r"(fair use|non[- ]?free|all rights reserved|copyrighted)", re.I)


def _is_free(lic):
    return bool(FREE_RE.search(lic)) and not NONFREE_RE.search(lic)




def _image_title(name):
    """Commons File: title for a bare name; .jpg/.JPG/.jpeg kept as-is, other
    raster extensions -> .jpg (Commons stores one jpg per building photo)."""
    if not name.lower().startswith("file:"):
        name = "File:" + name
    base, ext = os.path.splitext(name)
    if ext.lower() in (".jpg", ".jpeg"):
        return name
    if ext.lower() in (".png", ".tiff", ".tif", ".webp", ".gif"):
        return base + ".jpg"
    return name + ".jpg"


def _crosswiki(info):
    md = info.get("extmetadata") or {}
    v = md.get("UsageByOtherProjects", {}).get("value", "")
    return bool(v) and "non-free" not in v.lower()


def _nearby_images(lat, lon, radius=300, limit=20):
    """Files geotagged within `radius` metres of the venue — strong evidence a
    photo depicts the building (or its immediate block)."""
    if lat is None or lon is None:
        return []
    try:
        data = _api({"list": "geosearch", "gscoord": f"{lat}|{lon}",
                     "gsradius": radius, "gslimit": limit, "gsprimary": "all"})
    except Exception:
        return []
    return [_image_title(g["title"]) for g in
            data.get("query", {}).get("geosearch", []) if g.get("ns") == 6]




def _strong_category(name, cat, geo_tokens, locality):
    """True when the category NAMES this venue at THIS place: every
    distinctive name token appears, AND the category carries either the city
    token or a metro locality token. Pure names with no locality anywhere
    ('Holocene', 'Warfield') are homonym bait — report-only, never rank 0."""
    ctoks = set(re.findall(r"[a-z0-9']+", cat.lower()))
    toks = _name_tokens(name)
    if not toks or not all(w in ctoks for w in toks):
        return False
    return locality in ctoks or bool(ctoks & geo_tokens)


# Commons categories that hold interiors/promo/unrelated media rather than
# building exteriors — a venue's image must be the building itself.
BAD_CAT_RE = re.compile(r"(interior|interiors|concerts? at|gigs? at|performances? at|"
                        r"posters?|flyers?|tickets?|setlists?|set lists?|maps?)", re.I)


def _refine_category(cat, queries):
    """A parent category (e.g. 'The Castros') can mix in venues of the same
    name elsewhere and non-building media. Keep only direct subcategories that
    look like this exact venue, and return them as extra member sources."""
    try:
        subs = _api({"list": "categorymembers", "cmtitle": "Category:" + cat,
                     "cmtype": "subcat", "cmlimit": 50})
    except Exception:
        return []
    names = [m["title"].split(":", 1)[1] for m in
             subs.get("query", {}).get("categorymembers", [])]
    keep = []
    for n in names:
        if BAD_CAT_RE.search(n):
            continue
        nlow = n.lower()
        if any(q.lower() in nlow for q in queries):
            keep.append(n)
        elif len(nlow) > 20 and nlow.startswith(cat.lower()[:20]):
            keep.append(n)  # long names starting with the venue name: "'X' (venue), San Diego"
    return keep


def _subcat_members(cats, limit=30):
    out = []
    for c in cats[:4]:
        out += _category_members(c, limit=limit)
    return out


def _name_tokens(name):
    stop = {"the", "hall", "theatre", "theater", "ballroom", "amphitheater",
            "auditorium", "center", "concerts", "by", "and"}
    return [w for w in re.findall(r"[a-z0-9']+", name.lower()) if w not in stop]


def _relevance(title, name):
    """Filename-match score, conservative: the full venue name as a phrase
    scores 1; otherwise every distinctive token (>=3 chars) must appear as
    its own word or the score caps at 0.5 — 'David Warfield' vs 'The Warfield
    Theatre' caps at 0.5 and can never auto-pass. Phrase matches still need
    geotag/category corroboration in the auto-propose rule (namesakes exist)."""
    t = re.sub(r"[_()]+", " ", title.lower())
    t = " " + re.sub(r"\s+", " ", re.sub(r"[^a-z0-9']+", " ", t)).strip() + " "
    nlow = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", name.lower())).strip()
    if " " + nlow + " " in t:
        return 1.0
    toks = _name_tokens(name)
    hits = sum(1 for w in toks if " " + w + " " in t)
    frac = hits / max(len(toks), 1)
    if any(len(w) >= 3 and " " + w + " " not in t for w in toks):
        return min(frac, 0.5)
    return frac


def _geo_close(info, meta):
    """True when the photo's geotag is within ~300 m of the venue. The
    auto-propose rule additionally requires the filename to name the venue,
    so a corner-lot street shot can't slip through on proximity alone."""
    coords = info.get("coordinates") or []
    lat, lon = meta.get("lat"), meta.get("lon")
    if not coords or lat is None or lon is None:
        return False
    c = coords[0]
    return abs(c.get("lat", 0) - lat) < 0.003 and abs(c.get("lon", 0) - lon) < 0.003


def candidates_for(venue_id, meta, query=None, limit=8, counts=None,
                   web_recs=None):
    """Ranked candidate File: titles with imageinfo for one venue.
    `counts` (optional dict) receives how many raw hits each source rank got;
    `web_recs` (optional dict) collects the web candidates by pseudo-title."""
    name = meta["name"]
    city = (meta.get("city") or "").split(",")[0]
    # Category probes carry a locality qualifier so the homonym categories
    # Commons loves ("Holocene" = the geological epoch, "Warfield" = a ball-
    # player, "The Independent" = a newspaper) cannot pass the name-token
    # test. A category like "The Castro Theatre" still passes exactly.
    locality = city.replace(" ", "_").lower()
    # Locality tokens from city/metro let a venue-named category or filename
    # carry the location instead of repeating the venue name.
    geo_tokens = set(re.findall(r"[a-z0-9']+",
                                f"{city} {meta.get('metro') or ''}".lower()))
    # Tokens too common to prove locality on their own (partial city names,
    # state fragments, generic words).
    geo_tokens -= {"san", "diego", "los", "angeles", "new", "york", "ca",
                   "or", "wa", "the", "of", "street", "hall", "music"}
    raw_counts = counts if counts is not None else {}
    queries = []
    if query:
        queries.append(query)
    if venue_id in FALLBACK_QUERY:
        queries.append(FALLBACK_QUERY[venue_id])
    city_q = city if city.lower() not in name.lower() else ""
    combined = f'"{name}" {city_q}'.strip()
    if combined not in queries:
        queries.append(combined)
    combined_short = f"{name} {city_q}".strip()
    if combined_short not in queries:
        queries.append(combined_short)

    # Source ranks (lower = stronger identity evidence):
    #  0 = file hosted under the Commons category that IS this venue
    #  1 = member of that category or its matching subcategories
    #  2 = geotagged within ~1 km of the building
    #  3 = Commons image search / generic full-text search (noisy)
    rank = {}

    def add(ts, r):
        for t in ts:
            if t.startswith(SKIP_FILE_PREFIXES):
                continue
            if t not in rank or r < rank[t]:
                rank[t] = r

    def add_files(ts, r):
        # Every raster gets its .jpg twin probed too: Commons building photos
        # are usually stored as .jpg while articles/categories reference the
        # .png name (and vice versa); dead titles simply return no imageinfo.
        norm = []
        for t in ts:
            if t.startswith(SKIP_FILE_PREFIXES):
                continue
            nt = t if t.startswith("File:") else _image_title(t)
            norm.append(nt)
            # Format twins: Commons stores each photo under one exact title,
            # and a category listing reports only that one, but article refs
            # and searches drift between .jpg/.png/.JPG; wrong-case/format
            # titles simply return no imageinfo, so twins cost nothing.
            if "." in nt:
                stem = nt.rsplit(".", 1)[0]
                for ext in (".jpg", ".png"):
                    twin = stem + ext
                    if twin != nt and twin not in norm:
                        norm.append(twin)
        add(norm, r)

    # Sources run concurrently; the shared _api limiter keeps it polite.
    probes = [name, f"{name} ({city})", f"{name} ({city.split(' ')[0]})",
              f"{name} (venue)", f"{name} (theatre)", f"{name} (music venue)"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        probe_f = {c: pool.submit(_category_exists_cached, c) for c in probes}
        geo_f = pool.submit(_nearby_images, meta.get("lat"), meta.get("lon"))
        img_f = pool.submit(_search_images, combined)
        txt_f = pool.submit(_search_files, combined_short)

        cat = next((c for c in probes if probe_f[c].result()), None)
        cats = []
        if cat:
            strong_cat = _strong_category(name, cat, geo_tokens, locality)
            try:
                cats = _refine_category(cat, queries) if strong_cat else []
            except Exception:
                cats = []
            # Files under a category that NAMES the venue: rank 0. A broader
            # parent category (e.g. "The Castros", "The Warfield" — which also
            # holds a baseball player) mixes subjects: it only feeds the
            # report (rank 3), so a bare name match can never auto-propose.
            add_files(_category_members(cat, limit=30), 0 if strong_cat else 3)
            if cats:
                add_files(_subcat_members(cats), 1)
        if venue_id in STRONG_FALLBACK:
            # Curated proposal-file categories for venues whose Commons
            # category is misnamed/ambiguous (never replaces the probes).
            for c in STRONG_FALLBACK[venue_id]:
                if _category_exists_cached(c):
                    add_files(_category_members(c, limit=30), 0)
        add(geo_f.result(), 2)
        # The searches dominate runtime (~1 min each) and exist for the human
        # review report; the strong sources above already drive auto-proposal.
        add_files(img_f.result(), 3)
        add_files(txt_f.result(), 3)
        # 4. Web image search (Kagi, if configured): fills venues Commons
        # cannot. Keyed by pseudo-title "web:<url>"; the real record lives in
        # web_recs and gets probed by _probe_web_image, which downloads the
        # image to confirm TRUE native dimensions (search engines' reported
        # sizes are often thumbnails) and a decodable image.
        if web_recs is not None:
            for r in _kagi_images(f'"{name}" {city} photo'):
                u = r["image_url"]
                if u.lower().split("?")[0].endswith((".svg", ".gif")):
                    continue
                key = "web:" + u
                if key not in rank:
                    rank[key] = 4
                    web_recs[key] = r

    order = sorted((t for t in rank if not t.startswith("web:")),
                   key=rank.get)[:70]
    web_order = sorted((t for t in rank if t.startswith("web:")),
                       key=rank.get)[:12]
    for r in rank.values():
        raw_counts[r] = raw_counts.get(r, 0) + 1
    info = _imageinfo(order)
    geos = _geo_of(order)
    for t, g in geos.items():
        if t in info:
            info[t]["coordinates"] = [g]
    web_info = {}
    for t in web_order:
        web_info[t] = _probe_web_image(web_recs.get(t, {}))
    rows = []
    for t in order + web_order:
        if t.startswith("web:"):
            w = web_info.get(t)
            if not w:
                continue
            rec = web_recs.get(t, {})
            title_txt = rec.get("title", "") + " " + (rec.get("page_url") or "")
            rows.append({
                "title": t,
                "cat": None,
                "rank": 4,
                "width": w["width"], "height": w["height"],
                "mime": w["mime"],
                "bytes": w["bytes"],
                "url": rec.get("image_url"),
                "page_url": rec.get("page_url"),
                "license": "REVIEW",   # licensing is a human judgment here
                "commons_usages": False,
                "geo": False,
                "free": True,          # not decidable mechanically; reviewer decides
                "big_enough": min(w["width"], w["height"]) >= MIN_PX,
                "relevance": _relevance(title_txt, name),
            })
            continue
        ii = info.get(t)
        if not ii:
            continue
        rows.append({
            "title": t,
            "cat": cats[0] if cats else cat,
            "rank": rank[t],
            "width": ii.get("width"), "height": ii.get("height"),
            "mime": ii.get("mime"),
            "bytes": ii.get("size"),
            "url": ii.get("url"),
            "license": _license(ii),
            "commons_usages": _crosswiki(ii),
            "geo": _geo_close(ii, meta),
            "free": _is_free(_license(ii)),
            "big_enough": min(ii.get("width") or 0, ii.get("height") or 0) >= MIN_PX,
            "relevance": _relevance(t.split(":", 1)[1], name),
        })
    rows.sort(key=lambda r: (not r["free"], r["rank"], -r["relevance"],
                             -(min(r["width"] or 0, r["height"] or 0))))
    # Identity floor: drop candidates that neither name the venue at all nor
    # sit in its category (city noise: a geotag 900 m away, a street photo of
    # the neighbourhood). Geo alone is a weak keep — the venue sits among
    # other buildings.
    rows = [r for r in rows if r["rank"] == 4
            or r["rank"] <= 1 or r["relevance"] >= 0.5 or r["geo"]]
    return rows[:limit]


# ---------------------------------------------------------------- find pass

def cmd_find(args):
    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("Pillow is required: pip3 install --user pillow")
    proposals = {}
    if os.path.isfile(PROPOSALS_PATH):
        proposals = json.load(open(PROPOSALS_PATH))

    report = ["# Venue image candidates", "",
              "Approve by setting `\"approved\": true` (or editing `file`), then run:",
              "`python3 common/venue_images.py apply`", ""]
    def save():
        with open(PROPOSALS_PATH, "w") as f:
            json.dump(proposals, f, indent=2, sort_keys=True)
            f.write("\n")
        with open(REPORT_PATH, "w") as f:
            f.write("\n".join(report) + "\n")

    only = set(args.only.split(",")) if getattr(args, "only", None) else None
    todo = [(vid, m) for vid, m in sorted(venues_mod.VENUES.items())
            if not only or vid in only]
    for n, (vid, meta) in enumerate(todo, 1):
        raw_counts = {}
        try:
            web_recs = {}
            rows = candidates_for(vid, meta, query=args.query,
                                  counts=raw_counts, web_recs=web_recs)
        except Exception as e:  # one venue's API hiccup must not lose the run
            rows = []
            print(f"  {vid}: search failed — {e}")
        report.append(f"## {vid} — {meta['name']} ({meta['city']})")
        if rows:
            report.append(f"- category: `{rows[0]['cat'] or '(none)'}`")
            report.append(f"- sources by rank: {raw_counts}")
            for r in rows:
                flags = []
                if not r["free"]:
                    flags.append("LICENSE:" + r["license"])
                if not r["big_enough"]:
                    flags.append(f"TOO-SMALL {r['width']}x{r['height']}")
                if r["mime"] != "image/jpeg":
                    flags.append(r["mime"])
                if r["geo"]:
                    flags.append("geo-match")
                if r["rank"] <= 1:
                    flags.append("venue-category")
                line = (f"- [{r['relevance']:.2f}] `{r['title'][:90]}` "
                        f"{r['width']}x{r['height']} {r['license']}")
                if r.get("page_url"):
                    line += f"\n    page: {r['page_url']}"
                report.append(line
                              + (" " + ",".join(flags) if flags else ""))
        else:
            report.append("- no candidates found")
        report.append("")

        # remember each web candidate's page for the reviewer
        web_pages = {r["title"]: r.get("page_url") for r in rows
                     if r["rank"] == 4}
        cur = proposals.get(vid, {})
        if cur.get("approved") or cur.get("file"):
            continue  # a human already chose; leave it alone
        if not rows:
            print(f"  [{n}/{len(todo)}] {vid}: NO candidates (search degraded?)")
        # Auto-propose only with venue-level certainty: free-licensed >=750px
        # JPEG either (a) hosted in the venue's own Commons category (rank
        # 0/1 — the identity question is answered by curation), or (b) file-
        # named for the venue AND geotagged at the building. A bare filename
        # match never passes on its own (namesakes: Belly Up Chicago…).
        # Concert/stage shots are welcome: the venue's identity must be
        # certain, but the subject may be the room in full swing.
        for r in rows:
            named = r["relevance"] >= 0.66
            strong = r["rank"] <= 1 or (r["geo"] and named)
            if (r["rank"] != 4                    # web hits need a human
                    and r["free"] and r["mime"] == "image/jpeg"
                    and r["big_enough"] and strong):
                srcname = {0: "category", 1: "subcategory",
                           2: "geotag"}.get(r["rank"], "geotag")
                proposals[vid] = {"file": r["title"], "approved": False,
                                  "auto": True, "source": srcname,
                                  "category": r["cat"],
                                  "note": f"{r['width']}x{r['height']} {r['license']}"}
                break
        else:
            proposals[vid] = {"file": None, "approved": False, "auto": False,
                              "note": "no strong auto candidate — pick from the report"}
        print(f"  [{n}/{len(todo)}] {vid}: "
              f"{proposals[vid]['file'] or proposals[vid]['note']}")
        if n % 5 == 0:
            save()

    save()
    print(f"wrote {PROPOSALS_PATH} and {REPORT_PATH}")


# --------------------------------------------------------------- apply pass

def _resize(info, im):
    from PIL import Image
    if min(info["width"], info["height"]) < MIN_PX:
        raise ValueError(f"source is {info['width']}x{info['height']}, below {MIN_PX}")
    if min(info["width"], info["height"]) <= TARGET_PX:
        return im  # native size already satisfies the rule
    scale = TARGET_PX / max(info["width"], info["height"])
    return im.resize((round(info["width"] * scale), round(info["height"] * scale)),
                     getattr(Image, "Resampling", Image).LANCZOS)


def _save(im, dest_dir, venue_id):
    from PIL import Image
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A") if "A" in im.getbands() else None)
        im = bg
    elif im.mode != "RGB":
        im = im.convert("RGB")
    os.makedirs(dest_dir, exist_ok=True)
    im.save(os.path.join(dest_dir, venue_id + ".jpg"), "JPEG",
            quality=85, optimize=True)


def _store(info, im, venue_id):
    for base in (os.path.join(ROOT, venue_id),
                 os.path.join(ROOT, "data-repo", venue_id)):
        _save(im, base, venue_id)
        # Attribution sidecar — free licences (CC-BY in particular) require
        # crediting the author wherever the image is displayed.
        _provenance(base, venue_id, info)


def _provenance(dest_dir, venue_id, info):
    md = info.get("extmetadata") or {}
    with open(os.path.join(dest_dir, "CREDITS.json"), "w") as f:
        json.dump({
            "venue_id": venue_id,
            "file": info.get("_title"),
            "url": info.get("url"),
            "license": info.get("_lic") or _license(info),
            "artist": _strip_markup(md.get("Artist", {}).get("value", "")),
        }, f, indent=2)
        f.write("\n")


def _audit(venue_id):
    p = os.path.join(ROOT, venue_id, venue_id + ".jpg")
    q = os.path.join(ROOT, "data-repo", venue_id, venue_id + ".jpg")
    if not (os.path.isfile(p) and os.path.isfile(q)):
        return False
    from PIL import Image
    with Image.open(p) as im:
        return min(im.size) >= MIN_PX and im.format == "JPEG"


def _apply_commons(f):
    """Commons candidate: license re-verified at apply time."""
    from PIL import Image
    info = _imageinfo([f]).get(f)
    if not info:
        raise ValueError("File: page not found on Commons")
    info["_title"] = f
    if not _is_free(_license(info)):
        raise ValueError(f"license {_license(info)!r} is not redistributable")
    req = urllib.request.Request(info["url"], headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        im = Image.open(io.BytesIO(resp.read()))
        im.load()
    return im, info


def _apply_web(prop, vid):
    """Web candidate: the human already judged licensing; an explicit
    `license` field is REQUIRED so the stored CREDITS.json records what was
    believed at approval time (no unlicensed image enters the feed by
    accident)."""
    from PIL import Image
    lic = (prop.get("license") or "").strip()
    if not lic or lic.upper() in ("REVIEW", "TBD", "UNKNOWN"):
        raise ValueError("web image needs a `license` note in the proposal "
                         "(what the source page says / why redistribution is OK)")
    url = prop.get("image_url") or (prop["file"][len("web:"):]
                                    if prop["file"].startswith("web:") else None)
    if not url:
        raise ValueError("web proposal missing image_url")
    raw = _fetch_image(url)
    im = Image.open(io.BytesIO(raw))
    im.load()
    info = {"width": im.width, "height": im.height,
            "url": url, "_title": (prop.get("page_url") or url),
            "_lic": lic, "page": prop.get("page_url"),
            "extmetadata": {"Artist": {"value": prop.get("artist", "unknown")},
                            "LicenseShortName": {"value": lic}}}
    return im, info


def cmd_apply(args):
    try:
        from PIL import Image
    except ImportError:
        sys.exit("Pillow is required: pip3 install --user pillow")
    if not os.path.isfile(PROPOSALS_PATH):
        sys.exit("no proposals — run `find` first")
    proposals = json.load(open(PROPOSALS_PATH))
    done, skipped, failed = [], [], []
    for vid, prop in sorted(proposals.items()):
        if vid not in venues_mod.VENUES:
            print(f"  {vid}: not in the venue registry — skipped")
            skipped.append(vid)
            continue
        if not prop.get("approved"):
            skipped.append(vid)
            continue
        if _audit(vid):
            print(f"  {vid}: already stored and valid")
            done.append(vid)
            continue
        f = prop.get("file")
        if not f:
            print(f"  {vid}: approved but no file chosen — SKIPPED")
            failed.append(vid)
            continue
        try:
            if f.startswith("web:"):
                im, info = _apply_web(prop, vid)
            else:
                im, info = _apply_commons(f)
            im = _resize(info, im)
            _store(info, im, vid)
            print(f"  {vid}: saved {im.width}x{im.height} from {f[:70]} "
                  f"({info.get('_lic') or _license(info)})")
            done.append(vid)
        except Exception as e:
            print(f"  {vid}: FAILED — {e}")
            failed.append(vid)
    print(f"\napplied {len(done)}, skipped (unapproved) {len(skipped)}, failed {len(failed)}")
    if failed:
        print("failed:", ", ".join(failed))


def cmd_audit(args):
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        sys.exit("Pillow is required: pip3 install --user pillow")
    missing, bad = [], []
    for vid in sorted(venues_mod.VENUES):
        p = os.path.join(ROOT, vid, vid + ".jpg")
        q = os.path.join(ROOT, "data-repo", vid, vid + ".jpg")
        if not os.path.isfile(p):
            missing.append(vid)
        elif not _audit(vid):
            bad.append(vid)
        elif not os.path.isfile(q):
            bad.append(vid + " (missing in data-repo)")
    print(f"{len(venues_mod.VENUES) - len(missing) - len(bad)}/{len(venues_mod.VENUES)} venues ok")
    if missing:
        print("missing:", ", ".join(missing))
    if bad:
        print("invalid:", ", ".join(bad))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find", help="write candidate proposals + report")
    f.add_argument("--query", help="override search query (single-venue debugging)")
    f.add_argument("--only", help="comma-separated venue ids to (re)search")
    sub.add_parser("apply", help="verify + save approved images")
    sub.add_parser("audit", help="check stored images meet the rules")
    args = ap.parse_args()
    {"find": cmd_find, "apply": cmd_apply, "audit": cmd_audit}[args.cmd](args)


if __name__ == "__main__":
    main()
