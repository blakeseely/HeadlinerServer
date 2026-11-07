"""TicketWeb scraper for The Crocodile (discovered 2026-11-07).

The Crocodile's own Squarespace site is DEAD as a calendar (placeholder
"Event Five" markup, upcoming:[]); the venue's primary-ticket platform is
TicketWeb, venue id 10352:

    https://www.ticketweb.com/venue/the-crocodile-seattle-wa/10352

TicketWeb's edge (Fastly + its own bot manager) 502/403s bare curl AND a
headless-browser session from the same IP, but passes a full browser header
set from curl (no JS needed!). Send the HEADERS below verbatim or get walls.

The venue page server-renders up to ~10 upcoming shows as an inline JSON-LD
LIST of MusicEvent/TheaterEvent blocks (correct local startDate clocks —
unlike STG's MEC). The longer calendar is hydrated client-side by an Angular
XHR whose endpoint lives in a lazily-loaded bundle we could not pin down on
2026-11-07; until found, the feed's horizon is the LD window (~10 newest on
sales, refreshing nightly — Casbah-tier honesty, all real). If you later
find the full-schedule endpoint, extend fetch_events() and note it here.

eventStatus vocabulary seen: EventScheduled (others = schema.org Cancelled/
Postponed mapped; unknown verbatim). offers carries price/currency/availability.
"""
import json
import re
import subprocess

VENUE_URL = "https://www.ticketweb.com/venue/the-crocodile-seattle-wa/10352"

HEADERS = [
    "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "-H", "Accept-Language: en-US,en;q=0.9",
]


class TicketWebBlocked(Exception):
    pass


def fetch_page(url=VENUE_URL):
    r = subprocess.run(["curl", "-s", "--compressed", "-m", "30"] + HEADERS + [url],
                       capture_output=True, text=True)
    h = r.stdout
    if "ld+json" not in h:
        raise TicketWebBlocked(
            "no ld+json in body (bot-wall/interstitial) — TicketWeb paused "
            "this fingerprint; do NOT retry-loop, wait for the wall TTL")
    return h


def fetch_events(html=None):
    """-> list of LD event dicts (upcoming, venue page order)."""
    h = html or fetch_page()
    out = []
    for L in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', h, re.S):
        try:
            j = json.loads(L, strict=False)
        except ValueError:
            continue
        for x in (j if isinstance(j, list) else [j]):
            if isinstance(x, dict) and "Event" in str(x.get("@type")) and x.get("startDate"):
                out.append(x)
    return out


def map_status(ld):
    st = str(ld.get("eventStatus") or "")
    offers = ld.get("offers") or {}
    avail = str(offers.get("availability") or "")
    if "Cancelled" in st:
        return "cancelled"
    if "Postponed" in st or "Rescheduled" in st:
        return "postponed"
    if "SoldOut" in avail:
        return "sold out"
    if "EventScheduled" in st or "Scheduled" in st:
        return "on sale"
    if not st:
        # TicketWeb's venue LD window omits eventStatus for plain on-sales
        # (verified 2026-11-07: 9/10 events had no status key at all; the
        # sold-out branch above already claimed the ones that have offers)
        return "on sale"
    return st.replace("https://schema.org/", "").lower() or None
