#!/usr/bin/env python3
"""Fetch the Cafe du Nord schedule (venue adapter capture step).

The venue rebuilt its site (2026-11): the old <li class="show-row"> cards are
gone. The /shows page is now a month calendar — <li class="cal-day has-shows"
data-date="YYYY-MM-DD"> holding <li class="cal-show cal-show--cdn|sah
is-on-sale|is-waitlist|is-sold-out|is-on-sale-soon" data-room="cdn|sah"> with a
headliner anchor, a show <time>, and a status/room badge. It carries date, room,
headliner, show time, and ticket status — but NOT the presenter, support acts,
doors, age, ticket link, or description.

The clean, complete source is the RSS feed: https://cafedunord.com/feed.xml.
Each <item> has a title "Headliner with Support · Tue Nov 17 · Cafe du Nord",
a detail-page <link>, a <category> (the room name), and a CDATA <description>
whose <p> lines carry:
    Live Nation presents
    Tue Nov 17, 2026. Doors 7 PM · Show 8 PM.
    Cafe du Nord · Downstairs        (or "Swedish American Hall · Upstairs")
    21+ · $32.42                     (or "All ages")
    Sold out                         (optional status line)
    An evening with                  (optional; "with" is in the title too)
    <support act name>               (optional; the line after that label)
    <show description paragraph>

So the design:
  * PRIMARY = RSS feed — the complete backbone (one room: "Cafe du Nord"
    downstairs + "Swedish American Hall" upstairs). It is structured, stable,
    and carries every field the HTML calendar omits, including support acts.
  * CROSS-CHECK = the /shows calendar — parsed for (date -> {name, room,
    show_iso, status, event_page}) and diffed against the feed to warn if the
    two disagree on room, status, or show time, or if a show is missing.
    If the feed is ever empty but the calendar has shows, we fall back to the
    calendar rows (enriched by the detail pass for what it lacks).
  * DETAIL PASS = per-show detail page (/shows/<slug>/) fetched incrementally
    (small thread pool, cached by event_page, bounded by DETAIL_MAX) for the
    ticket LINK (offers.url in the MusicEvent JSON-LD), the description, and
    the per-artist Spotify links (common.spotify.extract_links, which already
    knows the Cafe du Nord "listen__btn" markup). Reschedules/refresh only
    re-fetch pages never captured for spotify.

Output (cache/):
  shows.json    list of per-show records
  details.json  dict event_page -> {description, spotify}  (incremental)
  shows_raw.html  the raw /shows calendar (for debugging the new markup)

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
FEED_URL = "https://cafedunord.com/feed.xml"
BASE = "https://cafedunord.com"
# Safety valve: the detail pass must not grow without bound.
DETAIL_MAX = 60

ROOM_NAMES = {"cdn": "Cafe du Nord (downstairs)",
              "sah": "Swedish American Hall (upstairs)"}
# Ticket-status vocabulary used by build.py (normalize both sources to this).
STATUS_VALUES = {"on sale", "sold out", "waitlist", "on sale soon"}
# Calendar CSS status class -> canonical status.
CAL_STATUS = {"is-on-sale": "on sale", "is-waitlist": "waitlist",
              "is-sold-out": "sold out", "is-on-sale-soon": "on sale soon"}
# Room: the RSS <category> / description line names the room in words.
ROOM_BY_NAME = {"cafe du nord": "cdn", "swedish american hall": "sah"}


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


def _iso_day(t):
    """'2026-11-17T20:00:00-08:00' / '/shows/2026-11-17-<slug>' / any string
    containing an ISO date -> 'YYYY-MM-DD' (or None)."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _iso_datetime(t):
    """Calendar <time datetime> -> naive ISO 'YYYY-MM-DDTHH:MM' (or None)."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", t or "")
    return f"{m.group(1)}T{m.group(2)}" if m else None


def _time_from_display(disp, day_iso):
    """Display time like '7 PM' -> naive ISO using the event's day."""
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?", disp or "", re.I)
    if not m or not day_iso:
        return None
    h = int(m.group(1)); mi = int(m.group(2) or 0)
    ap = (m.group(3) or "").upper()
    if ap == "PM" and h != 12:
        h += 12
    elif ap == "AM" and h == 12:
        h = 0
    return f"{day_iso}T{h:02d}:{mi:02d}"


