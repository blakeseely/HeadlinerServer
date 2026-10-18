#!/usr/bin/env python3
"""Fetch the Warfield Theatre schedule (venue adapter capture step).

Source: https://www.thewarfieldtheatre.com/events/all  — an AEG/AXS venue
template, but UNLIKE theregencyballroom.com (whose /events path is a JS app
that 403s both curl and real browsers), the Warfield's listing is fully
server-rendered HTML. One plain GET (browser user-agent, no Cloudflare)
returns every upcoming show as a card. Each card carries the FULL bill as
four separate lines:

    <h5 class="accentColor">Goldenvoice Presents</h5>   presenter
    <h5>The Valley Girl Problems Tour</h5>             tour/show title
    <h3 class="carousel_item_title_small"><a>…</a></h3> headliner
    <h4>with GIRLSET</h4>                              support

plus the date, the show time, the ticket button (its `status_N` class +
label encodes on-sale / sold-out / coming-soon) and the AXS ticket URL.
So the listing alone is the complete, cleanly-structured backbone — no
JSON-LD Event node, no flight payload, no per-detail title parsing.

Detail pages (/events/detail/<id>/) add the two fields the listing lacks:
doors time and the age restriction (from the event's <ul class="details">).
Fetched one-per-show with a small thread pool, cached incrementally by
detail id so a reschedule/refresh only re-fetches what's new.

Output (cache/):
  events.json   list of per-show records (presenter, tour, headliner,
                support, date, show_time, doors, age, ticket_*, event_page)
  details.json  dict detail_id -> {doors, age, desc}  (incremental)
  events.json.fetched_at  stamp written by update_all.py after a successful
                fetch (the runner skips the re-crawl when it's < 24h old)

The Warfield bills live music only (rock / alt / K-pop / electronic /
theater-musical tours), so the build classifies everything `music` and
links every act to Apple Music.
"""
import os, re, html, json, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(CACHE, "events.json")
DETAILS = os.path.join(CACHE, "details.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
EVENTS_URL = "https://www.thewarfieldtheatre.com/events/all"
# Safety valve: the detail pass must not grow without bound.
DETAIL_MAX = 60


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
    """Tags -> whitespace-collapsed text, entities unescaped."""
    if not fragment:
        return None
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    t = re.sub(r"\s+", " ", t).strip(" \u00a0-–—:,.|;")
    return t or None


def _card(src, start):
    """Return the source of the <div> that OPENS at `start`, using a
    depth counter (the Independent lesson: a title-tag anchor never
    terminates with a naive counter; counting only <div> is safe here)."""
    depth = 0
    for m in re.finditer(r"<div\b|</div>", src[start:]):
        if m.group() == "<div":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return src[start:start + m.end()]
    return src[start:]


def parse_events(src):
    """Extract every event card -> per-show records (dedup by detail id)."""
    rows, seen = [], set()
    for m in re.finditer(r'<div class="entry\s+alt?\s*warfield clearfix\s*">', src):
        card = _card(src, m.start())

        did_m = re.search(r"/events/detail/(\d+)", card)
        did = did_m.group(1) if did_m else None
        if did and did in seen:
            continue
        if did:
            seen.add(did)

        pres_m = re.search(r'<h5 class="accentColor[^"]*">(.*?)</h5>', card, re.S)
        tour_m = re.search(r"<h5>(.*?)</h5>", card, re.S)
        head_m = re.search(
            r'<h3 class="carousel_item_title_small">\s*<a[^>]*>(.*?)</a>', card, re.S)
        sup_m = re.search(r"<h4[^>]*>(.*?)</h4>", card, re.S)
        date_m = re.search(r'<span class="date">\s*<span[^>]*></span>\s*(.*?)</span>', card, re.S)
        time_m = re.search(r'<span class="time">\s*<span[^>]*></span>\s*(.*?)</span>', card, re.S)
        btn_m = re.search(
            r'class="btn-tickets[^"]*status_(\d+)"[^>]*>(.*?)</a>', card, re.S)
        axs_m = re.search(r'href="(https://www\.axs\.com/events/[^"]+)"', card)

        if not head_m:
            continue

        status_text = _text(btn_m.group(2)) if btn_m else None
        if status_text:
            status = ("sold out" if "sold out" in status_text.lower()
                      else "coming soon" if "coming soon" in status_text.lower()
                      else "on sale")
        else:
            status = None

        rows.append({
            "detail_id": did,
            "event_page": (f"https://www.thewarfieldtheatre.com/events/detail/{did}"
                           if did else None),
            "presenter": _text(pres_m.group(1)) if pres_m else None,
            "tour": _text(tour_m.group(1)) if tour_m else None,
            "headliner": _text(head_m.group(1)) if head_m else None,
            "support": _text(sup_m.group(1)) if sup_m else None,
            "date": _text(date_m.group(1)) if date_m else None,
            "show_time": _text(re.sub(r"^\s*Show\s*", "", time_m.group(1))) if time_m else None,
            "doors": None,
            "age": None,
            "ticket_status": status,
            "ticket_link": axs_m.group(1) if axs_m else None,
            "description": None,
        })
    rows.sort(key=lambda r: (r.get("date") or ""))
    return rows


def parse_detail(src):
    """Detail page -> {doors, age, desc} (the fields the listing lacks)."""
    if not src:
        return None
    do = re.search(r'doors"><label class="block">Doors</label><label>(.*?)</label>', src, re.S)
    ag = re.search(r'age_res">(.*?)</div>', src, re.S)
    dt = re.search(r'<li class="date">\s*<label>Date</label>(.*?)</li>', src, re.S)
    de = re.search(r'<div[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</div>', src, re.S)
    rec = {
        "date_full": _text(dt.group(1)) if dt else None,
        "doors": _text(do.group(1)) if do else None,
        "age": _text(ag.group(1)) if ag else None,
        "desc": (_text(de.group(1))[:1500] if de else None),
    }
    return rec if any(rec.values()) else None


def fetch_details(rows):
    """Fetch each show's detail page for doors/age. Incremental: cached
    records (by detail id) are reused, only new ids hit the network."""
    have = {}
    if os.path.exists(DETAILS):
        try:
            have = json.load(open(DETAILS))
        except ValueError:
            have = {}
    todo = [r["detail_id"] for r in rows
            if r.get("detail_id") and r["detail_id"] not in have]
    todo = todo[:DETAIL_MAX]
    if todo:
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(fetch,
                              f"https://www.thewarfieldtheatre.com/events/detail/{did}"): did
                    for did in todo}
            for f in futs:
                did = futs[f]
                rec = parse_detail(f.result())
                if rec:
                    have[did] = rec
                    time.sleep(0.4)  # be polite
    json.dump(have, open(DETAILS, "w"), indent=1, ensure_ascii=False)
    return have


