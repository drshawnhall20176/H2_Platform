# H2 Sports Platform — Build Checkpoint

**This is the multi-sport platform build.** It is the live source of truth (merged MLB + WNBA on
one sport-selector foundation). MLB runs exactly as the standalone did originally; WNBA is now a
second real, priced sport — not a placeholder.

## What's in this checkpoint (all tested — 216/216 tests green)

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
- **Production crash fix (2026-07-14):** Best Bets threw `ValueError` on a real WNBA slate — a
  perfectly consistent player (cleared a line in all 10 recent games) drove the bootstrap's
  `prob_over` to exactly `1.0`, so `prob_to_american` returned `None`, which broke the `"{:+d}"`
  format string on the Fair-price column. Two-layer fix: `wnba_projections._clip_prob` keeps every
  probability strictly inside `(0.02, 0.98)` at the source (both `build_best_bets` and
  `default_board_from_index`) — a small sample shouldn't claim 100% certainty anyway, not just a
  display-crash workaround — plus `na_rep="—"` on the Best Bets format call as a second line of
  defense. Locked in with `test_build_best_bets_never_produces_a_none_fair_price`.

### Hot Hand Engine — WNBA's opponent-adjustment layer (2026-07-14)
New WNBA-only page (`views/11_Hot_Hand_Engine.py`), plus a small Best Bets fix requested alongside
it (the Diagnostic Inspector's WNBA game log now shows real opponent + date instead of an
uninformative "Game #").
- **Not a literal Dinger Engine/Matchup Lab port** — those lean on Statcast (pitch-level tracking
  data with no free WNBA equivalent). Conceptualized instead around a real signal that already
  exists unused: every slate build fetches both teams' box scores, meaning opponent defensive
  strength (recent PTS/REB/AST/3PM allowed) was sitting in already-fetched data.
- **`wnba_engine.get_game_team_totals(game_id)`** — team-level per-game stats from
  `boxscore.teams[]`, reusing the SAME cached CDN response `get_game_boxscore` already fetches for
  that game (zero extra network cost when both are called for the same game).