# ---------------------------------------------------------------------------
# RSS feed — the primary source
# ---------------------------------------------------------------------------

def _feed_items(src):
    return re.findall(r"<item>(.*?)</item>", src, re.S)


def _item_field(item, tag):
    m = re.search(r"<%s>(.*?)</%s>" % (tag, tag), item, re.S)
    return m.group(1).strip() if m else None


def _item_description_cdata(item):
    m = re.search(r"<description><!\[CDATA\[(.*?)\]\]></description>", item, re.S)
    if m:
        return m.group(1)
    m = re.search(r"<description>(.*?)</description>", item, re.S)
    return m.group(1) if m else None


def _split_title(title):
    """'Jammy Buffet · Tue Nov 17 · Cafe du Nord'
    -> (name_part 'Jammy Buffet', date_str 'Tue Nov 17', room_str 'Cafe du Nord').
    'LAYA with DJ Trauma · Wed Nov 18 · Cafe du Nord'
    -> ('LAYA with DJ Trauma', 'Wed Nov 18', 'Cafe du Nord').
    The title is HTML-entity-escaped in the feed (&apos; &amp; …); unescape it."""
    title = html.unescape(title or "")
    parts = [p.strip() for p in title.split("·")]
    if len(parts) < 3:
        return title, None, None
    return parts[0], parts[1], parts[2]


def _room_from_text(text):
    """Room key from a name/wording: 'Cafe du Nord · Downstairs' -> 'cdn'."""
    low = (text or "").lower()
    if "swedish american hall" in low or "upstairs" in low:
        return "sah"
    if "cafe du nord" in low or "downstairs" in low:
        return "cdn"
    return None


def _head_support(name_part):
    """'Internet Girl with OSHE' -> ('Internet Girl', 'OSHE').
    'LIPSTICK N' -> ('LIPSTICK N', None) — '&' / 'and' stay inside one act
    name; only a standalone ' with ' (or a leading '+') separates acts, and a
    support act never starts with a capitalized 'With' as a band name here.
    Returns (headliner, support_raw_or_None)."""
    s = (name_part or "").strip()
    if not s:
        return None, None
    # split on the FIRST standalone ' with ' (case-insensitive)
    m = re.match(r"^(.*?)\s+with\s+(.+)$", s, re.I)
    if m:
        head, sup = m.group(1).strip(), m.group(2).strip()
        if head:
            return head, sup or None
    # fallback: a leading '+ ' with no ' with '
    if s.startswith("+ "):
        sup = s[2:].strip()
        return sup or s, None
    return s, None


def _parse_feed_description(desc_cdata):
    """The RSS <description> CDATA -> dict of fields.
    The CDATA is a run of <p> blocks (the first is the event poster <img>).
    After splitting on </p> the lines are, in order: a short meta block
    (presenter, 'date. Doors X · Show Y.', 'Room · Floor', 'AGE · $price',
    optional status), an optional 'An evening with' label line + support line,
    then the show description paragraph."""
    if not desc_cdata:
        return {}
    # Split the CDATA into text lines at </p> boundaries; strip tags within.
    chunks = re.split(r"</p>", desc_cdata)
    lines = []
    for c in chunks:
        t = html.unescape(re.sub(r"<[^>]+>", " ", c))
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            lines.append(t)

    out = {"presenter": None, "doors": None, "show_time": None, "room": None,
           "age": None, "status": None, "price": None, "support": None,
           "description": None}
    if not lines:
        return out

    # presenter: first line that says '…presents' (short label line)
    for l in lines:
        if re.search(r"presents?\b", l, re.I) and len(l) < 40:
            out["presenter"] = l
            break

    # date + times line: 'Tue Nov 17, 2026. Doors 7 PM · Show 8 PM.'
    for l in lines:
        dm = re.search(r"([A-Z][a-z]{2} [A-Z][a-z]{2} \d{1,2}, \d{4})", l)
        if not dm and not re.search(r"Doors", l, re.I):
            continue
        doors_m = re.search(r"Doors\s+(\d{1,2}(?::\d{2})?\s*(?:AM|PM)?)", l, re.I)
        show_m = re.search(r"Show\s+(\d{1,2}(?::\d{2})?\s*(?:AM|PM)?)", l, re.I)
        if dm:
            out["date_hint"] = dm.group(0)
        if doors_m:
            out["doors"] = doors_m.group(1).strip()
        if show_m:
            out["show_time"] = show_m.group(1).strip()
        break

    # room line: 'Cafe du Nord · Downstairs' / 'Swedish American Hall · Upstairs'
    for l in lines:
        if "·" in l and _room_from_text(l):
            out["room"] = _room_from_text(l)
            out["room_line"] = l
            break

    # age / price line: '21+ · $32.42' / 'All ages · $30.36' / 'All ages'
    for l in lines:
        if re.search(r"\$\d", l) or re.search(r"\b21\+\b", l) or re.search(r"\bAll ages\b", l):
            am = re.search(r"\b(21\+|All ages)\b", l)
            pm = re.search(r"\$(\d+(?:\.\d+)?)", l)
            out["age"] = am.group(1) if am else None
            out["price"] = pm.group(0) if pm else None
            break

    # optional status line: exactly one of the known statuses
    for l in lines:
        if l.lower() in {"sold out", "on sale", "waitlist", "on sale soon"}:
            out["status"] = l.lower()
            break

    # support: an 'An evening with' label line — the support act is the next
    # short line (a real description paragraph is long, so a <60-char next
    # line is the act).
    for i, l in enumerate(lines):
        if re.search(r"^An (?:evening )?with\b", l, re.I):
            if i + 1 < len(lines) and len(lines[i + 1]) < 60:
                out["support"] = lines[i + 1]
            break

    # description: the longest line that is not a meta line
    meta = {out.get("presenter"), out.get("room_line"), out.get("support"),
            out.get("date_hint")}
    for l in lines:
        if len(l) > 80 and l not in meta:
            out["description"] = re.sub(r"\s+", " ", l).strip()
            break

    return out


