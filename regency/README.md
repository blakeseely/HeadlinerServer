# The Regency Ballroom

Source: **theregencyballroom.com** — an AEG/AXS event-venue template. The
`/events` path is a JS app that 403s plain HTTP clients (nginx) and even real
browsers without a JS round-trip, but the template renders its event list from
a **public Azure-blob JSON published by AEG** (no auth, no key):

    https://aegwebprod.blob.core.windows.net/json/events/9/events.json

`fetch.py` does NOT hardcode that URL — it discovers it on the homepage each
run (regex over the HTML, with the last-known URL as fallback). One GET
returns the full calendar (40 shows, newest → oldest) with pre-structured
fields; there is no per-show detail page to crawl, no JSON-LD to unescape.

Each feed event gives us everything the build needs directly:

| feed field                              | → show field      |
|-----------------------------------------|-------------------|
| `title.headlinersText`                  | headline_artists  |
| `title.supportingText` ("with A, B")    | support_artists   |
| `title.presentedByText`                 | presenters        |
| `title.tour` (when ≠ headliner)         | show_title        |
| `eventDateTimeISO` / `doorDateTime`     | date, show_time, doors |
| `age`                                   | age_rating        |
| `ticketing.status` / `ticketURL`        | ticket_status / ticket_link |
| `eventId`                               | event_page        |
| `description` (AxS boilerplate)         | — dropped         |

Notes:
- `doorDateTime` is naive (no tz) while `eventDateTimeISO` carries the venue
  tz — build.py re-attaches the door time to the tz-aware event date.
- `ticketPriceLow/High` are `$0` for every current event (AXS hides prices
  pre-sale), so the price note is never emitted.
- "An Evening With <Artist>" headlines: the prefix is surfaced as
  `set_format`, the artist is looked up without it.
- All bills are live music → `event_type: "music"` (no film/comedy here).
- The feed is ~564KB with per-artist bios/media; `fetch.py` slims each event
  to the fields the build reads (~200KB cache).

Apple Music: 61/63 unique artists found (60 exact, 1 close, 2 not found —
both honestly).
