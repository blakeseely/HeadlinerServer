# Great American Music Hall (venue adapter)

Venue-specific part of the shared Headliners pipeline. GAMH (470 O'Farrell,
downtown SF) is a plain server-rendered site, so a plain GET with a browser
user-agent is all it takes.

## Data source — two-part backbone

1. **`greatmusichall.com/events/`** — the listing page embeds a complete
   JSON-LD `Event` block per show (name, performer, startDate, url, offers,
   description, location). This is the authoritative calendar (currently
   ~23 shows, Oct 2026 → Mar 2027) and is re-fetched on every run.
2. **Each show's detail page** (`/events/<slug>/`) — fetched for the
   "with support from A, B and C." line (and description), because the
   JSON-LD `performer` is headliner-only. Detail records are cached in
   `cache/details.json` and reused until the show's URL disappears.

We deliberately do **not** scrape `gamh.com/calendar` (the See Tickets
widget) as the primary source: a plain GET returns only the first ~12 events
and the rest lazy-load through a nonce-gated `admin-ajax` call, which is
fragile for a recurring pipeline.

| Step | File | Output |
|------|------|--------|
| 1. Fetch | `fetch.py` | `cache/events.json` (one record per show: name, performer, start, date, url, ticket link/status, price, description) + `cache/details.json` (url → support acts, desc) |
| 2. Apple Music | `../common/lookup.py` | `cache/lookup.json` — incremental by default, `--full` to re-match all |
| 3. Build | `build.py` | `data/shows.json` (shared format; `stats.apple_music` block) |

```
python3 fetch.py                     # re-pull the calendar + detail pages
python3 ../common/lookup.py          # re-lookup Apple Music (new artists only)
python3 build.py                     # rebuild data/shows.json
# or just: cd .. && python3 update_all.py --venues gamh
# view: http://127.0.0.1:8050/gamh/   (root serve.py)
```

## What's venue-specific here

- **Everything at GAMH is live music.** The only classification is a
  non-music bill (festival, awards/poetry night, Christmas variety show) →
  `event_type` `other` (see `OTHER_RE`). Everything else is `music`.
- **`fetch.py`** — parses the JSON-LD `Event` array as the backbone, then
  fetches each show's detail page (4 threads, polite delay) for the support
  line. Names/performers/descriptions are `html.unescape`d — the venue
  double-encodes entities in the JSON-LD (`Nile &amp; Coroner`).
- **`split_support()`** — the support parser. The venue's own lowercase
  "with support from …" always wins; a capitalized "Featuring" is a fallback
  only at a sentence/clause start, and a lowercase mid-sentence "featuring"
  covers triple bills. Genre descriptors and prose are stripped/rejected:
  - leading all-lowercase runs are trimmed (`doom metal crushers Primitive Man` → `Primitive Man`);
  - `NON_ACT_RE` rejects show prose (songs, albums, "surround sound", discography…);
  - `_split_bill()` joins an "and" that sits between two descriptor words
    (`up and coming`) so it never fragments, then drops parts that are pure
    descriptor fragments. Stylized lowercase names (`swell foop`,
    `dougie poole`) are **kept**.
- **`build.py`** — splits multi-artist headliner names (`Nile & Coroner`,
  `A / B`) into co-headliners; the JSON-LD `performer` overrides the title's
  casing when it's a single name; support acts are de-duped against the
  headliners.

Shared parts (one copy, in `common/`): Apple Music confidence engine +
`artist_obj` (`apple_music.py`), show record shape / sort / JSON writer
(`build.py`), the reviewer page (`viewer/index.html`), the picker + server
(root `serve.py`).

## Apple Music

~35 unique artists across the current run. Tiers: 1.0 exact (auto-link),
≥0.80 close (auto-link, flagged for review), <0.80 not linked. The
`LINK_FLOOR` 0.80 guard and the DJ/bill guards live in `common/apple_music.py`
and apply to every venue that matches.

## Re-extract / re-scrape

`fetch.py` is incremental on the detail pages (cached URLs are skipped); the
`events/` listing is re-fetched every run because the window slides. The
`update_all.py` runner skips the site crawl when `cache/events.json.fetched_at`
is < 24 h old (`--refresh` / `--full` force it).
