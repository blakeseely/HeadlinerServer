#!/usr/bin/env python3
"""Fetch the Roseland Theater schedule (venue adapter capture step).

Source: roselandpdx.com — WordPress + rhp-events (same Music Venue
Properties plugin as Wonder Ballroom, but the template DRIFTED):

  * wrapper class grew suffixes:  class = "col-12 eventWrapper rhpSingleEvent
    py-4 px-0 rhp-event__single-event--list"  -> anchor on rhpSingleEvent,
    do NOT require the class to end there;
  * eventDate carries NO YEAR ("Sun, Nov 08") — the year comes from the
    month separators in document order (<span class='rhp-events-list-
    separator-month ...'><span>November 2026</span></span>); every block
    inherits the most recent preceding separator;
  * no eventAgeRestriction div — age lives in the notes box
    (rhp-event-notes-box), which may also hold other notes;
  * doors line has no comma ("Doors: 7 pm Show: 8 pm").

/eventspage/2/ exists but the SSR payload is IDENTICAL to page 1 (client-
side pagination) — pagination is walked with a fresh-rows stop (crystalball
pattern), so a page 2 mirroring page 1 stops the walk.

This venue also RECEIVES moved shows (Wonder Ballroom's
"**MOVED TO ROSELAND THEATER** FROST CHILDREN" is billed here as a normal
Roseland date) — no special handling needed, it just appears.

CTA classes seen: on-sale, sold-out. Status prefixes in titles: none seen
2026-11-06, but the wonderball build rule is kept defensively.

Output cache/shows.json (list). No freshness stamp (update_all owns it).
"""
import os, re, html, json, time, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
BASE = "https://roselandpdx.com"
PAGES = [BASE + "/events/"] + [BASE + f"/events/page/{n}/" for n in range(2, 9)]
MONTHS = {m: i for i, m in enumerate(
    ("jan feb mar apr may jun jul aug sep oct nov dec".split()), 1)}
AGE_RE = re.compile(r"(?i)^(all ages(?:\s+\d+\+)?|\d{1,2}\+|all ages, kids "
                    r"(?:under|welcome)[^.,;]*|\d{1,2}\+ (?:and over|only))")


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
    if not fragment:
        return None
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def parse_page(src):
    """One events page -> rows, date = (nearest preceding month-separator
    YEAR) + (eventDate month/day)."""
    marks = [(mm.start(), mm.group(1).strip()) for mm in re.finditer(
        r"separator-month[^>]*><span>([^<]+)</span>", src)]
    starts = [m.start() for m in re.finditer(
        r'class\s*=\s*"col-12\s+eventWrapper\s+rhpSingleEvent', src)]
    rows = []
    for s in starts:
        blk = src[s: next((x for x in starts if x > s), s + 60000)]
        year = None
        for pos, label in marks:
            if pos < s:
                my = re.match(r"([A-Za-z]+)\s+(\d{4})", label or "")
                if my:
                    year = int(my.group(2))
        um = re.search(r'<a\s+id\s*=\s*"eventTitle"[^>]*href="([^"]+)"', blk)
        tm = re.search(r'<a\s+id\s*=\s*"eventTitle"[^>]*>\s*<h2[^>]*>(.*?)</h2>', blk, re.S)
        if not um or not tm:
            continue
        def field(pat):
            m = re.search(pat, blk, re.S)
            return _text(m.group(1)) if m else None
        dm = re.search(r'id="eventDate"[^>]*>\s*(.*?)</div>', blk, re.S)
        dtext = _text(dm.group(1)) if dm else None
        date = None
        md = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})", dtext or "")
        if md and year and md.group(1).lower()[:3] in MONTHS:
            date = f"{year}-{MONTHS[md.group(1).lower()[:3]]:02d}-{int(md.group(2)):02d}"
        doors_show = field(r'eventDoorStartDate[^>]*>(.*?)</div>')
        doors = show = None
        if doors_show:
            m = re.search(r"doors\s*:?\s*(\d{1,2}(?::\d{2})?\s*[ap]\.?\s*m\.?)", doors_show, re.I)
            if m:
                doors = re.sub(r"\s+", "", m.group(1)).lower()
            m = re.search(r"show\s*:?\s*(\d{1,2}(?::\d{2})?\s*[ap]\.?\s*m\.?)", doors_show, re.I)
            if m:
                show = re.sub(r"\s+", "", m.group(1)).lower()
        cta = re.search(r'class="rhp-event-cta\s+([a-z-]+)"', blk)
        href = re.search(r'class="rhp-event-cta\s+[a-z-]+">\s*<a[^>]*href="([^"]+)"', blk)
        notes = field(r'rhp-event-notes-box[^>]*>(.*?)</div>')
        age = note = None
        if notes:
            ma = AGE_RE.match(notes)
            if ma:
                age = ma.group(0)
                rest = notes[len(ma.group(0)):].strip(" ,;.-")
                note = rest or None
            else:
                note = notes
        rows.append({
            "date": date, "date_text": dtext,
            "head_billed": _text(tm.group(1)),
            "support_billed": field(r'<h4\s+id="evSubHead"[^>]*>(.*?)</h4>'),
            "promoter": field(r'eventTagLine[^>]*>(.*?)</div>'),
            "doors": doors, "show_time": show, "age": age, "note": note,
            "cost": field(r'rhp-event__cost-text--list[^>]*>(.*?)</span>') if 'cost-text' in blk else None,
            "cta_class": cta.group(1) if cta else None,
            "ticket_link": html.unescape(href.group(1)) if href else None,
            "event_page": html.unescape(um.group(1)),
        })
    return rows


