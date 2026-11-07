#!/usr/bin/env python3
"""Fetch Keller Auditorium events (venue adapter capture step).

Keller is a City-owned, Metro-operated Portland'5 Centers for the Arts
theater — its schedule only exists inside the PORTLAND'5 calendar at
portland5.com/events (the old kellerauditorium.portlandoregon.gov DNS is
GONE; kellerauditorium.org is domain-squat spam).

portland5.com is a server-rendered Drupal site with clean teaser markup:
each card carries teaser__venue-name / teaser__title a / teaser__body.
/events?page=N paginates (~10/page, ~12 pages, all five Portland'5
theaters) — we KEEP ONLY venue == "Keller Auditorium" (one venue per feed).

Keller is a true multiplex house: concerts, comedy, Broadway musical runs
(one event page = a WEEK+ of performances), ballet, lectures. Single-date
events show "Tuesday, November 10, 2026 | 8:00 PM" in the header and carry
NO performance list; runs show "November 27 to December 20, 2026" plus an
event-performance-list of <li>s: __date "Nov 27" (no year — year inferred
by NEAREST-FUTURE, cross-year runs included) + __time "Friday, 7:30 PM"
(+ optional __details note) + a per-performance evue ticket link.

Per-event detail pages add: doors ("7:00 PM" OR the venue phrasing "30
minutes prior to start"), age restriction, location, support ("With X
(support)"), starting price, reschedule/cancel sentences written into the
body text, and a ticket button whose label may read Sold out.

Output cache/shows.json: one record PER EVENT PAGE with a performances[]
array (build.py explodes it into one feed row per performance). No
freshness stamp (update_all owns it).
"""
import os, re, html, json, time, datetime, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
BASE = "https://www.portland5.com"
VENUE_KEEP = "Keller Auditorium"
MONTHS = {m: i for i, m in enumerate(
    ("jan feb mar apr may jun jul aug sep oct nov dec".split()), 1)}


def fetch(url, retries=2):
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
                final = r.geturl()
                if final != url:
                    # Drupal redirected (e.g. /event/clue -> /events while a
                    # next-season run's detail alias is unpublished): the
                    # body belongs to some OTHER page — caller must not
                    # parse it as this event.
                    return None
                return body
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


def parse_teasers(src):
    out = []
    # window each card from its teaser__venue marker to the NEXT card's
    # marker (the footer — buy button — lives AFTER teaser__footer opens,
    # so a non-greedy group up to 'teaser__footer' never sees the CTA)
    at = [m.start() for m in re.finditer(r'<div class="teaser__venue">', src)]
    for k, s in enumerate(at):
        c = src[s: at[k + 1] if k + 1 < len(at) else s + 8000]
        vm = re.search(r'teaser__venue-name">([^<]+)<', c)
        tm = re.search(r'href="(/event/[^"]+)"[^>]*><span>([^<]+)</span>', c)
        bm = re.search(r'teaser__body">(.*?)</div>', c, re.S)
        ft = re.search(r'teaser__footer.*?<a[^>]*href="([^"]+)"[^>]*>.*?link__text">\s*([^<]*?)\s*<', c, re.S)
        if not vm or not tm:
            continue
        out.append({
            "venue": vm.group(1).strip(),
            "title": html.unescape(tm.group(2)).strip(),
            "event_page": BASE + tm.group(1),
            "teaser_body": _text(bm.group(1)) if bm else None,
            "cta_href": html.unescape(ft.group(1)) if ft else None,
            "cta_text": _text(ft.group(2)) if ft else None,
        })
    return out


DATE_HEAD_RE = re.compile(
    r"([A-Z][a-z]+ \d{1,2})(?: to ([A-Z][a-z]+ \d{1,2})| to (\d{1,2}))?, (\d{4})")