- **`wnba_engine.get_team_recent_allowed_stats(team_id, before_date, n)`** — averages the
  OPPONENT's totals across a team's last n games (what they've been allowing, not scoring).
- **`get_team_recent_game_ids` now returns richer dicts** (`{gameId, date, opp_id, opp_name}`, not
  just IDs) — needed for the allowed-stats lookup, and incidentally what let the Best Bets
  inspector fix show real opponent/date. `get_player_recent_games`'s game-log entries now carry
  `opp`/`date` too. `build_slate`'s rows carry a new `_opp_id` field.
- **`wnba_projections.build_hot_hand_board(rows, opp_allowed)`** — Matchup Score = player's recent
  average × (opponent's allowed rate ÷ the average allowed rate across every opponent actually on
  tonight's slate). Deliberately NOT a full-league scan (cheap, and honestly labeled as "relative
  to tonight's other matchups," not a season-calibrated defensive rating). Missing opponent data
  stays neutral (1.00×) rather than fabricating a boost or penalty.
- **Deliberately kept separate from the priced probabilities** — Edge Board and Best Bets stay
  recent-form-only on purpose. This is a new analytical signal on its own page, not something
  silently folded into what a live betting board prices — a more conservative design choice given
  the stakes of the latter.
- Gated WNBA-only via a new generalized `sport_only_leads` mechanism in `streamlit_app.py`
  (replacing the old MLB-specific `mlb_only_leads`), so this pattern is ready for any future
  sport-specific analysis page without another refactor.

### Closing-line capture made sport-aware (2026-07-14)
`capture_closing_lines.py` (the GitHub Action that auto-populates CLV — see
`.github/workflows/capture-closing-lines.yml`) was still fully MLB-hardcoded in three separate
spots, discovered when asked directly whether the scheduled workflows update both sports:
`fetch_events`/`fetch_event_props` with no `sport=` (silently defaulted to MLB), and bet markets
filtered through `clv_capture.MARKET_TO_ODDS_KEY` (MLB's 7 markets only) with no
`supported_markets=` passed to `parse_event_offers` either — the same class of gap
`fetch_slate_props` had before it was fixed for Edge Board, just in a script that hadn't been
touched yet. **Practical effect: WNBA bets were never getting a closing line captured at all,
silently.** `clv_capture.py` itself already supported a `market_map`/`single_line_markets`
override per sport (unused by the runner) — no changes needed there. The runner now groups open
bets by their `sport` column and calls a new `capture_for_sport(sport_key, bets, api_key)` once
per represented sport, using that sport's own `odds_sport_key`/`market_map`/`single_line_markets`
from the registry. Legacy bets with no `sport` column default to MLB, matching `betlog.py`'s own
convention. Also widened the workflow's cron schedule — it only ran during MLB's typical 5-11pm ET
window, which would have missed WNBA day games (an 11am ET tip-off showed up earlier this season)
even with the code fixed. Locked in with `test_main_groups_open_bets_by_sport` and
`test_capture_for_sport_uses_that_sports_own_odds_key_and_market_map`.

### Matchup Lab — WNBA player-vs-opponent deep-dive (2026-07-14)
New WNBA-only page (`views/12_Matchup_Lab.py`), the second half of the Dinger Engine/Matchup Lab
conceptualization — built deliberately after Hot Hand Engine (not in parallel), since it reuses
Hot Hand Engine's opponent-defense foundation rather than re-deriving it.
- **Three real signals, shown separately, not blended into one number** (unlike Hot Hand Engine's
  single Matchup Score) — deliberate: this page is meant to let you weigh the signals yourself.
  1. Recent form — the player's own last-10 average (same number Best Bets/Edge Board price off).
  2. Head-to-head history — this exact player's stats in every game their team has played against
     tonight's SPECIFIC opponent this season. Genuinely new capability, not reused from Hot Hand
     Engine: `get_team_recent_game_ids` gained a `days_back` parameter (defaulting to 45,
     unchanged for every existing caller) so the same tested scoreboard-scanning logic can also
     run a season-wide scan instead of a second implementation. `get_player_history_vs_opponent`
     filters that scan to one specific opponent. Honestly empty (not guessed) when two teams
     haven't met yet — normal, since WNBA teams typically play each other only 2-4 times a season.
  3. Opponent defense trend — `get_team_recent_allowed_stats` (Hot Hand Engine's function) called
     twice with different `days_back` — last-10 vs. season-wide — to show whether a defense is
     trending looser or tighter than their own established norm, not just a single snapshot.
- **A real type-mismatch bug caught before shipping, not after:** ESPN's JSON gives team IDs as
  strings; `get_team_recent_game_ids`'s `opp_id` field was never converted, so a naive `==`
  comparison against a properly-typed `int` opp_id parameter would have silently matched zero
  games, every time. Caught by writing a test with the EXACT string-shaped fixture the real data
  actually has, not a conveniently-already-int test fixture — `test_get_player_history_vs_opponent_
  filters_to_that_opponent_only` locks in the fix.
- **`player_row`/`build_slate` gained a `_team_id` field** (the player's own team, not just
  `_opp_id`) — needed to call the H2H lookup at all, since a row previously only knew the
  opponent's ID, not its own.
- Occupies the same nav slot as MLB's Matchup Lab (same title/icon/url_path) rather than a
  differently-named page — consistent with how every other shared page (Best Bets, Command
  Center, etc.) doesn't rename itself per sport; they're mutually exclusive via `sport_only_leads`
  so there's no actual collision, just a deliberately consistent UX slot.
- Full pipeline (build_slate → H2H lookup → opponent trend → build_matchup_profile) verified
  end-to-end with synthetic data before shipping, including a genuine head-to-head match
  correctly filtered from other non-matching opponents — the same integration-test discipline
  that caught the `curate_selections` bug earlier in Stage 3.

### Matchup Lab: sharpened "how does this team play her" (2026-07-14)
Prompted by thinking ahead to an NBA build (same question would apply there): the original H2H
Avg was a real signal but a blunt one — no proper baseline, no visibility into variance within a
small sample, and no way to tell "one specific stat is being targeted" from "everything dipped a
little." Three real fixes, not a new section:
- **`wnba_engine.get_player_season_games(player_id, team_id, before_date)`** — the player's
  full-season log (any opponent), which H2H Avg is now compared against instead of Recent Avg.
  Comparing against a 10-game recency window conflates "this team's specific effect on her" with
  "she's just been hot/cold lately in general" — the season baseline isolates the former.
  Refactored the shared season-start-date logic (`_days_since_season_start`) out of
  `get_player_history_vs_opponent` so both functions use it, rather than duplicating it.
  `get_player_recent_games` gained a `days_back` parameter (default 45, backward compatible) to
  make this possible without a second scoreboard-scanning implementation.
- **H2H variance flagging** — the min–max spread across her head-to-head meetings, flagged as
  "High Variance" when it's wide relative to her season norm. A small H2H sample that's wildly
  inconsistent game-to-game is a different, less trustworthy signal than a small sample that's
  been consistent, and the page now says so explicitly instead of showing a single flat average.
- **Cross-market suppression detection** — `build_matchup_profile` now looks across all four
  markets together (not each independently) and flags the ONE market, if any, where her H2H
  performance is distinctly lower (not just "a bit lower," genuinely separated from her other
  markets) than the rest. This is the honest answer to "how do they play her": not scheme detail
  (not buildable from free box-score data, and this doesn't pretend otherwise), but which specific
  stat category — not just her scoring overall — actually gets suppressed against this team.
  Deliberately conservative: requires both an absolute threshold (ratio < 0.75 vs season) AND
  clear separation from the next-lowest market (≥0.15 gap), so an evenly tough game across every
  stat doesn't get mis-flagged as one targeted effect. Tested against both failure modes directly.
- Page restructured into two focused tables (player signals vs. opponent whole-team defensive
  trend) instead of one increasingly wide one — each table's scope is now stated in its own
  header, addressing real user confusion (screenshot-confirmed) about whether "Defense Trend" was
  player-specific, position-specific, or team-wide (it's team-wide — see the Stage 3 clarity fix
  above this one, which added scope callouts but hadn't yet added the season-baseline/suppression
  layer this entry covers).

### Production fix: team-level stat field names (2026-07-14)
Hot Hand Engine showed `Opp Allows = 0.0` and `Matchup Factor = 1.00×` for every single row on a
real slate — confirmed as a systematic bug, not per-team randomness. Root cause: `get_game_team_
totals`'s field-name guesses for `boxscore.teams[].statistics[].name` were wrong, the same class
of surprise found repeatedly throughout the WNBA build. Confirmed live this time (not another
blind guess) against a real documented CDN boxscore example (ScrapeCreators' walkthrough):
made-count stats use COMBO names — `"threePointFieldGoalsMade-threePointFieldGoalsAttempted"`,
not a bare `"threePointFieldGoalsMade"` key. Fixed with `_find_team_stat`, which tries multiple
candidate names (exact match, then prefix match) per stat rather than a single guess — also
covers the `"totalRebounds"` vs `"rebounds"` naming split already found for player-level stats,
in case it recurs here too. **This fix benefits Matchup Lab as well as Hot Hand Engine** — both
pages' opponent-defense signals (`Opp Recent Allowed`/`Opp Season Allowed`/`Defense Trend`) are
built on this exact function, so both were silently returning all-zero opponent data. Locked in
with `test_get_game_team_totals_handles_real_combo_named_fields`, using the exact real-world
combo-key shape rather than a synthetic simple-name fixture that wouldn't have caught this.

### Theme-proof gradients
- **`styling.py`** — per-cell text contrast (dark on pale, white on deep), benchmark-anchored
  thresholds so a stat colors the same everywhere. SLG/xwOBA are green-when-high on every page
  that colors them (Matchup Lab used to reverse this vs. Dinger Engine — fixed, and a regression
  test (`test_slg_xwoba_same_direction_on_every_page`) locks it in).

### Hot Hand Engine pace adjustment (2026-07-15)
Fixed the pace/defense conflation identified as the top-priority WNBA model gap: Hot Hand
Engine's "Opp Allows" signal previously couldn't tell "this team has a bad defense" apart from
"this team just plays fast, so everyone accumulates more counting stats against them" — those
look identical in raw per-game allowed totals.

- **`wnba_engine.py`** — `_parse_stat_value` and `_find_team_stat` both gained a `side` param
  ("left"/default = makes, "right" = attempts) so combo fields like
  `fieldGoalsMade-fieldGoalsAttempted` can yield FGA, not just makes. `get_game_team_totals` now
  also returns `poss`, an estimated-possessions figure per team per game (standard
  `FGA − OREB + TOV + 0.44×FTA` formula). `get_team_recent_allowed_stats` averages `poss`
  alongside pts/reb/ast/fg3m. **Caveat, stated honestly:** the pts/reb/ast/fg3m field names were
  confirmed live (see the combo-key fix above); the FGA/FTA/OREB/TOV field names are an educated
  guess based on ESPN's established naming conventions, not yet confirmed against a live example.
  A diagnostic dump fires automatically if `poss` comes back 0 while the other fields parse fine
  — the same safety net that caught the original combo-key bug — so a wrong guess here surfaces
  in the diagnostics rather than silently reverting to neutral factors everywhere.
- **`wnba_projections.py`** — `build_hot_hand_board`'s Matchup Factor is now computed from
  per-100-possession allowed rates, not raw per-game allowed totals. Two new columns, "Opp
  Allows /100 Poss" and "Slate Avg /100 Poss", carry the actual pace-adjusted numbers; "Opp
  Allows" and the new "Opp Pace" column stay as raw, human-recognizable context. A team with too
  few recent games to have a possession reading falls back to neutral (1.00×), same as the
  existing "no data yet" behavior — never a fabricated adjustment.
- **`views/11_Hot_Hand_Engine.py`** — banner and column reference updated to explain the
  pace-adjusted rate driving the color/tag, and to stop claiming "no pace adjustment yet."
- Matchup Lab's own "Opp Recent/Season Allowed" and "Defense Trend" columns are unaffected by
  this fix and intentionally left as-is: that page compares one team's own allowed rate across
  two time windows (recent vs. season), not across different opponents with different paces, so
  the conflation this fix addresses doesn't apply there the same way. Its "no pace adjustment"
  caption is still accurate and left in place.

### Matchup Lab recent-form trend chart (2026-07-15)
Second item on the WNBA model-enhancement priority list (pace adjustment above was #1). "Is she
trending toward or away from the number" as a glance-able chart instead of scanning a table —
the direct, honest analog of a stock trader's candlestick: a value moving over time, plotted.

- **`odds_api.py`** — new `market_lines_for_player(offers, player_name, projections_module=None)`:
  a pure, sport-agnostic lookup that picks the actual sportsbook prop line(s) for one player from
  already-fetched offers, reusing `compute_edges`'s name-normalization matching. If a market has
  offers at more than one point (different books), the point backed by the most total book quotes
  wins — a simple, honest consensus proxy, not a claim of real line-shopping logic.
- **`wnba_projections.py`** — `default_line(market_key)`, `market_list()`, `stat_key_for(col)`
  expose `_MARKET_SPEC`/`_STAT_KEY` publicly for callers outside the module (instead of reaching
  into private dicts). `build_trend_series(log)` reverses a player's most-recent-first game log
  into chronological order for left-to-right plotting.
- **`views/12_Matchup_Lab.py`** — a new 2×2 grid of small Plotly line charts (Points/Rebounds/
  Assists/Threes), one per market, showing the player's last 10 games with a dashed reference
  line at the current prop number. **Honest scope correction from how this was originally
  described:** the actual live sportsbook line does NOT already exist in Matchup Lab's data the
  way the original brainstorm assumed — `build_slate` is pure box-score/roster data, no odds.
  Getting the real number means a live Odds API fetch, the same one Edge Board already does.
  Built it the same way: **button-gated** ("📡 Fetch live lines"), not automatic on player switch,
  and **cached for the whole slate at once** (`load_offers`, ttl=300) — switching between players
  after the first fetch costs zero extra API quota, only a genuinely new date does. Before a fetch
  (or with no `ODDS_API_KEY` configured), the chart falls back to the model-only board's own
  default line, clearly labeled "Model default" in the chart annotation rather than presented as
  a live quote it isn't.
- Uses `plotly.graph_objects`, already pinned in `requirements.txt` and the established charting
  convention on this platform (Track Record, Command Center) — no new dependency added.
- **Bug fix, same day:** the first version let Plotly auto-detect the x-axis type from the "MM-DD"
  date-label strings, which Plotly mis-parsed as full dates and resolved to a nonsense range
  (confirmed by reproducing it: `full_figure_for_development` resolved to `type: "date"`, range
  `2006-12-14` to `2007-10-18`, for input as ordinary as `["07-01", "07-05", "07-10"]`). Likely
  also explained an "only one point showing" report — with real dates close together, the same
  bad parsing can collapse the axis into a near-zero range, stacking real points on top of each
  other rather than actually losing them. Fixed by forcing `fig.update_xaxes(type="category")` so
  the labels are never date-parsed at all.

### WNBA rest / back-to-back fatigue (2026-07-15)
Third item on the WNBA model-enhancement priority list. Second night of a back-to-back is a
well-documented real fatigue effect; computable entirely from game dates already fetched for
`get_team_recent_game_ids` — zero new network calls.

- **`wnba_engine.py`** — new `get_team_rest_info(team_id, before_date, days_back=10)`: days since
  a team's last completed game, and whether tonight is a back-to-back (`rest_days <= 1`). A short
  10-day lookback (not the 45-day "recent form" window) since rest only cares about the
  immediately prior game. No prior game found in the window (start of season) reports an honest
  `rest_days=None`, never a fabricated "well-rested" default.
- **`wnba_projections.py`** — `build_hot_hand_board` takes an optional `team_rest` param, keyed by
  the PLAYER'S OWN team (not the opponent — fatigue is about her legs, not theirs). Adds "Rest
  Days"/"B2B" to every output row. Deliberately NOT folded into Matchup Factor/Score: pace
  adjustment corrected a real measurement conflation in an existing number, while rest is a
  genuinely separate risk a trader should weigh on its own, not silently baked into a score that
  already means something else.
- **`views/11_Hot_Hand_Engine.py`** — per-team rest computed once per unique team on the slate
  (not per player), a "Rest" filter ("⚠️ Back-to-back only"), and a human-readable "Rest" column
  ("⚠️ B2B" / "3d rest" / "—" for unknown).
- **`views/12_Matchup_Lab.py`** — both teams' rest shown under the player header (her own team's,
  for fatigue risk, and the opponent's, for symmetry/context), reusing the same
  `get_team_rest_info` call.

## NOT YET DONE (next stages)
- **Blowout/minutes risk, injury/availability context** — the two remaining model-enhancement
  items from the original priority list, not yet built. Blowout/minutes risk ties into game
  spreads (already available via the Odds API); injury/availability has no clean free data source
  the way box scores do for the others, so it needs its own scoping pass.
- **Real line movement history (candlestick-proper)** — the trend chart above overlays a single
  CURRENT line on historical game values; a true line-movement view (the line itself moving over
  time, the closer stock-candlestick analog) still needs `capture_closing_lines.py` changed to
  log every snapshot instead of overwriting the latest one. Bigger lift, sequenced after the
  two items above.
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
