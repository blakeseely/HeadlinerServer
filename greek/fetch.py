#!/usr/bin/env python3
"""Fetch the Greek Theatre (Berkeley) schedule — the venue adapter capture step.

Source: https://thegreekberkeley.com — the official **UC Berkeley** Greek Theatre
site (2001 Gayley, Berkeley, CA), run by **Another Planet Entertainment**
(same TicketWeb/WordPress platform as the Fox Oakland). It is fully
server-rendered (plain GET, no Cloudflare, no JS app). NOTE: the canonical
thegreek.com (the *full* season — theater/film/music) is hard-Cloudflare-blocked
for both curl and a real browser, so this official UC site is the open source.
It is APE's exclusive-promoter concert listing (the Greek's *music* shows),
currently a handful of upcoming concerts in one unpaginated listing.

Listing: https://thegreekberkeley.com/event-listing/ — one
<div class="mix detail-information"> card per show with the whole bill as
separate fields (no title grammar):
    date      <div class="single-date-show" itemprop="startDate"
               content="October 19, 2026 7:30 pm">
    tour      <div class="topline">…</div>   (may stack a banner line)
    headliner <h2 class="show-title" itemprop="name">…</h2>
    support   <div class="support">Act<br>Act</div>   (<br>-separated)
    times     <span class="event__doors-open">…</span>
               <span class="event__start-time">Show: …</span>
    tickets   <a class="button[ ghost][ soldout]" …>Buy Tickets</a>
    page      <a href="https://thegreekberkeley.com/events/<slug>">

Detail pages (/events/<slug>/) add the two things the listing lacks, fetched
incrementally by event_page (thread pool, cached in details.json): the age
line (the <div class="more-information"> block) and the <div class="bio">
per-artist description.

Output (cache/):
    shows.json     list of per-show records
    details.json   dict event_page -> {age, notice, bio}  (incremental)

Do NOT write a freshness stamp — the root update_all.py runner writes
cache/shows.json.fetched_at and skips the re-crawl when it is < 24h old.
"""
import os, re, html, json, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(CACHE, "shows.json")
DETAILS = os.path.join(CACHE, "details.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
LISTING_URL = "https://thegreekberkeley.com/event-listing/"
BASE = "https://thegreekberkeley.com"
DETAIL_MAX = 60          # safety valve for the detail pass


def fetch(url, retries=2):
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA,
                              "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(1.5)
    print(f"  ! fetch failed {url}: {last!r}")
    return None


def _text(fragment):
    """Tags -> text with entities unescaped. <br> becomes a real newline (so a
    multi-line support bill keeps its line breaks); other tags collapse to a
    space. Newlines are preserved (only [ \\t] are collapsed); empty -> None."""
    if not fragment:
        return None
    t = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n[ \t]+", "\n", t)
    t = re.sub(r"[ \t]*\n[ \t]*", "\n", t)   # keep single newlines
    t = t.strip()
    return t or None


def _block(src, start):
    """Source of the <div> that OPENS at `start`, via a balanced <div> depth
    counter (the Independent lesson: anchor on a stable container class, count
    only <div>, stop at its own close — a title-tag anchor never terminates)."""
    depth = 0
    for m in re.finditer(r"<div\b|</div>", src[start:]):
        if m.group() == "<div":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return src[start:start + m.end()]
    return src[start:]


def parse_cards(src):
    """Every <div class="mix detail-information"> card -> a per-show record."""
    rows, seen = [], set()
    for m in re.finditer(r'<div class="mix detail-information"', src):
        card = _block(src, m.start())

        dm = re.search(r'single-date-show"[^>]*content="([^"]*)"', card)
        date = dm.group(1) if dm else None
        top_m = re.search(r'class="topline"[^>]*>(.*?)</div>', card, re.S)
        head_m = re.search(r'<h2 class="show-title"[^>]*>(.*?)</h2>', card, re.S)
        sup_spans = re.findall(r'class="support"[^>]*>(.*?)</div>', card, re.S)
        doors_m = re.search(r'event__doors-open">([^<]*)', card)
        show_m = re.search(r'event__start-time">([^<]*)', card)
        btn_m = re.search(r'class="button[^"]*(?:soldout)?[^"]*"[^>]*>([^<]*)', card)
        btn_cls = re.search(r'class="(button[^"]*soldout[^"]*)"', card)
        href_m = re.search(r'href="(' + BASE + r'/events/[^"]+)"', card)

        # the venue's markup: Doors: <span>6:30 pm | </span> <span>Show: 7:30 pm</span>
        # -> strip the trailing " | " separator from doors and the "Show:" prefix.
        doors = _text(doors_m.group(1)) if doors_m else None
        if doors:
            doors = doors.replace(" |", "").strip() or None
        show_time = _text(show_m.group(1)) if show_m else None
        if show_time:
            show_time = re.sub(r"^\s*Show:\s*", "", show_time).strip() or None

        head = _text(head_m.group(1)) if head_m else None
        if not head:
            continue

        key = (date, head.lower())
        if key in seen:
            continue
        seen.add(key)

        # support: the venue <br>-separates each act — keep it as a LIST so
        # the build splits on the venue's own line breaks (not word "and").
        sup = [ _text(s) for s in sup_spans ]
        sup = [ s for s in sup if s ]

        rows.append({
            "date": date,
            "headliner": head,
            "tour": _text(top_m.group(1)) if top_m else None,
            "support": sup,
            "doors": doors,
            "show_time": show_time,
            "ticket_status": "sold out" if btn_cls else "on sale",
            "ticket_link": (html.unescape(btn_m.group(1)).strip() or None)
                            if btn_m else None,
            "event_page": html.unescape(href_m.group(1)) if href_m else None,
            "age": None,
            "notice": None,
            "bio": None,
        })
    return rows


def _date_iso(date_str):
    """'October 18, 2026 7:30 pm' -> '2026-10-18' (None if unparseable)."""
    if not date_str:
        return None
    m = re.match(r"([A-Za-z]+) (\d{1,2}), (\d{4})", date_str)
    if not m:
        return None
    months = {m2: i + 1 for i, m2 in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"])}
    mon = months.get(m.group(1))
    if not mon:
        return None
    return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"


def _clean_bio(raw):
    """Tags->text, then strip the calendar-widget / ad-script tail that the
    venue appends after the real bio on some shows."""
    if not raw:
        return None
    t = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    # cut at the first script-y / widget marker (jQuery(..., stLight, etc.)
    t = re.split(r"jQuery\(|stLight\.|window\.", t)[0]
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def _more_information(src):
    """The fixed 4-paragraph info block -> (age, notice).

    age    = the 'This event is <x>.' line (the only variable paragraph).
    notice = a venue-move / rebooking paragraph (present instead of the
             standard Telegraph-Room boilerplate on a couple of shows)."""
    i = src.find('<div class="more-information"')
    if i == -1:
        return None, None
    block = src[i:i + 4000]
    ps = [ _text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", block, re.S) ]
    ps = [ p for p in ps if p ]
    age = None
    for p in ps:
        m = re.match(r"This event is (?:recommended )?([^.]*?)\.", p, re.I)
        if m:
            age = m.group(1).strip()
            break
    notice = None
    for p in ps:
        if re.search(r"been moved|will be honored|rebooked|rescheduled|reschedule", p, re.I):
            notice = p[:600]
            break
    return age, notice


def _detail(src):
    """Detail page -> {age, notice, bio} (None values where absent)."""
    if not src:
        return {"age": None, "notice": None, "bio": None}
    age, notice = _more_information(src)
    bio = None
    bi = src.find('<div class="bio">')
    if bi != -1:
        block = _block(src, bi)
        bio = _clean_bio(block)
    return {"age": age, "notice": notice, "bio": bio}


def fetch_details(rows):
    """Fetch each show's detail page for age + bio. Incremental: cached
    event_pages are reused, only new ones hit the network. On re-fetch we keep
    the prior value if the new one is empty (a transient failure shouldn't
    clobber a good capture)."""
    have = {}
    if os.path.exists(DETAILS):
        try:
            have = json.load(open(DETAILS))
        except ValueError:
            have = {}
    todo = [r["event_page"] for r in rows
            if r.get("event_page") and r["event_page"] not in have]
    todo = todo[:DETAIL_MAX]
    if todo:
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(fetch, url): url for url in todo}
            for f in futs:
                url = futs[f]
                new = _detail(f.result())
                old = have.get(url, {})
                have[url] = {
                    "age": new.get("age") or old.get("age"),
                    "notice": new.get("notice") or old.get("notice"),
                    "bio": new.get("bio") or old.get("bio"),
                }
                time.sleep(0.3)   # be polite
    json.dump(have, open(DETAILS, "w"), indent=1, ensure_ascii=False)
    return have


def main():
    os.makedirs(CACHE, exist_ok=True)
    src = fetch(LISTING_URL)
    if src is None:
        raise SystemExit("could not fetch the /event-listing/ page")
    open(os.path.join(CACHE, "listing_raw.html"), "w").write(src)

    rows = parse_cards(src)
    details = fetch_details(rows)
    for r in rows:
        if r.get("event_page"):
            d = details.get(r["event_page"], {})
            r["age"] = d.get("age")
            r["notice"] = d.get("notice")
            r["bio"] = d.get("bio")

    rows.sort(key=lambda r: _date_iso(r.get("date")) or "")
    json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)
    n_bio = sum(1 for r in rows if r.get("bio"))
    n_age = sum(1 for r in rows if r.get("age"))
    n_sup = sum(1 for r in rows if r.get("support"))
    print(f"shows: {len(rows)}  (support: {n_sup}, age: {n_age}, bio: {n_bio}, "
          f"details cached: {len(details)})")
    for r in rows:
        print(f"  {_date_iso(r['date']) or '?':12}  {r['headliner'][:30]:30} "
              f"{str(r.get('age') or ''):18} {str(r.get('ticket_status') or ''):9} "
              f"{str(r.get('support') or '')[:24]}")


if __name__ == "__main__":
    main()
