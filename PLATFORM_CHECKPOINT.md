# H2 Sports Platform — Build Checkpoint

**This is the multi-sport platform build.** It is the live source of truth (merged MLB + WNBA on
one sport-selector foundation). MLB runs exactly as the standalone did originally; WNBA is now a
second real, priced sport — not a placeholder.

## What's in this checkpoint (all tested — 130/130 tests green)

### Stage 1 — the sport-selector foundation
- **`sports.py`** — the sport registry, the heart of the platform. `Sport.engine` / `.projections`
  lazily import a sport's own modules by name, so pages can call `sports.active().engine` instead
  of hardcoding `mlb_engine`.
- **`odds_api.py`** — sport-agnostic: `sport`, `markets`, `projections_module` are parameters.
  `fetch_slate_props` (the function Edge Board actually calls) now threads `sport` all the way
  through — Stage 1 had left this one silently hardcoded to MLB; fixed in Stage 2.
- **`betlog.py`** — `sport` column on every bet, with a `sport` filter on `list_bets` (legacy rows
  with no sport are treated as MLB).

### Stage 2 — sport selector wired in + WNBA built out
- **`streamlit_app.py`** — sidebar sport selector is live (`sports.render_sport_selector()`).
  MLB-only analysis pages (Pitching Lab, Dinger Engine, Matchup Lab) disappear from nav — not just
  greyed out, actually unrouted — when a non-MLB sport is active.
- **Owner/public split** — same codebase, deployed twice on Streamlit Cloud, differing only by one
  secret (`AUDIENCE = "public"` on the Discord-facing deployment). Gates Bet Log, Media Room,
  Podcast Studio, and Edge Board off the public build. `streamlit_app_discord.py` is the second
  deployment's entrypoint — 2 lines, no logic of its own (Streamlit Cloud requires a distinct
  entrypoint file per app; two apps can't share one).
- **Edge Board is now genuinely sport-routed** — dispatches through `sports.active().engine` /
  `.projections` instead of hardcoded `mlb_engine`/`projections` imports. This is the one page that
  actually runs a second sport's live board end-to-end.
- **Bet Log / Track Record** — filter by active sport; markets list and ledger both sport-aware.
- **`sports.require_sport(key, feature_name)`** — a STRICTER guard than `require_live_engine`, for
  pages that haven't been individually ported yet and still hardcode MLB's engine internally
  (Media Room, Podcast Studio, Retrospective, Best Bets, Command Center). Blocks any sport but the
  required one, even one with real markets configured — `require_live_engine` alone stopped being
  a safe proxy for "this page supports the active sport" the moment WNBA got real markets too.

### WNBA — the second live sport (Core 4 markets: Points, Rebounds, Assists, Threes Made)
- **`config_wnba.py`** — 15-team reference list (2026 season, incl. Portland Fire / Toronto Tempo
  expansion), verified live on 2026-07-13. Reference data only — no longer used for team-ID
  cross-referencing (see below).
- **`wnba_engine.py`** — data layer on **ESPN's public API** (`site.api.espn.com` /
  `site.web.api.espn.com`), NOT `nba_api`. **Data source was switched mid-Stage-2** after a live
  deploy hit `requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='stats.nba.com', ...)` —
  confirmed via `nba_api`'s own GitHub issue history (#182, #320, #498, going back to 2020) as a
  long-standing, structural block on cloud-hosting IP ranges (AWS/Heroku/GCP/Streamlit Cloud), not
  a parameter bug. No amount of retries or header-tuning fixes an IP-level block, so rather than
  patch around it, the engine was rewritten against ESPN's endpoint family instead — same
  "unofficial API" risk category as nba_api, but with no comparable cloud-blocking pattern in its
  own issue history. Endpoints and field names came from github.com/pseudo-r/Public-ESPN-API's
  documented schemas (WNBA gamelog explicitly listed as verified working), not live testing — same
  sandbox network limitation as before. The rewrite only touched the fetch layer; `avg_minutes`,
  `player_row`, and `build_slate` (the pure orchestration logic) are untouched, and all their
  existing tests passed unchanged — the payoff of keeping those two layers separate. Simpler than
  the nba_api version in two ways: no team-ID cross-reference table needed (ESPN's scoreboard
  response carries team IDs + names inline) and no WNBA season-string guessing (gamelog defaults
  to the current season server-side).
