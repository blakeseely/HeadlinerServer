#!/usr/bin/env python3
"""Fetch The Independent SF calendar (theindependentsf.com).

Two captures, both via a plain GET with a browser user-agent (the site is
WordPress + the TicketWeb "tw-" plugin; not bot-walled):

  1. The home / listings page lists every upcoming show:
       .tw-event-item  ->  name (.tw-name > a), day, href, "with X" support,
                           Show time, and the date.
     -> cache/event_list.json   (the lightweight list)
  2. Each show's detail page (/tm-event/<slug>/) carries the canonical header:
       .tw-prefix              tour name (may be empty)
       .tw-name.event-title    headliner (the page's own <title> too)
       .tw-attractions         support act(s)
       .tw-date-time           "Fri, Oct 16 Doors: 8:30 pm | Show: 9:00 pm"
       .tw-age-restriction     "All Ages"
       .tw-description         promo text
       .tw-buy-tix-btn         Buy Tickets / Sold Out!  (the ticket link)
     The venue injects a large mini-calendar of *other* upcoming shows
     (.tw-event-name.tw-remove-when …) into the same page, so we read only the
     header region, never the whole body.

     -> cache/vfinal.json   (one record per show; the `lines` array is the
        DOM text-node order of the header, which build.py's parse_title /
        support-slot / tour-line heuristics consume verbatim.)

The site has been redesigned over time (the old cache carried a leading horse
emoji in <title> that the current pages no longer emit) — the `lines` contract
is what matters, and it is stable across the redesign.
"""
import os, re, json, html, time, urllib.request
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
HOME = "https://www.theindependentsf.com/"

# header element classes whose text becomes a `lines` entry (in DOM order)
HEADER_CLS = ("tw-prefix", "event-title", "tw-attractions", "tw-date-time",
              "tw-age-restriction", "tw-description", "tw-buy-tix-btn")


