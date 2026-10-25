#!/usr/bin/env python3
"""Fetch The Chapel schedule (https://thechapelsf.com/calendar/).

The Chapel is a Mission-District live-music venue (777 Valencia St; an old
mortuary). Its calendar page is a plain-GET WordPress page whose body is 12
server-rendered month tables (one per calendar month — the full season). Each
event card sits in a <td> and carries:

  * day number         <div class="fs-16 date-number">21</div>  (same <td>)
  * month + year       the table header, e.g. "October 2026"
  * title + link       <div class="... seetickets-calendar-event-title"><a>…</a>
  * support            <p class="supporting-talent">Supporting Talent: …</p>
  * doors / show       <p class="doortime-showtime">Show at 8PM</p> + doors line
  * buy / status       <a class="button-gettickets" aria-label="…on <Month D>">

The ticket link is the Seetickets page (wl.seetickets.us/event/…), which is
bot-walled (Cloudflare) — we keep it as the ticket_link/event_page but do NOT
scrape it. The Chapel's own site publishes no per-artist Spotify links, so this
venue has honest null Spotify (like Fillmore / GAMH / Warfield / August Hall /
Frost), not a Seetickets dependency.

Output: cache/events.json — one record per unique event (dedup on link).
"""
import os, re, json, html, urllib.request, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "cache", "events.json")
RAW = os.path.join(ROOT, "cache", "calendar_raw.html")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
URL = "https://thechapelsf.com/calendar/"

MONTHS = {n: i + 1 for i, n in enumerate(
    ["january", "february", "march", "april", "may", "june",
     "july", "august", "september", "october", "november", "december"])}
MONTHS_ABBR = {k[:3]: v for k, v in MONTHS.items()}


def fetch(url=URL):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def clean(s):
    if not s:
        return None
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _split_cards(tbl):
    """(cell_prefix, card_block) pairs. Each card's day number sits in a
    <div class="date-number"> that is a SIBLING BEFORE the card inside the same
    <td>. cell_prefix is the text from the card's own <td> open tag up to the
    card — i.e. exactly that cell's content before the card, which holds ONE
    date-number (the card's day).

    The window is bounded at the card's <td> start, NOT a fixed byte offset.
    An empty weekday cell is ~48 bytes, so a fixed 300-char lookback reaches
    back across 5-6 empty cells and re.search then returns the OLDEST
    date-number in the span — a date 1-6 days EARLY. (This was the Chapel
    stale-date bug: the raw HTML was correct, the window was not cell-scoped.)
    Bounding to the own <td> makes the window hold exactly the card's day."""
    starts = [m.start() for m in re.finditer(
        r'<div class="[^"]*seetickets-calendar-event-container[^"]*"', tbl)]
    out = []
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(tbl)
        td_starts = [m.start() for m in re.finditer(r'<td[\s>]', tbl[:s])]
        win = td_starts[-1] if td_starts else 0
        out.append((tbl[win:s], tbl[s:end]))
    return out


