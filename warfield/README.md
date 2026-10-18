# The Warfield Theatre

Source: **thewarfieldtheatre.com** — an AEG/AXS venue template. Unlike the
Regency Ballroom (whose `/events` path is a JS app that 403s both curl and
real browsers), the Warfield's listing at `/events/all` is **fully
server-rendered** — one plain GET (browser user-agent, no Cloudflare) returns
every upcoming show. Each card carries the whole bill as four separate lines:

| line | element | example |
|---|---|---|
| presenter | `<h5 class="accentColor">` | Goldenvoice Presents |
| tour / show title | `<h5>` | The Valley Girl Problems Tour |
| headliner | `<h3 …><a>` | Kylie Cantrall |
| support | `<h4>` | with GIRLSET |

plus the date, the show time, and the ticket button (its `status_N` class +
label encodes on-sale / sold-out / coming-soon). No JSON-LD `Event` node and
no flight payload to decode — the listing is the clean backbone.

`fetch.py` walks the cards (a balanced-`<div>` counter extracts each; the
listing is not paginated, so one request is the whole schedule) and then
fetches each `/events/detail/<id>/` page (small thread pool, cached
incrementally by id) for the two fields the listing lacks: **doors** and the
**age restriction**. `cache/events.json` holds ~12 shows.

## Bill handling

Because the bill is already structured, `build.py` mostly maps 1:1. Two cases
need real logic:

- **A support marker inside the headliner line** — `Cookies Christmas 2026
  ft. Berner, Paul Wall, & Baby Bash`. The `ft./feat./with` part after the
  marker becomes support; and because "Cookies Christmas 2026" is a *host +
  event + year* bill, a trailing `Christmas|Halloween|… + year` tail is split
  off so the real lead act (**Cookies**) is looked up and the tail becomes the
  show title ("Christmas 2026").
- **A bare comma list in the support line** — `Sippy, Machaki` → two support
  artists (vs `with X` → one).

Everything else maps directly: tour line → `show_title`, presenter line →
`presenters`, `date_full` → `date`, doors/age → the shared fields.

## Apple Music

19/20 unique artists found (18 exact, 1 likely). The one not-found is **Song
Dongye** — genuinely absent from the Apple catalog (closest match @ 0.0), so
it is honestly left unlinked. The Warfield bills live music only (rock / alt /
K-pop / electronic / theater-musical tours), so every show is `music`.
