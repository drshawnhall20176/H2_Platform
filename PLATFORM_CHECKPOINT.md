# H2 Sports Platform — Build Checkpoint

**This is the multi-sport platform build.** It is the live source of truth (merged MLB + WNBA on
one sport-selector foundation). MLB runs exactly as the standalone did originally; WNBA is now a
second real, priced sport — not a placeholder.

## What's in this checkpoint (all tested — 180/180 tests green)

### Stage 1 — the sport-selector foundation
- **`sports.py`** — the sport registry, the heart of the platform. `Sport.engine` / `.projections`
  lazily import a sport's own modules by name, so pages can call `sports.active().engine` instead
  of hardcoding `mlb_engine`.
- **`odds_api.py`** — sport-agnostic: `sport`, `markets`, `projections_module` are parameters.
  `fetch_slate_props` (the function Edge Board actually calls) now threads `sport` all the way
  through — Stage 1 had left this one silently hardcoded to MLB; fixed in Stage 2. **A second,
  related bug found via a live WNBA odds fetch (2026-07-14):** `fetch_slate_props` passed
  `markets` into the API call (`fetch_event_props`) correctly, but never into the *parsing* step
  (`parse_event_offers`), which has its own independent default of MLB's `SUPPORTED_MARKETS`.
  Real WNBA offers were being fetched successfully and then silently discarded during parsing —
  every market key got filtered out because none of `player_points`/`player_rebounds`/etc. are in
  MLB's list. Symptom was `Props matched: 0` **and** `Unmatched: 0` together (not a name-mismatch
  count > 0), which is the tell that the offers list itself was empty before matching ever ran.
  This bug was latent since Stage 1 — invisible for MLB purely because MLB's markets happened to
  equal the hardcoded default, so nothing exposed it until a second sport's markets genuinely
  differed. Locked in with `test_fetch_slate_props_threads_markets_into_parsing`.
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
  pages that haven't been individually ported and still hardcode one sport's engine internally.
  Used in Stage 2 to gate Media Room/Podcast Studio/Retrospective/Best Bets/Command Center to MLB
  before they had real WNBA support (see Stage 3 below — all five now use `require_live_engine`
  instead, since they're genuinely sport-routed). Still the right tool for any future page that
  hardcodes one sport before it's been ported.

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
- **Boxscore data source fix (2026-07-14):** with rosters fixed, the same diagnostic approach
  showed `get_game_boxscore` reaching real team blocks (`keys = ['team', 'statistics',
  'displayOrder', 'homeAway']`) but with no `players` key at all — confirmed on BOTH
  `site.api.espn.com` and `site.web.api.espn.com`'s `summary` endpoint (identical shape on both
  hosts, ruling out a simple hostname mismatch). Root cause: for these WNBA games, per-player
  boxscore data isn't nested inside each team block on the "site" API family at all — it lives on
  a genuinely different pathway, `cdn.espn.com`, confirmed live via a widened diagnostic dump:
  `gamepackageJSON.boxscore.players` is a real array there, a SIBLING to `boxscore.teams` (one
  entry per team) rather than nested inside each team block the way the "site" family's schema
  assumed. `get_game_boxscore` now calls `cdn.espn.com/core/wnba/boxscore?xhr=1&gameId=...`
  instead. Locked in with `test_get_game_boxscore_uses_cdn_endpoint`.
- **Live-verified end to end (2026-07-14):** real WNBA slate, real rosters, real boxscores, real
  Odds API props, real edges computed and displayed on Edge Board — confirmed via screenshot.

### Stage 3 — the other five pages made genuinely WNBA-aware (2026-07-14)
Media Room, Podcast Studio, Retrospective, Best Bets, and Command Center were gated MLB-only via
`require_sport` in Stage 2. All five are now real ports, not just an unlocked guard — each was
checked for what's actually MLB-specific vs. genuinely shared logic before touching it:
- **`wnba_engine.get_team_recent_game_ids` lookahead-bias fix** — excludes games ON before_date
  itself, not just future ones. Mattered beyond tonight's board: called for a PAST date (retro
  grading, after that date's games are done), the target game would otherwise leak into its own
  "recent form" sample. A genuine correctness bug, not just plumbing — locked in with
  `test_get_team_recent_game_ids_excludes_games_on_the_target_date_itself`.
- **`wnba_engine.get_player_results(date_str)`** — added, matching `mlb_engine.get_player_results`'s
  exact contract (`Dict[player_id, Dict[stat_key, value]]`), so `retro.py`'s grading logic works
  identically for either sport with zero changes to the grading code itself.
- **`wnba_projections.build_best_bets(rows)`** — new. Ranks plays by conviction (model prob ÷ a
  0.5 reference — the WNBA default lines aren't book-calibrated the way MLB's per-market
  reference rates are, so treating them as genuinely even is the honest choice, not an
  approximation). "Why" reasoning comes from the player's own recent-game log (hit-rate at the
  line, hot/cold trend) since no park/weather/platoon signals exist for basketball. Output schema
  matches `projections.build_best_bets` exactly (Player/PlayerId/Team/Game/Opp/Market/Side/Line/
  ModelProb/Fair/Conviction/Why) so every consuming page renders either sport's plays through the
  same code.