def parse(src):
    """Walk each month table; emit one record per event card."""
    # Split into month tables, tracking each table's header (month + year).
    blocks = re.split(
        r'(?=<table[^>]*class="[^"]*seetickets-calendar[^"]*")', src)
    rows, seen = [], set()
    for b in blocks[1:]:
        end = b.find("</table>")
        tbl = b[:end] if end > 0 else b
        # header = nearest "Month YYYY" text preceding the <table> tag
        pre = src[max(0, src.find(b) - 400):src.find(b)] if b in src else ""
        hm = re.search(r"([A-Za-z]{3,9})\s+(\d{4})", html.unescape(re.sub(r"<[^>]+>", " ", pre)))
        if not hm:
            continue
        mon = MONTHS.get(hm.group(1).lower())
        year = int(hm.group(2))
        if not mon:
            continue
        for cell_prefix, c in _split_cards(tbl):
            def g(pat, flags=0):
                m = re.search(pat, c, flags)
                return m.group(1) if m else None

            url = g(r'href="(https://wl\.seetickets\.us/event/[^"]+)"')
            if not url or url in seen:
                continue
            # The day number is a <div class="date-number"> SIBLING that
            # precedes the card inside the same <td> (never inside the card
            # block). cell_prefix spans exactly that <td>'s pre-card content,
            # so take the LAST date-number in it — the card's own day.
            days = re.findall(r'date-number[^>]*>\s*(\d{1,2})\s*<',
                              cell_prefix + c[:80])
            day = int(days[-1]) if days else None
            if day is None:
                dm2 = re.search(r'date-number[^>]*>\s*(\d{1,2})\s*<', c[:200])
                day = int(dm2.group(1)) if dm2 else None

            date = None
            if day:
                date = f"{year:04d}-{mon:02d}-{int(day):02d}"

            # ticket / event page + status. The buy button's own TEXT is the
            # status: "Buy Tickets" (on sale) / "Sold Out" / "More Info" (no
            # public sale — treat as None, not a real status).
            status = None
            btn = re.search(r'<(?:a|div)\s+[^>]*class="[^"]*button-gettickets[^"]*"[^>]*>(.*?)</(?:a|div)>', c, re.S)
            if btn:
                t = clean(btn.group(1))
                if t:
                    if re.search(r"sold\s*?out", t, re.I):
                        status = "sold out"
                    elif re.search(r"buy|tickets", t, re.I):
                        status = "on sale"
            # title (first event-title anchor); support; times
            title = clean(g(r'seetickets-calendar-event-title[^>]*>.*?<a[^>]*>(.*?)</a>', re.S))
            sup = clean(g(r'supporting-talent[^>]*>(.*?)</p>', re.S))
            # doors + show time: the doortime-showtime line holds "Show at X"
            # then a following line "Doors at Y".
            show_time = doors = None
            stm = re.search(r'(?i)Show\s+at\s+([A-Za-z0-9:]+)', c)
            dom = re.search(r'(?i)Doors\s+at\s+([A-Za-z0-9:]+)', c)
            if stm:
                show_time = stm.group(1)
            if dom:
                doors = dom.group(1)
            # age / price / genre (list cards only; may be absent)
            age = clean(g(r'class="ages"[^>]*>(.*?)</span>', re.S))

            rows.append({
                "url": url,
                "title": title,
                "date": date,
                "doors": doors,
                "show_time": show_time,
                "support": sup,
                "age": age,
                "ticket_link": url,
                "ticket_status": status,
                "aria_date": g(r'aria-label="[^"]*on\s+([A-Za-z]+ \d{1,2}(?:, \d{4})?)"'),
            })
            seen.add(url)
    rows.sort(key=lambda r: (r["date"] or "9999", r["doors"] or ""))
    return rows


def main():
    src = fetch()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(RAW, "w").write(src)
    rows = parse(src)
    # Cross-check: the venue's own aria-label carries the event date (yearless
    # "Dec 07"). The table date and the aria date must agree on month+day —
    # the only independent ground truth in the HTML. This is the tripwire that
    # catches window drift (the 2026-10 stale-date bug) on a nightly run.
    for r in rows:
        a, d = r.get("aria_date"), r.get("date")
        if a and d:
            parts = a.split()
            am = MONTHS_ABBR.get(parts[0].lower().rstrip(","))
            if am is not None:
                ad = int(parts[1])
                if (am, ad) != (int(d[5:7]), int(d[8:10])):
                    print(f"WARNING: aria/date disagree  {d}  aria='{a}'  {r['title']}")
    json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)
    no_date = [r["title"] for r in rows if not r["date"]]
    no_title = [r["title"] for r in rows if not r["title"]]
    print(f"events: {len(rows)}")
    if rows:
        print(f"first: {rows[0]['date']}  {rows[0]['title']}")
        print(f"last:  {rows[-1]['date']}  {rows[-1]['title']}")
    print(f"missing date: {len(no_date)} {no_date[:5]}")
    print(f"missing title: {len(no_title)} {no_title[:5]}")


if __name__ == "__main__":
    main()