- **`wnba_projections.py`** — unchanged by the data-source switch (operates only on `rows`/`meta`
  from `build_slate`, doesn't know or care which API produced them). Empirical bootstrap model:
  resamples each player's last 10 games (`config_wnba.RECENT_GAMES_N`) with replacement to build a
  probability distribution per stat. Documented v1 limitation: no opponent/pace adjustment yet.
  Reuses the genuinely sport-agnostic math from `projections.py` (`prob_over`, `prob_for_side`,
  `normalize_name`, `format_et`) rather than duplicating it.
- Registry: `sports.py`'s WNBA entry is `enabled=True` with real `markets`/`market_map`. WNBA
  player props confirmed on the free tier of the-odds-api.com (not gated behind a paid plan).
- `requirements.txt`: `nba_api` removed (no longer a dependency). No new dependency needed — the
  ESPN engine only uses `requests`, already required elsewhere in the platform.
- Media Room, Podcast Studio, Retrospective, Best Bets, Command Center are **not** WNBA-aware yet —
  explicitly gated to MLB-only via `require_sport`, so picking WNBA shows a clear "not built for
  this page yet" message instead of silently running MLB content under a WNBA label.

### Theme-proof gradients
- **`styling.py`** — per-cell text contrast (dark on pale, white on deep), benchmark-anchored
  thresholds so a stat colors the same everywhere. SLG/xwOBA are green-when-high on every page
  that colors them (Matchup Lab used to reverse this vs. Dinger Engine — fixed, and a regression
  test (`test_slg_xwoba_same_direction_on_every_page`) locks it in).

## NOT YET DONE (next stages)
- **Media Room / Podcast Studio / Retrospective / Best Bets / Command Center for WNBA** — currently
  MLB-only by explicit guard (see above). Porting these means real content work, not just an
  import swap (Podcast Studio's script generation is written in baseball terms throughout).
- **WNBA opponent/pace adjustment** — v1 projection model is recent-form-only.
- **Stage 3:** flip NFL on (engine/projections modules exist — `nfl_engine.py`/`nfl_projections.py`
  — but are untested and `nfl_data_py` isn't in `requirements.txt` yet; markets/market_map in the
  registry are still empty).
- **Stage 4+:** NBA, NHL, NCAAF, NCAAMB as their engines are built.

## Deploy notes
- Main file path = `streamlit_app.py` for the owner app, `streamlit_app_discord.py` for the
  Discord/public app (same repo/branch, both apps — Streamlit Cloud requires distinct entrypoints
  per app, see Stage 2 above).
- Python 3.11 via the app's Advanced-settings dropdown (runtime.txt alone is ignored on Cloud)
- Requirements are pinned; keep them pinned. `nba_api==1.11.4` added for WNBA.
- Add the `sport` column to the live Supabase `bets` table if it isn't there already (betlog
  self-migrates via `ADD COLUMN IF NOT EXISTS` — verify on first deploy).
- Discord/public app's own Settings → Secrets needs `AUDIENCE = "public"` plus the same DB/API
  secrets as the owner app.
- **First-deploy WNBA checklist:** confirmed via screenshot on 2026-07-13 that the `nba_api`-based
  build hit a real production `ReadTimeout` against `stats.nba.com` — a known cloud-IP-blocking
  issue with that data source, not fixable via retries (see WNBA section above). `wnba_engine.py`
  was rewritten against ESPN's public API instead, from documented response schemas rather than
  live testing (same sandbox limitation as before). Confirm a real WNBA slate loads on Edge Board
  without errors. If it's still empty, check Streamlit Cloud's logs for `WNBA ESPN API request
  failed` entries — every fetch failure is logged with the exact URL and params that failed.