- **`wnba_projections.explain_miss(row, market)`** — WNBA equivalent of `retro.explain_miss`.
  "Catchable" means trending up over the last 3 games before this one (recency weighting hadn't
  caught up); "genuine outlier" means no such trend, just variance.
- **`retro.market_report(plays, results, market)`** — new, generalizes the four near-identical
  MLB-specific report functions (`homer_report`/`pitcher_k_report`/`batter_tb_report`/
  `batter_hits_report`) into one function parameterized by market. Works for any market in
  `MARKET_STAT` (extended with WNBA's four). `grade_play`/`grade_slate`/`_calibration` needed no
  changes at all — already fully market-agnostic underneath.
- **`selections.attach_live_ev`** — gained an optional `market_map` parameter (same pattern as
  `odds_api.compute_edges`), defaulting to MLB's `MARKET_TO_ODDS_KEY`. `filter_known_pitcher`
  needed no change — WNBA plays always carry a real opponent team name, so it's a harmless no-op
  there rather than something needing its own version.
- **`podcast.py`** — `TEACHING_SEGMENTS_WNBA`, a 5-segment library (CLV, parlays, recent-form-vs-
  season-average, rotation-minutes/blowout-risk, variance) parallel to MLB's 6. `assemble_script`
  and `rotating_teaching` both take a `sport` parameter that swaps every baseball-flavored phrase
  (park/weather, "went deep", the Aaron-Judge-style real-player example, "that's baseball") for a
  basketball-appropriate one — the Dr. Hall/Deezy dynamic, section structure, and teaching slot
  are unchanged, since that personality format is genuinely sport-agnostic. `_DEEZY_PUSH` gained
  entries for all four WNBA markets. Swept the full WNBA script output for leaked MLB terms
  (`test_assemble_script_wnba_has_no_leaked_mlb_terms`) — zero found.
- **Each page's loader was split, not just swapped** — an MLB branch (unchanged, still uses
  statcast/weather/FIP) and a generic branch (any sport whose engine/projections don't need that
  enrichment — currently just WNBA). Best Bets' MLB-only "Diagnostic Inspector" (PA/park/weather
  decomposition) is replaced for WNBA with an honest equivalent: the player's actual last-N-games
  table for that exact stat — real receipts, not fabricated park/weather signals that don't apply
  to basketball.
- **A real integration bug caught by testing the full chain, not just each piece in isolation:**
  `curate_selections` (used by Media Room and Podcast Studio) is genuinely sport-agnostic and
  already lived in `projections.py` — but wasn't re-exported from `wnba_projections.py`, so every
  WNBA page calling `sport.projections.curate_selections(...)` would have crashed with
  `AttributeError` on first real use. Caught by running the actual build_best_bets → 
  curate_selections → grade_slate → market_report → explain_miss → assemble_script chain
  end-to-end with synthetic data before shipping, not just each function's own unit tests — none
  of which would have caught a missing re-export. Fixed and locked in with
  `test_curate_selections_is_reachable_via_wnba_projections`.
- **`Command Center` also picked up a small, separate correctness fix**: `bets = B.list_bets()`
  had no sport filter (a Stage 1/2 gap, same shape as the earlier Track Record/Bet Log fix) — now
  `B.list_bets(sport=_active.key)`.

### Theme-proof gradients
- **`styling.py`** — per-cell text contrast (dark on pale, white on deep), benchmark-anchored
  thresholds so a stat colors the same everywhere. SLG/xwOBA are green-when-high on every page
  that colors them (Matchup Lab used to reverse this vs. Dinger Engine — fixed, and a regression
  test (`test_slg_xwoba_same_direction_on_every_page`) locks it in).

## NOT YET DONE (next stages)
- **WNBA opponent/pace adjustment** — v1 projection model is recent-form-only (no opponent
  defensive strength, no pace adjustment). Best Bets/Media Room/Podcast Studio's "Why" reasoning
  is honest about this being recent-form-only, not a claim of a more sophisticated model.
- **`nfl_engine.py`/`nfl_projections.py`** exist but are untested and `nfl_data_py` isn't in
  `requirements.txt` yet; markets/market_map in the registry are still empty. Flipping NFL on is
  Stage 4, not started.
- **NBA, NHL, NCAAF, NCAAMB** — no engines built yet.

## Deploy notes
- Main file path = `streamlit_app.py` for the owner app, `streamlit_app_discord.py` for the
  Discord/public app (same repo/branch, both apps — Streamlit Cloud requires distinct entrypoints
  per app, see Stage 2 above).
- Python 3.11 via the app's Advanced-settings dropdown (runtime.txt alone is ignored on Cloud)
- Requirements are pinned; keep them pinned. No new dependency for WNBA — the ESPN engine only
  uses `requests`, already required elsewhere (nba_api was tried and removed — see WNBA section).
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
