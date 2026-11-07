"""Shared scraper for the El Corazón / Funhouse site (discovered 2026-11-07).

Both Seattle punk rooms are run by one org and share ONE Webflow site
(elcorazonseattle.com — the pages brand themselves "El Corazon Funhouse",
Instagram funhouseseattle, ticketing opendate.io). /calendar is fully
server-rendered Webflow CMS: each `ec-col-item w-dyn-item` carries separate
structured fields — calendar-headliners, calendar-supports (comma list),
start-date ("November 7, 2026" full text), doors-cal, show-time-cal, venue,
and a hidden webflow-link <a> to the /shows/<slug> page. No JS, no API, no
pagination seen (64 upcoming items at discovery).

The venue field splits the feeds: 'El Corazón' and
'Mammoth NW Presents - El Corazón' (third-party-promoter nights at the
venue) belong to El Corazón; 'The Funhouse' to Funhouse. Match by substring
on "corazón"/"funhouse" (accent-fold first).

The show pages' "Get Tickets" button carries no stable opendate URL in the
calendar markup (and detail pages mostly list artist links), so ticket_link
stays None (polarishall precedent: honesty over fabricated links). No ticket
status vocabulary exists anywhere on the site — ticket_status None too.
calendar-supports is separate from calendar-headliners, but bills still go
through the proven parse_bill grammar (headliners field itself can hold
co-billed "A & B").
"""
import html as _html
import re
import subprocess

BASE = "https://www.elcorazonseattle.com"

MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def _get(url):
    return subprocess.run(
        ["curl", "-sL", "--compressed", "-m", "25", url],
        capture_output=True, text=True).stdout


def _fold(s):
    import unicodedata
    s = _html.unescape(s or "")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def _iso(date_text):
    m = re.match(r"(?i)([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", date_text or "")
    if not m or m.group(1).lower()[:3] not in MONTHS:
        return None
    return f"{m.group(3)}-{MONTHS[m.group(1).lower()[:3]]:02d}-{int(m.group(2)):02d}"


def _norm_time(t):
    if not t:
        return None
    m = re.match(r"(?i)^(\d{1,2})(?::(\d{2}))?\s*(a|p)\.?\s*m\.?\s*$", t.strip())
    if not m:
        return t
    mm = m.group(2)
    mm = "" if mm == "00" else mm
    return f"{int(m.group(1))}{(':'+mm) if mm else ''}{m.group(3).lower()}m"


_CALENDAR_EMPTY = ("w-dyn-bind-empty", "This is some text")


def _field(block, cls):
    m = re.search(rf'class="{cls}"[^>]*>\s*<div>(.*?)</div>', block, re.S)
    if not m:
        return ""
    raw = m.group(1)
    if any(k in raw for k in _CALENDAR_EMPTY):
        return ""
    return _fold(re.sub(r"<[^>]+>", "", raw))


def fetch_calendar():
    html = _get(BASE + "/calendar")
    blocks = re.findall(r'class="ec-col-item w-dyn-item"(.*?)(?=class="ec-col-item w-dyn-item"|</div>\s*</div>\s*<div class="w-dyn-empty|$)',
                        html + "</div>", re.S)
    out = []
    for b in blocks:
        head = _field(b, "calendar-headliners") or _field(b, "title")
        if not head:
            continue
        link = re.search(r'href="(/shows/[^"]+)"', b)
        out.append({
            "headliners": head,
            "supports": _field(b, "calendar-supports"),
            "date": _iso(_field(b, "start-date")),
            "doors": _norm_time(_field(b, "doors-cal")),
            "show_time": _norm_time(_field(b, "show-time-cal")),
            "venue": _field(b, "venue"),
            "detail": (BASE + link.group(1)) if link else None,
            "title": _field(b, "title") or head,
        })
    return out


def build_shows(cards, venue_substr, common_build, apple_music, bill,
                spotify, lookup_cache, spotify_cache, canonical=None):
    """Cards -> feed rows for the venue whose label contains venue_substr
    (accent-folded, case-insensitive). canonical = set of folded labels
    that ARE the plain venue; any other matched label ("Mammoth NW Presents
    - El Corazon") gets a promoter note. (First pass compared against the
    substring itself and flagged EVERY row — 2026-11-07.)"""
    import datetime
    today = datetime.date.today().isoformat()
    lookup = apple_music.load_lookup_cache(lookup_cache)
    needle = venue_substr.lower()
    shows = []
    for c in cards:
        if not c["date"] or c["date"] < today:
            continue
        if needle not in c["venue"].lower():
            continue
        # The Webflow calendar-supports field is ALREADY a clean comma list —
        # split it directly. Only the headliners field goes through the
        # bill grammar (it can hold compound "A and B" bills or a tour tail).
        # Routing supports through parse_bill mangles hyphenated names
        # ("Psycho-Frame" -> "Psycho" + a dropped "Frame, Volatile Ways" tour
        # tail; validator caught 2026-11-28/22, LOW support diffs).
        parsed = bill.parse_bill(c["title"] or c["headliners"])
        heads = [h.strip(" -–—,.|:;") for h in parsed["heads"] if h.strip()] or [c["headliners"].strip(" -–—,.|:;")]
        support = [s.strip(" -–—,.|:;") for s in parsed["support"] if s.strip()]
        for s in (c["supports"] or "").split(","):
            s = s.strip(" -–—,.|:;")
            if s and s.lower() not in {h.lower() for h in heads} and s.lower() not in {x.lower() for x in support}:
                support.append(s)
        tour = parsed.get("tour")
        if tour and tour.lower() == c["headliners"].lower():
            tour = None
        rec = common_build.show(
            event_type="music",
            needs_review=False,
            headline_artists=[apple_music.artist_obj(h, lookup) for h in heads],
            support_artists=[apple_music.artist_obj(s, lookup) for s in support],
            show_title=(tour.strip(" -–—,.|:;") or None) if tour else None,
            date=c["date"],
            doors=c["doors"],
            show_time=c["show_time"],
            ticket_link=None,
            ticket_status=None,
            event_page=c["detail"],
            room=None,
            age_rating=None,
            note=(f"Promoted as “{c['venue']}” (third-party series at this venue)."
                  if canonical and c["venue"].lower() not in canonical else None),
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
