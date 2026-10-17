# The Independent (venue adapter)

Venue-specific part of the shared Headliners pipeline. The Independent's
site is a WordPress site with the TicketWeb plugin (`tw-*` markup); every
show is listed on the home page, and each event detail page carries the
canonical header. A plain GET with a browser user-agent is all it takes.

| Step | File | Output |
|------|------|--------|
| 1. Fetch | `fetch.py` | `cache/event_list.json` (all shows: name, day, href) + `cache/vfinal.json` (per event: title tag, event-column `lines`, doors/show times, buy URL) |
| 2. Apple Music | `../common/lookup.py` | `cache/lookup.json` (one entry per artist: link, matched, confidence, status) — incremental by default, `--full` to re-match all |
| 3. Build | `build.py` | `data/shows.json` (shared format; `stats.apple_music` block) |

```
python3 fetch.py                     # re-pull the calendar
python3 ../common/lookup.py          # re-lookup Apple Music (new artists only)
python3 build.py                     # rebuild data/shows.json
# or just: cd .. && python3 update_all.py --venues independent
# view: http://127.0.0.1:8050/independent/   (root serve.py)
```

## What's venue-specific here

- `fetch.py` — the event header lives in the first
  `<div class="… event-column">` (tour prefix, event-title, attractions,
  date-time, age-restriction, description, buy button); the parser opens at
  that div, counts only `<div>` depth, and stops when the column closes, so
  the share row, "Related Events" mini calendar, and privacy footer that the
  site injects after it can never leak into `lines` (the array `build.py`
  consumes). `lines` is the DOM text-node order of the header.
- `parse_title()` — the Independent's canonical source is the venue's
  `<title>` tag. Heuristics: "Artist - ShowTitle" dash split, with/+ bill
  splitting (parens-aware, never on 'and'), b2b co-headliners, "(Live + DJ)"
  set-format extraction, "& the Band" / "and his Band" kept whole.
- `OVERRIDES` — genuinely ambiguous titles pinned by hand (The Emo Night
  Tour, @NICKCHEO, Swervedriver "Raise at 35", POSTPONED: Dogma).
- The support-slot / presenter / tour-line extraction from the page's event
  column.

Shared parts (one copy, in `common/`): Apple Music confidence engine +
`artist_obj` (`apple_music.py`), show record shape / sort / JSON writer
(`build.py`), the reviewer page (`viewer/index.html`), the picker + server
(root `serve.py`).

## Apple Music

85 shows, 138 unique artists. Tiers: 1.0 exact (auto-link), ≥0.80 close
(auto-link, flagged), <0.80 not linked (near-miss retained for review).
The `LINK_FLOOR` 0.80 guard and the DJ/bill guards live in
`common/apple_music.py` and apply to every venue that matches.

## Re-extract / re-scrape

Year logic: shows captured in Oct 2026 with months Oct–Dec → 2026;
Jan–Sep → 2027 (the next calendar year, all past from the capture date).
