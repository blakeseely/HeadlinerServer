#!/usr/bin/env python3
"""Fetch Brick & Mortar Music Hall's schedule into cache/events.json.

Source: www.brickandmortarmusic.com — a TicketWeb WordPress site (same
platform as August Hall). The /shows listing (NOT paginated: /page/N/ returns
the identical 21 shows — a thickbox-style "Next", not real pagination) gives,
per show, the billed title + doors + show time + age + ticket status + detail
URL + a compact MM.DD date. Each /tm-event/… detail page adds the FULL date
(with year — the listing's MM.DD has none), the canonical billed name (in the
<page> title), and the per-artist bio (plain <p>, no dedicated class).

All of it is server-side HTML (no JSON-LD Event node — the ld+json is only
Yoast's WebPage/Website graph), so plain GETs work with curl.

cache/events.json   list of {url, title, date, doors, show_time, age,
                    ticket_status, ticket_link, description} — one per show,
                    as published (oldest→newest). The root update_all runner
                    writes the events.json.fetched_at freshness stamp.
"""
import concurrent.futures
import html
import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://www.brickandmortarmusic.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MAX_PAGES = 6
WORKERS = 3


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def strip_tags(fragment):
    t = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def clean_time(s):
    """'7:00PM' -> '7:00 pm'; strip the 'Doors:' / 'Show:' label."""
    if not s:
        return None
    s = re.sub(r"^\s*(Doors|Show)\s*:\s*", "", s.strip())
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(?<=\d)(PM|AM)\b", lambda m: " " + m.group(1).lower(),
               s, re.I)
    return s.strip() or None


# ---------------------------------------------------------------- listing
def parse_listing(page_html):
    """(cards, max_page_linked). Card = one /shows event:
    {url, title, doors, show_time, age, status, mmdd}."""
    cards = []
    for seg in re.split(r'(?=<div class="tw-image">)', page_html)[1:]:
        m = re.search(r'href="([^"]+/tm-event/[a-z0-9-]+/)"', seg)
        if not m:
            continue
        url = m.group(1)
        name = re.search(r'<div class="tw-name">.*?<a[^>]*>(.*?)</a>',
                         seg, re.S)
        doors = re.search(r'tw-event-door-time">([^<]+)</span>', seg)
        show = re.search(r'tw-event-time">([^<]+)</span>', seg)
        age = re.search(r'tw-age-restriction">(.*?)<span class="tw-price"',
                        seg, re.S)
        mmdd = re.search(r'tw-event-date[^"]*">\s*(\d{1,2})\.(\d{1,2})', seg)
        # ticket button: class tail encodes the sale state
        status = None
        b = re.search(r'<a[^>]+class="[^"]*tw-buy-tix-btn[^"]*"[^>]*>', seg)
        if b:
            cls = b.group(0)
            if "tw_soldout" in cls:
                status = "sold out"
            elif "tw_ticketssold" in cls:
                status = "on sale"
        tlink = re.search(r'href="(https://www\.ticketweb\.com/event/[^"]+)"',
                          seg)
        cards.append({
            "url": url,
            "title": strip_tags(name.group(1)) if name else "",
            "doors": clean_time(strip_tags(doors.group(1)) if doors else None),
            "show_time": clean_time(strip_tags(show.group(1)) if show else None),
            "age": strip_tags(age.group(1)) if age else None,
            "ticket_status": status,
            "ticket_link": html.unescape(tlink.group(1)) if tlink else None,
            "mmdd": (int(mmdd.group(1)), int(mmdd.group(2))) if mmdd else None,
        })
    maxp = max([int(p) for p in re.findall(r"shows/page/(\d+)/", page_html)]
               or [1])
    return cards, maxp


def fetch_listing():
    cards, seen = [], set()
    page = 1
    while page <= MAX_PAGES:
        url = (f"{BASE}/shows/page/{page}/" if page > 1 else f"{BASE}/shows")
        raw = get(url)
        batch, maxp = parse_listing(raw)
        fresh = [c for c in batch if c["url"] not in seen]
        for c in batch:
            seen.add(c["url"])
        cards.extend(fresh)
        # the /shows listing is NOT actually paginated — /page/N/ returns the
        # same shows — so stop on the first non-growing page.
        if not fresh or maxp <= page:
            break
        page += 1
        time.sleep(0.3)
    return cards


# ---------------------------------------------------------------- details
def parse_detail(raw, fallback):
    rec = dict(fallback)
    # full date (with year) — the only thing the listing truly lacks
    d = re.search(r'class="tw-event-date[^"]*"[^>]*>\s*([^<]+?)\s*</', raw, re.S)
    rec["date"] = strip_tags(d.group(1)) if d else None
    # canonical billed name from the <page> title: "<Name> - Brick and Mortar…"
    t = re.search(r"<title>(.*?)\s*-\s*Brick and Mortar Music Hall.*?</title>",
                  raw, re.S)
    if t:
        rec["title"] = strip_tags(t.group(1)) or rec["title"]
    # description = the first real content paragraph (skip cookie-consent).
    # On these pages the bio is a plain <span><p> block; the consent UI is a
    # classed <p>. Pick the longest non-consent paragraph.
    best = None
    for m in re.finditer(r"<p([^>]*)>(.*?)</p>", raw, re.S):
        attrs, body = m.group(1), m.group(2)
        if "dnsc-" in attrs or "cookie" in attrs.lower():
            continue
        txt = strip_tags(body)
        if len(txt) < 40:
            continue
        if re.search(r"cookies?|consent|personal data|instagram|css/js|"
                     r"track", txt, re.I):
            continue
        if best is None or len(txt) > len(best):
            best = txt
    rec["description"] = best
    return rec


def main():
    cards = fetch_listing()
    if not cards:
        raise SystemExit("no event cards found on the listing")
    print(f"listing: {len(cards)} shows")

    def do(c):
        for attempt in (1, 2, 3):
            try:
                return parse_detail(get(c["url"]), c)
            except Exception as exc:  # retry transient network blips
                if attempt == 3:
                    print(f"  !! {c['url']} failed: {exc}", flush=True)
                    return dict(c, date=None, description=None)
                time.sleep(1.5 * attempt)

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(do, c): c for c in cards}
        rows = []
        for fut in concurrent.futures.as_completed(futs):
            rows.append(fut.result())

    order = {c["url"]: i for i, c in enumerate(cards)}
    rows.sort(key=lambda r: order.get(r["url"], 999))
    os.makedirs(os.path.join(HERE, "cache"), exist_ok=True)
    with open(os.path.join(HERE, "cache", "events.json"), "w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"saved {len(rows)} events -> cache/events.json "
          f"({sum(1 for r in rows if r.get('date'))} with full date, "
          f"{sum(1 for r in rows if r.get('description'))} with description)")


if __name__ == "__main__":
    main()
