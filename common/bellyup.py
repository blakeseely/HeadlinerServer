"""Shared parser for bellyup.com's TicketWeb calendar.

The Belly Up Presents group (bellyup.com) is the shared promoter of San Diego's
mid-size venues, so ONE GET of https://bellyup.com/calendar carries the whole
multi-venue season:

  * a TicketWeb `events:[…]` JS array — the schedule backbone:
        id, start (MySQL datetime), title (billed name), venue
        ('<div class="tw-cal-full-venue">Belly Up</div>'), doors,
        displayTime ('Show: 7:30PM')
  * one hidden popup `<div id="tw-event-dialog-<id>">` per event with the
    canonical name + detail URL, the description (tw-description), the
    prefix text ('Seated Show'), the venue name, and the ticket button whose
    class (tw_onsale / tw_offsale / tw_onsalesoon / tw_soldout) encodes the
    sale state.

Each venue adapter (bellyup/ thesound/ thecasbah/ theobservatory/
musicbox/ humphreys) runs fetch.py against this module, keeps ONLY its own
venue's events, and writes cache/events.json. build.py then parses the
TicketWeb title grammar with bill.parse_bill.
"""
import re
import html as _html


def _clean(s):
    """HTML -> text: unescape entities, strip tags, collapse whitespace."""
    if not s:
        return None
    t = re.sub(r"<[^>]+>", " ", s)
    t = _html.unescape(t)
    t = t.replace("\xa0", " ").replace("\u2019", "'").replace("\u2018", "'")
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def extract_events(h):
    """The TicketWeb fullcalendar JS array, as a list of dict records.

    The array is hand-written JS object literals (unquoted keys, single
    quotes), so it is normalized with a quote-aware tokenizer — a blanket
    quote replacement would corrupt apostrophes in artist names.
    """
    import json
    i = h.find("events:")
    if i < 0:
        return []
    try:
        start = h.index("[", i)
    except ValueError:
        return []
    depth, inq, esc = 0, None, False
    raw = None
    for k in range(start, len(h)):
        c = h[k]
        if inq:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == inq:
                inq = None
            continue
        if c in "\"'":
            inq = c
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                raw = h[start:k + 1]
                break
    if raw is None:
        return []
    out, k, n = [], 0, len(raw)
    while k < n:
        c = raw[k]
        if c == "'":
            j, buf = k + 1, []
            while j < n and raw[j] != "'":
                if raw[j] == "\\" and j + 1 < n and raw[j + 1] == "'":
                    buf.append("'")
                    j += 2
                    continue
                buf.append(raw[j])
                j += 1
            s = "".join(buf).replace("\\", "").replace('"', '\\"')
            out.append('"' + s + '"')
            k = j + 1
            continue
        out.append(c)
        k += 1
    txt = "".join(out)
    txt = re.sub(r"([{,])\s*([a-zA-Z_]+)\s*:", r'\1"\2":', txt)
    txt = re.sub(r",\s*([}\]])", r"\1", txt)
    try:
        evs = json.loads(txt)
    except Exception:
        return []
    recs = []
    for e in evs:
        if not isinstance(e, dict) or not e.get("id") or not e.get("start"):
            continue
        recs.append({
            "id": str(e.get("id")),
            "start": str(e.get("start") or ""),
            "title": _clean(e.get("title") or ""),
            "venue": _clean(e.get("venue") or ""),
            "doors": _clean(e.get("doors") or ""),
            "display_time": _clean(e.get("displayTime") or ""),
        })
    return recs


def extract_popups(h):
    """Per-event extras, keyed by event id.

    Sources, joined by the ticket URL's trailing event id (the TicketWeb
    button lives in the calendar LIST, not inside the popup, but its href
    ends in /<eventid>):
      * popup  — canonical name, detail URL, description, prefix text,
                 venue name
      * button — the tw-cal-button's class (sale state) + ticket URL
    Returns {id: {name, event_page, description, prefix_text,
    venue_name, ticket_class, ticket_link}}; absent fields are None.
    """
    pops = {}
    for m in re.finditer(r'id="tw-event-dialog-(\d+)"', h):
        pid = m.group(1)
        if pid in pops:
            continue
        block = h[m.start(): m.start() + 8000]

        def grab(cls):
            mm = re.search(r'class="' + cls + r'[^"]*"[^>]*>(.*?)</div>', block, re.S)
            return _clean(mm.group(1)) if mm else None

        name_m = re.search(
            r'class="tw-name"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            block, re.S)
        pops[pid] = {
            "name": _clean(name_m.group(2)) if name_m else None,
            "event_page": name_m.group(1) if name_m else None,
            "description": grab("tw-description"),
            "prefix_text": grab("tw-prefix-text"),
            "venue_name": grab("tw-venue-name"),
            "ticket_class": None,
            "ticket_link": None,
        }
    # calendar-list ticket buttons: join onto their event via the URL id
    for bm in re.finditer(
            r'<a[^>]*class="([^"]*tw-cal-button[^"]*)"[^>]*href="([^"]+)"', h):
        cls, url = bm.group(1), bm.group(2)
        m = re.search(r"/(\d+)(?:\?|$)", url)
        if not m:
            continue
        rec = pops.get(m.group(1))
        if rec is not None and rec.get("ticket_class") is None:
            rec["ticket_class"] = cls
            rec["ticket_link"] = url
    return pops


def sale_state(cls):
    if not cls:
        return None
    if "soldout" in cls:
        return "Sold Out"
    if "onsalesoon" in cls:
        return "On Sale Soon"
    if "ticketssold" in cls:
        return "On Sale"
    if "onsale" in cls:
        return "On Sale"
    if "offsale" in cls:
        return "Not On Sale"
    if "protected" in cls:
        return "Not On Sale"
    return None
