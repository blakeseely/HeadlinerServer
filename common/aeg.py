"""Shared scraper for AEG Carbonhouse/AXS venue sites (discovered 2026-11-07).

Showbox Presents (showboxpresents.com, aggregate of The Showbox + Showbox
SoDo + shows PRESENTED at other venues) and Neumos (neumos.com, own site) are
both AEG Live Carbonhouse sites backed by AXS. The /events page server-
renders the first ~20 cards; older events load via
GET /events/events_ajax/<offset>, whose body is a JSON-ENCODED HTML STRING
(json.loads first — raw grep finds nothing and looks like the end of the
calendar while it is not). Walk until a page carries zero cards.

Bot-wall quirk: neumos.com 406s a full Chrome User-Agent (TLS-fingerprint
mismatch) but serves plain curl defaults — send NO custom UA here (the
inverse of the BGC lesson).

Two card flavors:
  A (showboxpresents): table rows — h5.accentColor=presenter, h5=tour,
     h3>a=headliner, h4=support ("with X, Y"), full dated `Sat, Nov 7, 2026`
     date, `Show 7:00 PM` time, a `@ Venue` label per card (the calendar
     MIXES venues: shows presented at WAMU/Moda/Roseland/Wonder Ballroom…
     must be filtered by that label — cross-venue bills belong to the other
     venue's own feed), button class `status_N` + text.
  B (neumos): `eventItem entry` — .promotion-text=presenter, h3.title>a
     headliner, h4.tagline=support ('+'-separated), .promotion-text.tour=tour,
     aria-label full date, `.time` "Doors: 7:00 PM" (that is DOORS, not the
     show), `.age` on card, button class `onsalenow` + data-canceled attr.

Detail pages (/events/detail/<id|slug>, server-rendered, fetch
incrementally) give the authoritative Time/Doors/Ages trio:
  flavor A: span.doors <label>Doors</label><label>7:00 PM</label>;
            li.age_res text; label Time value.
  flavor B: same structure.
Status: button text/class is the venue's vocabulary — enumerate and map
every variant, never default-on-sale (warfield lesson).
"""
import json
import re
import subprocess
import html as _html

UA = None  # curl default; do NOT impersonate Chrome here (neumos 406s it)


def _get(url):
    cmd = ["curl", "-sL", "--compressed", "-m", "25"]
    if UA:
        cmd += ["-A", UA]
    cmd.append(url)
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def _text(frag):
    t = re.sub(r"<[^>]+>", " ", frag)
    return _html.unescape(re.sub(r"\s+", " ", t)).strip()


DATE_RE = re.compile(r"(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(?P<day>\d{1,2}),?\s+(?P<yr>\d{4})", re.I)
MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def _iso(date_text):
    m = DATE_RE.search(date_text or "")
    if not m or m.group("mon").lower()[:3] not in MONTHS:
        return None
    mo = MONTHS[m.group("mon").lower()[:3]]
    return f"{m.group('yr')}-{mo:02d}-{int(m.group('day')):02d}"


def _cards_a(html):
    out = []
    # split on entry divs (alt/presents class variants tolerated — warfield alt? lesson)
    frags = re.split(r'<div class="entry(?:\s+[\w-]+)*\s+clearfix', html)
    for f in frags[1:]:
        pres = re.search(r'<h5 class="accentColor[^"]*"[^>]*>(.*?)</h5>', f, re.S)
        tour = re.search(r'<h5>\s*(?:<a[^>]*>)?([^<]+?)\s*(?:</a>)?\s*</h5>', f, re.S)
        head = re.search(r'<h3[^>]*>\s*<a[^>]*>(.*?)</a>', f, re.S)
        sup = re.search(r'<h4[^>]*>(.*?)</h4>', f, re.S)
        dt = re.search(r'class="date"[^>]*>(.*?)</span>\s*<span class="time"', f, re.S)
        tm = re.search(r'class="time"[^>]*>(?:\s*<span[^>]*></span>)?\s*(.*?)</span>', f, re.S)
        ven = re.search(r'class="venue"[^>]*>(?:<span[^>]*>@</span>)?\s*(.*?)</span>', f, re.S)
        btn = re.search(r'class="btn-tickets[^"]*?status_(\w+)[^"]*"[^>]*>(?:<i[^>]*></i>)?\s*([^<]+?)\s*</a>', f, re.S)
        href = re.search(r'href="(https://[^"]+/events/detail/\d+)"', f)
        axs = re.search(r'href="(https://www\.axs\.com/events/\d+/[^"]+)"', f)
        if not head:
            continue
        out.append({
            "flavor": "A",
            "presenter": _text(pres.group(1)) if pres else None,
            "tour": _text(tour.group(1)) if tour and _text(tour.group(1)) else None,
            "head": _text(head.group(1)),
            "support_raw": _text(sup.group(1)) if sup else None,
            "date": _iso(_text(dt.group(1)) if dt else ""),
            "time_raw": _text(tm.group(1)) if tm else None,
            "venue": _text(ven.group(1)) if ven else None,
            "status_code": btn.group(1) if btn else None,
            "btn_text": btn.group(2) if btn else None,
            "detail": href.group(1) if href else None,
            "ticket_ticket_link": axs.group(1) if axs else None,
        })
    return out


