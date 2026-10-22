# Apple Music search discrepancies: amc (app catalog) vs web search

Generated 2026-10-22 10:33 PDT. Compared **0** unique real artist names across all 13 venues
(every billed headliner + support act, deduped) against BOTH sources.

- **amc empty, web found it:** 0 — these are the ones the amc-first path silently misses
- Both found results, but different sets: 0
- Indeterminate (a search call failed mid-run): 0

## amc returns nothing, Apple Music web search returns something

These terms resolve in the web catalog but not in the app catalog the `amc` CLI drives. Each is now cross-checked at lookup time (web overrides an empty amc result), but the gap itself is worth knowing about.

| Search term | Web catalog results (top 5) |
|---|---|
