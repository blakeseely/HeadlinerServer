# Headliners

Extraction + review tooling for live-music (and film/comedy) show calendars.
Each venue is a self-contained sub-project with its own fetch/build/serve
pipeline and a local side-by-side reviewer.

## Venues

| Dir | Venue | Source | Reviewer | Shows |
|-----|-------|--------|----------|-------|
| [`independent/`](independent/) | The Independent, San Francisco | theindependentsf.com | `:8050` | music; Apple Music matching (confidence tiers) |
| [`castro/`](castro/) | The Castro Theatre, San Francisco | thecastro.com | `:8051` | music + film + comedy + other (derived categories); no Apple Music |

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
cd independent && python3 serve.py      # http://127.0.0.1:8050
cd castro      && python3 serve.py       # http://127.0.0.1:8051
```

The two venues share the *pattern* (fetch → build JSON → side-by-side viewer)
but keep separate code where their markup differs — the Castro has no category
labels in its HTML, so it derives music/film/comedy from description text.

See each venue's own README for pipeline details.
