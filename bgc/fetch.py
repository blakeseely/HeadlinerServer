#!/usr/bin/env python3
"""Fetch the Bill Graham Civic Auditorium schedule (venue adapter capture).

Source: https://billgrahamcivic.com/calendar — a fully server-rendered
listing (Another Planet Entertainment WordPress site, wpengine-hosted, NO
Cloudflare: plain GETs with a browser UA work). One GET returns every
upcoming show in the calendar (no pagination — the /event-listing page is
the same shows via a JS search widget; the /calendar article list is the
complete season, past shows fall off). Each show is an
<article class="event qtip"> card with clean structured fields:

    headliner   <h2 class="attraction_title show-title" itemprop="name">
    support     <div class="bottomline">Azzecca<br>DJ Holographic</div>
    date        <p class="event__start-date" content="YYYY-MM-DD HH:MM">
    doors/show  <span class="event__doors-open"> / <span class="event__start-time">
    ticket      <a class="mar-0 button [ghost soldout|custom]"> (Buy Tickets /
                Sold Out! / SHOW MOVED / SIGN UP / PRESALE 10/28)
    page        <a href="https://billgrahamcivic.com/events/<slug>">

The listing lacks the age rating, per-artist Spotify links, and a bio. The
detail pages (/events/<slug>) are server-rendered and carry all three:
  * age:  "This event is all ages." / "This event is 18 and over."
  * spotify: one <div class="attraction"> block per artist, each with a
    class="music" open.spotify.com link (common.spotify.extract_links,
    strategy A, handles it)
  * bio:  the headliner's <div class="bio"> paragraph (empty for some)

Detail pages are fetched incrementally (3 workers, cached in details.json
keyed by event_page; a page that published nothing stores spotify=None so
backfills stay finite).

Output (cache/):
  events.json   list of per-show records (id, date, doors, show_time,
                headliner, support_raw, age, ticket_status, ticket_link,
                event_page, description, spotify)
  details.json  dict event_page -> {age, spotify, description} (incremental)

Do NOT write a freshness stamp — the root update_all.py runner writes
cache/events.json.fetched_at and skips the re-crawl when it is < 24h old.
"""
import os, re, html, json, sys, time, datetime, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import spotify

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(CACHE, "events.json")
DETAILS = os.path.join(CACHE, "details.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
CALENDAR_URL = "https://billgrahamcivic.com/calendar"
BASE = "https://billgrahamcivic.com"
# Safety valve: the description pass must not grow without bound.
DETAIL_MAX = 60

# venue button text/state -> the shared ticket_status vocabulary
STATUS_MAP = {
    "buy tickets": "on sale",
    "sold out": "sold out",
    "show moved": "moved",
    "sign up": "sign up",
    "waiting list": "waitlist",
}
# "PRESALE 10/28" and friends: the button text is the status (free string)


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
    """Tags -> whitespace-collapsed text, entities unescaped. Newlines kept
    as single spaces (support acts are <br>-separated and re-split on
    newline/comma in the build)."""
    if not fragment:
        return None
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def _article(src, start):
    """Source of the <article> that OPENS at `start` (balanced depth count;
    the Independent lesson: count only the article tag, not all tags)."""
    depth = 0
    for m in re.finditer(r"<article\b|</article>", src[start:]):
        if m.group() == "<article":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return src[start:start + m.end()]
    return src[start:]


def parse_shows(src):
    """Every <article class="event qtip"> card -> a per-show record."""
    rows, seen = [], set()
    for m in re.finditer(r'<article class="event qtip" id="(\d+)"', src):
        card = _article(src, m.start())

        date_m = re.search(r'event__start-date[^>]*content="(\d{4}-\d{2}-\d{2})', card)
        head_m = re.search(r'show-title"[^>]*>(.*?)</h2>', card, re.S)
        head = _text(head_m.group(1)) if head_m else None
        if not head:
            continue
        href_m = re.search(r'href="(%s/events/[^"]+)"' % re.escape(BASE), card)
        page = html.unescape(href_m.group(1)) if href_m else None

        key = (date_m.group(1) if date_m else None, page or head.lower())
        if key in seen:
            continue
        seen.add(key)

        doors_m = re.search(r'event__doors-open">([^<]+)<', card)
        show_m = re.search(r'event__start-time">([^<]+)<', card)
        sup_m = re.search(r'class="bottomline">(.*?)</div>', card, re.S)
        btn_m = re.search(r'class="mar-0 button[^"]*"[^>]*>([^<]+)<', card)

        sup_raw = None
        if sup_m:
            # <br>-separated acts: preserve the line breaks for the build's
            # comma-split (a trailing "feat. A, B" line stays one entry).
            sup = re.sub(r"<br\s*/?>", "\n", sup_m.group(1))
            sup = html.unescape(re.sub(r"<[^>]+>", "\n", sup))
            lines = [re.sub(r"\s+", " ", l).strip() for l in sup.split("\n")]
            sup_raw = "\n".join(l for l in lines if l) or None

        status = None
        ticket_link = None
        if btn_m:
            label = btn_m.group(1).strip()
            status = STATUS_MAP.get(label.lower(), label)
            href = re.search(r'class="mar-0 button[^"]*"[^>]*href="([^"]+)"', card)
            if not href:
                href = re.search(r'href="([^"]+)"[^>]*class="mar-0 button[^"]*"', card)
            if href:
                ticket_link = html.unescape(href.group(1))
                if "ticketmaster.com" not in ticket_link and "ticketweb.com" not in ticket_link \
                        and "axs.com" not in ticket_link and "seetickets" not in ticket_link:
                    ticket_link = None  # a "SHOW MOVED"/"SIGN UP" button to our own page is not a ticket link

        rows.append({
            "id": m.group(1),
            "date": date_m.group(1) if date_m else None,
            "doors": _text(doors_m.group(1)) if doors_m else None,
            "show_time": _text(show_m.group(1)) if show_m else None,
            "headliner": head,
            "support_raw": sup_raw,
            "age": None,
            "ticket_status": status,
            "ticket_link": ticket_link,
            "event_page": page,
            "description": None,
            "spotify": None,
        })
    return rows


def _detail_fields(src):
    """Detail page -> {age, spotify, description} (all may be None)."""
    if not src:
        return {"age": None, "spotify": None, "description": None}
    age = None
    m = re.search(r"This event is ([^.<]+?)\.", src)
    if m:
        a = re.sub(r"\s+", " ", m.group(1)).strip()
        age_map = {"all ages": "All ages", "18 and over": "18+",
                   "21 and over": "21+", "20 and over": "20+",
                   "16 and over": "16+", "14 and over": "14+"}
        age = age_map.get(a.lower(), a)
    links = spotify.extract_links(src) or None
    # description: the headliner's bio paragraph (the FIRST non-empty
    # attraction block's bio — the page lists the headliner first).
    desc = None
    for blk in re.split(r'<div[^>]*class="[^"]*attraction[^"]*"', src)[1:]:
        bio = re.search(r'<div class="bio">(.*?)</div>', blk, re.S)
        if bio:
            t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", bio.group(1))).strip()
            if len(t) >= 80:
                desc = t[:1500]
                break
    return {"age": age, "spotify": links, "description": desc}


def fetch_details(rows):
    """Fetch each show's detail page for age/spotify/description.
    Incremental: cached event_pages are reused; a page that published no
    spotify link stores spotify=None and is left alone (finite backfill)."""
    have = {}
    if os.path.exists(DETAILS):
        try:
            have = json.load(open(DETAILS))
        except ValueError:
            have = {}
    have = {k: v for k, v in have.items() if isinstance(v, dict) and "spotify" in v}
    todo = [r["event_page"] for r in rows
            if r.get("event_page") and r["event_page"] not in have]
    todo = todo[:DETAIL_MAX]
    if todo:
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(fetch, url): url for url in todo}
            for f in futs:
                url = futs[f]
                have[url] = _detail_fields(f.result())
                time.sleep(0.3)  # be polite
    json.dump(have, open(DETAILS, "w"), indent=1, ensure_ascii=False)
    return have


