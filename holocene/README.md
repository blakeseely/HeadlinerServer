# Holocene (Portland, OR)

Electronic/DJ + indie club on SE Morrison (~450 cap). Feed:
`data/shows.json` (metro `Portland`).

## Domain warning

The venue REBUILT: `holocenepdx.com` is **NXDOMAIN**; the live site is
**holocene.org** (calendar `/events`, event pages `/events/<ISO>-<slug>`).
Old notes pointing at holocenepdx.com are dead.

## Source

Custom SSR site, no bot wall, no WP. `/events` returns every upcoming show
server-rendered (`article.crow` rows; etix-backed, `data-id` = etix
performance id). ISO date comes from the event **href** — the visible badge
has no year. Buy-button variants: plain=`Tickets`, `disabled`="Sold out"
(keeps its etix href), `at-door`="At the door", `crow-buy-none` (no status
— detail page decides).

Per-show event pages bill PRE-PARSED — h1 `ev-title` IS the headliner,
`ev-sub` the tour, `ev-with` the support clause, plus a Doors/Ages `<dl>` —
and carry a schema.org **MusicEvent JSON-LD** (`performer[]`, `doorTime`,
`startDate` = SHOW start (verified: "9PM" calendar vs T21:00),
`eventStatus`, `offers{availability, price}`). fetch.py crawls these
incrementally (details.json).

## Rules encoded in build.py

- **Never run calendar titles through parse_bill** — "Emo Nite at Holocene
  presented by Emo Nite LA" butchers into headliner "by Emo Nite LA".
  `ev-title` wins verbatim; only `ev-with` is split (local with-clause
  stripper; "Special Guests"/"TBA" dropped).
- DJ/rave nights are `music` (Club Darc rule); tight comedy regex; the
  occasional children's-arts assembly → `other`.
- LD `eventStatus` → cancelled rows keep `ticket_status=cancelled`;
  postponed/rescheduled → note + needs_review. `availability=SoldOut`
  overrides the button class.

## Validation

`SOURCES["holocene"]` = calendar rows (`parse_holocene`) + new
`support_mode="ld_performers"`: per-show fetch of the event page, support =
`performer[]` entries not matching a feed headliner. First run: 48/48 dates,
48/48 heads, 10/10 support, 0 findings.
