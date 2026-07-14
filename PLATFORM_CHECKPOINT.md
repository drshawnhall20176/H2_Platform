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
- **`wnba_engine.py`** — data layer on **ESPN's public API**, NOT `nba_api`. Went through TWO
  data-source pivots during Stage 2, both driven by live debugging with real deploy output rather
  than guesswork:
  1. `nba_api`/`stats.nba.com` → ESPN, after a production `ReadTimeout` confirmed `nba_api`'s
     long-documented cloud-IP-blocking problem (see git history / earlier checkpoint text).
  2. Within the ESPN rewrite itself: `.../athletes/{id}/gamelog` → `.../summary?event={id}`
     (per-game boxscore), after live responses (pasted back from the deployed app) showed the
     gamelog endpoint's real WNBA shape diverges from its own documentation — `events` is a dict
     keyed by game ID, not a list, and individual events carry game context (opponent, score,
     result) but no per-player stat line at all. wehoop (SportsDataverse's R package built
     specifically for ESPN's WNBA/WBB data) independently documents that exact endpoint family as
     "less stable than the rest of the surface," which matches what was found. The boxscore
     endpoint pulls every player's stats for a game in one call — fetched once per game and shared
     across every player on the slate who played it (`_get_json_cached`, ~12x fewer requests than
     one gamelog call per player).
  Team-level boxscore fields were confirmed against a real independent example (ScrapeCreators'
  walkthrough); the player-level `statistics[].names/athletes/stats` shape is still sourced from
  documentation, not a confirmed live WNBA response — verify on first deploy after this fix, same
  as before. `_get_json`/`_get_json_cached` log every failed request with the exact URL/params, so
  a mismatch shows up in Streamlit Cloud's logs rather than silently as an empty slate.
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
- **Roster shape fix (2026-07-14):** `_diag` instrumentation (see below) showed `get_schedule`
  correctly finding both real games for the date, but all 4 team rosters returning 0 players with
  no "missing key" warning — meaning `athletes` was present but not shaped as the documented
  `{"position", "items": [...]}` groups. `get_team_roster` now handles both that shape AND a flat
  list of player objects directly (the more likely real WNBA shape), rather than assuming one.

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
- **First-deploy WNBA checklist:** confirmed live (schedule endpoint verified directly, gamelog
  endpoint's real shape captured via live responses pasted back from the deployed app) that the
  athlete-gamelog approach didn't carry per-player stats for WNBA the way documented — rewritten
  to pull from the per-game boxscore instead (see WNBA section above). Confirm a real WNBA slate
  loads on Edge Board without errors. If it's still empty, check Streamlit Cloud's logs for `WNBA
  ESPN API request failed` entries — every fetch failure logs the exact URL and params. If there
  are NO such entries but the slate is still empty, the boxscore's `players[].statistics[].
  athletes[]` shape is the next thing to verify live — that part is still sourced from
  documentation, not a confirmed WNBA response.