def parse_detail(src, teaser):
    d = dict(teaser)
    # header date + single-show time
    head_zone = src[:src.find("</article>") if "</article>" in src else 12000]
    dh = DATE_HEAD_RE.search(re.sub(r"<[^>]+>", " ", head_zone))
    d["header_date"] = None
    d["date_start"] = d["date_end"] = None
    if dh:
        d["header_date"] = dh.group(0)
        m1 = re.match(r"([A-Za-z]+) (\d{1,2})", dh.group(1))
        if m1:
            d["date_start"] = f"{dh.group(4)}-{MONTHS[m1.group(1).lower()[:3]]:02d}-{int(m1.group(2)):02d}"
        end_txt = dh.group(2) or dh.group(3)
        if end_txt:
            m2 = re.match(r"([A-Za-z]+ )?(\d{1,2})", end_txt)
            mo = MONTHS[m2.group(1).strip().lower()[:3]] if m2.group(1) else int(d["date_start"][5:7]) if d["date_start"] else None
            if mo:
                d["date_end"] = f"{dh.group(4)}-{mo:02d}-{int(m2.group(2)):02d}"
    d["show_time"] = None
    if d.get("teaser_body"):
        tmb = re.search(r"\b(\d{1,2}:\d{2}\s*[AP]M)\b", d["teaser_body"], re.I)
        if tmb:
            d["show_time"] = tmb.group(1).replace(" ", "").lower()
    elif dh:
        tmb = re.search(r"\b(\d{1,2}:\d{2}\s*[AP]M)\b",
                        re.sub(r"<[^>]+>", " ", head_zone[dh.end():dh.end() + 400]), re.I)
        if tmb:
            d["show_time"] = tmb.group(1).replace(" ", "").lower()
    d["price"] = None
    pm = re.search(r"Starting at \$([\d.,]+)", src)
    if pm:
        d["price"] = "$" + pm.group(1)
    bt = re.search(r'header.*?link__text">\s*([^<]{3,30})\s*<', src, re.S)
    d["header_cta"] = _text(bt.group(1)) if bt else None

    # performance list (runs); single-date events have none. Window per
    # event-performance block — a lazy `.*?` with an OPTIONAL trailing
    # group matches zero-width and never captures the ticket link.
    perfs = []
    pat = re.compile(r'<div\s+class="event-performance">')
    at = [m.start() for m in pat.finditer(src)]
    for k, s in enumerate(at):
        b = src[s: at[k + 1] if k + 1 < len(at) else s + 3000]
        dm = re.search(r'event-performance__date">([^<]+)<', b)
        if not dm:
            continue
        tm = re.search(r'event-performance__time">([^<]*)<', b)
        nm = re.search(r'event-performance__details">([^<]*)<', b)
        tk = re.search(r'event-performance__tickets">\s*<a[^>]*href="([^"]+)"', b, re.S)
        perfs.append({"date_text": _text(dm.group(1)), "time_text": _text(tm.group(1)) if tm else None,
                      "perf_note": _text(nm.group(1)) if nm else None,
                      "ticket": html.unescape(tk.group(1)) if tk else None})
    d["performances"] = perfs

    # Event Details block: doors / age — dt/dd key-value pairs
    def detail_field(label):
        m = re.search(r'event-details__detail-key">\s*' + re.escape(label) +
                      r'\s*</dt>\s*<dd[^>]*>(.*?)</dd>', src, re.S)
        return _text(m.group(1)) if m else None
    d["doors"] = detail_field("Doors Open")
    d["age"] = detail_field("Age Restriction or Recommendation")
    d["location"] = detail_field("Location")

    # support line: "With X (support)" possibly several; strip tags first
    body_txt = re.sub(r"<[^>]+>", " ", src)
    body_txt = re.sub(r"\s+", " ", html.unescape(body_txt))
    d["support_billed"] = re.findall(r"(?:With|Featuring)\s+(.{2,160}?)\s*\(support\)", body_txt)
    # schedule-change sentences written into body text
    chg = re.search(r"((?:[^.]{0,160}(?:originally scheduled|has been rescheduled|"
                    r"been cancelled|been canceled|been postponed)[^.]{0,240})\.)", body_txt)
    d["change_note"] = chg.group(1).strip() if chg else None
    # bio for classification: the DESCRIPTION ZONE — from the <h1> to the
    # Event Details block. (Anchoring on body_txt.find(title) grabs the
    # first title occurrence, which lives in nav/breadcrumbs, producing a
    # generic-menu "bio" that misclassifies every event.)
    h1i = src.find("<h1")
    edi = src.find("event-details__detail-key")
    zone = src[h1i: edi if edi > h1i else h1i + 9000] if h1i >= 0 else body_txt
    zone_txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", zone))).strip()
    bi = zone_txt.find(d["title"])
    d["bio"] = (zone_txt[bi + len(d["title"]): bi + len(d["title"]) + 3000]
                if bi >= 0 else zone_txt[:3000])
    return d


