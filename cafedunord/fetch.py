#!/usr/bin/env python3
"""Fetch the Cafe du Nord schedule (venue adapter capture step).

Source: https://cafedunord.com/shows — a fully server-rendered listing. One
plain GET (browser user-agent, no Cloudflare, no JS app) returns every
upcoming show across BOTH rooms. Each is a clean <li class="show-row"> card:

    <li data-room="cdn|sah" data-date="YYYY-MM-DD" data-status="on-sale|waitlist"
        data-age="all-ages|21+">
      presenter   <p class="show-row__presenter">Live Nation presents</p>
      headliner   <h3 class="show-row__headliner"><a>…</a></h3>
      support     <p class="show-row__support"><span class="act">with X</span>…</p>
      times       <span class="show-times__doors">Doors <time>…</time>
                  <span class="show-times__show">Show <time>…</time>
      room        <span class="room-tag room-tag--cdn|sah">Cafe du Nord|Swedish American Hall</span>
      tickets     <a class="btn btn--secondary|tertiary show-row__btn" href="…ticketweb…">

The listing is the complete backbone (one room: 39 "Cafe du Nord"
downstairs shows + 7 "Swedish American Hall" upstairs shows; dates are ISO in
data-date). Only the show DESCRIPTION is missing from the listing — the
detail pages (/shows/<slug>/) each carry a full schema.org MusicEvent
JSON-LD (performer, ISO doorTime/startDate, description, offers). We fetch
those (small thread pool, cached incrementally by slug) for the description
and nothing else; reschedule/refresh only re-fetches new slugs.

Output (cache/):
  shows.json    list of per-show records (date, room, presenter, headliner,
                support, doors, show_time, age, ticket_status, ticket_link,
                event_page, description)
  details.json  dict slug -> description  (incremental)

Do NOT write a freshness stamp — the root update_all.py runner writes
cache/shows.json.fetched_at and skips the re-crawl when it is < 24h old.
"""
import os, re, html, json, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import spotify

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(CACHE, "shows.json")
DETAILS = os.path.join(CACHE, "details.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
SHOWS_URL = "https://cafedunord.com/shows"
BASE = "https://cafedunord.com"
# Safety valve: the description pass must not grow without bound.
DETAIL_MAX = 60

ROOM_NAMES = {"cdn": "Cafe du Nord (downstairs)", "sah": "Swedish American Hall (upstairs)"}


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
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def _li(src, start):
    """Return the source of the <li> that OPENS at `start`, using a balanced
    <li> depth counter (the Independent lesson: a title-tag anchor never
    terminates with a naive counter; counting only <li> is safe here)."""
    depth = 0
    for m in re.finditer(r"<li\b|</li>", src[start:]):
        if m.group() == "<li":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return src[start:start + m.end()]
    return src[start:]


def _time_pair(card, which):
    """'doors'/'show' -> (display, iso) from the <time> in the card."""
    m = re.search(r'show-times__%s">[^<]*<time datetime="([^"]*)"[^>]*>(.*?)</time>' % which,
                  card, re.S)
    if not m:
        return None, None
    return _text(m.group(2)), m.group(1)


def parse_shows(src):
    """Every <li class="show-row"> card -> a per-show record (dedup by date+headliner)."""
    rows, seen = [], set()
    for m in re.finditer(r'<li class="show-row\b[^"]*"\s', src):
        card = _li(src, m.start())

        def attr(name):
            mm = re.search(r'data-%s="([^"]*)"' % name, card)
            return mm.group(1) if mm else None

        date = attr("date")
        pres_m = re.search(r'show-row__presenter">(.*?)</p>', card, re.S)
        head_m = re.search(r'show-row__headliner"><a [^>]*>(.*?)</a>', card, re.S)
        href_m = re.search(r'show-row__headliner"><a href="([^"]+)"', card)
        sup_spans = re.findall(r'class="act"[^>]*>(.*?)</span>', card, re.S)
        doors, doors_iso = _time_pair(card, "doors")
        showtime, show_iso = _time_pair(card, "show")
        btn_m = re.search(r'show-row__btn" href="([^"]+)"', card)

        head = _text(head_m.group(1)) if head_m else None
        if not head:
            continue

        key = (date, head.lower())
        if key in seen:
            continue
        seen.add(key)

        # support: the venue splits acts across <span class="act"> (comma-
        # separated); join them back, strip the leading "with", split on ,/&/and.
        sup_raw = " ".join(_text(s) or "" for s in sup_spans).strip()
        sup_raw = re.sub(r"^(?:with|and)\s+", "", sup_raw, flags=re.I).strip()

        status = attr("status")
        status_map = {"on-sale": "on sale", "waitlist": "waitlist",
                      "sold-out": "sold out"}
        room = attr("room")
        age = attr("age")
        age_map = {"all-ages": "All ages", "21+": "21+"}

        event_page = (BASE + href_m.group(1)) if href_m else None
        rows.append({
            "date": date,
            "room": room,
            "room_name": ROOM_NAMES.get(room) if room else None,
            "presenter": _text(pres_m.group(1)) if pres_m else None,
            "headliner": head,
            "support_raw": sup_raw or None,
            "doors": doors,
            "doors_iso": doors_iso,
            "show_time": showtime,
            "show_iso": show_iso,
            "age": (age_map.get(age, age) if age else None),
            "ticket_status": (status_map.get(status, status) if status else None),
            "ticket_link": html.unescape(btn_m.group(1)) if btn_m else None,
            "event_page": event_page,
            "description": None,
        })
    rows.sort(key=lambda r: (r.get("doors_iso") or r.get("date") or ""))
    return rows


def _description(src):
    """Detail page -> description from the MusicEvent JSON-LD (or None)."""
    if not src:
        return None
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', src, re.S):
        try:
            d = json.loads(m.group(1))
            tl = d.get("@type")
            tl = [tl] if isinstance(tl, str) else tl
            if "MusicEvent" in tl and d.get("description"):
                t = re.sub(r"\s+", " ", d["description"]).strip()
                return t[:1500] or None
        except ValueError:
            continue
    return None


def fetch_details(rows):
    """Fetch each show's detail page for its description. Incremental: cached
    slugs (by event_page) are reused, only new ones hit the network."""
    have = {}
    if os.path.exists(DETAILS):
        try:
            have = json.load(open(DETAILS))
        except ValueError:
            have = {}
        # older cache shape (slug -> description string) -> {description, spotify}
        # (legacy entries get spotify=None = "not yet captured for spotify")
        have = {k: (v if isinstance(v, dict) else {"description": v, "spotify": None})
                for k, v in have.items()}
    # Re-crawl only pages never captured for spotify (the key is absent). A
    # page crawled that published no link stores spotify=None and is left
    # alone — a key-presence check makes the backfill finite.
    todo = [r["event_page"] for r in rows
            if r.get("event_page")
            and (r["event_page"] not in have
                 or not isinstance(have[r["event_page"]], dict)
                 or "spotify" not in have[r["event_page"]])]
    todo = todo[:DETAIL_MAX]
    if todo:
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(fetch, url): url for url in todo}
            for f in futs:
                url = futs[f]
                src = f.result()
                have[url] = {"description": _description(src),
                             "spotify": (spotify.extract_links(src) or None)
                             if src else None}
                time.sleep(0.3)  # be polite
    json.dump(have, open(DETAILS, "w"), indent=1, ensure_ascii=False)
    return have


