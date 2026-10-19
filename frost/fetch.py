#!/usr/bin/env python3
"""Fetch the Frost Amphitheater (Stanford University) schedule.

Source: https://live.stanford.edu — **Stanford Live**, the university's arts
organisation, is the promoter of record for the Frost Amphitheater's
ticketed concerts (the summer season). It is a client-rendered ("Made")
app, so the /events/calendar page HTML is empty — but the page renders from
a public JSON API:

    GET https://live.stanford.edu/api/events/Live

One GET returns the ENTIRE current season as a JSON array (no pagination,
no Cloudflare — curl works; the `Frost` boolean field the site itself uses
flags every Frost Amphitheater show). Each record carries the billed title
(+ presenter Prefix / series Suffix), a Summary, Tag list, EventLink (the
detail-page path), and Performances[] (ISO StartDate/EndDate + TicketLink).

The detail page (/events/<season>/frost/<slug>/) is fully SERVER-RENDERED
(plain GET) and supplies what the API lacks: the tour title line, the
per-date "Featured Artists:" support lists, the age line, and the artist
bio. Fetch it only for Frost shows, incrementally by URL.

Output (cache/):
    events.json   list of per-show records (the runner stamps this .fetched_at)
    details.json  dict event_page -> {tour, age, description, doors, ticket_status}

NOTE: the season is summer-heavy. In the off-season (fall/winter) the API's
`Frost` flag is false for everything and this venue correctly yields ZERO
shows — that is the expected, honest end state, not a bug.

Do NOT write a freshness stamp — the root update_all.py runner writes
cache/events.json.fetched_at and skips the re-crawl when it is < 24h old.
"""
import os, re, html, json, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(CACHE, "events.json")
DETAILS = os.path.join(CACHE, "details.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
API_URL = "https://live.stanford.edu/api/events/Live"
BASE = "https://live.stanford.edu"
FROST_VENUE = "Frost Amphitheater"
DETAIL_MAX = 60          # safety valve for the detail pass


def fetch(url, retries=2):
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA,
                              "Accept": "application/json, text/html",
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
    space. Newlines are preserved (only [ \t] are collapsed); empty -> None."""
    if not fragment:
        return None
    t = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n[ \t]+", "\n", t)
    t = re.sub(r"[ \t]*\n[ \t]*", "\n", t)
    t = t.strip()
    return t or None


def _block(src, start):
    """Source of the <div> that OPENS at `start`, via a balanced <div> depth
    counter (stop at its own close)."""
    depth = 0
    for m in re.finditer(r"<div\b|</div>", src[start:]):
        if m.group() == "<div":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return src[start:start + m.end()]
    return src[start:]


# ---------------------------------------------------------------------------
# API -> per-show record
# ---------------------------------------------------------------------------

def _pt(dt_str):
    """'2026-04-16 20:00:00' -> (iso_date, '8:00 pm') in Pacific-ish wall
    time (the site is Pacific; the API omits the zone). None if unparseable."""
    if not dt_str:
        return None, None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})", dt_str)
    if not m:
        return None, None
    iso = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    h, mi = int(m.group(4)), int(m.group(5))
    ampm = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    time = f"{h12}:{mi:02d} {ampm}"
    return iso, time


def is_frost(ev):
    """A Frost Amphitheater show: the site's own Frost flag, or a
    frost-venue / frost-slug fallback (guards against the flag being
    restructured)."""
    if ev.get("Frost") is True:
        return True
    venue = str(ev.get("Venue") or "")
    link = str(ev.get("EventLink") or "").lower()
    return (venue.strip().lower() == FROST_VENUE.lower()
            or "frost" in link)


def event_page(ev):
    link = ev.get("EventLink")
    if not link:
        return None
    link = html.unescape(link).strip()
    if link.startswith("/"):
        link = BASE + link
    if not link.endswith("/"):
        link = link.rstrip("/")
    return link


def parse_events(data):
    """Filter the season JSON to Frost shows -> per-show records."""
    rows, seen = [], set()
    for ev in data:
        if not is_frost(ev):
            continue
        title = html.unescape(ev.get("Title") or "")
        if not title:
            continue
        perfs = ev.get("Performances") or [{}]
        first = perfs[0]
        date, show_time = _pt(first.get("StartDate"))
        iso_dates = []
        for p in perfs:
            d, _ = _pt(p.get("StartDate"))
            if d and d not in iso_dates:
                iso_dates.append(d)
        # canonical (first / earliest) date
        if not date and iso_dates:
            date = iso_dates[0]
        ticket_link = None
        status = None
        for p in perfs:
            t = p.get("TicketLink")
            if t:
                ticket_link = t
                ttitle = (p.get("TicketLinkTitle") or "").lower()
                if "sold out" in ttitle:
                    status = "sold out"
                elif ttitle and "buy" in ttitle:
                    status = "on sale"
                break
        page = event_page(ev)
        if (page or (date, title.lower())) in seen:
            continue
        seen.add(page or (date, title.lower()))
        rows.append({
            "id": ev.get("ID"),
            "title": title,
            "display_title": html.unescape(ev.get("DisplayTitle") or "") or None,
            "prefix": html.unescape(ev.get("Prefix") or "") or None,
            "suffix": html.unescape(ev.get("Suffix") or "") or None,
            "summary": html.unescape(ev.get("Summary") or "") or None,
            "tags": [html.unescape(t) for t in (ev.get("Tag") or []) if t],
            "date": date,
            "dates": iso_dates or (None),
            "show_time": show_time,
            "formatted_date": html.unescape(ev.get("FormattedDate") or "") or None,
            "ticket_link": ticket_link,
            "ticket_status": status,
            "event_page": page,
            # detail-derived (filled by fetch_details):
            "tour": None,
            "age": None,
            "doors": None,
            "description": None,
            "support": None,
        })
    rows.sort(key=lambda r: (r.get("date") or ""))
    return rows


# ---------------------------------------------------------------------------
# Detail pages -> the fields the API lacks
# ---------------------------------------------------------------------------

def _clean_bio(raw):
    """Tags->text, then cut at a script/widget marker and collapse."""
    if not raw:
        return None
    t = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    t = re.split(r"jQuery\(|stLight\.|window\.|This performance is ticketed", t)[0]
    t = re.sub(r"\s+", " ", t).strip()
    # drop pure boilerplate / ticketing-fee sentences
    t = re.sub(r"This performance is ticketed by AXS[^\n]*", "", t)
    t = re.sub(r"subject to AXS service fees\.", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t or None


def _age(src):
    """The 'This event is 18+ …' line -> a short age rating (or None).
    Scoped to the visible message <p> (NOT raw src — that also matches the
    same phrase inside inline JS)."""
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", src, re.S):
        block = m.group(1)
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", block)))
        # a direct, tight age token (18+ / 16+ / all ages …) — the venue's own
        # wording. We do NOT try to parse the whole (long) sentence.
        m2 = re.search(r"This event is (\d{1,3}\+|all ages|every age|recommended for (?:all|everyone|kids|children))",
                       t, re.I)
        if m2:
            a = m2.group(1).strip(" .")
            if a and len(a) < 25:
                return a
    return None


def _doors(src):
    """'Gates open at 6:30 PM' / 'Doors open …' -> a clean doors string."""
    for m in re.finditer(r"(?:Gates|Doors) open(?:s)? at?\s*([0-9]{1,2}[:.][0-9]{2}\s*[AP]M?)", src):
        t = m.group(1)
        t = re.sub(r"\.(\d)", ":\1", t)
        am = re.match(r"(\d{1,2}):(\d{2})\s*([AaPp])\.?[Mm]?\.?", t)
        if am:
            h, mi = int(am.group(1)), int(am.group(2))
            pm = am.group(3).upper() == "P"
            h12 = h % 12 or 12
            return f"{h12}:{mi:02d} {'pm' if pm else 'am'}"
    return None


def _tour_and_bio(src):
    """(tour, description). The tour is the dedicated
    <span class="event-header__suffix">; the description is the <p> prose of
    the main content block (boilerplate dropped). None/None when absent."""
    tour = None
    m = re.search(r'class="event-header__suffix"[^>]*>(.*?)</span>', src, re.S)
    if m:
        tour = _text(m.group(1))
    bio = None
    i = src.find("event-header__title")
    if i != -1:
        region = src[i:i + 14000]
        region = re.split(r"<script|application/ld\+json|frost-graphic", region)[0]
        paras = [ _text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", region, re.S) ]
        keep = []
        for p in paras:
            if not p:
                continue
            # drop ticketing / age / ID boilerplate
            if re.search(r"ticketed by|AXS service fees|government-issued|"
                          r"valid,? physical form|copies or pictures of ids", p, re.I):
                continue
            if len(p) < 40:          # the bio is the substantial prose
                continue
            keep.append(p)
        if keep:
            bio = " ".join(keep)
            bio = re.sub(r"\s+", " ", bio).strip()
    return tour, (bio[:2000] if bio else None)


def _featured(src):
    """Per-date 'Featured Artists:' lists -> a flat list of support acts.
    Each such <p> holds the date header (bold lead-in) then the acts, one per
    <br>. We convert <br> to real newlines, drop the header, split, and
    dedupe — the acts themselves contain no line breaks."""
    out = []
    for m in re.finditer(r"Featured Artists:?\s*(?:&nbsp;|\s)*", src, re.I):
        seg = src[m.end():m.end() + 2500]
        seg = re.split(r"</p>|class=\"text-center\"|Directions|Know Before", seg)[0]
        t = re.sub(r"<br\s*/?>", "\n", seg, flags=re.I)
        t = html.unescape(re.sub(r"<[^>]+>", "", t))
        for part in t.split("\n"):
            a = re.sub(r"^\s*Featured Artists:?[ \t]*", "", part, flags=re.I)
            a = a.replace("\xa0", " ")            # &nbsp;
            a = re.sub(r"\s+", " ", a).strip(" \t,&")
            if a and len(a) > 2 and not re.search(r"\d{4}", a):
                out.append(a)
    seen, deup = set(), []
    for a in out:
        if a.lower() in seen:
            continue
        seen.add(a.lower())
        deup.append(a)
    return deup


def _detail(src):
    """Detail page -> {tour, age, doors, description, support, ticket_status}."""
    if not src:
        return {k: None for k in
                ("tour", "age", "doors", "description", "support", "ticket_status")}
    tour, bio = _tour_and_bio(src)
    age = _age(src)
    doors = _doors(src)
    support = _featured(src) or None
    # ticket status from the page's own buttons (more authoritative than the
    # API's TicketLinkTitle, which is often just "Buy Tickets")
    status = None
    if re.search(r"Sold\s?[Oo]ut|sold out", src):
        status = "sold out"
    elif re.search(r"(?i)(buy tickets|add to cart|select seats)", src):
        status = "on sale"
    return {
        "tour": tour,
        "age": age,
        "doors": doors,
        "description": bio,
        "support": support,
        "ticket_status": status,
    }


def fetch_details(rows):
    """Fetch each show's detail page. Incremental: cached event_pages are
    reused, only new ones hit the network. On re-fetch we keep the prior
    value if the new one is empty (a transient failure shouldn't clobber a
    good capture)."""
    have = {}
    if os.path.exists(DETAILS):
        try:
            have = json.load(open(DETAILS))
        except ValueError:
            have = {}
    todo = [r["event_page"] for r in rows
            if r.get("event_page")
            and r["event_page"] not in have
            and r["event_page"].rstrip("/") not in have]
    todo = todo[:DETAIL_MAX]
    if todo:
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(fetch, url): url for url in todo}
            for f in futs:
                url = futs[f]
                new = _detail(f.result())
                old = have.get(url, {}) or have.get(url.rstrip("/"), {})
                merged = {}
                for k in ("tour", "age", "doors", "description",
                           "support", "ticket_status"):
                    merged[k] = new.get(k) or old.get(k)
                have[url.rstrip("/")] = merged
                time.sleep(0.3)   # be polite
    json.dump(have, open(DETAILS, "w"), indent=1, ensure_ascii=False)
    return have


def main():
    os.makedirs(CACHE, exist_ok=True)
    data = fetch(API_URL)
    if data is None:
        raise SystemExit("could not fetch the events API")
    try:
        data = json.loads(data)
    except ValueError as e:
        # not JSON — a Cloudflare block / error page; fail loudly
        raise SystemExit(f"events API did not return JSON: {e}")
    if not isinstance(data, list):
        raise SystemExit("events API shape changed (not a list)")
    rows = parse_events(data)
    details = fetch_details(rows)
    for r in rows:
        if r.get("event_page"):
            # tolerant join: ignore a trailing-slash mismatch between the
            # listing's URL and a previously-cached detail URL.
            d = details.get(r["event_page"]) or details.get(r["event_page"].rstrip("/")) or {}
            for k in ("tour", "age", "doors", "description", "support"):
                if d.get(k) is not None:
                    r[k] = d[k]
            if d.get("ticket_status"):
                r["ticket_status"] = d["ticket_status"]
    json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)
    n = len(rows)
    print(f"season events: {len(data)}  ->  Frost shows: {n}"
          f"  (details cached: {len(details)})")
    for r in rows:
        print(f"  {str(r.get('date') or '?'):12}  {r['title'][:32]:32} "
              f"{str(r.get('show_time') or ''):9} {str(r.get('ticket_status') or ''):9} "
              f"{str(r.get('tour') or '')[:22]}")


if __name__ == "__main__":
    main()
