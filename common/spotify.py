"""Spotify artist links — scraped from the venue's own event pages.

Unlike Apple Music (catalog search), these links come from the venue site
itself: the venues that publish a per-artist Spotify link (Independent,
Castro, Fox Oakland, Greek, Brick & Mortar, Cafe du Nord, Regency) have their
detail pages parsed for the artist's open.spotify.com link. Venues whose sites
don't publish one simply have null links — an honest gap, never a search
fallback (the project's Option-2 decision: no API key).

This module owns the shared bits:

  * extract_links(html)  -> {artist_name: spotify_url} for one detail page.
    Handles the template flavors these sites use (attraction blocks,
    per-artist social rows, data-title'd listen buttons). Links are
    normalized (?si= tracking stripped) and deduped.
  * norm_link / norm_name            — the canonical forms the joins key on.
  * merge_shows(shows, linkmap)      — attach a link to the right artist
    record by exact normalized name (unmatched artists stay None).
  * from_captures / stats            — normalize a venue's varied capture
    caches to {page: {name: url}} and build the `stats.spotify` block.
  * fetch_spotify / load_cache / save_cache — the incremental per-page
    backfill used by venues whose own fetcher doesn't walk detail pages.
  * spotify_links_json               — read a link off a structured record
    (the Regency AEG blob's association records).

The fetchers capture per event page; the builds join by artist name.
"""
import concurrent.futures
import html as _html
import json
import os
import re
import time
import urllib.request

from .apple_music import relabel

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# open.spotify.com/(artist|playlist|album|track|...)/<id>
_LINK_RE = re.compile(
    r'["\'(](https?://(?:www\.|open\.)?spotify\.com/(?:artist|playlist|album|track|show)/[A-Za-z0-9]+)[^"\'<>]*')


def norm_link(href):
    """Canonicalize a spotify URL: open.spotify.com host, no query string
    (?si= tracking) or fragment. Returns None for non-spotify or malformed."""
    if not href:
        return None
    m = re.match(r'https?://(?:www\.|open\.)?spotify\.com/(artist|playlist|album|track|show)/([A-Za-z0-9]+)',
                 href.strip())
    if not m:
        return None
    return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}"


def _clean_name(t):
    t = _html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"\s+", " ", t).strip()
    t = t.strip(":\u200b-–— ")
    return t or None


