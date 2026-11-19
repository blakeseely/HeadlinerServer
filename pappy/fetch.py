#!/usr/bin/env python3
"""Fetch the Pappy & Harriet's schedule (https://pappyandharriets.com/calendar).

Pappy & Harriet's is the historic Pioneertown Palace (53688 Pioneertown Rd,
Pioneertown CA — grouped with the LA market in the app, per the owner). Its
site is a WordPress install behind a bot wall: the rendered HTML routes
(/live-music, /calendar, /home) 403 BOTH curl AND a real browser, so the human
pages are NOT a viable recurring source. The old source — the WordPress REST
API page (wp-json/wp/v2/pages?slug=calendar) whose content.rendered carried
server-rendered seetickets month tables + list-view cards — is DEAD: the site
moved to a Tixwhirl/FullCalendar JS plugin, and that page content is now only
plugin scaffolding (tw-plugin-calendar, fc-daygrid-*) with no event markup.

Where the data lives now (verified): the calendar plugin loads its feed via an
AJAX POST:

      POST https://pappyandharriets.com/wp-admin/admin-ajax.php
      form: action=get_events_for_calendar, nonce=<page nonce>,
            start=<today>, end=<~18 months out>, params={…template…}

(the nonce is a constant baked into the /calendar page — if a request ever
comes back with an error, we re-fetch that page once and re-extract it.)
The JSON response carries:

  * events[] (the backbone, one per show): {id, start (YYYY-MM-DD), title,
    doors, displayTime (the show time), sortkey, url:" #tw-event-dialog-<id>"}
    — the url is a dialog fragment, NOT a page; the event page is /calendar.
  * popupdata (the enrichment): one <div class="tw-cal-event-popup"
    id="tw-event-dialog-<id>"> per event, matched to events[] by id:
      tw-name               -> the billed title (a "Name at/with Support"
                               lead splits into a clean headliner + tail)
      tw-name-presenting    -> the promoter ("… Presents:")
      tw-attractions        -> the billed bill, per-artist <span> acts, head
                               first, in published order; the spot where the
                               plugin publishes per-artist Spotify links
                               (common.spotify.extract_links runs here)
      tw-description        -> the show description (P&H policies boilerplate)
      tw-prefix-text        -> ages ("All Ages")
      tw-info-price-buy-tix -> price text + the buy button, whose class is
                               tw_offsale | tw_onsale | tw_soldout, and the
                               ticketweb.com EVENT url (the purchase link —
                               i.ticketweb.com image urls are skipped)

This venue publishes NO genre and NO price (confirmed across the whole feed),
so those fields stay honest nulls for build.py. Past dates are already pruned
server-side; night-split shows are separate ids, not multi-day passes, and
all stay. Genre-less titles stay music via build.py's classifier.

Output: cache/events.json — one record per unique show (deduped by id).
"""
import os, re, json, html, datetime
import urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
import sys
sys.path.insert(0, ROOT)
from common import spotify

