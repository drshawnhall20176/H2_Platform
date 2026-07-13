# H2 Sports Platform — Build Checkpoint

**This is the multi-sport platform build, snapshotted after Stage 1 + the theme-proof styling.**
It is the intended future source of truth (merged MLB + the sport-selector foundation). MLB runs
exactly as the standalone does today; the platform scaffolding is additive and does not change MLB
behavior.

## What's in this checkpoint (all tested — 10/10 test files green)

### Stage 1 — the sport-selector foundation
- **`sports.py`** — the sport registry. All 7 leagues registered: MLB (live), NFL (engine present,
  not yet wired live), and WNBA / NBA / NHL / NCAAF / NCAAMB as placeholders (enabled=False).
  Adding a league later = one entry here. This is the heart of the platform.
- **`odds_api.py`** — refactored sport-agnostic: `sport`, `markets`, and `projections_module` are
  parameters (MLB defaults preserved, so nothing breaks).
- **`clv_capture.py`** — refactored sport-agnostic: `market_map` and `single_line_markets` are
  parameters (MLB defaults preserved).
- **`betlog.py`** — `sport` column added to SQLite + Postgres schemas, with self-migration and a
  `sport` filter on `list_bets` (legacy rows with no sport are treated as MLB).
- Backward-compat proven: the full MLB suite passes against the refactored modules.

### Theme-proof gradients
- **`styling.py`** — heatmap coloring that computes text color PER CELL from the background
  luminance (dark text on pale cells, white on deep) so tables are readable in BOTH light and dark
  mode. Avoids matplotlib (a past segfault source) by interpolating RGB directly; supports diverging
  RdYlGn; installs a drop-in `Styler.theme_gradient` method.
- All 7 MLB heatmap pages converted from `background_gradient` -> `theme_gradient` (0 raw calls left).

### Workflow fix folded in
- `.github/workflows/capture-closing-lines.yml` now installs the full pinned deps
  (`pip install -r requirements.txt`) so the runner never crashes on a missing transitive import.

## NOT YET DONE (next stages)
- **Stage 2:** wire the sport selector into the UI; make the shared proof pages (Edge Board, Bet
  Log, Track Record, Media Room, Podcast, Retrospective) call `sports.active()` instead of hardcoded
  MLB; hide MLB-specific analysis pages (Dinger/Pitching/Matchup Lab) when a non-MLB sport is active.
- **Stage 3:** flip NFL on as the second live sport (fill its markets/market_map in the registry).
- **Stage 4+:** the remaining five leagues as their engines are built.

## Deploy notes (when the platform goes live, same lessons as the MLB repo)
- Main file path = `streamlit_app.py`
- Python 3.11 via the app's Advanced-settings dropdown (runtime.txt alone was ignored on Cloud)
- Requirements are pinned; keep them pinned
- Add the `sport` column to the live Supabase `bets` table (betlog self-migrates via
  `ADD COLUMN IF NOT EXISTS`, so this may be automatic — verify)