def main():
    os.makedirs(CACHE, exist_ok=True)
    src = fetch(SHOWS_URL)
    if src is None:
        raise SystemExit("could not fetch the /shows page")
    open(os.path.join(CACHE, "shows_raw.html"), "w").write(src)

    rows = parse_shows(src)
    details = fetch_details(rows)
    for r in rows:
        if r.get("event_page"):
            d = details.get(r["event_page"]) or {}
            r["description"] = d.get("description")
            r["spotify"] = d.get("spotify") or {}

    rows.sort(key=lambda r: (r.get("doors_iso") or r.get("date") or ""))
    json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)
    n_desc = sum(1 for r in rows if r.get("description"))
    n_sah = sum(1 for r in rows if r.get("room") == "sah")
    print(f"shows: {len(rows)} (sah/upstairs: {n_sah}, with description: {n_desc}, "
          f"detail pages cached: {len(details)})")
    if rows:
        print(f"first: {rows[0]['date']}  {rows[0]['headliner']}")
        print(f"last:  {rows[-1]['date']}  {rows[-1]['headliner']}")
    for r in rows[:12]:
        print(f"  {r.get('date') or '?'}  {r['headliner'][:32]:32} "
              f"{str(r.get('doors') or ''):8} {str(r.get('ticket_status') or ''):9} "
              f"{str(r.get('support_raw') or '')[:24]}")


if __name__ == "__main__":
    main()