def parse_feed(src):
    """RSS items -> per-show records (full data; dedup by date+headliner)."""
    rows, seen = [], set()
    for item in _feed_items(src):
        title = _item_field(item, "title")
        link = _item_field(item, "link")
        category = _item_field(item, "category")
        desc_cdata = _item_description_cdata(item)

        name_part, date_str, room_str = _split_title(title)
        d = _parse_feed_description(desc_cdata)

        # day: prefer the ISO year-month-day found in the date line, else the
        # detail-page slug (/shows/YYYY-MM-DD-<slug>) — both are reliable.
        day = _iso_day(d.get("date_hint") or "")
        if not day and link:
            day = _iso_day(link)
        if not day:
            continue  # can't place it on the calendar; build skips it anyway

        # room: the title's room NAME is authoritative (it names the hall);
        # the description room-line's "· Downstairs/Upstairs" floor text and
        # the <category> are weaker hints. The detail page's own room-tag
        # agrees with the feed (e.g. HARBOUR is in the eponymous Cafe du Nord
        # hall, not the upstairs hall the /shows calendar lists).
        room = _room_from_text(room_str) \
            or d.get("room") \
            or _room_from_text(category)
        if room not in ("cdn", "sah"):
            room = "cdn"

        head, support = _head_support(name_part)
        if not head:
            continue
        # support: prefer the description's support line if present, else the
        # title's 'with' tail.
        support_raw = d.get("support") or support
        if support_raw:
            support_raw = re.sub(r"^(?:with|and)\s+", "", support_raw, flags=re.I).strip()

        key = (day, head.lower())
        if key in seen:
            continue
        seen.add(key)

        doors = d.get("doors")
        show_time = d.get("show_time")
        # status: description line is authoritative; the title/room has none
        status = d.get("status")

        rows.append({
            "date": day,
            "room": room,
            "room_name": ROOM_NAMES.get(room),
            "presenter": d.get("presenter"),
            "headliner": head,
            "support_raw": support_raw or None,
            "doors": doors,
            "doors_iso": _time_from_display(doors, day),
            "show_time": show_time,
            "show_iso": _time_from_display(show_time, day),
            "age": d.get("age"),
            "ticket_status": status,
            "ticket_link": None,
            "event_page": link,
            "description": d.get("description"),
            "price": d.get("price"),
        })
    rows.sort(key=lambda r: (r.get("doors_iso") or r.get("date") or ""))
    return rows


# ---------------------------------------------------------------------------
# HTML calendar — cross-check / fallback
# ---------------------------------------------------------------------------

