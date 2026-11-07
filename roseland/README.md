# Roseland Theater (Portland, OR)

Large touring room (~1,400 cap), same ownership as Wonder Ballroom (Music
Venue Properties). Feed: `data/shows.json` (metro `Portland`).

## Source — same plugin as Wonder Ballroom, drifted template

`roselandpdx.com/events/` — WordPress rhp-events, server-rendered, but the
markup has **drifted** from wonderball's, so a shared parser would rot
fast; each venue keeps its own parser and a drift in either trips that
venue's audit:

- wrapper class carries suffixes (`…rhpSingleEvent py-4 px-0 rhp-event__
  single-event--list`) — anchor on the leading token only;
- `eventDate` has **no year** ("Sun, Nov 08") — the year comes from the
  month-separator spans ("November 2026") in document order; the fetch
  warns if a card's printed month disagrees with its separator;
- no `eventAgeRestriction` div — age comes from the notes box
  (`rhp-event-notes-box`), split into `age_rating` + verbatim `note`;
- doors line without a comma ("Doors: 7 pm Show: 8 pm");
- `/events/page/2/` is a client-side mirror of page 1 (identical SSR
  payload) — pagination walks until a page yields nothing fresh.

This venue **receives moved shows**: Wonder Ballroom's
`**MOVED TO ROSELAND THEATER** FROST CHILDREN` bills here as a normal
2026-12-06 date (verified 2026-11-06).

Build rules = wonderball's (title status prefixes, colon-presenters,
en-dash tails, clause-less support as co-headline). Live Nation passes
through as a presenter.

## Validation

`SOURCES["roseland"]` = `parse_roseland` (separator-year dates, loose
wrapper anchor, notes-box), explicit support mode. First run: 33/33 dates,
33/33 heads, 23/23 support, 0 findings.