def main():
    os.makedirs(CACHE, exist_ok=True)
    src = fetch(EVENTS_URL)
    if src is None:
        raise SystemExit("could not fetch the events page")
    open(os.path.join(CACHE, "events_raw.html"), "w").write(src)

    rows = parse_events(src)
    details = fetch_details(rows)

    for r in rows:
        d = details.get(r.get("detail_id") or "")
        if d:
            r["doors"] = d.get("doors")
            r["age"] = d.get("age")
            r["date_full"] = d.get("date_full")
            r["description"] = d.get("desc")
    rows.sort(key=lambda r: (r.get("date_full") or r.get("date") or ""))

    json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)
    n_doors = sum(1 for r in rows if r.get("doors"))
    print(f"events: {len(rows)} (with doors: {n_doors}, detail pages: {len(details)})")
    if rows:
        print(f"first: {rows[0]['date']}  {rows[0]['headliner']}")
        print(f"last:  {rows[-1]['date']}  {rows[-1]['headliner']}")
    print("no date:", [r["headliner"] for r in rows if not r.get("date")][:5])
    for r in rows[:12]:
        print(f"  {r.get('date') or '?':18} {r['headliner'][:38]:38} "
              f"{str(r.get('doors') or ''):10} {str(r.get('ticket_status') or ''):11} "
              f"{r.get('support') or ''}")


if __name__ == "__main__":
    main()
