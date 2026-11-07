# Crystal Ballroom

Source: **crystalballroompdx.com** — McMenamins' historic ballroom (Pearl/
West End), programmed by Edgefield Concerts. WordPress + *The Events
Calendar* (TEC), no bot wall. First venue of the **Portland** metro.

The schedule lives in TWO open endpoints that are joined by event URL:

| endpoint | what it provides |
|---|---|
| TEC REST `GET /wp-json/tribe/events/v1/events?per_page=50&page=N` | the FULL upcoming window (~70 rows / 2 years): ISO `start_date` (verified to be the SHOW start, not doors), description, cost, canonical URL. No ticket links, no lineup. |
| card grid — homepage + `/events/page/2…N/` (12 cards/page, ends at a 404) | what the venue BILLS as its show calendar: promoter, tour-tail h1 (`display-in-title`), h2 subtitle (`hidden-card-title`), and the `buy-button` → etix.com. No dates with a year. |

BACKBONE = the card grid. The REST rows with no card (~17) are recurring
non-show programming (History & Art Tour, First Thursday market) — the
fetch SKIPS them and prints their titles as a warning, so a real show ever
appearing card-less is visible, not silent.

## The two card flavors

The homepage tour-schedule widget bills richly (h1 `display-in-title` + h2
`hidden-card-title`); the deeper `/events/page/N` grid cards bill as a plain
`<div class="title" id="crystal-card-title">` with no support field. Rather
than parse two shapes, `fetch.py` re-reads every show's DETAIL page (cached
incrementally by URL) — each one carries the h1/h2 identically, plus the
server-rendered `event-singular-time-details` module ("5:30pm doors, 7pm
show" + the age note, the venue's ONLY age source). The detail-page fields
are authoritative over the card fields.

On cards lacking an h2 element the lazy `(.*?)</h2>` can run past the
element into a related card and swallow page boilerplate — titles/supports
go through `_title_frag`, which rejects >200-char fragments or ones
containing "Tickets / Add To Calendar / Share Event" (the NYE-ball card
class).

## Bill handling (`build.py`)

The h1 + h2 are re-assembled and run through `common.bill.parse_bill` (the
shared TicketWeb grammar), with three venue-specific rules:

* an h2 that starts with **"Presents …"** or ends with **"… Tour"** is the
  headliner's own TOUR ("Presents Still Searching" — Senses Fail;
  "Distracted AF Tour" — Thundercat), joined as a dash tail for the show
  title, NEVER as a co-bill;
* a support clause (**with / w/ / featuring / special guest**) goes through
  bill's normal support split (comma-only; "special guest" boilerplate
  dropped); a bare non-clause h2 joins as ` x ` (co-headline);
* **"An evening with X"** keeps the whole title as ONE headliner (the
  chapel/pappy precedent — the Apple engine resolves X via compound-part
  search).

Event type: music by default; `other` for the venue's market/bazaar
programming (Brewfest class); comedy from a TIGHT bio regex — with
"Comedy Central" (the TV channel) scrubbed first, because a Neil Diamond
tribute's bio listing its TV appearances mis-flagged once (2026-11).

Time policy: the venue's own "8pm show" line wins; TEC `start_date` is the
fallback. Doors only ever come from the time module (50/54 shows publish
it). Ticket status: only "Tickets" (→ `on sale`) exists on the buttons
today; any NEW button text is kept verbatim (no default-on-sale).

No venue-published per-artist Spotify links → registry
`has_spotify_lookup: True` (API lookup fills what it can; honest nulls for
local/DJ acts).
