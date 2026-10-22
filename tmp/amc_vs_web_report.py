#!/usr/bin/env python3
"""Live scan: for every unique real billed name in the system, search amc
(the app catalog) and the Apple Music web search, and report:
  GAP    -- amc returns NOTHING but the web catalog returns hits
  DIFF   -- both return hits, but different sets (informational)
  WEBO   -- amc failed hard, web returned hits
Writes apple_search_discrepancies_live.md next to itself.
"""
import json, os, sys, time, urllib.parse, urllib.request
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import apple_music as am

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "apple_search_discrepancies_live.md")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36")


def web_hits(term):
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": term, "media": "music", "entity": "musicArtist", "limit": 5})
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode())
            return [x.get("artistName") for x in d.get("results", [])[:5]]
        except Exception:
            time.sleep(1.5)
    return None


def amc_hits(term):
    r = am._amc_search(term)
    if r is None:
        return None
    return [x.get("artistName") for x in r[:5]]


def main():
    names, seen = [], set()
    for d in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, d, "data", "shows.json")
        if not os.path.isfile(p):
            continue
        for s in json.load(open(p))["shows"]:
            for a in s.get("headline_artists", []) + s.get("support_artists", []):
                n = a["name"] if isinstance(a, dict) else str(a)
                if n.startswith("(") or n in seen:
                    continue
                seen.add(n)
                names.append(n)
    print(f"{len(names)} unique real artist names", flush=True)

    rows = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(amc_hits, n): n for n in names}
        for k, f in enumerate(concurrent.futures.as_completed(futs), 1):
            rows[futs[f]] = [f.result(), None]
            if k % 100 == 0:
                print(f"  amc {k}/{len(names)}", flush=True)
    for k, n in enumerate(names, 1):
        rows[n][1] = web_hits(n)
        time.sleep(0.5)
        if k % 100 == 0:
            print(f"  web {k}/{len(names)}", flush=True)

    gap, diff, webonly, indet = [], [], [], []
    for n in names:
        aw, wv = rows[n]
        if aw is None:
            (webonly if wv else indet).append((n, "amc call failed", wv))
        elif not aw and wv:
            gap.append((n, wv))
        elif aw and wv is None:
            indet.append((n, "web search failed (403)", None))
        elif aw and wv and set(aw) != set(wv):
            diff.append((n, aw, wv))

    with open(OUT, "w") as f:
        f.write("# Apple Music search discrepancies: amc (app catalog) vs Apple Music web search\n\n")
        f.write(f"Live scan, generated {time.strftime('%Y-%m-%d %H:%M %Z')}. "
                f"Compared **{len(names)}** unique billed artist names "
                f"(all 13 venues, headliners + support, deduped) against BOTH sources.\n\n")
        f.write(f"| category | count |\n|---|---|\n"
                f"| **amc empty, web found it** (the real blind spots) | {len(gap)} |\n"
                f"| both found results, different sets (mostly ordering/limit-5 noise) | {len(diff)} |\n"
                f"| web hit while amc call failed | {len(webonly)} |\n"
                f"| indeterminate (a call failed) | {len(indet)} |\n\n")
        f.write("## amc returns nothing; Apple Music web search returns something\n\n")
        f.write("These resolve in the web catalog but not in the app catalog `amc` drives. "
                "Lookup now cross-checks the web when amc comes up empty, so they still "
                "get linked — but the app-catalog gap itself is what this section documents.\n\n")
        f.write("| Billed name | Web catalog results (top 5) |\n|---|---|\n")
        for n, wv in sorted(gap, key=lambda x: x[0].lower()):
            f.write(f"| {n} | {'; '.join(w for w in wv if w)} |\n")
        if webonly:
            f.write("\n## Web hit while amc call failed (treated same as the gap)\n\n")
            f.write("| Billed name | Web results |\n|---|---|\n")
            for n, why, wv in sorted(webonly, key=lambda x: x[0].lower()):
                f.write(f"| {n} | {'; '.join(w for w in wv if w)} |\n")
        if diff:
            f.write("\n## Both sources returned results, but different sets\n\n")
            f.write("Usually benign (web caps at 5 hits, ranking differs). Included for completeness.\n\n")
            f.write("| Billed name | amc (top 5) | web (top 5) |\n|---|---|---|\n")
            for n, aw, wv in sorted(diff, key=lambda x: x[0].lower()):
                f.write(f"| {n} | {'; '.join(x for x in aw if x)} | {'; '.join(x for x in wv if x)} |\n")
        if indet:
            f.write("\n## Indeterminate (a search call failed mid-run)\n\n")
            for n, why, wv in sorted(indet, key=lambda x: x[0].lower()):
                f.write(f"- {n} — {why}" + (f" / web: {'; '.join(w for w in wv if w)}" if wv else "") + "\n")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