def main():
    os.makedirs(CACHE, exist_ok=True)
    src = fetch(CALENDAR_URL)
    if src is None:
        raise SystemExit("could not fetch the /calendar page")
    open(os.path.join(CACHE, "calendar_raw.html"), "w").write(src)

    rows = parse_shows(src)

    # Past shows fall off the calendar, but keep the capture honest: drop any
    # date strictly before today (a "SHOW MOVED" row can hold a stale date).
    today = datetime.date.today().isoformat()
    n_before = len(rows)
    rows = [r for r in rows if not r["date"] or r["date"] >= today]
    if len(rows) != n_before:
        print(f"dropped {n_before - len(rows)} past/moved row(s)")

    details = fetch_details(rows)
    for r in rows:
        d = details.get(r.get("event_page") or "") or {}
        r["age"] = d.get("age")
        r["spotify"] = d.get("spotify") or {}
        r["description"] = d.get("description")

    rows.sort(key=lambda r: (r.get("date") or "", r.get("show_time") or ""))
    json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)
    print(f"shows: {len(rows)} (with age: {sum(1 for r in rows if r['age'])}, "
          f"with spotify: {sum(1 for r in rows if r['spotify'])}, "
          f"with bio: {sum(1 for r in rows if r['description'])}, "
          f"detail pages cached: {len(details)})")
    if rows:
        print(f"first: {rows[0]['date']}  {rows[0]['headliner']}")
        print(f"last:  {rows[-1]['date']}  {rows[-1]['headliner']}")
    for r in rows[:12]:
        sup = (r["support_raw"] or "").replace("\n", ", ")
        print(f"  {r['date'] or '?'}  {r['headliner'][:30]:30} "
              f"{str(r.get('doors') or ''):12} {str(r.get('ticket_status') or ''):12} {sup[:28]}")


if __name__ == "__main__":
    main()
