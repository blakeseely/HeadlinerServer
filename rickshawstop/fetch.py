#!/usr/bin/env python3
"""Fetch the Rickshaw Stop schedule (https://rickshawstop.com/calendar/).

The Rickshaw Stop is a Mission/Civic-Center live-music venue (155 Fell St).
Its site is a WordPress install behind Cloudflare: the rendered HTML routes
(/calendar/, /, /events) hard-403 BOTH curl and a real browser (the
`__cf_bm` / `ki-edge` bot wall), so the human pages are NOT a viable recurring
source. BUT the WordPress REST API is open:

      GET https://rickshawstop.com/wp-json/wp/v2/pages?slug=calendar

returns the calendar page's `content.rendered` fully SERVER-RENDERED (one
stable GET; the page stores its list-view cards + 12 month tables as WP
content). We read the feed from the API, not the walled HTML.

Two regions of that content, merged into one record per show:

  * MONTH TABLES  (the backbone, ~50 shows, Oct 2026 -> Apr 2027): 12
    server-rendered <table class="seetickets-calendar">, one per calendar
    month (month + year in the header). Each event card sits in a <td> and
    carries: day number (<div class="fs-16 date-number">), a ticket href,
    the billed title, Show/Doors times, and the buy-button status.
  * LIST-VIEW CARDS (the enrichment, the ~10 nearest shows): rich cards
    (<div ... data-listtype="list">) that add the clean headliner name,
    "Supporting Talent: …", the GENRE, ages and price — none of which the
    tables carry.

The two regions share ticket URLs, so we merge on a normalized URL key:
every table show keeps its date/title/times, and the nearest shows gain the
list-view genre/headliner/support/ages on top.

Ticket URLs come from several ticketers (Seetickets, Eventim, Ticketmaster,
sickening.events) and ~18 of them are wrapped in a spam-filter redirect
(urldefense.com/v3/__<real-url>;__) which we unwrap. We keep the unwrapped
URL as ticket_link/event_page but do NOT scrape the detail pages: they are
vor.us/Eventim JS apps (bot-walled / "you're in line"), so per-artist Spotify
is an honest null — the registry turns on the Spotify API lookup instead.

Output: cache/events.json — one record per unique show (dedup on URL).
"""
import os, re, json, html, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cache", "events.json")
RAW = os.path.join(HERE, "cache", "calendar_raw.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
API = "https://rickshawstop.com/wp-json/wp/v2/pages?slug=calendar&_fields=id,link,content"

MONTHS = {n: i + 1 for i, n in enumerate(
    ["january", "february", "march", "april", "may", "june",
     "july", "august", "september", "october", "november", "december"])}

# A ticket/event link: any of the real ticketers, or the spam-filter wrapper.
TICKET_RE = re.compile(
    r'href="([^"]*(?:seetickets|eventim|ticketmaster|sickening|urldefense)[^"]*)"')


def fetch(url=API):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def clean(s):
    if not s:
        return None
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def unwrap(href):
    """Unwrap the urldefense spam-filter redirect to the real ticket URL."""
    if not href:
        return None
    m = re.match(r"https://urldefense\.com/v3/__([^?]+)\?.*?:__", href) or \
        re.match(r"https://urldefense\.com/v3/__([^_].*?);__", href)
    if m:
        href = m.group(1)
    href = re.sub(r"\?.*$", "", href)   # drop ?afflky=… / camefrom=… tracking
    return href or None


def norm_key(url):
    """Join key: host + path, lowercase, query stripped. Tolerant of the
    seetickets<->eventim host swap (they're the same event under two brands)."""
    if not url:
        return None
    m = re.search(r"https?://[^/]+(/[^?#]*)", url)
    if not m:
        return None
    path = m.group(1)
    # seetickets and eventim share the /event/<slug>/<id> shape; normalize host
    hm = re.search(r"https?://([^/]+)/", url)
    host = hm.group(1) if hm else ""
    if host.endswith(("seetickets.us", "eventim.us")):
        host = "eventim.us"
    return (host + path).lower().rstrip("/")


def first_ticket(card):
    """The unwrapped ticket/event URL from a card, or None."""
    m = TICKET_RE.search(card)
    return unwrap(m.group(1)) if m else None


def parse_tables(src):
    """Backbone: one record per event card in the month tables."""
    rows = {}
    blocks = re.split(
        r'(?=<table[^>]*class="[^"]*seetickets-calendar[^"]*")', src)
    for b in blocks[1:]:
        end = b.find("</table>")
        tbl = b[:end] if end > 0 else b
        # month + year from the header text immediately preceding the table
        # (the markup is <span class="bold">October</span> 2026 — the tag
        # splits the month from the year, so strip tags first, then match).
        pos = src.find(b)
        pre = src[max(0, pos - 220):pos]
        pre_text = html.unescape(re.sub(r"<[^>]+>", " ", pre))
        month_name = "|".join(MONTHS)
        hm = re.search(r"\b(" + month_name + r")\s+(\d{4})\b", pre_text, re.I)
        if not hm:
            continue
        mon = MONTHS.get(hm.group(1).lower())
        year = int(hm.group(2))
        if not mon:
            continue
        starts = [m.start() for m in re.finditer(
            r'<div class="[^"]*seetickets-calendar-event-container[^"]*"', tbl)]
        for i, s in enumerate(starts):
            e = starts[i + 1] if i + 1 < len(starts) else len(tbl)
            card = tbl[s:e]
            url = first_ticket(card)
            key = norm_key(url)
            # day number is a <div class="date-number"> SIBLING that precedes
            # the card inside the same <td> (NOT in the card block). Bound the
            # lookback at the enclosing <td> start so we never read the day
            # number of the previous week-cell.
            td_start = tbl.rfind("<td", 0, s)
            look = tbl[td_start if td_start != -1 else 0:s]
            dm = re.search(r'date-number[^>]*>\s*(\d{1,2})\s*<', look)
            day = int(dm.group(1)) if dm else None
            date = f"{year:04d}-{mon:02d}-{day:02d}" if day else None

            tm = re.search(
                r'seetickets-calendar-event-title[^>]*>.*?<a[^>]*>(.*?)</a>',
                card, re.S)
            title = clean(tm.group(1)) if tm else None

            show_time = doors = None
            stm = re.search(r'(?i)Show\s+at\s+([A-Za-z0-9:]+)', card)
            dom = re.search(r'(?i)Doors\s+at\s+([A-Za-z0-9:]+)', card)
            if stm:
                show_time = stm.group(1)
            if dom:
                doors = dom.group(1)

            # buy-button text = ticket status ("Buy Tickets" / "Sold Out")
            status = None
            btn = re.search(
                r'<a[^>]*class="[^"]*button-gettickets[^"]*"[^>]*>(.*?)</a>',
                card, re.S)
            if btn:
                t = clean(btn.group(1))
                if t:
                    if re.search(r"sold\s*?out", t, re.I):
                        status = "sold out"
                    elif re.search(r"buy|tickets|info", t, re.I):
                        status = "on sale"

            rec = {
                "url": url,
                "title": title,
                "date": date,
                "doors": doors,
                "show_time": show_time,
                "ticket_link": url,
                "ticket_status": status,
                "event_page": url,
            }
            if key and key not in rows:
                rows[key] = rec
    return rows


def parse_list_cards(src):
    """Enrichment: the nearest shows' rich fields, keyed by normalized URL."""
    enr = {}
    starts = [m.start() for m in re.finditer(
        r'data-listtype="list"', src)]
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(src)
        card = src[s:e]
        url = first_ticket(card)
        key = norm_key(url)
        if not key:
            continue
        g = lambda p, fl=0: (lambda m: m.group(1) if m else None)(
            re.search(p, card, fl))
        head = clean(g(r'class="fs-12 headliners">(.*?)</p>', re.S))
        genre = clean(g(r'class="fs-12 genre">(.*?)</p>', re.S))
        age = clean(g(r'class="ages"[^>]*>(.*?)</span>', re.S))
        price = clean(g(r'class="fs-12 price[^"]*"[^>]*>(.*?)</span>', re.S))
        sup = clean(g(r'class="fs-12 supporting-talent">(.*?)</p>', re.S))
        header = clean(g(r'class="fs-12 header">(.*?)</p>', re.S))
        presenters = [header] if header else []
        if key not in enr:
            enr[key] = {
                "headliner": head,
                "genre": genre,
                "age": age,
                "price": price,
                "support": sup,
                "presenters": presenters,
            }
    return enr


def parse(src):
    tables = parse_tables(src)
    enrichment = parse_list_cards(src)
    rows = list(tables.values())
    # attach enrichment where the show is in the nearest list-view window
    for r in rows:
        key = norm_key(r.get("url"))
        if key in enrichment:
            r.update({k: enrichment[key].get(k)
                      for k in ("headliner", "genre", "age",
                                "support", "price", "presenters")})
    rows.sort(key=lambda r: (r.get("date") or "9999", r.get("doors") or ""))
    return rows


def main():
    raw = fetch()
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise SystemExit("calendar page not found via API (got "
                         f"{type(data).__name__})")
    content = data[0].get("content", {}).get("rendered", "")
    if not content:
        raise SystemExit("calendar page returned empty content")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(RAW, "w"), ensure_ascii=False)
    rows = parse(content)
    json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)
    no_date = [r["title"] for r in rows if not r["date"]]
    no_title = [r["title"] for r in rows if not r["title"]]
    with_genre = sum(1 for r in rows if r.get("genre"))
    print(f"events: {len(rows)}  (with genre/enrichment: {with_genre})")
    if rows:
        print(f"first: {rows[0]['date']}  {rows[0]['title']}")
        print(f"last:  {rows[-1]['date']}  {rows[-1]['title']}")
    print(f"missing date: {len(no_date)} {no_date[:5]}")
    print(f"missing title: {len(no_title)} {no_title[:5]}")


if __name__ == "__main__":
    main()
