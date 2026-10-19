# Frost Amphitheater (Stanford University)

Source: **Stanford Live** — `https://live.stanford.edu`, the university's arts
organisation, which promotes the Frost Amphitheater's ticketed concerts (the
summer season, ticketed via AXS).

## Why Stanford Live and not arts.stanford.edu

The Frost Amphitheater is an on-campus Stanford venue, but its concerts are
promoted and ticketed by Stanford Live, whose website (`live.stanford.edu`)
is the source of record. The university's `arts.stanford.edu` calendar is
Cloudflare-walled for both curl and real browsers, so it is NOT a viable
recurring source. Stanford Live's calendar page is a client-rendered app (its
HTML is an empty shell), but it renders from a public JSON API:

    GET https://live.stanford.edu/api/events/Live

One GET returns the **entire current season** as a JSON array — no pagination,
no Cloudflare, plain `curl` works. Every record carries a `Frost` boolean the
site itself uses to flag Frost Amphitheater shows, plus the billed title,
presenter, series suffix, summary, tags, and per-performance dates/ticket
links.

## Data flow

1. `fetch.py` pulls the season JSON and keeps the Frost shows
   (`Frost: true`, with a venue-name / slug fallback). Each show's detail
   page (`/events/<season>/frost/<slug>/`) is **fully server-rendered** and
   fetched incrementally (threaded, cached in `cache/details.json`) for what
   the API lacks: the tour title (`event-header__suffix`), the per-date
   "Featured Artists" support lists, the age line, the doors time, and the
   artist bio.
2. `build.py` maps to the shared show shape. Multi-night shows (two
   performances) become one record with the first date; the other dates are
   folded into `note` ("(2 dates) Also: …"). `room` stays None (single
   amphitheater). Every show is `event_type: music`.

## Scope note: the off-season is legitimately empty

Frost is a **summer** venue (season runs roughly April–October). In the
off-season the API's `Frost` flag is `false` for everything and this venue
correctly yields **zero shows** — an honest empty calendar, not a bug. When
the next season is announced by Stanford Live, the 4 AM refresh picks it up
automatically.