def extract_links(page_html):
    """Per-artist spotify links for one (server-rendered) detail page.

    Returns {artist_name: normalized_spotify_url}. Each strategy below
    yields (name, url) pairs; names are kept as published (display form),
    URLs deduped. Flavors:

    A. attraction blocks — <div class="attraction">…<h2 class=
       "attraction_title"><a>NAME</a></h2>… a class="music" spotify link.
       (thecastro.com, thefoxoakland.com, thegreekberkeley.com)
    B. per-artist social rows — a NAME header inside a section that contains
       class="social-link spotify" / role=link title="spotify".
       (TicketWeb: theindependentsf.com, brickandmortarmusic.com)
    C. listen buttons — a class="listen__btn" spotify link whose
       data-title="NAME …" names its artist. (cafedunord.com)
    D. venue-level fallback — any spotify link whose nearest preceding
       text is a plausible artist name (kept last resort).
    """
    out = {}

    def add(name, url):
        if not name or not url:
            return
        out.setdefault(name, norm_link(url))

    # --- A: attraction blocks ------------------------------------------------
    for blk in re.split(r'<div[^>]*class="[^"]*attraction[^"]*"', page_html)[1:]:
        names = re.findall(
            r'<h[12][^>]*attraction_title[^>]*>(.*?)</h[12]>', blk, re.S)
        if not names:
            names = re.findall(r'<h[12][^>]*>.*?itemprop="performer">(.*?)</h[12]>',
                               blk, re.S)
        links = _LINK_RE.findall(blk)
        if not links:
            continue
        for n in names:
            add(_clean_name(n), links[0])

    # --- B: per-artist sections with a social spotify row ---------------------
    # The anchor carries the spotify marker in class/role/title; the href may
    # sit BEFORE the class (TicketWeb) or after it, so take a window around the
    # match. The artist name is the nearest heading in the lookback — but when
    # the page has named artist sections, bound the lookback to the enclosing
    # section start (a fixed window can spill past a later section into a
    # "Related Events" footer and grab the WRONG act's name).
    for m in re.finditer(r'class="social-link\s+spotify"', page_html):
        i = m.start()
        starts = [s.start() for s in re.finditer(
            r'<div[^>]*class="[^"]*(?:artist-list|tw-subsection)[^"]*"', page_html)
            if s.start() < i]
        # the nearest artist-section start before the marker bounds the lookback
        # (a fixed window can spill into a "Related Events" footer or a
        # SIBLING show's section and grab the WRONG act's name)
        lo = max(0, max(starts)) if starts else max(0, i - 4000)
        names = [x for x in (
            _clean_name(n) for n in re.findall(
                r"<h[1-4][^>]*>(.*?)</h[1-4]>", page_html[lo:i], re.S)) if x]
        # window wide enough for the line-broken TicketWeb attribute list
        url_m = re.search(r'href="(https?://[^"]*open\.spotify\.com[^"]*)"',
                          page_html[max(0, i - 200):i + 400])
        if names and url_m:
            add(names[-1], url_m.group(1))

    # --- C: listen buttons with data-title -----------------------------------
    # Cafe du Nord: <a class="... listen__btn" href="spotify" data-title=
    # "NAME on Spotify" ...> — attribute order can vary, so scan the anchor.
    for m in re.finditer(r'<a[^>]*class="[^"]*listen__btn[^"]*"[^>]*>', page_html):
        tag = m.group(0)
        url_m = re.search(r'href="([^"]+)"', tag)
        title_m = re.search(r'data-title="([^"]+)"', tag)
        if not url_m or "spotify" not in url_m.group(1):
            continue
        if title_m:
            name = re.sub(r"\s+on\s+(spotify|youtube|apple\s*music|bandcamp|soundcloud)\b.*$",
                          "", title_m.group(1), flags=re.I)
            add(_clean_name(name), url_m.group(1))

    # --- D: last resort — the page's main act is the LAST plausible text
    # before the FIRST spotify social row (TicketWeb-style pages, where the
    # artist's section heading can sit too far back to key on, and a "Related
    # Events" footer lists OTHER shows earlier in the window). Prefer a
    # candidate that matches the <title> tag; else accept the last plausible
    # one, and only when nothing else matched.
    if not out:
        m0 = re.search(r'open\.spotify\.com/(?:artist|playlist|album|track)/[A-Za-z0-9]+',
                       page_html)
        if m0:
            # the first spotify link on the page is the headliner's
            m0 = next(m for m in _LINK_RE.finditer(page_html))
            i = m0.start()
            seg = _html.unescape(re.sub(r"<[^>]+>", "\x00",
                                        page_html[max(0, i - 25000):i]))
            title_m = re.search(r"<title>(.*?)</title>", page_html, re.S)
            title = None
            if title_m:
                t = _clean_name(title_m.group(1))
                if t:
                    t = re.sub(r"\s*[|\-–—]\s*.*$", "", t).strip()  # drop venue tail
                    title = norm_name(t) if t else None
            cands = [t.strip(" \t|·•-–—: ") for t in seg.split("\x00")]
            cands = [re.sub(r"\s+", " ", c) for c in cands if c]
            keep = [c for c in cands
                    if 3 < len(c) <= 45 and re.search(r"[A-Za-z]{3,}", c)
                    and not re.search(r"(?i)\b(doors?|tickets?|buy|sold|show|sponsor|"
                                      r"related events|cookie|consent|instagram|"
                                      r"facebook|youtube|google|sign up|subscribe|"
                                      r"all ages|18 and up|16 and up|plus\b|"
                                      r"oct|nov|dec|jan|feb|mar|apr|may|jun|jul|aug|sep)\b", c)
                    and not re.search(r"^\d", c)]
            pick = None
            if title:
                for c in reversed(keep):
                    if norm_name(c) == title:
                        pick = c
                        break
            if pick is None and keep:
                pick = keep[-1]
            if pick:
                add(pick, m0.group(0) and page_html[m0.start():m0.start() + 300])
    return {k: v for k, v in out.items() if v}


