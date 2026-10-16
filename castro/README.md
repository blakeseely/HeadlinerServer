# The Castro Theatre — show extraction

Extracts the full event calendar from [thecastro.com](https://thecastro.com/calendar/)
(music, film, comedy, and other) into a reviewable JSON file, with a local
side-by-side viewer to check the extraction against the live site.

Sibling project: `independent-sf` (The Independent). This one has its own
fetch/build/serve code because the site's markup and the (absent) category
labels are different, but the viewer pattern is the same.

## Pipeline

| Step | File | Output |
|------|------|--------|
| 1. Fetch | `fetch_calendar.py` | `cache/calendar.json` (one record per calendar card: title, date, doors/show times, topline/bottomline, ticket link + status) |
| 2. Details | browser-captured | `cache/details.json` (per event page: `desc` + `bio`) |
| 3. Build | `build.py` | `data/shows.json` |
| 4. Review | `serve.py` | `http://127.0.0.1:8051` |

```
python3 fetch_calendar.py   # re-pull the calendar (needs a working thecastro.com fetch)
python3 build.py            # classify + split + assemble data/shows.json
python3 serve.py            # open the reviewer
```

## Category classification

The site does **not** label a card with a category (music / film / comedy).
`build.py: classify()` derives one from the event text using a cascade:

1. `DJ …` title → **music**
2. venue film **stamp** in `desc`/topline (rating line, "Film format",
   festival credit, 35mm/70mm) → **film**
3. **music** evidence in the bio/topline (band, album, songs, producer,
   tour, …) → **music**
4. **comedy** evidence in title/bio (comedian, stand-up, comedy) → **comedy**
5. soft film words (screening, "directed by", sing-along, watch party) → **film**
6. spoken-word / award shows (The Moth GrandSLAM, Legends Awards) → **other**
7. default → **music**; flagged `needs_review` when the body is only the
   generic all-ages stub (the 13 detail pages that returned no description).

Title signals are checked before bio signals: the billed name is the strongest
evidence ("Fred Armisen: Comedy for Musicians…" is comedy even though his bio
says "musician").

## Apple Music

Per the request, **no Apple Music matching** is done for the Castro — the
artist objects are plain `{name}` records. (The Independent project does the
confidence-tiered Apple Music lookup; the viewer here renders plain chips and
skips the "not found" / near-match logic.)

## Notes
- `cache/calendar_raw.html` is a bulky HTML snapshot and is git-ignored.
- The Castro is `thecastro.com` (the `.org` is a parked squatter).
- Detail pages are behind Cloudflare for plain HTTP; `details.json` was
  captured by navigating in a real browser. Re-capture is a browser step, not
  part of `build.py`.