def _cards_b(html):
    out = []
    frags = re.split(r'<div class="eventItem entry(?:\s+[\w-]+)*\s+clearfix', html)
    for f in frags[1:]:
        pres = re.search(r'<div class="promotion-text">([^<]*)</div>', f)
        head = re.search(r'<h3[^>]*class="[^"]*title[^"]*"[^>]*>\s*<a[^>]*>(.*?)</a>', f, re.S)
        tag = re.search(r'<h4[^>]*class="[^"]*tagline[^"]*"[^>]*>(.*?)</h4>', f, re.S)
        tour = re.search(r'<div class="promotion-text tour">([^<]+)</div>', f)
        dl = re.search(r'class="date[^"]*"[^>]*aria-label="([^"]+)"', f)
        tm = re.search(r'<div class="time">([^<]+)</div>', f)
        age = re.search(r'<div class="age">([^<]+)</div>', f)
        btn = re.search(r'<a href="(https://www\.axs\.com/events/\d+/[^"]+)"[^>]*class="tickets ([^"]*)"[^>]*data-canceled="(\w+)"[^>]*data-nonbuy="(\w+)"[^>]*>\s*([^<]+?)\s*</a>', f, re.S)
        det = re.search(r'href="(?:https://www\.neumos\.com)?(/events/detail/[^"]+)"', f)
        if not head:
            continue
        out.append({
            "flavor": "B",
            "presenter": _html.unescape(pres.group(1)).strip() if pres else None,
            "tour": _html.unescape(tour.group(1)).strip() if tour else None,
            "head": _text(head.group(1)),
            "support_raw": _text(tag.group(1)) if tag else None,
            "date": _iso(dl.group(1) if dl else ""),
            "time_raw": _html.unescape(tm.group(1)).strip() if tm else None,
            "venue": None,
            "status_code": (btn.group(2) + "|c=" + btn.group(3) + "|nb=" + btn.group(4)) if btn else None,
            "btn_text": btn.group(5) if btn else None,
            "detail": ("https://www.neumos.com" + det.group(1)) if det else None,
            "ticket_ticket_link": btn.group(1) if btn else None,
            "age_card": _html.unescape(age.group(1)).strip() if age else None,
        })
    return out


def fetch_calendar(base):
    """Full upcoming calendar cards for an AEG venue site (both flavors)."""
    html0 = _get(base.rstrip("/") + "/events/")
    cards0 = _cards_a(html0) + _cards_b(html0)
    cards = list(cards0)
    # The ajax window equals the first-page size: Showbox renders 20, Neumos
    # 12 — a fixed step of 20 silently returns an empty window at offset 20
    # for a 12-page site and the calendar ends truncated (neumos shipped 12
    # of ~24 events; caught by the cleanroom validator 2026-11-07).
    step = len(cards0) or 20
    off, prev_sig = step, None
    while off <= 400:
        raw = _get(f"{base.rstrip('/')}/events/events_ajax/{off}")
        try:
            html = json.loads(raw)
        except Exception:
            html = raw
        if isinstance(html, dict):
            html = html.get("html", "")
        if not isinstance(html, str):
            break
        page = _cards_a(html) + _cards_b(html)
        if not page:
            break
        cards.extend(page)
        sig = {c["detail"] or (c["head"], c["date"]) for c in page}
        if sig == prev_sig:
            break  # offset clamped at the last page
        prev_sig = sig
        off += step
    # dedup by detail url
    seen, out = set(), []
    for c in cards:
        k = c["detail"] or (c["head"], c["date"])
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


def fetch_detail(url):
    """Detail page → {doors, show_time, age, status_text} or None."""
    h = _get(url)
    if not h:
        return None
    out = {}
    m = re.search(r'<span class="[^"]*doors[^"]*"[^>]*>\s*<label[^>]*>Doors</label>\s*<label>([^<]+)</label>', h)
    if m:
        out["doors"] = _html.unescape(m.group(1)).strip()
    m = re.search(r'<span class="[^"]*text-large[^"]*"[^>]*>\s*<label>Time</label>\s*([^<]+)</span>', h)
    if m:
        out["show_time"] = _html.unescape(m.group(1)).strip()
    m = re.search(r'class="age_res"[^>]*>([^<]+)<', h)
    if m:
        out["age"] = _html.unescape(m.group(1)).strip()
    m = re.search(r'class="btn-?tickets?[^"]*"[^>]*>(?:<i[^>]*></i>)?\s*([^<]{3,40}?)\s*</a>', h)
    if m:
        out["status_text"] = _html.unescape(m.group(1)).strip()
    return out or None


# ---------------------------------------------------------------- build side

