# The Fillmore, San Francisco (venue adapter)

Venue-specific part of the shared Headliners pipeline. The Fillmore
(`thefillmore.com`) is a Live Nation venue running a Next.js app; its
`/shows` page is a plain 200 (no bot wall) and — better than the Castro —
its embedded React-server (RSC) flight payload carries everything: the
billed artist lineup (headliner + support, venue-authored), dates/times,
ticket links + status, and the venue's own Music / Arts & Theatre segment.

| Step | File | Output |
|------|------|--------|
| 1. Fetch | `fetch_calendar.py` | `cache/calendar.json` (per event: billed name, url, start, status, segment, `important_info`, full `artists` list) |
| 2. Build | `build.py` | `data/shows.json` (shared format; `stats.event_types` + `stats.apple_music` blocks) |

```
python3 fetch_calendar.py   # re-pull the schedule
python3 build.py            # rebuild data/shows.json
# Apple Music links (shared engine):
python3 ../common/lookup.py --full   # then rebuild
# view: http://127.0.0.1:8050/fillmore/   (root serve.py)
```

## What's venue-specific here

- **RSC extraction** (`fetch_calendar.py`): the event array lives in the
  `self.__next_f.push([1,"…"])` chunks; it is unescaped at the byte level
  (`\uXXXX` → UTF-8) then parsed by a bracket scanner — no browser needed.
- **Bill reconciliation** (`build.py`): the venue's own `artists` list is
  the authoritative lineup, so the build never parses a bill string. It only
  reconciles the billed event name against that list:
  - split titles ("Artist – Tour"): the lead is the headliner; when the lead
    equals `artists[0]` case/accent-insensitively the venue's canonical
    spelling is shown (accented "José Madero"); otherwise the billed lead
    stands ("The Big Star Quintet").
  - a tour-NAMED lead ("Sanctuary Park Tour: Celebrating 40 Years of The
    Jayhawks") is not an artist → `artists[0]` headlines, whole billed name
    becomes the show title.
  - multi-night pass placeholders (00:00:01 starts, e.g. "SIX (6) Show
    Ticket") are dropped; each individual night is its own event.
  - `Feat. X and Y` clauses in the title add support acts that are absent
    from the artists list (solo billings like Pattie Gonia).
- **Categorization**: the site's `Arts & Theatre` segment is comedy/variety
  (Pattie Gonia, Matt Rogers) → `other`; everything else is `music`. There
  is no film at this venue.