def main():
    os.makedirs(CACHE, exist_ok=True)
    seen, rows = set(), []
    first_html = None
    for pi, url in enumerate(PAGES, 1):
        src = fetch(url)
        if src is None:
            break
        if pi == 1:
            first_html = src
        found = parse_page(src)
        fresh = [r for r in found if r["event_page"] not in seen]
        if not fresh:
            break
        for r in fresh:
            seen.add(r["event_page"])
        rows.extend(fresh)
        time.sleep(0.3)
    if first_html:
        with open(os.path.join(CACHE, "events.html"), "w", encoding="utf-8") as f:
            f.write(first_html)
    rows.sort(key=lambda r: (r["date"] or "9999", r["event_page"]))
    json.dump(rows, open(os.path.join(CACHE, "shows.json"), "w"),
              indent=1, ensure_ascii=False)
    print(f"rows: {len(rows)} (pages walked: {min(pi, len(PAGES))})")
    nod = [r for r in rows if not r["date"]]
    if nod:
        print(f"WARNING rows without a date: {len(nod)}")
        for r in nod:
            print("    ", r["date_text"], r["head_billed"][:60])
    # separator-year vs printed month must agree (catches separator drift)
    mism = []
    for r in rows:
        md = re.search(r"([A-Za-z]{3,9})\.?\s+\d{1,2}", r["date_text"] or "")
        if r["date"] and md and md.group(1).lower()[:3] in MONTHS and \
           MONTHS[md.group(1).lower()[:3]] != int(r["date"][5:7]):
            mism.append(f"{r['date']} vs '{r['date_text']}' {r['head_billed'][:40]}")
    if mism:
        print(f"WARNING separator-month mismatches: {len(mism)}")
        for line in mism[:8]:
            print("    ", line)
    from collections import Counter
    print("cta classes:", dict(Counter(r["cta_class"] or "-" for r in rows)))
    print("with age:", sum(1 for r in rows if r["age"]), "| with note:", sum(1 for r in rows if r["note"]))
    if rows:
        print(f"first: {rows[0]['date']}  {rows[0]['head_billed'][:60]}")
        print(f"last:  {rows[-1]['date']}  {rows[-1]['head_billed'][:60]}")


if __name__ == "__main__":
    main()