def main():
    os.makedirs(CACHE, exist_ok=True)
    seen, teasers = set(), []
    page = 1
    while page <= 40:
        src = fetch(f"{BASE}/events?page={page}")
        if src is None:
            break
        fresh = 0
        for t in parse_teasers(src):
            # key on (URL, card date text): multi-season repeats share one
            # Drupal alias but their teaser date ranges differ — URL-only
            # dedup swallows the second run's card (Clue: Nov 2026 run and
            # Mar 2027 run both linked /event/clue)
            k = (t["event_page"], t.get("teaser_body"))
            if k in seen:
                continue
            seen.add(k)
            if t["venue"] == VENUE_KEEP:
                teasers.append(t)
            fresh += 1
        if not fresh:
            break
        page += 1
        time.sleep(0.25)
    print(f"calendar pages: {page} | events: {len(seen)} | {VENUE_KEEP}: {len(teasers)}")

    details = []
    html_by_url = {}
    for t in teasers:
        # same event URL can carry SEVERAL run cards (multi-season repeats
        # share one Drupal alias); the main loop deduped pages by URL, here
        # each card gets its own record keyed by its teaser date text
        src = html_by_url.get(t["event_page"])
        if src is None:
            src = fetch(t["event_page"]) or ""
            html_by_url[t["event_page"]] = src
        if not src:
            # redirected/unpublished detail: keep the card, synthesize from
            # the teaser body range — build.py bills the run's FIRST
            # published card date with needs_review until details exist
            d = dict(t)
            cd = DATE_HEAD_RE.search(t.get("teaser_body") or "")
            d.update({"header_date": cd.group(0) if cd else None,
                      "date_start": None, "date_end": None, "show_time": None,
                      "price": None, "header_cta": None, "performances": [],
                      "doors": None, "age": None, "location": None,
                      "support_billed": [], "change_note": None, "bio": "",
                      "card_only": True})
            if cd:
                m1 = re.match(r"([A-Za-z]+) (\d{1,2})", cd.group(1))
                if m1:
                    d["date_start"] = f"{cd.group(4)}-{MONTHS[m1.group(1).lower()[:3]]:02d}-{int(m1.group(2)):02d}"
                end_txt = cd.group(2) or cd.group(3)
                if end_txt and d["date_start"]:
                    m2 = re.match(r"([A-Za-z]+ )?(\d{1,2})", end_txt)
                    mo = MONTHS[m2.group(1).strip().lower()[:3]] if m2.group(1) else int(d["date_start"][5:7])
                    d["date_end"] = f"{cd.group(4)}-{mo:02d}-{int(m2.group(2)):02d}"
            details.append(d)
            continue
        d = parse_detail(src, t)
        if d.get("date_start") and t.get("teaser_body"):
            # detail belongs to a DIFFERENT run than this card (alias
            # still owned by the older run): fall back to the card record
            card_dt = DATE_HEAD_RE.search(t["teaser_body"])
            card_start = None
            if card_dt:
                m1 = re.match(r"([A-Za-z]+) (\d{1,2})", card_dt.group(1))
                if m1:
                    card_start = f"{card_dt.group(4)}-{MONTHS[m1.group(1).lower()[:3]]:02d}-{int(m1.group(2)):02d}"
            if card_start and d["date_start"] != card_start:
                keep = dict(t)
                keep.update({"header_date": card_dt.group(0),
                             "date_start": card_start, "date_end": None,
                             "show_time": None, "price": None, "header_cta": None,
                             "performances": [], "doors": None, "age": None,
                             "location": None, "support_billed": [],
                             "change_note": None, "bio": "", "card_only": True})
                details.append(keep)
                continue
        details.append(d)
        time.sleep(0.3)
    details.sort(key=lambda d: d.get("date_start") or "9999")
    json.dump(details, open(os.path.join(CACHE, "shows.json"), "w"),
              indent=1, ensure_ascii=False)
    nper = sum(1 for d in details if d["performances"])
    print(f"details: {len(details)} (with performance runs: {nper}, "
          f"performances total: {sum(len(d['performances']) for d in details)})")
    nod = [d["title"] for d in details if not d["date_start"]]
    if nod:
        print("WARNING no header date:", nod)
    noloc = [d["title"] for d in details if d.get("location") and VENUE_KEEP.lower() not in (d["location"] or "").lower()]
    if noloc:
        print("WARNING location not Keller:", noloc)


if __name__ == "__main__":
    main()