def parse_calendar(src):
    """The /shows calendar -> {date: {name, room, show_iso, status, event_page}}
    (one entry per cal-show; a date with two rooms keeps the last — the feed
    is the source of truth and the calendar is only a structural check)."""
    cal = {}
    # Walk each cal-day, then its cal-show children.
    for day_m in re.finditer(
            r'<li class="cal-day\b[^"]*"[^>]*data-date="([^"]+)"[^>]*>(.*?)(?=<li class="cal-day\b|\Z)',
            src, re.S):
        date = day_m.group(1)
        day_body = day_m.group(2)
        for show_m in re.finditer(
                r'<li class="cal-show\b([^>]*)"[^>]*>(.*?)</li>(?=\s*</ul>|<li class="cal-show|\Z)',
                day_body, re.S):
            attrs, body = show_m.group(1), show_m.group(2)
            room = "sah" if "cal-show--sah" in attrs else "cdn"
            data_room = re.search(r'data-room="([^"]+)"', attrs)
            if data_room:
                room = data_room.group(1)
            status = None
            for cls, val in CAL_STATUS.items():
                if cls in attrs:
                    status = val
                    break
            name_m = re.search(r'cal-show__name"[^>]*>(.*?)</a>', body, re.S)
            time_m = re.search(r'cal-show__time" datetime="([^"]+)"[^>]*>(.*?)</time>', body, re.S)
            href_m = re.search(r'cal-show__name"\s+href="([^"]+)"', body)
            name = _text(name_m.group(1)) if name_m else None
            if not name:
                continue
            cal[date] = {
                "name": name,
                "room": room,
                "show_iso": _iso_datetime(time_m.group(1)) if time_m else None,
                "status": status,
                "event_page": (BASE + href_m.group(1)) if href_m else None,
            }
    return cal


def cross_check(rows, cal):
    """Diff the feed rows against the calendar; print warnings on disagreement."""
    if not cal:
        print("  (calendar cross-check skipped: no cal-day rows parsed)")
        return
    n_warn = 0
    for r in rows:
        c = cal.get(r["date"])
        if not c:
            continue
        if c.get("room") and c["room"] != r.get("room"):
            print(f"  ! ROOM mismatch {r['date']} {r['headliner']}: "
                  f"feed={r.get('room')} calendar={c.get('room')}")
            n_warn += 1
        if c.get("status") and r.get("ticket_status") and \
                c["status"] != r.get("ticket_status"):
            print(f"  ! STATUS mismatch {r['date']} {r['headliner']}: "
                  f"feed={r.get('ticket_status')} calendar={c['status']}")
            n_warn += 1
        if c.get("show_iso") and r.get("show_iso") and \
                c["show_iso"][:16] != r.get("show_iso", "")[:16]:
            print(f"  ! SHOW-TIME mismatch {r['date']} {r['headliner']}: "
                  f"feed={r.get('show_iso')} calendar={c['show_iso']}")
            n_warn += 1
    # shows on the calendar that the feed did not return
    feed_dates = {r["date"] for r in rows}
    for date, c in cal.items():
        if date not in feed_dates:
            print(f"  ! calendar-only show (missing from feed) {date} {c.get('name')}")
            n_warn += 1
    print(f"  calendar cross-check: {len(cal)} calendar days, {n_warn} warning(s)")


def calendar_rows(cal):
    """Build fallback rows from the calendar when the feed returns nothing."""
    rows = []
    for date in sorted(cal):
        c = cal[date]
        rows.append({
            "date": date,
            "room": c.get("room"),
            "room_name": ROOM_NAMES.get(c.get("room")),
            "presenter": None,
            "headliner": c.get("name"),
            "support_raw": None,
            "doors": None,
            "doors_iso": None,
            "show_time": None,
            "show_iso": c.get("show_iso"),
            "age": None,
            "ticket_status": c.get("status"),
            "ticket_link": None,
            "event_page": c.get("event_page"),
            "description": None,
            "price": None,
        })
    rows.sort(key=lambda r: (r.get("show_iso") or r.get("date") or ""))
    return rows


# ---------------------------------------------------------------------------
# Detail pass — ticket link, description, spotify (incremental)
# ---------------------------------------------------------------------------

