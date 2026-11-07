#!/usr/bin/env python3
"""Fetch the Wonder Ballroom schedule (venue adapter capture step).

Source: wonderballroom.com — WordPress + the venue group's own "rhp-events"
plugin (Music Venue Properties: same shop as Roseland Theater). NO bot wall,
NO TEC REST API (it 404s) — but /events/ is FULLY server-rendered: all 35
upcoming shows in one GET, every field on the card. No pagination, no
detail crawl needed.

Card anatomy (one <div class = "col-12 eventWrapper rhpSingleEvent "> block
per show — note the venue template's spaces inside the attribute!):

    <a id = "eventTitle" href="/event/<slug>/wonder-ballroom/portland-oregon/">
        <h2 ...>BILLED TITLE</h2>                     <- head (+ tour tail)
    <h4 id="evSubHead">                                <- support clause or ''
    <div class="dateEvent ...">Friday, November 6      <- human date
    <div id="eventDate" ...>Fri, Nov 06, 2026          <- FULL date (use this)
    <div class="eventTagLine ...">Monqui Presents      <- promoter
    <span ...>Doors : 6:30 pm, Show : 7:30 pm          <- doors/show line
    <div class="eventAgeRestriction ...>all ages       <- age (verbatim)
    <span class="rhp-event__cost-text--list">$42.75 to $45
    <span id="ctaspan-..." class="rhp-event-cta on-sale">
        <a ... href="https://www.etix.com/...">Buy Tickets
    </span>

CTA status classes seen 2026-11-06: on-sale | sold-out | off-sale. The
billed title itself carries status prefixes the venue writes in the name:
"*CANCELLED* The Residents", "*Postponed* SiM", "**MOVED TO ROSELAND
THEATER** FROST CHILDREN" — kept VERBATIM here; build.py interprets them.

The same card is repeated in a mobile-view block: rows are deduped by
event_page URL, preferring the block that carries the CTA.

Output cache/shows.json: list of per-show records. Do NOT write a freshness
stamp — the root update_all.py runner writes cache/shows.json.fetched_at.
"""
import os, re, html, json, time, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7") + \
     (" AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36")
LIST = "https://wonderballroom.com/events/"
MONTHS = {m: i for i, m in enumerate(
    ("jan feb mar apr may jun jul aug sep oct nov dec".split()), 1)}


def fetch(url, retries=2):
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(1.5)
    print(f"  ! fetch failed {url}: {last!r}")
    return None


def _text(fragment):
    if not fragment:
        return None
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def parse_events(src):
    """eventWrapper blocks -> show records. The wrapper attribute literally
    reads `class = "col-12 eventWrapper rhpSingleEvent "` (spaces around
    the '=') — match it loosely and never 'fix' it."""
    starts = [m.start() for m in re.finditer(r'class\s*=\s*"col-12\s+eventWrapper\s+rhpSingleEvent\s*"', src)]
    raw_rows = []
    for i, s in enumerate(starts):
        blk = src[s: starts[i + 1] if i + 1 < len(starts) else s + 60000]

        def field(pat):
            m = re.search(pat, blk, re.S)
            return _text(m.group(1)) if m else None

        um = re.search(r'<a\s+id\s*=\s*"eventTitle"[^>]*href="([^"]+)"', blk)
        title = re.search(r'<a\s+id\s*=\s*"eventTitle"[^>]*>\s*<h2[^>]*>(.*?)</h2>', blk, re.S)
        title = _text(title.group(1)) if title else None
        if not um or not title:
            continue
        cta = re.search(r'class="rhp-event-cta\s+([a-z-]+)"', blk)
        href = re.search(r'class="rhp-event-cta\s+[a-z-]+">\s*<a[^>]*href="([^"]+)"', blk)
        doors_show = field(r'eventDoorStartDate[^>]*>(.*?)</div>')
        doors = show = None
        if doors_show:
            m = re.search(r"doors\s*:?\s*(\d{1,2}(?::\d{2})?\s*[ap]\.?\s*m\.?)", doors_show, re.I)
            if m:
                doors = re.sub(r"\s+", "", m.group(1)).lower()
            m = re.search(r"show\s*:?\s*(\d{1,2}(?::\d{2})?\s*[ap]\.?\s*m\.?)", doors_show, re.I)
            if m:
                show = re.sub(r"\s+", "", m.group(1)).lower()
        full_date = field(r'id="eventDate"[^>]*>\s*(.*?)</div>')
        date = None
        m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})", full_date or "")
        if m and m.group(1).lower()[:3] in MONTHS:
            date = f"{m.group(3)}-{MONTHS[m.group(1).lower()[:3]]:02d}-{int(m.group(2)):02d}"
        raw_rows.append({
            "date": date,
            "date_text": full_date,
            "head_billed": title,
            "support_billed": field(r'<h4\s+id="evSubHead"[^>]*>(.*?)</h4>'),
            "promoter": field(r'eventTagLine[^>]*>(.*?)</div>'),
            "doors": doors,
            "show_time": show,
            "age": field(r'<div\s+class\s*=\s*"eventAgeRestriction[^"]*"[^>]*>(.*?)</div>'),
            "cost": field(r'rhp-event__cost-text--list[^>]*>(.*?)</span>'),
            "cta_class": cta.group(1) if cta else None,
            "ticket_link": html.unescape(href.group(1)) if href else None,
            "event_page": html.unescape(um.group(1)),
        })
    # dedupe by event_page (the mobile-view repeat of every card): keep the
    # block carrying the CTA (real status + ticket link); first-seen elsewise
    by_url = {}
    for r in raw_rows:
        prev = by_url.get(r["event_page"])
        if prev is None or (r["cta_class"] and not prev["cta_class"]):
            by_url[r["event_page"]] = r
    rows = list(by_url.values())
    rows.sort(key=lambda r: r["date"] or "9999")
    return rows


def main():
    os.makedirs(CACHE, exist_ok=True)
    src = fetch(LIST)
    if src is None:
        raise SystemExit("FATAL: /events/ unreachable")
    with open(os.path.join(CACHE, "events.html"), "w", encoding="utf-8") as f:
        f.write(src)
    rows = parse_events(src)
    json.dump(rows, open(os.path.join(CACHE, "shows.json"), "w"),
              indent=1, ensure_ascii=False)
    print(f"event blocks -> rows: {len(rows)}")
    nod = [r for r in rows if not r["date"]]
    if nod:
        print(f"WARNING rows without a parsed date: {len(nod)}")
        for r in nod:
            print("    ", r["date_text"], r["head_billed"][:60])
    noc = [r for r in rows if not r["cta_class"]]
    if noc:
        print(f"rows with no CTA span (status unknown): {len(noc)}")
        for r in noc[:6]:
            print("    ", r["date"], r["head_billed"][:60])
    print("cta classes:", sorted({r["cta_class"] or '-' for r in rows}))
    if rows:
        print(f"first: {rows[0]['date']}  {rows[0]['head_billed'][:60]}")
        print(f"last:  {rows[-1]['date']}  {rows[-1]['head_billed'][:60]}")


if __name__ == "__main__":
    main()
