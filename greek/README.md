# Greek Theatre (Berkeley)

Source: **thegreekberkeley.com** — the official **UC Berkeley** Greek Theatre
site (2001 Gayley, Berkeley, CA), run by **Another Planet Entertainment**
(same TicketWeb/WordPress platform as the Fox Oakland). It is fully
server-rendered (plain GET, no Cloudflare, no JS app).

> **Scope note.** The *full* Greek season (music **and** the famous theater /
> film programming) lives on **thegreek.com**, which is **hard-Cloudflare-blocked**
> for both curl and a real browser, so it cannot be a recurring scraper source.
> thegreekberkeley.com is APE's **exclusive-promoter concert listing** — the
> Greek's *music* shows. It is a small, live schedule (a handful of upcoming
> concerts; APE has added more over time, and the adapter picks up whatever the
> listing page currently serves). All shows here are therefore `music`.

## The listing is the backbone

`/event-listing/` is fully server-rendered and **not paginated** (one GET = the
whole listing; the "Next" in the page is a JS thickbox string, not real
pagination — `/event-listing/page/2/` returns the same shows). Each show is a
`<div class="mix detail-information">` card with the bill as separate fields:

| field | source |
|---|---|
| date | `<div class="single-date-show" itemprop="startDate" content="October 19, 2026 7:30 pm">` |
| tour | `<div class="topline">…</div>` (may stack a banner / reschedule-notice line) |
| headliner | `<h2 class="show-title">…</h2>` |
| support | `<div class="support">Act<br>Act</div>` (`<br>`-separated) |
| doors / show | `<span class="event__doors-open">` + `<span class="event__start-time">` |
| tickets | `<a class="button[ ghost][ soldout]">` (class encodes sold out) |
| page | `<a href="/events/<slug>">` |

Detail pages (`/events/<slug>/`) add the two things the listing lacks, fetched
**incrementally by event_page** (thread pool, cached in `cache/details.json`):
- **age** — the `<div class="more-information">` block (its age line is the only
  variable paragraph; the rest is venue boilerplate).
- **description** — the `<div class="bio">` per-artist bio (a rare venue-move /
  reschedule notice is kept as `note`).

## Bill handling

- **Support** splits on the venue's own line breaks (`<br>` → newline) + commas,
  **not** `&`/`and`.
- **Headliner** is one billed act; a colon-tail (`Ms. Lauryn Hill & Wyclef Jean:
  Celebrating 30 years…`) is split off so the headliner stays clean. A headliner
  like `Ms. Lauryn Hill & Wyclef Jean` is billed as **one** joint act — the Apple
  Music engine searches the whole name, falls back to the parts, and flags the
  partial (Lauryn Hill @ 70%) for review rather than silently mis-linking.
- **Tour** = the topline, stripped of banner lines *and* reschedule-notice lines
  ("Show Rescheduled from 10/18/2026 …" is dropped from the title; the full
  notice is preserved as `note`).
- **Single room** (the Greek amphitheater) → `room` stays null.
- **event_type** = `music` (all APE concerts); we still classify from the
  venue's own copy rather than hardcoding, in case APE ever lists a comedy show.

## Apple Music

5/7 unique artists found (5 exact, 2 honest not-founds: the `Ms. Lauryn Hill &
Wyclef Jean` joint bill — closest is Lauryn Hill @ 70%, flagged for review — and
the `DERON b2b Darmon` back-to-back DJ slot, a compound the catalog doesn't
resolve). No hand-coded special cases; the honest remainder is what the reviewer
is for.
