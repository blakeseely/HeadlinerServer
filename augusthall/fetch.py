#!/usr/bin/env python3
"""Fetch August Hall's schedule into cache/events.json.

Source: www.augusthallsf.com — a TicketWeb WordPress site. The /events/
listing (paginated, 20/page) gives the date + billed title + detail URL for
every show; each /tm-event/… detail page adds the full date, doors/show
times, age restriction, and on-sale status. All of it is server-side HTML
(no JSON-LD Event node, no JS data), so plain GETs work — verified with curl.

cache/events.json    list of {url, title, date, doors, show_time, age,
                     ticket_status, ticket_link} — one per show, newest
                     first as published. The root update_all runner writes
                     the events.json.fetched_at freshness stamp.
"""
import concurrent.futures
import html
import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://www.augusthallsf.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MAX_PAGES = 10
WORKERS = 3

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
     "oct", "nov", "dec"], 1)}


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def strip_tags(fragment):
    t = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


# ---------------------------------------------------------------- listing
def parse_listing(page_html):
    """(cards, max_page_linked). Cards: {url, title, month, day}."""
    cards = []
    for seg in re.split(r'(?=<div class="tw-image">)', page_html)[1:]:
        m = re.search(r'<a[^>]+href="([^"]+/tm-event/[a-z0-9-]+/)"', seg)
        if not m:
            continue
        url = m.group(1)
        # billed title = the anchor text of the tw-name link
        t = re.search(r'<div class="tw-name">.*?<a[^>]*>(.*?)</a>', seg, re.S)
        title = strip_tags(t.group(1)) if t else ""
        dm = re.search(r'tw-image-date">\s*([A-Za-z]+)\s*<span[^>]*>\s*(\d+)', seg)
        month = MONTHS.get(dm.group(1).lower()[:3]) if dm else None
        day = int(dm.group(2)) if dm else None
        cards.append({"url": url, "title": title,
                      "month": month, "day": day})
    maxp = max([int(p) for p in re.findall(r"events/page/(\d+)/", page_html)]
               or [1])
    return cards, maxp


def fetch_listing():
    cards, seen = [], set()
    page = 1
    while page <= MAX_PAGES:
        url = f"{BASE}/events/page/{page}/" if page > 1 else f"{BASE}/events/"
        raw = get(url)
        batch, maxp = parse_listing(raw)
        for c in batch:
            if c["url"] not in seen:
                seen.add(c["url"])
                cards.append(c)
        if not batch or maxp <= page:
            break
        page += 1
        time.sleep(0.3)
    return cards


# ---------------------------------------------------------------- details
DETAIL_FIELDS = {
    "date": r'class="tw-event-date-complete"[^>]*>(.*?)</',
    "doors": r'class="tw-event-door-time-complete"[^>]*>(.*?)</',
    "show_time": r'class="tw-event-time-complete"[^>]*>(.*?)</',
    "age": r'class="tw-age-restriction[^"]*"[^>]*>(.*?)</',
    "name": r'<div class="tw-name[^"]*"[^>]*>\s*<a[^>]*>(.*?)</a>',
}


def parse_detail(raw, fallback_url):
    rec = {"url": fallback_url}
    for field, pat in DETAIL_FIELDS.items():
        m = re.search(pat, raw, re.S)
        rec[field] = strip_tags(m.group(1)) if m else None
    rec["doors"] = re.sub(r"^[|\s:]+", "", rec.get("doors") or "") or None

    # ticket button: class carries the state, href the ticket link
    b = re.search(
        r'<a[^>]+class="[^"]*tw-buy-tix-btn[^"]*"[^>]*>(.*?)</a>', raw, re.S)
    status = None
    if b:
        cls_m = re.search(r'class="([^"]*)"', raw[b.start():b.end()])
        cls = cls_m.group(1) if cls_m else ""
        text = strip_tags(b.group(1)).lower()
        if "ended" in text or "ended" in cls:
            status = "sales ended"
        elif "sold" in text:
            status = "sold out"
        elif "coming" in text or "coming" in cls:
            status = "coming soon"
        elif "buy" in text or "on" in cls:
            status = "on sale"
        tm = re.search(r'href="(https://www\.ticketmaster\.com/[^"]+)"',
                       raw[b.start():b.end()])
        rec["ticket_link"] = tm.group(1) if tm else None
    rec["ticket_status"] = status
    return rec


def main():
    cards = fetch_listing()
    if not cards:
        raise SystemExit("no event cards found on the listing")
    print(f"listing: {len(cards)} shows")

    def do(url):
        for attempt in (1, 2, 3):
            try:
                rec = parse_detail(get(url), url)
                return rec
            except Exception as exc:  # retry transient network blips
                if attempt == 3:
                    print(f"  !! {url} failed: {exc}", flush=True)
                    return None
                time.sleep(1.5 * attempt)

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(do, c["url"]): c for c in cards}
        rows = []
        for fut in concurrent.futures.as_completed(futs):
            c = futs[fut]
            rec = fut.result()
            if rec is None:
                continue
            # the listing's billed title is the card title; the detail name
            # is the canonical spelling
            rec["title"] = rec.get("name") or c["title"]
            if c["month"] and c["day"] and not rec.get("date"):
                rec["month"], rec["day"] = c["month"], c["day"]
            rows.append(rec)

    order = {c["url"]: i for i, c in enumerate(cards)}
    rows.sort(key=lambda r: order.get(r["url"], 999))
    os.makedirs(os.path.join(HERE, "cache"), exist_ok=True)
    with open(os.path.join(HERE, "cache", "events.json"), "w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"saved {len(rows)} events -> cache/events.json "
          f"({sum(1 for r in rows if r.get('date'))} with full date)")


if __name__ == "__main__":
    main()
