# The Castro Theatre (venue adapter)

Venue-specific part of the shared Headliners pipeline. The Castro
(`thecastro.com`) books music, film, and comedy; its calendar is
server-rendered (fetch-friendly) but its detail pages are
Cloudflare-protected (need a real browser).

| Step | File | Output |
|------|------|--------|
| 1. Fetch | `fetch_calendar.py` | `cache/calendar.json` (per card: title, date, doors/show times, topline/bottomline, ticket link + status) |
| 2. Details | browser-captured | `cache/details.json` (per event page: `desc` + `bio`) — re-capture is a manual browser step, not part of `build.py` |
| 3. Build | `build.py` | `data/shows.json` (shared format; `stats.event_types` block) |

```
python3 fetch_calendar.py   # re-pull the calendar
python3 build.py            # rebuild data/shows.json
# view: http://127.0.0.1:8050/castro/   (root serve.py)
```

## What's venue-specific here

- `classify()` — the site has **no category labels** in its markup, so the
  type (music/film/comedy/other) is derived from the event text. The one
  clean invariant: movie screenings carry a VENUE stamp in the `desc`
  field ("Film format subject to change.", "Rated R.**", 35mm/70mm) and/or
  a festival credit in the topline (SFFILM, Frameline, Criterion). Music and
  comedy events' `desc` is the all-ages stub; their real body is the `bio`.
  Cascade (first hit wins): DJ title → film stamp → music evidence →
  comedy evidence → soft film words → spoken-word/awards → music default
  (`needs_review` when the body is only the generic stub). Title signals
  beat bio signals (the billed name is the strongest evidence: "Fred
  Armisen: Comedy for Musicians" is comedy even though his bio says
  "musician").
- `split_name_title()` — "Artist: ShowTitle" with pins for colons that are
  part of the work's own name (`2001: A Space Odyssey`).
- `split_support()` — support from the calendar bottom line; a film's bottom
  line is format/credits, so support only applies to music events.
- `age_rating()` — 18+ / 16+ / R / all-ages from the description.

No Apple Music matching (per request): artist records are plain-name objects
(`common.apple_music.plain_artist`); the shared viewer renders them without
link tiers.

## Notes

- The Castro is `thecastro.com` (the `.org` is a parked squatter).
- `cache/calendar_raw.html` (bulky snapshot) is git-ignored.
- 13 detail pages returned only the generic stub (no `bio`/`desc`); those
  shows are flagged `needs_review` rather than guessed at.
