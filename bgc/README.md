# Bill Graham Civic Auditorium

Source: **billgrahamcivic.com** — the venue's official site, run by Another
Planet Entertainment on wpengine WordPress. Fully server-rendered: plain
GETs with a browser user-agent work (no Cloudflare, no JS app). The
auditorium bills **live music only** (pop / rock / hip-hop / electronic
tours), so every show is `music` and every act is matched to Apple Music.

## The /calendar listing is the backbone

One GET of `https://billgrahamcivic.com/calendar` returns **every** upcoming
show (no pagination — the `/event-listing` page is the same shows behind a JS
search widget; past shows fall off). Each is an
`<article class="event qtip">` card with clean structured fields:

| field | source | example |
|---|---|---|
| headliner | `<h2 class="attraction_title show-title">` | Moby |
| support | `<div class="bottomline">` (`<br>`-separated; an entry can be a comma run) | Azzecca / DJ Holographic |
| date | `<p class="event__start-date" content="YYYY-MM-DD HH:MM">` | 2026-11-05 |
| doors / show | `<span class="event__doors-open">` / `event__start-time` | 7:00 pm |
| ticket status | button text: `Buy Tickets` → on sale, `Sold Out!`, `SHOW MOVED`, `SIGN UP`, `PRESALE 10/28` | on sale |
| ticket link | the button's href (Ticketmaster) | … |
| event page | the `More Info` href → `/events/<slug>` | … |

The listing carries NO age rating and no Spotify links. The detail pages
(`/events/<slug>`) are server-rendered and add all three:

* **age** — the "This event is all ages." / "…18 and over." line
* **Spotify** — one `<div class="attraction">` block per artist, each with a
  `class="music"` open.spotify.com link (the shared `common.spotify.extract_links`
  strategy A picks them up per artist)
* **bio** — the headliner's `<div class="bio">` paragraph (empty for some
  shows → honest null)

Detail pages are fetched incrementally (3 workers, cached in
`cache/details.json` keyed by event page URL; a page that published no
Spotify link stores a `spotify: None` sentinel so backfills stay finite).

**The Theater at Bill Graham Civic Auditorium** is a separate ticketed room
in the same building with its own event category on the site. The
`/calendar` listing is venue-filtered to the auditorium (every row's
`venue-location-name` is the auditorium), so its shows are naturally out of
scope here — if the venue ever lists Theater shows in the main auditorium's
room, they will flow in through the same feed.

## Cache / build

* `fetch.py` → `cache/events.json` (+ `cache/details.json` incremental).
  Do NOT write a freshness stamp — the root `update_all.py` runner writes
  `cache/events.json.fetched_at`.
* `build.py` → `data/shows.json`. Support splits on NEWLINE and COMMA only
  (`&`/`and` live inside act names — "Grahame Lesh & Friends" is one band);
  a leading `feat.`/`featuring` credit is stripped off the first part;
  set-format parentheticals (`(DJ Set)`, `(duo)`) are stripped before the
  Apple Music lookup.
* Spotify: venue-published links win; `has_spotify_lookup: True` also lets
  the shared Spotify API lookup fill the acts the venue published no link for.