def norm_name(name):
    """Name key for matching: accent-stripped, punctuation-free, lowercase.
    (Single-letter titles keep their period — 'Ms. Hill' vs 'Ms Hill' must
    key identically, so the period is dropped before the punctuation sweep.)"""
    import unicodedata
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\b([A-Za-z])\.", r"\1", s)
    s = re.sub(r"[^a-z0-9 ]+", "", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def stats(shows):
    """Shared stats block (goes into the venue's `stats` as "spotify").

    Unique artists (deduped on the case-insensitive, accentless name) and
    how their links were sourced. `linked == venue + api + feed` exactly:
      venue — the venue's own page published the link
      api   — Spotify Web API lookup (common/spotify_lookup.py)
      feed  — the venue's structured data feed carried the link (regency AEG)
    `shows_with_link` = shows where ANY billed artist (headline or support)
    carries a link.
    """
    seen = {}
    for s in shows:
        for a in (s.get("headline_artists") or []) + (s.get("support_artists") or []):
            if isinstance(a, dict) and a.get("name"):
                seen.setdefault(norm_name(a["name"]), a)
    def src(a):
        # A link with no explicit source tag = venue-scraped (the publishing
        # venues attach it in their builds; the API path marks "api"; the
        # structured-feed path marks "feed").
        return a.get("spotify_source") or ("venue" if a.get("spotify") else None)
    return {
        "unique_artists": len(seen),
        "linked": sum(1 for a in seen.values() if a.get("spotify")),
        "venue": sum(1 for a in seen.values() if src(a) == "venue"),
        "api": sum(1 for a in seen.values() if src(a) == "api"),
        "feed": sum(1 for a in seen.values() if src(a) == "feed"),
        "shows_with_link": sum(1 for s in shows
                               if any(a.get("spotify")
                                      for a in (s.get("headline_artists") or [])
                                                    + (s.get("support_artists") or [])
                                      if isinstance(a, dict))),
    }


def merge_shows(shows, linkmap):
    """Attach captured per-artist Spotify links onto show records (in place).

    linkmap: {event_page_url: {artist_name: url}}. Artist names match on the
    accent/punctuation-normalized form. Returns the number of artists linked.
    Unmatched artists stay None: an honest gap, never a wrong link.
    Venue-published links are tagged spotify_source="venue" and their
    `spotify_label` reset (an exact venue link needs no review label)."""
    total = 0
    for s in shows:
        if not isinstance(s, dict):
            continue
        page = s.get("event_page") or ""
        lm = linkmap.get(page.rstrip("/")) or linkmap.get(page) or {}
        for a in (s.get("headline_artists") or []) + (s.get("support_artists") or []):
            if not isinstance(a, dict):
                continue
            for ln, url in lm.items():
                if norm_name(ln) == norm_name(a.get("name")):
                    a["spotify"] = url
                    a["spotify_source"] = "venue"  # the venue's own published link
                    a["spotify_label"] = None
                    relabel(a)
                    if url:
                        total += 1
                    break
    return total


def from_captures(captures, url_key=None):
    """Build a {event_page: {artist_name: url}} linkmap from the venue's
    captured events. `captures` is either:
      * a list of records, each carrying a "spotify" dict and an event-page
        url under `url_key` (falling back to href/url), or
      * a dict {url: {..spotify..}} (the url is the dict key — used by the
        castro/greek/fox detail caches).
    Venues keep their captured links in different caches; this normalizes
    them to the shape merge_shows() expects.
    """
    linkmap = {}
    if isinstance(captures, dict):
        items = captures.items()
    else:
        items = ((None, ev) for ev in captures)
    for key, ev in items:
        if not isinstance(ev, dict):
            continue
        page = None
        if isinstance(key, str):
            page = key
        else:
            for k in (url_key, "event_page", "href", "url"):
                if k and ev.get(k):
                    page = ev[k]
                    break
        cap = ev.get("spotify")
        if page and cap:
            linkmap[page.rstrip("/")] = cap
    return linkmap


def load_cache(path):
    """Load a venue's cache/spotify.json ({event_page: {name: url}})."""
    if not os.path.exists(path):
        return {}
    try:
        d = json.load(open(path))
    except (ValueError, OSError):
        return {}
    return d if isinstance(d, dict) else {}


def save_cache(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)


def spotify_links_json(rec_or_links):
    """Spotify link(s) from a structured JSON record (e.g. the Regency AEG
    blob's associations[*][*].links[] — {link_title, link_href}). No fetch:
    the data rides in the calendar the venue already pulls.
    Accepts a record dict (with a 'links' list) or a bare links list.
    Returns [normalized_url, ...]."""
    links = None
    if isinstance(rec_or_links, dict):
        links = rec_or_links.get("links")
    elif isinstance(rec_or_links, list):
        links = rec_or_links
    out = []
    for l in links or []:
        if not isinstance(l, dict):
            continue
        href = l.get("link_href") or ""
        n = norm_link(href)
        if n:
            out.append(n)
    return out


def fetch_spotify(rows, cache_path, url_key="event_page", detail_max=200,
                  workers=3, pause=0.3):
    """Incrementally fetch each show's event page and capture its per-artist
    Spotify links. Returns {page_url: {artist_name: url}}.

    rows: iterable of dicts; each page url is read from `url_key` (venues key
    their detail URL under event_page / url / href). Pages already in the
    cache are never re-fetched (only new slugs hit the network, so a stale
    cache still covers every current show); a failed refetch keeps the prior
    capture. The merged map is written back to cache_path.
    """
    have = load_cache(cache_path)
    todo = []
    for r in rows:
        url = r.get(url_key)
        if url and url.startswith("http") and url not in have:
            todo.append(url)
    todo = todo[:detail_max]
    if todo:
        def do(u):
            last = None
            for _ in range(3):
                try:
                    req = urllib.request.Request(u, headers={"User-Agent": UA})
                    page = urllib.request.urlopen(req, timeout=30).read().decode(
                        "utf-8", "replace")
                    return u, extract_links(page)
                except Exception as exc:
                    last = exc
                    time.sleep(1.5)
            print(f"  !! spotify {u} failed: {last}", flush=True)
            return u, {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            for u, links in ex.map(do, todo):
                have[u] = links if links else have.get(u) or links
                time.sleep(pause)  # be polite
        save_cache(cache_path, have)
    return have
