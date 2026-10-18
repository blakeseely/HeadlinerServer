# August Hall

Source: **augusthallsf.com** — a TicketWeb WordPress site. Everything is
server-side HTML (no JSON-LD Event node, no JS-rendered data), so plain GETs
work with curl.

Two-step capture in `fetch.py`:

1. **Listing** — `/events/page/N/` (20 cards/page, follow until the linked
   page numbers stop growing) gives each show's date, billed title, and its
   `/tm-event/…` detail URL.
2. **Details** — one GET per show (3 workers, 3 attempts) for the canonical
   name, full date, doors/show times, age restriction, and the ticket button
   (its class + text encode the status: `tw_onsale` → on sale,
   `tw_offsale` → sales ended, "Sold Out", "Coming Soon").

`cache/events.json` holds ~43 shows (the venue posts a long horizon, Oct 2026
→ Jun 2027).

## Title grammar (the interesting part)

`build.py` splits the billed title into headliner / support / tour title:

| billed title | headliner | support | show_title |
|---|---|---|---|
| `Actress` | Actress | — | — |
| `Ax and the Hatchetmen: The Late Checkout Tour 2026` | Ax and the Hatchetmen | — | The Late Checkout Tour 2026 |
| `Introducing The Aces with special guest Gatlin` | The Aces | Gatlin | — |
| `Lil Pete: Real Is Back Tour` | Lil Pete | — | Real Is Back Tour |
| `DJ Raphi HYPE TOUR USA 2.0` | DJ Raphi | — | HYPE TOUR USA 2.0 |
| `Baby Smoove Live! – The Purple Heart Tour` | Baby Smoove | — | The Purple Heart Tour (set_format: Live) |
| `VNV Nation – An Evening With` | VNV Nation – An Evening With (kept whole) | — | — |
| `NICE AS F*#K – BACK AS F**K NICE AS EVER` | NICE AS F*#K (as billed) | — | BACK AS F**K NICE AS EVER |

Rules that survive: tour tails after `:`, `–`, `-` are split only when the
left side still reads as an act; bare tour tails ("… Tour", "… Tour II",
"HYPE TOUR USA 2.0") split when the remainder is a plausible name; dangling
fragments ("An Evening With") are NOT treated as tour titles; `Live!` moves
to `set_format`. Censored asterisk runs stay verbatim (the venue obscures the
act, so no lookup is attempted for the name itself — support acts are
uncensored and are looked up normally).

## Apple Music

38/42 unique artists found, all exact. The 4 not-found are honest: a censored
name, Earlybirds Club, Begging For Sax, and the "Pre-Show Speakeasy" series
(a house event, not an artist).
