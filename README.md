# Headliners

Extraction + review tooling for live-music (and film/comedy) show calendars.
Each venue is a self-contained sub-project with its own fetch/build/serve
pipeline and a local side-by-side reviewer.

## Venues

| Dir | Venue | Source | Route | Shows |
|-----|-------|--------|-------|-------|
| [`independent/`](independent/) | The Independent, San Francisco | theindependentsf.com | `:8050/independent/` | music; Apple Music matching (confidence tiers) |
| [`castro/`](castro/) | The Castro Theatre, San Francisco | thecastro.com | `:8050/castro/` | music + film + comedy + other (derived categories); no Apple Music |

Each sub-project is laid out the same way:

```
<venue>/
  fetch*.py        # pull the venue's schedule into cache/
  build.py         # classify/parse into data/shows.json
  serve.py         # local reviewer (independent: 8050, castro: 8051)
  viewer/index.html
  cache/           # raw + per-page captures
  data/shows.json  # the extracted dataset
```

### Running

```
python3 serve.py            # ONE entry point: http://127.0.0.1:8050
```

The root `serve.py` serves the **theater picker** at `/`, then each venue's
reviewer underneath: `/independent/` and `/castro/` (same pages the
per-venue servers served). Data is re-read per request, so a fresh
`build.py` shows up immediately.

The per-venue `serve.py` scripts still work standalone (8050 / 8051) but the
unified root server replaces them for normal use — run one or the other.

The two venues share the *pattern* (fetch → build JSON → side-by-side viewer)
but keep separate code where their markup differs — the Castro has no category
labels in its HTML, so it derives music/film/comedy from description text.

See each venue's own README for pipeline details.