def map_status(code, btn_text, detail_status=None):
    """AEG button vocabulary, enumerated 2026-11-07:
    flavor A codes 1(Buy/Coming Soon) 2(Cancelled) 6(Get Tickets);
    flavor B classes onsalenow + data-canceled/data-nonbuy attrs.
    Unknown texts pass through VERBATIM (never default-on-sale)."""
    t = (btn_text or detail_status or "").strip().lower()
    if "cancel" in t:
        return "cancelled"
    if "sold" in t:
        return "sold out"
    if "postpon" in t or "reschedul" in t:
        return "postponed"
    if "coming soon" in t:
        return "coming soon"
    if "buy" in t or "get ticket" in t or "tickets" in t:
        return "on sale"
    if "|c=true" in (code or ""):
        return "cancelled"
    return t or None


def _norm_time(t):
    if not t:
        return None
    t = re.sub(r"(?i)^(show|doors)\s*:?\s*", "", t.strip())
    m = re.match(r"(?i)^(\d{1,2})(?::(\d{2}))?\s*(a|p)\.?\s*m\.?\s*$", t)
    if not m:
        return t
    mm = m.group(2)
    mm = "" if mm == "00" else mm
    return f"{int(m.group(1))}{(':'+mm) if mm else ''}{m.group(3).lower()}m"


def _norm_age(a):
    if not a:
        return None
    a = re.sub(r"\s+", " ", a).strip()
    if re.match(r"(?i)^all ages( to enter)?(,\s*21(&| and )?\s*(over )?to drink)?\.?$", a):
        return "All Ages to Enter, 21+ to Drink"
    return a


def build_shows(cards, details, venue_label, common_build, apple_music, bill,
                spotify, lookup_cache, spotify_cache):
    """AEG cards -> feed rows for ONE venue. venue_label None = take all
    cards (dedicated-site venues like Neumos); otherwise keep only cards
    whose @-label matches (the Showbox aggregate mixes venues)."""
    import datetime
    today = datetime.date.today().isoformat()
    lookup = apple_music.load_lookup_cache(lookup_cache)
    shows = []
    for c in cards:
        if not c["head"] or not c["date"] or c["date"] < today:
            continue
        if venue_label and (c.get("venue") or "").strip() != venue_label:
            continue
        d = details.get(c["detail"] or "") or {}
        # Billed title: head + support tail — proven parse_bill grammar.
        # Unannounced-support placeholders are NOT billing ("Amtrac with
        # Special Guests") — strip from the head AND never merge from the
        # support slot (2026-11-07: shipped as billed names).
        _boiler = r"(?i)[\s,:;-]*(?:with\s+|w/\s+)?(?:more\s+)?special\s+guests?(?:\s*[.!]?\s*(?:tba|to be announced))?\s*[.!]?\s*$"
        title = re.sub(_boiler, "", c["head"].strip()).strip()
        sup = (c.get("support_raw") or "").strip()
        if sup:
            sup = re.sub(r"(?i)^(with|w/|featuring|fx)\s*:?\s*", "", sup)
            sup = sup.replace(" + ", ", ")
            if re.sub(_boiler, "", sup).strip():
                title = f"{title} with {sup}"
        parsed = bill.parse_bill(title)
        heads = [h.strip(" -–—,.|:;") for h in parsed["heads"] if h.strip()] or [c["head"]]
        support = [s.strip(" -–—,.|:;") for s in parsed["support"] if s.strip()]
        tour = c.get("tour") or parsed.get("tour")
        if tour and _text(tour).lower() == title.lower():
            tour = None
        # times: flavor B card time is DOORS; details win where present
        card_time = c.get("time_raw") or ""
        doors = _norm_time(d.get("doors"))
        show_t = _norm_time(d.get("show_time"))
        if not doors and card_time.lower().startswith("doors"):
            doors = _norm_time(card_time)
        if not show_t and card_time.lower().startswith("show"):
            show_t = _norm_time(card_time)
        age = _norm_age(d.get("age") or c.get("age_card"))
        rec = common_build.show(
            event_type="music",
            needs_review=False,
            headline_artists=[apple_music.artist_obj(h, lookup) for h in heads],
            support_artists=[apple_music.artist_obj(s, lookup) for s in support],
            show_title=(tour.strip(" -–—,.|:;") or None) if tour else None,
            date=c["date"],
            doors=doors,
            show_time=show_t,
            ticket_link=c.get("ticket_ticket_link") or c.get("detail"),
            ticket_status=map_status(c.get("status_code"), c.get("btn_text"),
                                     d.get("status_text")) or "on sale",
            event_page=c.get("detail"),
            room=None,
            age_rating=age,
            note=None,
        )
        shows.append(rec)
    shows.sort(key=lambda s: (s.get("date") or "9999"))
    common_build.apply_spotify_lookup(shows, spotify_cache)
    from collections import Counter
    stats = {
        "event_types": dict(Counter(s["event_type"] for s in shows)),
        "apple_music": apple_music.apple_music_stats(shows),
        "spotify": spotify.stats(shows),
    }
    return shows, stats