OUT = os.path.join(HERE, "cache", "events.json")
RAW = os.path.join(HERE, "cache", "events_raw.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

CALENDAR = "https://pappyandharriets.com/calendar"
AJAX = "https://pappyandharriets.com/wp-admin/admin-ajax.php"
# The nonce the calendar page bakes into the plugin (constant; re-extracted
# from the page content as the fallback below).
NONCE = "bf99544d98"
NONCE_RE = re.compile(
    r'''["']?nonce["']?\s*[:=]\s*["']([0-9a-f]{6,12})["']''')
# The plugin's params blob (all nulls except the template).
PARAMS = {"id": None, "type": "calendar", "event_id": None, "event_ids": None,
          "tags": None, "excludetags": None, "genres": None, "start": None,
          "end": None, "venue": None, "org": None, "template": "default"}

MIN_EVENTS = 50          # below this the window is suspect -> widen and retry
WINDOW_DAYS = 540        # ~18 months out
WIDEN_DAYS = 180         # the widen step, ~6 more months

# The buy button's state class -> a ticket status.
STATUS_BY_CLASS = {"tw_offsale": "on sale", "tw_onsale": "on sale",
                   "tw_soldout": "sold out"}

# The TicketWeb EVENT url (the purchase link). Image urls live on the
# i.ticketweb.com host (https://i.ticketweb.com/i/…) and never match.
TICKETWEB_RE = re.compile(r'href="(https?://[^"\s]*ticketweb\.com/event/[^"\s]*)')

# "<Headliner> at <Support>" / "with" / "w/" — a cleaner split than the title
# grammar's prose-prone "with" branch; only when a capitalized name follows.
NAME_SPLIT_RE = re.compile(r"\s+(?:at|with|w/)\s+(?=[A-Z(])")


def fetch(url=CALENDAR, data=None, headers=None):
    req = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                 **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def clean(s):
    if not s:
        return None
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def ajax_body(nonce, start, end):
    return urllib.parse.urlencode({
        "action": "get_events_for_calendar",
        "nonce": nonce,
        "start": start,
        "end": end,
        "params": json.dumps(PARAMS, separators=(",", ":")),
    }).encode()


def ajax_fetch(nonce, start, end):
    """One polite AJAX call -> the parsed response, or None on any failure."""
    try:
        raw = fetch(AJAX, ajax_body(nonce, start, end), headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": CALENDAR})
        return json.loads(raw)
    except Exception as exc:
        print(f"  !! ajax fetch failed ({start}..{end}): {exc}")
        return None


def refresh_nonce():
    """Fallback: re-fetch the /calendar page once and re-extract the nonce."""
    try:
        m = NONCE_RE.search(fetch())
        return m.group(1) if m else None
    except Exception as exc:
        print(f"  !! nonce page fetch failed: {exc}")
        return None


def fetch_data():
    """Pull the calendar window: today -> ~18 months out. An error response
    re-extracts the nonce from the page and retries; a thin window (<50
    events) widens `end` another ~6 months and re-requests (superset)."""
    now = datetime.datetime.now()
    start = now.strftime("%Y-%m-%d")
    days = WINDOW_DAYS
    data = None
    for attempt in range(4):
        end = (now + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        data = ajax_fetch(NONCE, start, end)
        if data is None or data.get("error"):
            nonce = refresh_nonce()
            if nonce and nonce != NONCE:
                print(f"  nonce updated: {nonce}")
                data = ajax_fetch(nonce, start, end)
        if isinstance(data, dict) and not data.get("error") \
                and len(data.get("events") or []) >= MIN_EVENTS:
            return data
        print(f"  thin window ({start}..{end}) -> widening +{WIDEN_DAYS}d")
        days += WIDEN_DAYS
    return data


def parse_popups(src):
    """Enrichment: one dict per popup, keyed by the dialog event id."""
    enr = {}
    starts = [m.start() for m in re.finditer(
        r'<div[^>]*class="[^"]*tw-cal-event-popup[^"]*"', src)]
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(src)
        seg = src[s:e]
        mid = re.search(r'id="tw-event-dialog-(\d+)"', seg)
        if not mid:
            continue
        g = lambda p: (lambda m: clean(m.group(1)) if m else None)(
            re.search(p, seg, re.S))
        title = g(r'<div class="tw-name">(.*?)</div>')

        # the billed bill: per-artist <span> acts, head first, in published
        # order (the plugin's own structured split of the lineup).
        at = re.search(r'<div class="tw-attractions">(.*?)</div>', seg, re.S)
        acts = [html.unescape(a).strip() for a in
                re.findall(r"<span>(.*?)</span>", at.group(1), re.S)] \
            if at else []
        acts = [a for a in (clean(x) for x in acts) if a]

        presenting = g(r'<div class="tw-name-presenting">(.*?)</div>')
        presenters = [presenting] if presenting else None

        # the clean headliner (build.py falls back to title when null): a
        # "Name at/with Support" lead is the headliner; "An evening with: X"
        # keeps the published title AND names X; a bare title is its own head.
        headliner = None
        if title:
            if re.match(r"(?i)^an evening (?:with|at)\b", title):
                headliner = re.sub(
                    r"(?i)^an evening (?:with|at)[:\s]*", "", title).strip() \
                    or None
            else:
                m = NAME_SPLIT_RE.search(title)
                if m and m.start() > 0:
                    headliner = title[:m.start()].strip(" –—:") or None

        # support = the bill after the head. "An evening with: X" (head==acts[0])
        # and "Name at/with X" (the tail IS acts[0]) must not re-list the act;
        # word-order compare (not equality) because acts may differ in
        # punctuation (the title's "Um, Jennifer" vs span "Um, Jennifer" is the
        # same act, but the title lead "Mini Trees" drops nothing).
        support = None
        if len(acts) > 1:
            head_norm = _words(headliner or title or "")
            tail_norm = None
            m = NAME_SPLIT_RE.search(title or "")
            if m and m.start() > 0:
                tail_norm = _words(title[m.end():])
            sp = []
            for j, a in enumerate(acts):
                aw = _words(a)
                if j == 0 and (aw == head_norm[:len(aw)]
                               or (tail_norm and aw == tail_norm)):
                    continue
                sp.append(a)
            support = ", ".join(sp) if sp else None

        # buy button: its state class -> the status; its href -> the TicketWeb
        # event url (the purchase link).
        ticket_link = ticket_status = price = None
        buy = re.search(
            r'<a[^>]*class="[^"]*tw-buy-tix-btn[^"]*tw_(?:offsale|onsale|soldout)'
            r'[^"]*"[^>]*>', seg, re.I)
        if buy:
            cls = re.search(r"tw_(offsale|onsale|soldout)", buy.group(0), re.I)
            if cls:
                ticket_status = STATUS_BY_CLASS["tw_" + cls.group(1).lower()]
            href = re.search(r'href="([^"]+)"', buy.group(0))
            if href:
                tm = TICKETWEB_RE.search(
                    f'<a href="{html.unescape(href.group(1))}">')
                ticket_link = tm.group(1) if tm else None
        if not ticket_link:
            tm = TICKETWEB_RE.search(seg)
            ticket_link = tm.group(1) if tm else None
        m = re.search(r'(?:ADV|GA)\s*(?:early|day of)?\s*[:\-]?\s*\$\s?\d+',
                      seg, re.I)
        price = clean(m.group(0)) if m else None

        enr[mid.group(1)] = {
            "title": title,
            "headliner": headliner,
            "support": support,
            "genre": None,     # this feed publishes no genre field
            "age": g(r'<div class="tw-prefix-text">(.*?)</div>'),
            "description": g(r'<div class="tw-description">(.*?)</div>'),
            "price": price,
            "presenters": presenters,
            "ticket_link": ticket_link,
            "ticket_status": ticket_status,
            "spotify": spotify.extract_links(seg) or None,
        }
    return enr


def _words(s):
    """Lowercased alphanumeric word list of a name (order-sensitive key for
    head/support de-duplication across title vs span punctuation)."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split()


def _display_time(t):
    """The events[] time is a display string already; just drop a leading
    zero ('08:00 PM' -> '8:00 PM') so it reads like the rest of the feed."""
    t = (t or "").strip()
    return re.sub(r"^0(\d)", r"\1", t) or None


def parse(data):
    events = data.get("events") or []
    enr = parse_popups(data.get("popupdata") or "")
    rows, seen = [], set()
    for ev in events:
        eid = str(ev.get("id"))
        if not eid or eid == "None" or eid in seen:
            continue  # dedup by id
        # a "[2-Day Pass]" id sharing a date with the festival is a ticket
        # package, not a show (none in the current feed — guard anyway).
        ev_title = clean(ev.get("title"))
        if ev_title and re.search(r"\[\s*\d[- ]?day\s+pass\s*\]",
                                  ev_title, re.I):
            continue
        seen.add(eid)
        en = enr.get(eid, {})
        title = en.get("title") or ev_title
        rows.append({
            "date": ev.get("start"),
            "title": title,
            "headliner": en.get("headliner"),
            "support": en.get("support"),
            "genre": en.get("genre"),
            "age": en.get("age"),
            "doors": _display_time(ev.get("doors")),
            "show_time": _display_time(ev.get("displayTime")),
            "ticket_link": en.get("ticket_link"),
            "ticket_status": en.get("ticket_status"),
            "event_page": CALENDAR,
            "description": en.get("description"),
            "price": en.get("price"),
            "presenters": en.get("presenters"),
            "spotify": en.get("spotify"),
        })
    rows.sort(key=lambda r: (r.get("date") or "9999-99-99",
                             r.get("show_time") or ""))
    return rows


def main():
    data = fetch_data()
    if not isinstance(data, dict) or "events" not in data:
        raise SystemExit(f"calendar AJAX returned no events "
                         f"(got {type(data).__name__})")
    if data.get("error"):
        raise SystemExit("calendar AJAX returned an error response")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(RAW, "w"), ensure_ascii=False)
    rows = parse(data)
    json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)
    enriched = sum(1 for r in rows if r.get("description"))
    with_link = sum(1 for r in rows if r.get("ticket_link"))
    with_sp = sum(1 for r in rows if r.get("spotify"))
    no_date = [r["title"] for r in rows if not r.get("date")]
    no_title = [r["title"] for r in rows if not r.get("title")]
    print(f"events: {len(rows)}  (with enrichment: {enriched}, "
          f"with ticket link: {with_link}, with spotify: {with_sp})")
    if rows:
        print(f"first: {rows[0].get('date')}  {rows[0].get('title')}")
        print(f"last:  {rows[-1].get('date')}  {rows[-1].get('title')}")
    print(f"missing date: {len(no_date)} {no_date[:5]}")
    print(f"missing title: {len(no_title)} {no_title[:5]}")
    for r in rows[:10]:
        print(f"  {r.get('date')}  {r.get('doors')} / {r.get('show_time')}  "
              f"{r.get('title')}  [{r.get('ticket_status')}]")


if __name__ == "__main__":
    main()
