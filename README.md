# Headliners

One application that extracts and reviews show calendars for multiple
theaters. A shared pipeline in `common/` produces a **common JSON format**
for every venue; each theater is a thin adapter on top of it.

## Venues

| Dir | Venue | Source | Route | Notes |
|-----|-------|--------|-------|-------|
| [`independent/`](independent/) | The Independent, SF | theindependentsf.com | `:8050/independent/` | music; Apple Music matching (confidence tiers) |
| [`castro/`](castro/) | The Castro Theatre, SF | thecastro.com | `:8050/castro/` | music + film + comedy + other (derived); no Apple Music |

## Layout

```
common/              THE shared pipeline (venue-agnostic)
  venues.py          venue registry — ADD A NEW THEATER HERE (one dict entry)
  build.py           shared show record shape + run_build() (sort, stats, writer)
  apple_music.py     Apple Music confidence engine + artist records (one copy)
  lookup.py          Apple Music API driver (run per venue that wants links)
  viewer/index.html  ONE reviewer template; adapts to each venue's fields
independent/         venue adapter: fetch + title parser + build.py
castro/              venue adapter: fetch + category classifier + build.py
serve.py             single entry point: picker at /, venues at /<key>/
```

Each venue directory holds only what's venue-specific:

```
<venue>/
  fetch*.py        # pull the venue's schedule into cache/
  build.py         # map the cache into the shared show shape, then run_build()
  cache/           # raw captures + (if Apple Music) lookup.json
  data/shows.json  # the shared-format dataset
```

## The shared JSON format

Top level (every venue, same keys):

```json
{
  "venue": "The Castro Theatre", "venue_id": "castro",
  "venue_url": "...", "source_url": "...", "scraped_at": "2026-10-16",
  "count": 78,
  "shows": [ ... ],
  "stats": { "event_types": {"music": 58, ...} , "apple_music": {...} }
}
```

Each show (superset — fields a venue doesn't have are `null`):
`event_type, needs_review, headline_artists, support_artists, multi_artist,
show_title, presenters, set_format, date, date_label, doors, show_time,
ticket_link, ticket_status, event_page, age_rating, note, description`.

Artist records are always the same object:
`{name, apple_music, found, confidence, matched, match_label}` — venues
without Apple Music matching leave the match fields `null`.

`stats` carries any number of named blocks (`event_types`, `apple_music`, …);
the viewer and the picker render whichever are present.

## Adding a new theater

1. `mkdir <key>` and write `fetch*.py` to capture the schedule into `<key>/cache/`
   (Cloudflare-gated sites: capture detail pages via a real browser, as the
   Castro does).
2. Write `<key>/build.py`: map each raw event into `common.build.show(...)`
   records, then call `common.build.run_build(venue, key, venue_url, source_url, shows, stats)`.
3. Register it in `common/venues.py` (one dict entry: name, city, dir, has_apple_music).
4. Optionally, if it should get Apple Music links:
   `cd <key> && python3 ../common/lookup.py --full && python3 build.py`.

That's it — the picker card, the reviewer page, and the JSON envelope come
from `common/` automatically.

## Running

```
python3 serve.py            # ONE entry point: http://127.0.0.1:8050
```

`/` is the theater picker; `/independent/` and `/castro/` are the reviewers
(shared template, per-venue data injected). Data is re-read per request, so a
fresh `build.py` shows up immediately.

## Apple Music safety rule

Fuzzy (non-exact) matches below confidence **0.80** (`LINK_FLOOR` in
`common/apple_music.py`) are never auto-linked — the artist is marked not
found but the near-miss name + score are retained for human review. This rule
lives in exactly one place and applies to every venue that matches.