def fetch(url, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # transient; retry
            last = e
            time.sleep(2.0)
        if last is not None:
            raise last
        raise RuntimeError(f"fetch failed: {url}")


def clean(s):
    if s is None:
        return None
    if isinstance(s, re.Match):
        s = s.group(1) if s.groups() else s.group(0)
    if not s:
        return None
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def strip_style_script(src):
    src = re.sub(r"<script.*?</script>", " ", src, flags=re.S)
    src = re.sub(r"<style.*?</style>", " ", src, flags=re.S)
    return src


# ---------------------------------------------------------------------------
# 1. the listings page
# ---------------------------------------------------------------------------
def parse_list(src):
    src = strip_style_script(src)
    items = []
    for card in re.split(r'(?=<div class="row tw-event-item")', src):
        if not card.lstrip().startswith("<div"):
            continue
        m = re.search(
            r'<a[^>]*href="(https://www\.theindependentsf\.com/tm-event/[^"]+)"[^>]*title="([^"]*)"',
            card)
        if not m:
            continue
        href = html.unescape(m.group(1)).replace("&amp;", "&")
        if any(e["href"] == href for e in items):
            continue
        title_attr = m.group(2)                       # "Name - 16"
        name = clean(re.search(
            r'<div class="tw-name">\s*<a[^>]*>(.*?)</a>', card, re.S)) or title_attr
        day = None
        dm = re.search(r'<span class="tw-day-of-week">([^<]+)</span>', card)
        if dm:
            day = dm.group(1).strip()
        num = re.search(r'<span class="tw-event-date">(\d+)', card)
        name = re.sub(r"\s*-\s*\d+$", "", (name or title_attr)).strip()
        items.append({"name": name, "day": int(num.group(1)) if num else None,
                      "href": href, "title": title_attr})
    items.sort(key=lambda e: (e.get("day") or 99))
    return items


# ---------------------------------------------------------------------------
# 2. a detail page -> one vfinal record
# ---------------------------------------------------------------------------
# The event's real header lives in <div class="col-md-6 col-xs-12
# event-column">: prefix (tour) / event-title / tw-attractions /
# tw-date-time / tw-age-restriction / tw-description / tw-buy-tix-btn.
# Everything AFTER that div closes (share buttons, "Related Events" mini
# calendar, the privacy footer) is page chrome and must not leak in.

class HeaderLines(HTMLParser):
    """Collect the event header's text in DOM order, one line per block.

    The page has TWO sibling `<div class="… event-column">`s: the first holds
    the real header (prefix/tour, event-title, attractions, date-time,
    age-restriction, description, buy button); the second holds the image +
    share row, followed below by the "Related Events" mini calendar and the
    privacy footer. We open at the FIRST event-column, count only `<div>`
    depth, flush one line whenever a top-level block closes, and stop when
    that column closes — so no page chrome can ever leak into `lines`.
    """

    def __init__(self):
        super().__init__()
        self.lines = []
        self.depth = 0
        self.target = False
        self.buf, self.buf_len = [], 0

    def handle_starttag(self, tag, attrs):
        if self.target:
            if tag == "div":
                self.depth += 1
            return
        if tag == "div":
            cls = dict(attrs).get("class") or ""
            if "event-column" in cls:
                self.target = True
                self.depth = 1
                self.buf, self.buf_len = [], 0

    def handle_endtag(self, tag):
        if not self.target or tag != "div":
            return
        self.depth -= 1
        if self.depth <= 0:
            self._flush()
            self.target = False
        elif self.depth == 1:
            self._flush()      # a top-level header block ended

    def handle_data(self, data):
        if not self.target:
            return
        t = re.sub(r"\s+", " ", html.unescape(data)).strip()
        if not t:
            return
        if self.buf and self.buf[-1].strip() and self.buf_len < 200:
            self.buf[-1] += " " + t
        else:
            self.buf.append(t)
        self.buf_len += len(t)

    def _flush(self):
        t = " ".join(self.buf).strip()
        if t:
            self.lines.append(t)
        self.buf, self.buf_len = [], 0


def parse_detail(src, item):
    body = strip_style_script(src)
    hp = HeaderLines()
    hp.feed(body)
    header = list(hp.lines)          # [headliner, support, date…, age, desc, btn]

    # tour name lives in a .tw-prefix directly before the event-title
    tour = None
    m = re.search(r'<div class="tw-prefix">\s*(.*?)\s*</div>', body, re.S)
    if m:
        tour = clean(m.group(1))
    if tour and tour.lower() != (header[0].lower() if header else ""):
        header.insert(0, tour)

    # title tag (canonical casing; current pages drop the old leading emoji)
    t = re.search(r"<title>(.*?)</title>", src, re.S)
    title_tag = (clean(t.group(1)) if t else None) or (
        "%s | The Independent SF" % (item.get("name") or ""))

    # date_raw: day-of-week + date inside the date-time element
    dm = re.search(r'<span class="tw-day-of-week">(.*?)</span>', body, re.S)
    day = clean(dm.group(1)) if dm else None
    em = re.search(
        r'<span class="tw-event-date-complete">\s*<span class="tw-event-date">(.*?)</span>',
        body, re.S)
    date = clean(em.group(1)) if em else None
    date_raw = None
    if day or date:
        day = (day or "").rstrip(",").strip()
        if date:
            date_raw = f"{day}, {date}".strip(", ") or None
        else:
            date_raw = day

    dm2 = re.search(r'<span class="tw-event-door-time">(.*?)</span>', body, re.S)
    doors_raw = clean(dm2.group(1)) if dm2 else None
    sm = re.search(r'<span class="tw-event-time">(.*?)</span>', body, re.S)
    show_raw = re.sub(r"^Show:\s*", "", clean(sm.group(1)) or "") if sm else None

    # ticket link: the buy button in THIS event's header (the injected
    # mini-calendar also has buy buttons — take the one in the header region)
    buy_url, buy_status = None, None
    hi = body.find('class="tw-name event-title"')
    region = body[hi: hi + 4000] if hi >= 0 else body
    for mm in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*class="[^"]*tw-buy-tix-btn[^"]*"[^>]*>(.*?)</a>', region, re.S):
        lab = clean(mm.group(2))
        href = html.unescape(mm.group(1)).replace("&amp;", "&")
        if not lab:
            continue
        if re.search(r"sold\s*out", lab, re.I):
            buy_status = "sold out"
            continue
        buy_url = buy_url or href
        buy_status = buy_status or ("on sale" if re.search(r"buy", lab, re.I) else buy_status)

    # final `lines` = header (already in DOM order) with the date-time line
    # normalised to the "Mon, Oct 19 Doors: 7:30 pm | Show: 8:00 pm" form the
    # build's support-slot / headliner heuristics key on.
    norm_dt = None
    if date_raw:
        parts = [date_raw]
        if doors_raw:
            parts.append("Doors: %s" % doors_raw)
        if show_raw:
            parts.append("Show: %s" % show_raw)
        norm_dt = " | ".join(parts)
    lines = []
    for l in header:
        if not l:
            continue
        if re.match(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+\w+ \d+.*Doors:", l):
            lines.append(norm_dt or l)
            continue
        lines.append(l)
    if norm_dt and not any("Doors:" in l for l in lines):
        lines.append(norm_dt)

    return {
        "name": item.get("name"),
        "day": item.get("day"),
        "href": item.get("href"),
        "title_tag": title_tag,
        "date_raw": date_raw,
        "doors_raw": doors_raw,
        "show_raw": show_raw,
        "buy_url": buy_url,
        "lines": lines,
    }


def main():
    home = fetch(HOME)
    items = parse_list(home)
    os.makedirs(os.path.join(ROOT, "cache"), exist_ok=True)
    json.dump([{k: e[k] for k in ("name", "day", "href")} for e in items],
               open(os.path.join(ROOT, "cache", "event_list.json"), "w"),
               indent=1, ensure_ascii=False)
    print("list: %d events  (first %s, last %s)"
          % (len(items), items[0]["name"], items[-1]["name"]))

    out, fails = [], []
    for i, e in enumerate(items):
        try:
            rec = parse_detail(fetch(e["href"]), e)
            out.append(rec)
            print("  [%2d] %s  %s" % (i + 1, rec.get("date_raw"), rec.get("name")))
        except Exception as ex:
            fails.append((e.get("name"), repr(ex)))
            print("  [%2d] !! %s  (%s)" % (i + 1, e.get("name"), ex))
        time.sleep(0.3)

    json.dump(out, open(os.path.join(ROOT, "cache", "vfinal.json"), "w"),
              indent=1, ensure_ascii=False)
    print("saved %d events -> vfinal.json" % len(out))
    if fails:
        print("FAILED (%d): %s" % (len(fails), [f[0] for f in fails]))


if __name__ == "__main__":
    main()
