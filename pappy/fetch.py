#!/usr/bin/env python3
"""Fetch the Pappy & Harriet's schedule (https://pappyandharriets.com/calendar).

Pappy & Harriet's is the historic Pioneertown Palace (53688 Pioneertown Rd,
Pioneertown CA — grouped with the LA market in the app, per the owner). Its
site is a WordPress install behind a bot wall: the rendered HTML routes
(/live-music, /calendar, /home) 403 BOTH curl AND a real browser, so the human
pages are NOT a viable recurring source. BUT the WordPress REST API is open:

      GET https://pappyandharriets.com/wp-json/wp/v2/pages?slug=calendar

returns the calendar page's `content.rendered` fully SERVER-RENDERED (one
stable GET; the page stores its list-view cards + 12 month tables as WP
content). We read the feed from the API, not the walled HTML.

Two regions of that content, merged into one record per show:

  * MONTH TABLES  (the backbone): 12 server-rendered
    <table class="seetickets-calendar"> (one per calendar month,
    Oct 2026 -> Sep 2027). Each event card sits in a <td> and carries:
    day number (<div class="date-number">), ticket href, billed title,
    Show/Doors times, and the buy-button state (button-gettickets /
    button-soldout).
  * LIST-VIEW CARDS (the enrichment, the nearest ~40 shows): rich cards
    (<div ... data-listtype="list">) that add the clean headliner name,
    "Supporting Talent: …", the GENRE, ages, price, and full date.

The two regions share ticket URLs, so we merge on a normalized URL key:
every show keeps its table date/times, and the nearest shows gain the
list-view headliner/support/genre/ages/price on top. A show present in only
one region is still emitted (the list's date carries its own month).

Multi-day passes (a "[2-Day Pass]" row for the same festival) are DROPPED —
they are ticket packages, not shows. Ticket URLs point at Seetickets event
pages, which are bot-walled (the Chapel / Rickshaw lesson), so they are kept
only as ticket_link/event_page and never scraped — per-artist Spotify is an
honest null (the registry turns on the Spotify API lookup instead).

Output: cache/events.json — one record per unique show.
"""
import os, re, json, html, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cache", "events.json")
RAW = os.path.join(HERE, "cache", "calendar_raw.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
API = ("https://pappyandharriets.com/wp-json/wp/v2/pages"
       "?slug=calendar&_fields=id,link,content")

MONTHS = {n: i + 1 for i, n in enumerate(
    ["january", "february", "march", "april", "may", "june",
     "july", "august", "september", "october", "november", "december"])}
MON_ABBR = {m[:3].lower(): v for m, v in MONTHS.items()}

# A ticket/event link: the Seetickets family (the venue's only ticketer).
TICKET_RE = re.compile(
    r'href="([^"]*(?:seetickets|eventim|ticketmaster|sickening|urldefense)[^"]*)"')


def fetch(url=API):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
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
    """Unwrap a possible urldefense spam-filter redirect; drop tracking."""
    if not href:
        return None
    m = re.match(r"https://urldefense\.com/v3/__([^?]+)\?.*?:__", href) or \
        re.match(r"https://urldefense\.com/v3/__([^_].*?);__", href)
    if m:
        href = m.group(1)
    href = re.sub(r"\?.*$", "", href)
    return href or None


def norm_key(url):
    """Join key: host + path, lowercase, query stripped. Tolerant of the
    seetickets<->eventim host swap (same event, two brands)."""
    if not url:
        return None
    m = re.search(r"https?://([^/]+)(/[^?#]*)", url)
    if not m:
        return None
    host = m.group(1)
    if host.endswith(("seetickets.us", "eventim.us")):
        host = "eventim.us"
    return (host + m.group(2)).lower().rstrip("/")


def first_ticket(card):
    m = TICKET_RE.search(card)
    return unwrap(m.group(1)) if m else None


def button_status(card):
    """The buy button's CLASS + text -> a ticket status, or None."""
    m = re.search(r"<a[^>]*class='([a-z-]+?)\s*'\s*>(.*?)</a>",
                  card, re.S | re.I)
    if not m:
        m = re.search(r'<a[^>]*class="([a-z-]+?)"[^>]*>(.*?)</a>',
                      card, re.S | re.I)
    if not m:
        return None
    cls, text = m.group(1), clean(m.group(2))
    if "soldout" in cls or (text and re.search(r"sold\s*out", text, re.I)):
        return "sold out"
    if "sold" in cls or "protected" in cls:
        return "not on sale"
    if re.search(r"event passed|passed", text or "", re.I):
        return None  # past shows fall off on the next crawl
    if "gettickets" in cls or (text and re.search(r"buy|tickets|info", text, re.I)):
        return "on sale"
    return None


def parse_tables(src):
    """Backbone: one record per event card in the 12 month tables."""
    rows = {}
    blocks = re.split(
        r'(?=<table[^>]*class="[^"]*seetickets-calendar[^"]*")', src)
    for b in blocks[1:]:
        end = b.find("</table>")
        tbl = b[:end] if end > 0 else b
        # month + year live in the header text immediately before the table
        # (<span class="bold">October</span> 2026 — the tag splits month from
        # year, so strip tags first, then match).
        pos = src.find(b)
        pre = src[max(0, pos - 220):pos]
        pre_text = html.unescape(re.sub(r"<[^>]+>", " ", pre))
        hm = re.search(r"\b(" + "|".join(MONTHS) + r")\s+(\d{4})\b",
                       pre_text, re.I)
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
            # the card inside the same <td>; bound the lookback at the <td>
            # start so we never read the previous week-cell's day number.
            td_start = tbl.rfind("<td", 0, s)
            look = tbl[td_start if td_start != -1 else 0:s]
            dm = re.search(r'date-number[^>]*>\s*(\d{1,2})\s*<', look)
            day = int(dm.group(1)) if dm else None
            date = f"{year:04d}-{mon:02d}-{day:02d}" if day else None

            tm = re.search(
                r'seetickets-calendar-event-title[^>]*>.*?<a[^>]*>(.*?)</a>',
                card, re.S)
            title = clean(tm.group(1)) if tm else None
            if title and re.search(r"\[2-Day Pass\]", title, re.I):
                continue  # a ticket package, not a show

            stm = re.search(r'(?i)Show\s+at\s+([A-Za-z0-9:]+)', card)
            dom = re.search(r'(?i)Doors\s+at\s+([A-Za-z0-9:]+)', card)

            rec = {
                "url": url,
                "title": title,
                "date": date,
                "doors": dom.group(1) if dom else None,
                "show_time": stm.group(1) if stm else None,
                "ticket_link": url,
                "ticket_status": button_status(card),
                "event_page": url,
                "headliner": None,
                "genre": None,
                "age": None,
                "price": None,
                "support": None,
                "presenters": [],
            }
            if key and key not in rows:
                rows[key] = rec
    return rows


def list_date(s):
    """'Fri Oct 23' / 'Sat Nov 21 2027' -> (year, month, day) or None."""
    m = re.match(r"(?:[A-Za-z]{3,9}\s+)?([A-Za-z]{3,9})\s+(\d{1,2})"
                 r"(?:\s+(\d{4}))?", s or "")
    if not m:
        return None
    mon = MON_ABBR.get(m.group(1)[:3].lower())
    if not mon:
        return None
    return (int(m.group(3)) if m.group(3) else None, mon, int(m.group(2)))


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
        t = re.search(r'mb-12 title"><a[^>]*>([^<]+)</a>', card)
        title = clean(t.group(1)) if t else None
        if title and re.search(r"\[2-Day Pass\]", title, re.I):
            continue
        head = clean(g(r'class="fs-12 headliners">(.*?)</p>', re.S))
        genre = clean(g(r'class="fs-12 genre">(.*?)</p>', re.S))
        age = clean(g(r'class="ages"[^>]*>(.*?)</span>', re.S))
        price = clean(g(r'class="fs-12[^"]*"\s*>\s*<span class="price">(.*?)</span>', re.S))
        sup = clean(g(r'class="fs-12 supporting-talent">(.*?)</p>', re.S))
        header = clean(g(r'class="fs-12 header">(.*?)</p>', re.S))
        dtext = clean(g(r'mt-1r date">(.*?)</p>', re.S))
        ymd = list_date(dtext) if dtext else None
        presenters = [header] if header else []
        rec = {
            "url": url,
            "title": title,
            "date": (f"{ymd[0]:04d}-{ymd[1]:02d}-{ymd[2]:02d}"
                     if ymd and ymd[0] else None),
            "_date_raw": dtext if (ymd and ymd[0] is None) else None,
            "doors": None,
            "show_time": None,
            "ticket_link": url,
            "ticket_status": button_status(card),
            "event_page": url,
            "headliner": head or None,
            "genre": genre,
            "age": age,
            "price": price,
            "support": sup,
            "presenters": presenters,
        }
        if key not in enr:
            enr[key] = rec
    return enr


def parse(src):
    tables = parse_tables(src)
    enrichment = parse_list_cards(src)
    rows = list(tables.values())
    # a show in the list window but missing from the tables (a feed lag)
    for key, r in enrichment.items():
        if key not in tables:
            rows.append(r)
    for r in rows:
        key = norm_key(r.get("url"))
        en = enrichment.get(key)
        if en:
            for k in ("headliner", "genre", "age", "price", "support",
                      "presenters", "_date_raw"):
                if not r.get(k):
                    r[k] = en.get(k)
            # the list carries a full date the yearless/None table row lacks
            if not r.get("date") and en.get("date"):
                r["date"] = en["date"]
    # Resolve yearless list dates (the list bills 'Fri Oct 23' with no year).
    # Anchor on the table dates: the nearest table show sharing a month+day
    # supplies the year; a show whose month+day precedes every table date
    # takes the first table's year (it is the nearest upcoming occurrence).
    table_dates = [r["date"] for r in rows if r.get("date")]
    if table_dates:
        for r in rows:
            if r.get("date"):
                continue
            m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})", r.get("_date_raw") or "")
            if not m:
                continue
            mon = MON_ABBR.get(m.group(1)[:3].lower())
            if not mon:
                continue
            for t in sorted(table_dates):
                ty, tmon, tday = (int(x) for x in t.split("-"))
                if tmon == mon and tday == int(m.group(2)):
                    r["date"] = f"{t}"
                    break
            else:
                r["date"] = f"{table_dates[0][:4]}-{mon:02d}-" \
                    f"{int(m.group(2)):02d}"
            r.pop("_date_raw", None)
    for r in rows:
        r.pop("_date_raw", None)
    rows.sort(key=lambda r: (r.get("date") or "9999", r.get("doors") or ""))
    return rows


def main():
    raw = fetch()
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise SystemExit("live-music page not found via API (got "
                         f"{type(data).__name__})")
    content = data[0].get("content", {}).get("rendered", "")
    if not content:
        raise SystemExit("live-music page returned empty content")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(RAW, "w"), ensure_ascii=False)
    rows = parse(content)
    json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)
    no_date = [r["title"] for r in rows if not r.get("date")]
    no_title = [r["title"] for r in rows if not r.get("title")]
    with_genre = sum(1 for r in rows if r.get("genre"))
    print(f"events: {len(rows)}  (with genre/enrichment: {with_genre})")
    if rows:
        print(f"first: {rows[0].get('date')}  {rows[0].get('title')}")
        print(f"last:  {rows[-1].get('date')}  {rows[-1].get('title')}")
    print(f"missing date: {len(no_date)} {no_date[:5]}")
    print(f"missing title: {len(no_title)} {no_title[:5]}")


if __name__ == "__main__":
    main()
