#!/usr/bin/env python3
"""Fetch the Great American Music Hall schedule (venue adapter capture step).

Two plain-GET sources (a browser user-agent is all it takes; no Cloudflare,
no login):

  1. https://www.greatmusichall.com/events/  — the backbone. One page that
     lists every upcoming show as an HTML card AND embeds a JSON-LD
     schema.org/Event block per show: name, performer, startDate, url,
     offers (price + availability), description, location. The list is
     complete (verified 23 events, ~6 months out) because the cards are
     server-rendered — unlike gamh.com/calendar, whose See Tickets widget
     only returns the first page on a plain GET (the rest load via a
     nonce-gated admin-ajax call; driving that would be fragile for a
     weekly recurring pipeline).

  2. Per-show detail pages (the JSON-LD "url" on greatmusichall.com) —
     enrichment: the "with support from X, Y and Z" / "featuring special
     guest X" line from the body copy, plus the full description.

Output (cache/):
  events.json   list of per-show records: name, performer, start (ISO),
                date (YYYY-MM-DD), url, event_page, ticket_link, ticket_status,
                price, description (from the JSON-LD block)
  details.json  dict url -> {support: [..], desc: ...}  (plain-GET detail
                pass; keyed by the venue's own detail-page url)
  events.json.fetched_at  stamp written by update_all.py after a successful
                fetch (the runner skips the re-crawl when it's < 24h old)

All three venue sites are plain-GET-able with a browser UA; the multibyte
names GAMH bills are ASCII in the wild, so a utf-8 decode is safe here
(the Fillmore needed a byte-level flight unescape — this site doesn't).
"""
import os, re, html, json, time, urllib.request, datetime
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(CACHE, "events.json")
DETAILS = os.path.join(CACHE, "details.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
EVENTS_URL = "https://www.greatmusichall.com/events/"
# Safety valve: the detail pass must not grow without bound.
DETAIL_MAX = 60


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


def parse_events(src):
    """Extract the JSON-LD Event blocks -> per-show records (dedup by url)."""
    rows, seen = [], set()
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', src, re.S):
        if '"Event"' not in block:
            continue
        try:
            e = json.loads(block)
        except ValueError:
            continue
        url = e.get("url")
        if not url or url in seen:
            continue
        seen.add(url)

        start = e.get("startDate") or ""
        date = start[:10] if re.match(r"\d{4}-\d{2}-\d{2}", start) else None

        offers = e.get("offers") or {}
        price = offers.get("price")
        price = f"${float(price):g}" if price and str(price).replace(".", "", 1).isdigit() else None
        status = offers.get("availability", "")
        status = ("on sale" if "InStock" in status
                  else "sold out" if "SoldOut" in status
                  else None)

        name = html.unescape(e.get("name") or "").strip()
        perf = e.get("performer")
        if isinstance(perf, list):
            perf = ", ".join(
                html.unescape(p.get("name", "")) if isinstance(p, dict) else str(p)
                for p in perf)
        perf = html.unescape(perf or name).strip()

        rows.append({
            "name": name,
            "performer": perf,
            "start": start,
            "date": date,
            "url": html.unescape(url),
            "event_page": html.unescape(url),
            "ticket_link": offers.get("url") or None,
            "ticket_status": status,
            "price": price,
            "description": html.unescape(e.get("description") or "").strip() or None,
        })
    rows.sort(key=lambda r: r.get("date") or "9999")
    return rows


SUPPORT_RE = re.compile(
    r"with (?:support from|special guest)\s+([^.!?]{5,160}?)(?=[.;!]|$)", re.I)
# "Featuring" as a fallback, only at the start of a clause/sentence: a mid-
# sentence "featuring surround sound from every angle" / "featuring songs from
# his album" is prose describing the SHOW, not a bill. The venue's own
# lowercase "with support from …" line is the strongest signal and wins.
FEAT_RE = re.compile(
    r"(?:^|[.!,]\s*)[Ff]eaturing\s+(?:special guest\s+)?([^.!?]{5,160}?)(?=[.;!]|$)", re.I)
# Lowercase "featuring" mid-sentence — for triple bills like "…will be a
# triple bill featuring Metal Church and up and coming metal act Livekill."
FEAT_LOWER_RE = re.compile(
    r"(?<![a-zA-Z])[Ff]eaturing\s+(?:special guest\s+)?([^.!?]{5,160}?)(?=[.;!]|$)", re.I)
# Words that mark the RAW captured text as prose (an album, a song list, a
# venue description) rather than a bill. Checked once on the whole capture
# BEFORE splitting; kept narrow on purpose — 'live'/'band'/'metal' can sit
# inside an act's own name (Livekill, Metal Church) and must not reject.
NON_ACT_RE = re.compile(
    r"\b(songs?|albums?|records?|trio|quartet|collaborations?|powerful|"
    r"legendary|oldest|surround|set list|setlist|discography|tracks?)\b", re.I)
# Words that are descriptors, not act names: 'up', 'coming', genre words,
# 'metal act', 'band', … Billed act names always start with a Capital even
# when the genre is 'Metal'/'Doom' — the case distinction does the work.
DESC_WORDS = {"up", "coming", "rising", "emerging", "acclaimed", "legendary",
              "new", "local", "bay", "area", "doom", "metal", "punk", "rock",
              "pop", "country", "folk", "electronic", "indie", "band",
              "bands", "group", "act", "acts", "guest", "guests", "special",
              "crushers", "crusher", "musicians", "musician"}
# 'and' joining two descriptor words ('up and coming') is inside a descriptor
# RUN, not a bill separator — join it before splitting. 'and' between two
# real act names (or a name and a descriptor) is a separator.
AND_JOIN_RE = re.compile(
    r"\b(?:" + "|".join(sorted(DESC_WORDS)) + r")\s+and\s+"
    r"(?:" + "|".join(sorted(DESC_WORDS)) + r")\b", re.I)
# A trimmed part still leading with a descriptor word is a leftover fragment
# ('up Livekill' from a malformed capture) — drop it, never output it.
LEAD_DESC = {"up", "coming", "act", "acts", "band", "bands", "group",
             "guest", "guests", "special"}


def _trim_desc(part):
    """Strip a LEADING RUN of all-lowercase words from a support part.

    A billed act's name starts with a Capital, while the venue's descriptors
    are lowercase, so trimming every leading lowercase word recovers the name:
    'doom metal crushers Primitive Man' -> 'Primitive Man', 'up and coming
    metal act Livekill' -> 'Livekill', 'Metal Church' -> 'Metal Church' (first
    word is capital: nothing stripped). If the run is the WHOLE part (a
    genuinely lowercase act name like 'swell foop'), keep it untouched."""
    words = part.split()
    out = []
    seen_cap = False
    for w in words:
        has_cap = any(c.isupper() for c in w)
        if not has_cap and not seen_cap:
            continue
        seen_cap = seen_cap or has_cap
        out.append(w)
    return " ".join(out) if out else part


def _split_bill(s):
    """Split a support bill string into act names.

    1. Join 'and' that sits between two descriptor words ('up and coming'
       stays a run; the bill then splits cleanly on the next 'and').
    2. Split on ',', '/', '&' and 'and'.
    3. Trim each part's leading lowercase descriptors; drop parts that are
       entirely lowercase (pure descriptor fragments) or that still lead
       with a descriptor word (leftover fragments)."""
    prev = None
    while prev != s:
        prev = s
        s = AND_JOIN_RE.sub(lambda m: " ".join(m.group(0).split()), s)
    out = []
    for part in re.split(r",|\s*/\s*|\s*&\s*|\band\b", s):
        t = _trim_desc(re.sub(r"\s+", " ", part).strip(" -\u2013\u2014,.!"))
        if not t:
            continue
        words = t.split()
        # Drop parts made ENTIRELY of descriptor words ('up and coming',
        # 'metal act', …). A genuinely stylized all-lowercase act name
        # ('swell foop', 'dougie poole') has at least one non-descriptor
        # word and must survive — do NOT drop on islower().
        if all(w.lower().strip(" -\u2013\u2014,.!") in DESC_WORDS for w in words):
            continue
        if words[0].lower().strip(" -\u2013\u2014,.!") in LEAD_DESC:
            continue                      # leftover descriptor: drop
        if 2 <= len(t) <= 50 and not NON_ACT_RE.search(t):
            out.append(t)
    return out


def split_support(text):
    """'…with support from A, B and C.' / '…Featuring special guest D.'
    -> [A, B, C]. Prose (albums, songs, venue copy) is rejected."""
    m = (SUPPORT_RE.search(text) or FEAT_RE.search(text)
         or FEAT_LOWER_RE.search(text))
    if not m:
        return []
    s = m.group(1).strip()
    s = re.sub(r"^(?:special\s+)?guests?\b\s*", "", s, flags=re.I)
    if NON_ACT_RE.search(s):
        return []
    acts = []
    for part in _split_bill(s):
        a = re.sub(r"\s+(?:!|\.|\??\!)\s*$", "", part).strip()
        if 2 <= len(a) <= 50 and not NON_ACT_RE.search(a):
            acts.append(a)
    return acts


def parse_detail(src):
    """Detail page -> {support, desc}. Returns None when nothing usable."""
    if not src:
        return None
    text = html.unescape(re.sub(r"<script.*?</script>|<style.*?</style>", " ", src, flags=re.S))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    support = split_support(text)
    # The description: the JSON-LD description is already on the backbone
    # record; the detail adds nothing structurally, so keep the body stub.
    return {"support": support or None, "desc": text[:1200]}


def fetch_details(rows):
    """Fetch each show's detail page (venue's own domain only) for support
    acts. Runs incrementally: cached detail records are reused."""
    have = {}
    if os.path.exists(DETAILS):
        try:
            have = json.load(open(DETAILS))
        except ValueError:
            have = {}

    todo = [r["url"] for r in rows
            if "greatmusichall.com/events/" in r.get("url", "") and r["url"] not in have]
    todo = todo[:DETAIL_MAX]
    if todo:
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(fetch, u): u for u in todo}
            for f in futs:
                u = futs[f]
                src = f.result()
                rec = parse_detail(src)
                if rec and (rec["support"] or rec.get("desc")):
                    have[u] = rec
                    time.sleep(0.4)  # be polite
    json.dump(have, open(DETAILS, "w"), indent=1, ensure_ascii=False)
    return have


def main():
    os.makedirs(CACHE, exist_ok=True)
    src = fetch(EVENTS_URL)
    if src is None:
        raise SystemExit("could not fetch the events page")
    open(os.path.join(CACHE, "events_raw.html"), "w").write(src)
    rows = parse_events(src)
    details = fetch_details(rows)

    n_sup = sum(1 for r in rows if details.get(r["url"], {}).get("support"))
    json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)
    print(f"events: {len(rows)} (with support: {n_sup}, detail pages: {len(details)})")
    if rows:
        print(f"first: {rows[0]['date']}  {rows[0]['name']}")
        print(f"last:  {rows[-1]['date']}  {rows[-1]['name']}")
    print("no date:", [r['name'] for r in rows if not r['date']][:5])
    for r in rows[:12]:
        sup = details.get(r["url"], {}).get("support")
        print(f"  {r['date']}  {r['name'][:40]:40} {str(r['ticket_status'] or ''):9} "
              f"{str(r['price'] or ''):12} {('+ ' + ', '.join(sup)) if sup else ''}")


if __name__ == "__main__":
    main()