def _detail_fields(src):
    """Detail page -> {description, ticket_link, spotify} from JSON-LD + links."""
    if not src:
        return {"description": None, "ticket_link": None, "spotify": None}
    desc = ticket = None
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', src, re.S):
        try:
            d = json.loads(m.group(1))
            tl = d.get("@type")
            tl = [tl] if isinstance(tl, str) else tl
            if "MusicEvent" in tl:
                if d.get("description"):
                    desc = re.sub(r"\s+", " ", d["description"]).strip()[:1500]
                off = d.get("offers")
                if isinstance(off, list) and off:
                    off = off[0]
                if isinstance(off, dict) and off.get("url"):
                    ticket = off["url"]
        except ValueError:
            continue
    return {"description": desc, "ticket_link": ticket,
            "spotify": (spotify.extract_links(src) or None)}


def fetch_details(rows):
    """Fetch each show's detail page (ticket link, description, spotify).
    Incremental: pages already captured for spotify are reused; only new pages
    hit the network (bounded by DETAIL_MAX)."""
    have = {}
    if os.path.exists(DETAILS):
        try:
            have = json.load(open(DETAILS))
        except ValueError:
            have = {}
        # normalize legacy entries (slug -> description string) to dicts
        have = {k: (v if isinstance(v, dict) else
                    {"description": v, "spotify": None, "ticket_link": None})
                for k, v in have.items()}
    # Re-crawl a page when it was never captured for spotify, or when an
    # earlier crawl pre-dates the ticket-link field (ticket_link key absent
    # / not set). A page that published no link stores the keys with null
    # values and is left alone — key-presence checks keep the backfill
    # finite.
    todo = [r["event_page"] for r in rows
            if r.get("event_page")
            and (r["event_page"] not in have
                 or not isinstance(have[r["event_page"]], dict)
                 or "spotify" not in have[r["event_page"]]
                 or have[r["event_page"]].get("ticket_link") is None)]
    todo = todo[:DETAIL_MAX]
    if todo:
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(fetch, url): url for url in todo}
            for f in futs:
                url = futs[f]
                src = f.result()
                have[url] = _detail_fields(src)
                time.sleep(0.3)  # be polite
    json.dump(have, open(DETAILS, "w"), indent=1, ensure_ascii=False)
    return have


def main():
    os.makedirs(CACHE, exist_ok=True)

    # primary: the RSS feed
    feed_src = fetch(FEED_URL)
    feed_rows = parse_feed(feed_src) if feed_src else []

    # cross-check: the /shows calendar (always saved for debugging)
    cal_src = fetch(SHOWS_URL)
    if cal_src is not None:
        open(os.path.join(CACHE, "shows_raw.html"), "w").write(cal_src)
    cal = parse_calendar(cal_src) if cal_src else {}

    if feed_rows:
        rows = feed_rows
        cross_check(rows, cal)
    else:
        # feed unavailable/empty — fall back to the calendar (coarser)
        print("  ! RSS feed returned no rows; falling back to the HTML calendar")
        rows = calendar_rows(cal)
        if not rows:
            raise SystemExit("could not fetch the feed or the /shows calendar")

    # detail pass: ticket link + description + spotify (incremental)
    details = fetch_details(rows)
    for r in rows:
        if r.get("event_page"):
            d = details.get(r["event_page"]) or {}
            r["description"] = r.get("description") or d.get("description")
            r["ticket_link"] = r.get("ticket_link") or d.get("ticket_link")
            r["spotify"] = d.get("spotify") or {}

    rows.sort(key=lambda r: (r.get("doors_iso") or r.get("show_iso") or r.get("date") or ""))
    json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)

    n_desc = sum(1 for r in rows if r.get("description"))
    n_sah = sum(1 for r in rows if r.get("room") == "sah")
    n_ticket = sum(1 for r in rows if r.get("ticket_link"))
    print(f"shows: {len(rows)} (sah/upstairs: {n_sah}, with description: {n_desc}, "
          f"with ticket link: {n_ticket}, detail pages cached: {len(details)})")
    if rows:
        print(f"first: {rows[0]['date']}  {rows[0]['headliner']}")
        print(f"last:  {rows[-1]['date']}  {rows[-1]['headliner']}")
    for r in rows[:12]:
        print(f"  {r.get('date') or '?'}  {r['headliner'][:32]:32} "
              f"{str(r.get('doors') or ''):8} {str(r.get('ticket_status') or ''):11} "
              f"{str(r.get('support_raw') or '')[:24]}")


if __name__ == "__main__":
    main()
