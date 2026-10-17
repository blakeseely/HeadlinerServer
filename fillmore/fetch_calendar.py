#!/usr/bin/env python3
"""Fetch The Fillmore San Francisco schedule (https://www.thefillmore.com/shows).

The page is a Next.js app. Its React-server (RSC) flight payload — the
self.__next_f.push([1,"..."]) chunks — embeds the full event list as a JSON
array under "data":, with per event:

  * name                 billed event title ("Pouya - The Forever Glades Tour 2026")
  * url                  the Ticketmaster event page (ticket link + event page)
  * start_date_local / start_time_local / timezone
  * status_code          onsale | soldout | ...
  * segment              Music | Arts & Theatre (the site's own categorization)
  * genre
  * important_info       "Doors 7:00pm / Show 8:00pm Support = X" style string
  * artists              the FULL billed bill — headliner(s) + support acts,
                         the venue's own lineup, so no bill parsing of names
  * venue

Output: cache/calendar.json — one record per event.
(Plain GET with a browser user-agent works; no bot wall on this site.)
"""
import os, re, json, html, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "cache", "calendar.json")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
URL = "https://www.thefillmore.com/shows"


def fetch(url=URL):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def rsc_payload(src):
    """Decode the RSC flight chunks into one payload string.

    Each push body is a JS double-quoted string: \\uXXXX for a codepoint,
    \\ for backslash/quote, and standard \\n \\r \\t escapes. Unescape at
    the BYTE level (\\x is a single byte) then UTF-8-decode the result —
    that keeps multibyte names ("José Madero") intact. (Decoding the text
    first with Python's unicode_escape corrupts them into mojibake.)
    """
    SIMPLE = {ord(k): bytes([v]) for k, v in
              {"n": 10, "r": 13, "t": 9, "b": 8, "f": 12, "v": 11}.items()}
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', src, re.S)
    out = []
    for c in chunks:
        b = bytearray()
        i, n = 0, len(c)
        while i < n:
            ch = c[i]
            if ch == "\\" and i + 1 < n:
                nx = c[i + 1]
                if nx == "u" and i + 5 < n:
                    b += chr(int(c[i + 2:i + 6], 16)).encode("utf-8")
                    i += 6
                    continue
                b += SIMPLE.get(ord(nx), bytes([ord(nx)]))
                i += 2
                continue
            b += ch.encode("utf-8")
            i += 1
        out.append(bytes(b).decode("utf-8", "replace"))
    return "".join(out)


def extract_events(payload):
    """Bracket-scan the '"data":[ ... ]' event array out of the payload."""
    i = payload.find('"data":[')
    if i < 0:
        raise RuntimeError("no event array found in the RSC payload")
    start = i + len('"data":')
    depth, j = 0, start
    in_str, esc = False, False
    while j < len(payload):
        c = payload[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    break
        j += 1
    return json.loads(payload[start:j + 1])


def norm_event(e):
    arts = []
    for a in e.get("artists") or []:
        nm = (a.get("name") or "").strip()
        if nm:
            arts.append({"name": nm,
                         "segment": a.get("segment"),
                         "genre": a.get("genre")})
    return {
        "tm_id": e.get("tm_id"),
        "name": (e.get("name") or "").strip(),
        "url": e.get("url"),
        "start": f"{e.get('start_date_local') or ''} {e.get('start_time_local') or ''}".strip() or None,
        "timezone": e.get("timezone"),
        "status_code": e.get("status_code"),
        "genre": e.get("genre"),
        "segment": e.get("segment"),
        "important_info": e.get("important_info"),
        "artists": arts,
    }


def main():
    src = fetch()
    payload = rsc_payload(src)
    events = [norm_event(e) for e in extract_events(payload)]
    # dedup on tm_id + date, keep order, sort by date
    seen, rows = set(), []
    for e in events:
        k = (e["tm_id"], e["start"])
        if k in seen:
            continue
        seen.add(k)
        rows.append(e)
    rows.sort(key=lambda r: (r["start"] or "9999"))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)
    print(f"events: {len(rows)}")
    print(f"first: {rows[0]['start']}  {rows[0]['name']}")
    print(f"last:  {rows[-1]['start']}  {rows[-1]['name']}")
    print(f"missing date: {sum(1 for r in rows if not r['start'])}")
    for r in rows:
        sup = ", ".join(a["name"] for a in r["artists"][1:])
        print(f"  {r['start']}  {r['name'][:48]:48} {r['status_code'] or '?':10} "
              f"sup: {sup or '-'}")


if __name__ == "__main__":
    main()
