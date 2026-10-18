# Headliners

One application that extracts and reviews show calendars for multiple
theaters. A shared pipeline in `common/` produces a **common JSON format**
for every venue; each theater is a thin adapter on top of it.

## Venues

| Dir | Venue | Source | Route | Notes |
|-----|-------|--------|-------|-------|
| [`independent/`](independent/) | The Independent, SF | theindependentsf.com | `:8050/independent/` | music; Apple Music matching (confidence tiers) |
| [`castro/`](castro/) | The Castro Theatre, SF | thecastro.com | `:8050/castro/` | music + film + comedy + other (derived); Apple Music matching on music + comedy (film artists are movie/director names, not catalog artists) |
| [`fillmore/`](fillmore/) | The Fillmore, SF | thefillmore.com | `:8050/fillmore/` | music (site "Arts & Theatre" segment = comedy/variety → `other`); Apple Music matching on all |
| [`gamh/`](gamh/) | Great American Music Hall, SF | greatmusichall.com | `:8050/gamh/` | music (festival/awards/poetry/Christmas bills → `other`); support acts from each show's detail page; Apple Music matching on all |
| [`regency/`](regency/) | The Regency Ballroom, SF | theregencyballroom.com (AEG/AXS blob feed) | `:8050/regency/` | music (all bills); one unauthenticated AEG JSON GET = the whole calendar with headliners + support pre-structured; Apple Music matching on all |
| [`augusthall/`](augusthall/) | August Hall, SF | augusthallsf.com (TicketWeb WordPress) | `:8050/augusthall/` | music (all bills); listing pages + per-show detail pages (plain HTML, server-side); tour titles, "with" support, and censored names handled; Apple Music matching on all |

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
fillmore/            venue adapter: fetch (RSC payload) + bill reconciler + build.py
gamh/                venue adapter: fetch (JSON-LD + detail pages) + support parser + build.py
regency/             venue adapter: fetch (AEG/AXS public JSON feed) + build.py
augusthall/          venue adapter: fetch (TicketWeb listing + detail pages) + title parser + build.py
serve.py             single entry point: picker at /, venues at /<key>/
update_all.py        one command to refresh ALL venues (fetch/build/lookup/build
                     + per-venue diff; --full = full Apple Music re-match)
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
   Shape the artists with `common.apple_music.artist_obj(name, lookup)` so
   every show carries Apple Music links — see the mandate below.
3. Register it in `common/venues.py` with `has_apple_music: True` (one dict
   entry: name, city, dir, has_apple_music).
4. **Apple Music links — REQUIRED for every new theater:**
   `cd <key> && python3 ../common/lookup.py --full && python3 build.py`.
   Matching is **best-effort**: the shared engine resolves whatever it can
   resolve and honestly marks the rest not-found. We do NOT try to code every
   possible billed name — a small number of unresolvable names (compound
   bills, film credits, odd spellings) is expected and acceptable. The goal
   is to get *most*, and the `stats.apple_music` block (exact / close /
   needs_review / not_found) makes the coverage visible and reviewable.

That's it — the picker card, the reviewer page, and the JSON envelope come
from `common/` automatically.

## Running

```
python3 serve.py            # ONE entry point: http://127.0.0.1:8050
python3 update_all.py       # refresh every venue's data/shows.json
python3 update_all.py --full
```

`update_all.py` runs, per venue (registry order): fetch → build → Apple Music
lookup → build, then prints a diff vs the previous shows.json
(added / removed / schedule-changed / link-only). By default the site is
re-crawled only when the venue's cache is > 24h old (`.fetched_at` stamp;
`--refresh` forces it), and Apple Music is **incremental** — `common/lookup.py`
skips artists that already have a terminal status in the venue's
`cache/lookup.json` (and retries `error` entries). `--full` forces a complete
Apple Music re-match (and a re-crawl). `--venues a,b` restricts the run. A
venue whose fetch fails is skipped with a warning instead of blocking the rest.

`/` is the theater picker; `/independent/` and `/castro/` are the reviewers
(shared template, per-venue data injected). Data is re-read per request, so a
fresh `build.py` shows up immediately.

## Apple Music matching (mandatory, best-effort)

**Every theater gets Apple Music links on every show where possible.** When
adding a new theater, run the shared lookup (`common/lookup.py`) over its
artists — matching is on for all venues, not opt-in.

Matching is **best-effort by design**: we cannot code every possible billed
name, and the engine is *honest* rather than clever. A name it cannot
confidently resolve is marked not-found (or flagged `needs_review` for a close
near-miss) rather than force-linked. A handful of unresolvable names per
venue is expected and fine — the success bar is "get most," not 100%. The
`stats.apple_music` block (unique / found / exact / close / needs_review /
not_found) reports the real coverage so the reviewer can see what didn't
resolve.

Two safety rules guard the "get most" goal from becoming "get wrong":

- **`LINK_FLOOR` 0.80** (in `common/apple_music.py`): a fuzzy (non-exact)
  match below confidence 0.80 is never auto-linked — the artist is marked
  not-found but the near-miss name + score are retained for human review.
- **Compound bills**: a billed "A and B" / "A x B" that matches only one act
  is linked to that act but flagged "compound bill — links to … only", never
  silently presented as a full match.

Both rules live in exactly one place and apply to every venue that matches.
