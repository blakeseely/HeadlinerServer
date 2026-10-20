#!/usr/bin/env python3
"""Fetch The Castro Theatre calendar (https://thecastro.com/calendar/).

The calendar page is server-rendered HTML (WordPress + a list of
<article class="event"> cards), so a plain GET with a browser user-agent is
all it takes. Each card carries:

  * detail page URL          <a href=".../events/slug">
  * title                    <h2 class="attraction_title show-title">
  * start datetime           <p itemprop="startDate" content="2026-10-26 20:00">
  * doors / show times       <span class="event__doors-open"> / .event__start-time
  * top line                 <div class="topline">   (tour name, presenter,
                            "Late Show!", festival credit, "in 70mm", ...)
  * bottom line              <div class="bottomline"> (support act,
                            "Directed by ...", "Hosted by ...", format note)
  * ticket link              first ticket-vendor <a> inside .event-data
                            (Buy Tickets / Sold Out!)

Output: cache/calendar.json — one record per unique event.
Detail-page description + category classification happen later in build.py
against descriptions captured into cache/details.json (browser pass).
"""
import os, re, json, html, urllib.request, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import spotify

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "cache", "calendar.json")
SPOTIFY_CACHE = os.path.join(ROOT, "cache", "spotify.json")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
URL = "https://thecastro.com/calendar/"


def fetch(url=URL):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def clean(s):
    """Strip tags, unescape entities, normalize whitespace; keep <br> as space."""
    if not s:
        return None
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def parse_cards(src):
    """Split the calendar into per-event records (dedup on URL)."""
    parts = re.split(r'(?=<article class="event qtip")', src)
    parts = [p for p in parts if p.startswith("<article")]
    rows, seen = [], set()
    for c in parts:
        def g(pat, flags=0):
            m = re.search(pat, c, flags)
            return m.group(1) if m else None

        url = g(r'href="(https://thecastro\.com/events/[^"]+)"')
        if not url or url in seen:
            continue
        seen.add(url)

        start = g(r'itemprop="startDate"\s+content="([^"]+)"')
        # Ticket vendor buttons inside .event-data (attribute order varies, so
        # parse each <a>'s href + class individually). The "More Info" button
        # points back at the venue's own page — skip it.
        buy, status = None, None
        data_seg = re.search(r'<div class="[^"]*event-data[^"]*">(.*?)</div>', c, re.S)
        if data_seg:
            for m in re.finditer(r'<a\s+([^>]*)>(.*?)</a>', data_seg.group(1), re.S):
                attrs, inner = m.group(1), m.group(2)
                href = re.search(r'href="([^"]+)"', attrs)
                label = clean(inner) or ""
                if re.search(r"sold\s*out", label, re.I) or "soldout" in attrs.lower():
                    status = "sold out"
                    continue  # sold-out buttons may self-link to the event page
                if href and "thecastro.com/events" in href.group(1):
                    continue  # more info
                if href:
                    buy = html.unescape(href.group(1)).replace("&amp;", "&")
                    if re.search(r"\bbuy\b|\bselect seat", label, re.I):
                        status = "on sale"

        rows.append({
            "url": url,
            "title": clean(g(r'<h2[^>]*>(.*?)</h2>', re.S)),
            "start": start,                       # "2026-10-26 20:00"
            "doors": clean(g(r'class="event__doors-open"[^>]*>(.*?)</span>', re.S)),
            "show_time": clean(g(r'class="event__start-time"[^>]*>(.*?)</span>', re.S)),
            "topline": clean(g(r'<div class="topline"[^>]*>(.*?)</div>', re.S)),
            "bottomline": clean(g(r'<div class="bottomline"[^>]*>(.*?)</div>', re.S)),
            "ticket_link": buy,
            "ticket_status": status,
        })
    rows.sort(key=lambda r: (r["start"] or "9999"))
    return rows


def main():
    src = fetch()
    rows = parse_cards(src)
    open(os.path.join(ROOT, "cache", "calendar_raw.html"), "w").write(src)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)
    # Spotify: each event detail page publishes per-attraction links (strategy
    # A in common.spotify). Incremental — only new slugs hit the network; a
    # film page simply yields no link (honest null, like a not-found match).
    spotify.fetch_spotify(rows, SPOTIFY_CACHE, url_key="url")
    no_date = [r["title"] for r in rows if not r["start"]]
    no_buy = [r["title"] for r in rows if not r["ticket_link"]]
    sold = [r["title"] for r in rows if r.get("ticket_status") == "sold out"]
    print(f"events: {len(rows)}")
    print(f"first: {rows[0]['start']}  {rows[0]['title']}")
    print(f"last:  {rows[-1]['start']}  {rows[-1]['title']}")
    print(f"missing date: {len(no_date)} {no_date[:5]}")
    print(f"missing ticket link: {len(no_buy)} {no_buy[:8]}")
    print(f"sold out: {len(sold)}")
    for r in rows:
        print(f"  {r['start']}  {r['title']!r:55} bl={r['bottomline']!r}")


if __name__ == "__main__":
    main()
