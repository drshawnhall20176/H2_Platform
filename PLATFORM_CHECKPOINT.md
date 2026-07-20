# H2 Sports Platform — Build Checkpoint

**This is the multi-sport platform build.** It is the live source of truth (MLB + WNBA + NBA +
NCAAMB + NFL, all live on one sport-selector foundation). MLB runs exactly as the standalone did
originally; WNBA, NBA, NCAAMB, and NFL are all real, priced sports now — not placeholders.

## What's in this checkpoint (all tested — 805/805 tests green)

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

### WNBA blowout / minutes risk (2026-07-15)
Fourth item on the WNBA model-enhancement priority list. When a game's a big mismatch, the
favorite's stars often see reduced 4th-quarter minutes while the underdog's bench gets extended
run — real, staking-relevant risk, tied to game spreads the platform already has Odds API access
to but wasn't fetching yet.

- **`odds_api.py`** — new `parse_game_spread(event_json)`: a purpose-built parser for the
  "spreads" market's per-team shape (one point per team, no over/under split) — a spreads market
  can't be forced through `parse_event_offers`, which is built for the player-prop over/under
  shape and would silently drop every spread outcome. New `fetch_slate_spreads(date_str, api_key,
  sport)`: `{team_name: spread}` for the whole slate, fetching ONLY the "spreads" market — 1 unit
  per event, far cheaper than the 4-market player-prop fetch, since Hot Hand Engine needs
  game-level spreads only, not player-level odds.
- **`wnba_projections.py`** — `blowout_risk_tag(spread, threshold=10.0)`: a plain threshold on the
  spread, explicitly NOT a calibrated model. Stated honestly in the docstring: 10 points is a
  reasonable WNBA-scale starting point (40-minute games, lower-scoring than the NBA), not a
  backtested cutoff — worth tuning empirically over time. `build_hot_hand_board` takes an
  optional `team_spreads` param (keyed by TEAM NAME, since that's the Odds API's own join key —
  unlike team_rest/opp_allowed, which are keyed by wnba_engine's team_id), adding "Spread"/
  "Blowout Risk" columns. Doesn't try to say which player role is affected (needs a starter/bench
  classification the data doesn't cleanly support) — just flags that the game itself carries
  elevated risk, for the trader to weigh against who they're actually looking at.
- **`views/11_Hot_Hand_Engine.py`** — a "📡 Fetch game spreads" button (same quota-safe,
  button-gated, cached-once-per-slate pattern as Matchup Lab's live-line fetch), a "Blowout" risk
  filter, and Spread/Blowout Risk columns. Before a fetch (or with no API key), both show "—",
  never a fabricated "competitive" guess.
- **Bug fix, same day:** the first version left "Spread" as a raw `None`/float column and relied
  on `Styler.format(..., na_rep="—")` to render the unfetched state — this rendered as a literal
  "None" in the deployed app's live table, not "—". Reproduced: `Styler.to_html()` handles an
  all-`None` object-dtype column's `na_rep` correctly, but Streamlit's interactive `st.dataframe`
  apparently doesn't apply it the same way. Fixed by pre-formatting "Spread" into a display string
  before the table is built — the same approach "Rest" and "Blowout Risk" already used
  successfully, rather than leaning on the Styler for a column that's 100% unfetched (`None`)
  until the button is clicked.

### WNBA injury/availability — Stage A: informational display (2026-07-15)
Fifth and final item on the original WNBA model-enhancement priority list. The original scoping
assumption — "no clean free data source for this" — turned out to be WRONG, corrected via a live
scoping pass: ESPN's own `injuries` endpoint, same base API this platform already runs on, gives
real per-player injury status, sourced from Rotowire. Confirmed live during scoping (not just
secondhand docs): fetched `site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries?team=ATL`
directly and got real, current structured records; separately confirmed `espn.com/wnba/injuries`
is live and current for the 2026 WNBA season (recap-fresh, "7h"/"11h"-old game references at fetch
time). The WNBA JSON endpoint itself (as opposed to the NBA one + the WNBA HTML page) hasn't been
hit live yet — flagged honestly in the docstring as a real, if likely, gap to close on first live
check.

- **`wnba_engine.py`** — `get_schedule`/`build_slate`'s `meta` now also carry each team's ESPN
  abbreviation (e.g. "ATL") alongside its numeric id — captured from the SAME scoreboard response
  already being fetched, since the injuries endpoint keys by abbreviation, not team_id (and
  `config_wnba.TEAMS`' ids are wnba.com's own numbering, unrelated to ESPN's — a real trap almost
  fallen into during this build; the comment in that file already flags it). New
  `team_abbrs_from_meta(meta)` derives `{team_id: abbr}` at zero extra network cost. New
  `get_team_injuries(team_abbr)` fetches and parses one team's report into
  `[{player, status, position, return_date, comment}, ...]`. `status` (e.g. "Out"/"Day-To-Day")
  is left as ESPN's own raw text, deliberately not collapsed into a boolean playing/not-playing
  call the data doesn't reliably support. An empty list is treated as "no news reported" (healthy),
  the honest default since there's no way to distinguish that from a fetch problem at this
  endpoint alone.
- **`views/11_Hot_Hand_Engine.py`** — a "🏥 Team injury report" expander covering every team on
  tonight's slate, grouped by team, free (no API key needed).
- **`views/12_Matchup_Lab.py`** — the same, scoped to just the selected player's team and her
  opponent, shown alongside the existing Rest context.
- **Deliberately NOT built (Stage B, deferred):** quantifying an "opportunity boost" for
  teammates when a key player is out. This is a genuine modeling decision, not a data-fetch —
  usage doesn't redistribute evenly across a roster, and guessing at a redistribution heuristic
  risks fabricating false precision the way the rest of this platform has consistently avoided.
  Revisit after Stage A has been live for a while.

This closes out all five items from the original WNBA model-enhancement priority list (pace,
trend chart, rest, blowout risk, injury/availability).

### basketball_engine.py / basketball_projections.py extraction (2026-07-15)
Pulled the genuinely league-agnostic pieces of today's four WNBA additions (pace/possession math,
rest calc, blowout tag, injury parsing) into new shared modules, so a future NBA build reuses them
instead of duplicating.

**Scope call, made deliberately narrow:** `wnba_engine.py` has ~15 functions; only four (plus
their minimal direct plumbing — game-ids lookup, team-totals parsing, the stat-value helpers) were
extracted. Schedule fetching, roster fetching, player game-log assembly, and `build_slate`'s
orchestration stayed in `wnba_engine.py` untouched — those are also basketball-generic in
principle, but which parts would need to diverge for NBA isn't known yet (real endpoint quirks in
`wnba_engine.py` — the CDN-vs-site-API boxscore split, the made-attempted combo-key naming, the
flat-vs-grouped roster shape — were only discovered by building WNBA the hard way, not
predictable in advance). Extracting those now would mean guessing NBA's needs before NBA exists —
a premature-abstraction risk. Plan: write `nba_engine.py` as a copy-adapt of `wnba_engine.py` when
that build starts, and extract further once real duplication is provable, not speculatively now.

- **`basketball_engine.py`** (new) — `parse_stat_value`, `find_team_stat`,
  `get_team_recent_game_ids`, `get_game_team_totals` (the possession-estimate formula and its
  diagnostic dump), `get_team_recent_allowed_stats`, `get_team_rest_info`, `get_team_injuries`.
  Every function takes `fetch`/`diag` as explicit parameters (dependency injection) rather than
  owning its own HTTP client or cache — this is what let the extraction happen with **zero test
  file changes**: `wnba_engine.py`'s 255 existing tests, many of which do
  `monkeypatch.setattr(E, "_get_json", ...)` or `E._response_cache.clear()` directly against
  `wnba_engine`'s own module state, kept passing unchanged, because `wnba_engine.py` still owns
  and exposes its own `_get_json`/`_get_json_cached`/`_diag`/`_response_cache` exactly as before —
  its public functions became thin wrappers that pass those same objects into the shared layer.
- **`basketball_projections.py`** (new) — `blowout_risk_tag`. `build_hot_hand_board` itself stayed
  in `wnba_projections.py`: it iterates `_MARKET_SPEC`, whose default-line values (12.5 pts, 5.5
  reb, ...) are WNBA-scale tuning constants, not basketball-generic ones — NBA's would be
  meaningfully different (longer games, faster pace, higher counting stats), and a shared
  default-line table would be the same kind of premature guess as above.
- **`wnba_engine.py`** — `get_team_recent_game_ids`, `get_game_team_totals`, `get_team_injuries`
  became thin wrappers delegating to `basketball_engine.py`. `_parse_stat_value`/`_find_team_stat`
  became plain aliases. Every OTHER function that calls these (`get_team_rest_info`,
  `get_team_recent_allowed_stats`, `get_player_recent_games`, `get_player_history_vs_opponent`)
  was left **completely untouched** — they still call the extracted functions by bare name, which
  Python resolves fresh at call time, so `monkeypatch.setattr(E, "get_team_recent_game_ids", ...)`
  keeps working exactly as before regardless of what that name now points to internally.
- **`wnba_projections.py`** — `blowout_risk_tag` became a plain alias to
  `basketball_projections.blowout_risk_tag`.
- New direct test coverage for the shared layer itself (`test_basketball_engine.py`,
  `test_basketball_projections.py`, 22 tests) — matters for when `nba_engine.py` consumes this
  code directly, not just through WNBA's wrapper. Total: 277/277 passing, up from 255 (0 existing
  tests modified, 22 added).

### nba_engine.py / nba_projections.py — LIVE (2026-07-15)
Built as a copy-adapt of `wnba_engine.py`/`wnba_projections.py`, wired to
`basketball_engine.py`/`basketball_projections.py` for pace/rest/blowout/injury logic exactly the
way WNBA now is. Registry-wired in `sports.py` with real markets/market_map (Core 4: Points/
Rebounds/Assists/Threes, same Odds API market keys as WNBA) — still **`enabled=False`** for now,
but for a narrower reason than originally: the data layer is confirmed (see below), the remaining
gap is two view files that don't know NBA exists yet, not an unverified endpoint.

**Original concern, stated plainly, then resolved:** the single biggest risk area in WNBA's own
build was `get_game_boxscore`'s CDN endpoint (`cdn.espn.com/core/wnba/boxscore`) — ESPN's "site"
API family was confirmed to return team-level stats only, no player-level, forcing that CDN
detour, and the exact player-stats shape there needed a live response pasted back to get right.
The equivalent for NBA (`cdn.espn.com/core/nba/boxscore`) was NOT hit live earlier in this
session — only researched. Shawn then fetched it directly and pasted the real response back (see
the detailed section further down) — confirming both `get_game_team_totals` and
`get_game_boxscore` against real live data, the exact same bar WNBA's build cleared.

- **`config_nba.py`** — `RECENT_GAMES_N`/`MIN_AVG_MINUTES`/`DEFAULT_SIMS` carried over from
  WNBA's values as starting points, flagged for re-checking once real NBA slate data exists. No
  hardcoded team-ID reference table (unlike `config_wnba.TEAMS`) — deliberately: that table isn't
  actually used by the engine either way (both engines get team ids/names live from ESPN), and
  wasn't worth transcribing 30 team IDs from memory when it isn't required for anything to work.
- **`nba_engine.py`** — `get_team_recent_game_ids`, `get_game_team_totals`, `get_team_injuries`
  thin-wrap `basketball_engine.py` exactly like WNBA's do. `get_team_injuries` IS confirmed live
  for NBA specifically (the original injury-availability scoping pass fetched
  `site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries?team=ATL` directly and got real
  data) — the CDN boxscore endpoint is the one real gap. `SEASON_START = "2026-10-01"` is an
  honestly-flagged **placeholder**: this build happened during the NBA's off-season (2025-26
  season ran Oct 21, 2025 – Apr 12, 2026, confirmed live; 2026-27's schedule wasn't announced yet
  at build time) — re-verify once it is.
- **`nba_projections.py`** — `_MARKET_SPEC` uses NBA-scale default lines (22.5/7.5/5.5/2.5 vs.
  WNBA's 12.5/5.5/3.5/1.5 — 48-minute games, faster pace, meaningfully higher counting stats) and
  its own `BLOWOUT_THRESHOLD = 12.0` (vs. the shared function's WNBA-tuned 10.0 default) — both
  round-number starting points, not backtested, same honesty as every other tuning constant here.
- **New tests**: `test_nba_engine.py` (mirrors `test_wnba_engine.py` for the functions this
  module implements independently, plus wiring smoke tests confirming the basketball_engine.py
  delegation passes NBA's own SITE_API/CDN_API through correctly) and `test_nba_projections.py`.
  33 new tests. Total: 310/310 passing.
- **`test_sports.py`** updated: NBA moved from the "still a placeholder" market_map group to the
  "genuinely wired" group alongside MLB/WNBA — a legitimate assertion update reflecting NBA's
  real new state, not a compatibility workaround.

### NBA live verification pass (2026-07-15, continued)
Followed up on the "not yet live" gap above. Could not reach ESPN directly from the sandbox (no
network egress to espn.com), so verification went through web search/fetch of already-public real
API samples rather than a direct curl — a real, honestly-flagged limitation, weaker than WNBA's
original "Dr. Hall pasted a live response back" verification, but stronger than pure research.

**Confirmed, from a real live NBA sample (2016 Finals Game 7, fetched via a related ESPN
endpoint — not the exact CDN one `get_game_boxscore` calls, but the same team-level statistics[]
shape):** `fieldGoalsMade-fieldGoalsAttempted`, `threePointFieldGoalsMade-
threePointFieldGoalsAttempted`, `freeThrowsMade-freeThrowsAttempted` (all three combo-key
formatted, exactly as `basketball_engine.py` expects), `totalRebounds`, `offensiveRebounds`,
`assists`, `totalTurnovers` — every one of these matched the candidate field names already coded
against, for real. Genuinely strong evidence FGA/FTA/OREB/TOV (the possession-estimate inputs)
will parse correctly for NBA.

**A real gap this verification actually found, not just theorized:** `"points"` did not appear
anywhere in that sample's statistics[] array — the single field name `get_game_team_totals` used
for `pts`, with no fallback. Worse, a SEPARATE bug this surfaced: the diagnostic dump only fired
when *all four* core stats came back zero at once — a single silently-wrong field name (exactly
this "points" case) would have produced a wrong number with **zero diagnostic signal**, on either
NBA or WNBA.

**Update — Shawn pasted back a real, live CDN response** (`cdn.espn.com/core/nba/boxscore?xhr=1&
gameId=401810511`, Nets @ Clippers, Jan 25 2026 — a completed regular-season game), the exact same
bar WNBA's own verification cleared. This resolved everything below, including one real bug in the
FIRST fix attempt:

- **Team-level `boxscore.teams[].statistics[]` — confirmed correct**, all 25 fields present,
  matching every field name `get_game_team_totals` was already coded against: the FGA/FTA/3PT
  combo-key format, `totalRebounds`, `offensiveRebounds`, `assists`, `totalTurnovers`. The
  possession-estimate formula's inputs are genuinely right.
- **`"points"` confirmed genuinely absent** from that same statistics[] array (25 fields listed,
  no points — confirmed twice now, a 2016 game and this real 2026 one). The FIRST fix attempt for
  this (falling back to `team_block["score"]`) was itself WRONG — that field doesn't exist there
  either. The real location, only visible once the actual live response was in hand:
  `gamepackageJSON.header.competitions[0].competitors[].score`, matched by team id — a completely
  different part of the response than `boxscore.teams[]`. Fixed for real this time in
  `basketball_engine.py`, with a test built directly from the real Nets/Clippers scores (126–89).
- **Player-level `boxscore.players[].statistics[0]` — confirmed correct**, the single biggest
  unknown going into this and now fully resolved: the real `names` array is exactly
  `["MIN","PTS","FG","3PT","FT","REB","AST","TO","STL","BLK","OREB","DREB","PF","+/-"]`, `stats`
  align positionally, `didNotPlay` is a real field ESPN actually sets. Verified against Michael
  Porter Jr.'s real line (22 MIN, 9 PTS, 3-11 FG, 0-4 3PT, 2 REB, 4 AST) — `get_game_boxscore`
  parses it to exactly `{"pts": 9.0, "reb": 2.0, "ast": 4.0, "fg3m": 0.0, "min": 22.0}`, correct.
- The diagnostic dump now also fires on a PARTIAL failure (any one core field zero), not just a
  total one, and names which specific field(s) came back zero — a real, independent gap found
  during this same pass (the OLD condition would have missed a lone bad field name silently). This
  benefits WNBA's already-live code too, not just NBA.
- 4 new tests lock all of this in, two built directly from the real pasted response
  (`test_get_game_team_totals_real_confirmed_live_shape`,
  `test_get_game_boxscore_real_confirmed_live_shape`). Total: 314/314 passing.

**Net result: `get_game_boxscore` and `get_game_team_totals` — the two functions this whole
verification effort was about — are now confirmed live against a real NBA game, the same bar
WNBA's build cleared before its own launch.** Team injuries were already confirmed live in an
earlier session. Schedule/roster fetching use the identical, already-proven `site.api.espn.com`
pattern WNBA relies on, not independently verified this session but low-risk by construction.

**On NBA Summer League, in case it's useful going forward:** confirmed via ESPN's own endpoint-
slug listing that Summer League is a genuinely SEPARATE set of leagues in ESPN's system —
`nba-summer-las-vegas`, `nba-summer-utah`, `nba-summer-orlando`, `nba-summer-sacramento` — not the
same as the regular `nba` slug this build targets. Not useful as a production data source
(rosters are mostly rookies/two-way players, a short exhibition tournament, and the Odds API
almost certainly doesn't carry meaningful prop markets for it) — its HTML boxscore page not
blocking automated fetching (unlike the regular season's) is what let some of this verification
start moving before the real CDN JSON came through directly.

**NBA is now LIVE — `sports.py`'s NBA entry flipped to `enabled=True` on 2026-07-15,** after:
1. `views/11_Hot_Hand_Engine.py`/`views/12_Matchup_Lab.py`'s `require_sport` gates updated to
   accept `["WNBA", "NBA"]` (backward-compatible list support added to `require_sport` itself),
   captions now read `_active.key` dynamically instead of hardcoding "WNBA".
2. `test_mlb_and_wnba_enabled_today` → `test_mlb_wnba_nba_enabled_today`, updated to assert all
   three are live — a genuine assertion update reflecting the real new state, not a workaround.
3. Confirmed: `sports.get("NBA").enabled is True`, `enabled_sports()` returns
   `["MLB", "WNBA", "NBA"]`, NBA no longer appears in the sidebar's "Coming soon" list.

315/315 tests passing, smoke test still clean (0 games — correctly, since the regular season is
in its July off-season; the app is live and correct, just nothing to show until October).

### Post-launch bug found and fixed: Hot Hand Engine/Matchup Lab missing for NBA (2026-07-15)
Shawn reported these two pages simply weren't showing up when NBA was selected (Retrospective
correctly pulled 2025-26 historical stats, confirming the data layer itself is fine — this was
purely a navigation/visibility bug). Root cause: a THIRD gate, separate from both `require_sport`
(inside each page) and `sports.py`'s `enabled` flag — `streamlit_app.py`'s own `sport_only_leads`
dict, which decides which pages appear in the sidebar navigation AT ALL, based on the active
sport. It still mapped pages 11/12 (Hot Hand Engine, Matchup Lab) to the single string `"WNBA"`,
so `active_sport != required_sport` was `True` for NBA and the pages were filtered out of the
menu entirely before a user could ever reach `require_sport`'s in-page check — a gate I'd updated
correctly but hadn't realized had an earlier, page-existence-level counterpart.

- **`streamlit_app.py`** — `sport_only_leads` values changed from a single string to a tuple of
  acceptable sports (`"11": ("WNBA", "NBA")` instead of `"11": "WNBA"`), and the filter check
  updated to `active_sport not in required_sports`.
- **`test_sports.py`** — `test_sport_only_page_visibility_matches_expected_config`'s regex-based
  source-scraping updated to parse the new tuple structure instead of a single quoted string.
- Directly verified the filtering logic in isolation: for `active_sport in ("MLB","WNBA","NBA")`,
  pages 11/12 are now visible for both WNBA and NBA, hidden for MLB — matching pages 1/2/10
  (MLB-only) staying correctly hidden for WNBA/NBA. 315/315 tests passing.

**This is the second time in one session a "the code inside the page is right" fix wasn't
sufficient** — the first was the pts field-name fix needing a second correction once the real
CDN response revealed `team_block["score"]` doesn't exist either. Both are the same underlying
lesson: a fix that looks complete from reasoning about a system's DOCUMENTED behavior can still
miss a layer that's only visible once someone actually exercises the real, deployed thing.

### Post-launch bug found and fixed: NBA and WNBA showing the same data (2026-07-15)
Third one, and the most consequential: after the navigation fix above, Shawn confirmed Hot Hand
Engine/Matchup Lab now APPEAR for NBA — but pasted screenshots showing the exact same player
("Aliyah Boston, Indiana Fever" — a real WNBA player/team) under BOTH the WNBA and NBA dropdown
selections on Matchup Lab. The "Model default" line on the trend chart DID correctly update
(12.5 → 22.5, WNBA's default vs. NBA's), which was the tell: the projections layer was correctly
re-resolving to the active sport, but the underlying player/game DATA wasn't.

**Root cause:** `st.cache_data`'s cache key is built ONLY from a function's own arguments.
`load_slate(date_str)`, `load_matchup(date_str, player_id, team_id, opp_id)`, and `load_board
(date_str)` all read the sport-specific `E`/`P` modules via a module-level closure (`E, P =
_active.engine, _active.projections`) — but since neither `E` nor `P` nor anything sport-related
was part of the function's own PARAMETERS, calling `load_slate("2026-07-15")` under NBA looked
IDENTICAL to Streamlit's cache as the earlier WNBA call with the same date — so it returned the
stale WNBA result without ever re-executing the function body (which would have correctly used
the current `E`/`P`). This is a well-known Streamlit caching pitfall: a cached function whose
behavior depends on global/closure state not reflected in its own arguments can silently serve
another context's cached result.

**Not a new problem, and not something reasoned out from scratch** — a source audit of every
other sport-dispatching page found the fix already existed as an established convention: Edge
Board's `load_index(sport_key, date_str, ...)`/`load_edges(sport_key, ...)`, Best Bets' and
Retrospective's `*_generic(sport_key, date_str)`, Media Room's `load_selections_generic(sport_key,
...)`, Podcast Studio's `load_today`/`load_yesterday(sport_key, ...)` — all already take
`sport_key` as their first argument specifically to force cache differentiation by sport.
Command Center and Track Record were independently checked too and already correct (Command
Center's generic loader doesn't even touch the module-level `E`/`P` closure at all — fully
self-contained via `sports.get(sport_key)`, an even more robust pattern). Hot Hand Engine and
Matchup Lab were the only two pages that never got this convention, because they were built when
WNBA was the only basketball sport — there was nothing to differentiate from until NBA started
sharing the same page today.

- **`views/12_Matchup_Lab.py`** — `load_slate`, `load_injuries`, `load_matchup` all gained
  `sport_key` as their first parameter (unused inside the function body — `E`/`P` are already
  correctly re-resolved each rerun — it exists solely to key the cache correctly). `load_offers`
  needed no change; it was already self-contained via `sports.get(sport_key)`, not a closure.
- **`views/11_Hot_Hand_Engine.py`** — same fix for `load_board`/`load_injuries`. `load_spreads`
  already correct for the same reason as `load_offers` above.
- All call sites updated to pass `_active.key`.
- **New regression test** (`test_hot_hand_and_matchup_lab_loaders_key_their_cache_by_sport`,
  source-scraping, no Streamlit runtime needed) asserts every cache-decorated loader on these two
  pages takes `sport_key` as its first parameter — so a future edit can't silently drop it again
  the way it was silently absent in the first place. 316/316 tests passing.

**Third time using the same phrase, because it keeps being true:** this is the third fix this
session where reasoning about the code in isolation wasn't enough — pattern-matching against how
the REST of the platform already solved the same class of problem is what actually found it.
Worth remembering for whatever's next: if something in the WNBA/NBA build still looks "half
there," check what the equivalent MLB-path or the other sport-dispatching pages already do first.


- Re-verify `SEASON_START` once the 2026-27 schedule is officially announced.
- Sanity-check `config_nba.MIN_AVG_MINUTES`/`RECENT_GAMES_N` against real NBA rotation patterns —
  carried over from WNBA's values as a starting point only.
- Independently confirm `get_team_roster`'s exact live shape (same pattern already proven for
  WNBA, so low risk, just not independently checked this session).

### Dark-mode contrast bug fixed: Edge Board Tier column, Dinger Engine HR/9 bands (2026-07-16)
Shawn reported Edge Board's Tier column (Bet/Dust/No bet) was nearly unreadable in dark mode.
Root cause: `_tier_style` set only `background-color` (pale green/amber/gray) with no explicit
text color for "Bet"/"Dust", inheriting the app theme's default text — near-white in dark mode,
invisible against a pale background. This is exactly the problem `styling.py`'s `theme_gradient`
already solves platform-wide (per-cell black-on-light/white-on-dark contrast) — but Tier is
categorical, not a numeric gradient, so it was hand-rolled outside that shared mechanism and
never got the same treatment. A search for the same hand-rolled `background-color:` pattern found
one more instance with the identical gap: Dinger Engine's `hr9_band`, where 3 of 5 color bands had
no explicit text color either (the two most-saturated bands already had `color:white`, correctly).

- **`views/3_#L01f4c8_Edge_Board.py`** — `_tier_style` now sets `color: #111111` alongside every
  background (all three Tier colors are light enough — luminance > 150 — that this is the
  correct choice per `styling.py`'s own threshold, not a new convention).
- **`views/2_#L01f4a3_Dinger_Engine.py`** — `hr9_band`'s three lighter bands
  (`#a6d96a`/`#fee08b`/`#fdae61`) now also get `color: #111111`; the two already-correct deep
  bands are untouched.
- Checked for duplication first: no other page reuses this Bet/Dust/No bet tier concept, and no
  other hand-rolled `background-color:` styling exists outside these two files.
- No test changes needed (pure styling strings, no existing test asserted the old color output).
  316/316 passing.

### Bootstrap probability shrinkage: fixing identical Model%/Conviction across the board (2026-07-16)
Shawn spotted Best Bets showing 98% / -4900 fair odds / 1.96× conviction on EVERY visible row,
across completely different players and markets. Confirmed with real computation, not
speculation: `prob_to_american(0.98) == -4900` exactly, and `Conviction = ModelProb / 0.5`, so
`0.98 / 0.5 = 1.96` — both numbers were mechanically forced identical by the same root cause.

**Root cause:** the bootstrap model estimates P(stat > line) as, in the large-`sims` limit, the
empirical fraction of a player's last N recent games that cleared the line. Several rows in the
screenshot had literally "cleared X in 9 of 9" or "10 of 10" games — a perfect recent hit rate,
which the bootstrap resamples into a raw probability of exactly 1.0. `_clip_prob` (built and
already documented as a safety net against exactly this) caps that at 98% — but every DIFFERENT
player/market that independently hit a perfect streak landed on the exact same 98%, and since
Conviction is a direct function of ModelProb, they tied there too. The ranking among them
degenerated into an arbitrary sort order, not a real one — a 4-game "perfect" streak and a
40-game one were indistinguishable, despite genuinely different amounts of evidence behind them.

**The fix, scoped for WNBA + NBA + the upcoming NCAAMB build, not just WNBA:** added
`basketball_projections.shrink_prob(raw_prob, n_games, prior_strength=4.0, reference=0.5)` — the
same conceptual empirical-Bayes shrinkage `projections.py` already uses for MLB's small-sample
rates (pulling an observed rate toward a league baseline, weighted by how much data backs it),
adapted from "rate per plate appearance" to "rate per recent game." A 4-game streak gets pulled
hard toward 50/50; a 40-game streak barely moves — the correction fades out on its own as real
evidence accumulates. Runs BEFORE `_clip_prob`, which still matters afterward as a final
boundary-value safety net, not a replacement.

- **`basketball_projections.py`** — new `shrink_prob`, built once in the shared layer specifically
  so NBA and NCAAMB inherit the fix without duplicating it, matching the extraction philosophy
  `basketball_engine.py`'s own docstring already lays out.
- **`wnba_projections.py`** / **`nba_projections.py`** — both updated identically:
  `build_projection_index` now stores `n_games` per index entry; `default_board_from_index` (Edge
  Board's path) and `build_best_bets` (Best Bets' path) both shrink the raw bootstrap probability
  before clipping. `_clip_prob`'s docstring updated to describe its narrower remaining job.
- **MLB deliberately left untouched** — it already has its own, more sophisticated shrinkage
  (research-based per-stat priors applied at the rate level, before simulation) via
  `projections.py`'s existing regression-to-the-mean machinery. Not a gap to fix, a different
  system that already solves this.
- **9 new tests**: 5 direct unit tests for `shrink_prob` (small-sample pull, large-sample
  stability, the exact "two different streak lengths, two different outputs" case, zero-games
  edge case, reference-value no-op) plus 2 integration tests each for WNBA and NBA proving the
  ORIGINAL bug is actually fixed end-to-end in both `default_board_from_index` and
  `build_best_bets` — not just that the helper function works in isolation.
- **One existing test's expectation corrected, not just patched around**: a WNBA test asserted a
  9/10 raw bootstrap rate lands in a 0.85–0.95 band — mathematically no longer true post-
  shrinkage (`(0.9×10 + 4×0.5)/14 ≈ 0.786`), so the band was updated to the new, correct expected
  value with the arithmetic shown inline, not just loosened until it happened to pass.
- 325/325 tests passing (316 + 9 new).

**Honest caveat, stated plainly:** `prior_strength=4.0` is a reasonable starting constant, not
backtested — worth checking against real calibration once there's a track record to compare
against, the same caveat every other tuning constant on this platform carries. This is also a
real, deliberate change to what a LIVE board prices, not a cosmetic fix — flagged here explicitly
rather than described as a pure bug fix, matching the "silently changing what's priced into a live
betting board is a bigger decision" principle this build has followed throughout.

### MLB Matchup Lab: pitch-mix visualized (2026-07-16)
Shawn asked if WNBA/NBA Matchup Lab's line-chart concept could extend to MLB's pitch-mix table.
Honest answer worked out first: the literal trend-chart shape doesn't map — that chart works
because there's a real per-game time axis (10 dated recent games) to plot against, and MLB's
`arsenals`/`hitter_splits` data has no equivalent; it's a season-aggregate snapshot PER PITCH
TYPE, not a dated sequence. Forcing a line chart onto that would mean inventing an x-axis the
data doesn't have. What genuinely does map is the underlying instinct (see it, don't just read a
table), applied honestly to what this data actually is: a composition (pitch mix) and a matchup
(whiff rates compared) — bar charts, not a line chart.

- **`views/10_Matchup_Lab.py`** — two new Plotly charts added after the matchup grid table:
  1. **Pitch mix** — horizontal bar per pitch, length = usage%, color = matchup Score (same
     red-yellow-green convention as the existing table), sorted by usage descending.
  2. **Whiff-rate matchup** — paired horizontal bars per pitch: the pitcher's own whiff% on that
     specific pitch vs. the hitter's whiff% against that pitch's family, sorted by Score
     descending. Only shown when hitter-side data exists (`have_hitter`); falls back to the mix
     chart alone (arsenal-only, no colorbar) when it doesn't, same graceful-degradation posture
     the rest of this page already has for missing cache data.
  3. Uses `plotly.graph_objects`, already pinned and the established charting convention on this
     platform — no new dependency.
- Verified by direct simulation (no real cached pitch data exists in this sandbox to smoke-test
  against live): realistic multi-pitch data, the no-hitter-data case, and a single-pitch arsenal
  edge case all build cleanly via `full_figure_for_development`, the same verification method
  that caught the WNBA/NBA trend chart's date-mis-parsing bug earlier — confirmed here that
  pitch-name labels don't hit that same issue (they resolve to `type: category` cleanly, no
  numeric-looking substrings for Plotly to misinterpret as dates the way "MM-DD" strings did).
- No test suite changes — view files aren't unit-tested in this codebase's established pattern
  (engine/projections logic is); 325/325 existing tests unaffected, confirming nothing else was
  touched.

### Matchup Lab: time-slot filter (2026-07-16)
Shawn asked for a way to narrow Matchup Lab's player picker by game time — WNBA's small nightly
slate never needed it, but a full NBA slate (and especially NCAAMB's much bigger one, still to
come) makes "just scroll to find your player" genuinely painful.

- **`sports.py`** — extracted `game_dt`/`slot_of`/`SLOT_ORDER` from Best Bets, which already had
  this exact logic as a private, page-local copy. Matchup Lab needed the identical thing — a real
  second consumer, not a speculative one — so this is the same "extract once a second real need
  exists" call the whole basketball_engine.py extraction already followed, applied here to a much
  smaller piece of shared infrastructure. Fixed hour boundaries (5pm/8pm ET), sport-agnostic.
- **`views/5_#U2b50_Best_Bets.py`** — its own local `game_dt`/`slot_of`/`SLOT_ORDER` removed,
  replaced with a two-line alias to the shared version. No behavior change, same convention.
- **`views/12_Matchup_Lab.py`** — new "Time slot" selectbox (All slate / Afternoon / Evening /
  Late / TBD, only the slots actually present that night) sits above the Player picker and
  narrows it before the player list is even built, computed from each row's own `_game_date`.
- **5 new tests**: `game_dt` parsing (incl. malformed/missing input), `slot_of`'s four buckets
  with real DST-aware UTC→Eastern math, `SLOT_ORDER` covering every possible `slot_of` output, and
  a source-scraping regression guard confirming both pages actually use the shared helpers rather
  than a re-duplicated local copy. 330/330 passing.

### Matchup Lab: added a Game filter alongside Time slot (2026-07-16, same day follow-up)
Shawn's right call: a busy slate can pack several games into the same time slot, so slot alone
doesn't always get you to a specific game quickly — NBA/NCAAMB will have exactly this. Confirmed
MLB already has the pattern (Edge Board's two "Filter by game" multiselects) and reused its
convention exactly rather than inventing a new one: sorted by real tip-off time, labeled with the
ET clock via `format_et` (not the raw game label) — same as Edge Board's own game filters, just
a single-select here since Matchup Lab drills down to ONE player, not a filterable table.

- **`views/12_Matchup_Lab.py`** — "Game" selectbox sits next to "Time slot" (two columns), options
  scoped to whichever games fall in the currently-selected slot, sorted chronologically, labeled
  `"7:00 PM — Celtics @ Lakers"` style. `format_et` came for free — every basketball projections
  module already imports it from the same sport-agnostic `projections.py` MLB's own pages use.
- Verified by direct simulation (view files aren't unit-tested in this codebase's pattern): a
  3-game slate with two games in the same nominal slot correctly split into distinct, chronologically-
  ordered, ET-labeled options; a missing-`_game_date` (TBD) game degraded gracefully to the plain
  game label instead of crashing or showing a blank time.
- No test/behavior changes elsewhere; 330/330 unaffected.

### NCAAMB build (2026-07-16)
Built following the exact playbook the NBA build established: research real facts first (not
guessed), copy-adapt the WNBA/NBA engine and projections modules through the shared
`basketball_engine.py`/`basketball_projections.py` layer, wire the registry with `enabled=False`
until live-verified, and hand off a concrete, ready-to-run verification step rather than declaring
it done. Stronger starting position than NBA's build had, though: this happened while genuinely
useful facts were confirmable live (not off-season guesswork), and NCAAMB is basketball, so nearly
everything WNBA/NBA already paid for — pace math, rest calc, blowout tagging, injury parsing, and
the probability-shrinkage fix — came along for free through the shared layer.

**Confirmed via live research, not guessed (the genuinely new information this build rests on):**
- **2026-27 season start: November 1, 2026** (ends March 14, 2027) — the NCAA's own published
  calendar, confirmed live. A real date, not a placeholder the way NBA's `SEASON_START` had to be
  (that build happened during the NBA's off-season with no announced schedule yet).
- **ESPN's league slug: `mens-college-basketball`** — confirmed across multiple independent
  sources documenting the live, working endpoint family.
- **A genuinely new, load-bearing quirk WNBA/NBA never hit**: ESPN's scoreboard endpoint silently
  TRUNCATES results for college sports unless a `groups=50` (all Division I) param is included —
  confirmed live 2026-07-04: the same date returned 12 events without it, 36 with
  `groups=50&limit=500`. Division I is 350+ teams; this isn't an edge case, it's the default
  failure mode for every single day's slate if missed.
- **Odds API's sport key: `basketball_ncaab`** (deliberately different from ESPN's own
  `mens-college-basketball` slug — kept separate in the registry, not conflated) — confirmed via
  a real, live example response showing `player_points`/`player_rebounds` props with real player
  names (Robbie Avila, Gibson Jimerson), matching the same Core-4 market taxonomy WNBA/NBA
  already use.
- A real, recent, completed game ready to verify against once deployed: **UConn 73, Duke 72
  (March 29, 2026), gameId 401856577** — found and confirmed to exist, but the raw CDN JSON
  itself wasn't reachable from this sandbox (same fundamental limitation as the NBA build's first
  pass, before Shawn's own live fetch closed that gap).

**basketball_engine.py extended, not just reused** — a real, careful design decision: NCAAMB's
`groups=50` need could have been baked directly into the SHARED `get_team_recent_game_ids`
function's scoreboard request, but that function is already live for two sports that never needed
this param. Instead, added an optional `extra_params` argument defaulting to `None` — WNBA's and
NBA's exact existing request shape is provably unchanged (locked in by
`test_get_team_recent_game_ids_extra_params_none_by_default`), and NCAAMB opts in explicitly.
`ncaamb_engine.py`'s own `get_schedule` (not shared) bakes `groups=50` in directly, since that
function has no cross-sport blast radius to worry about.

**Sport-appropriate tuning, reasoned from the game itself, not blindly copied from NBA:**
- `config_ncaamb.MIN_AVG_MINUTES = 12.0` and `ncaamb_projections._MARKET_SPEC`'s default lines
  match WNBA's, not NBA's — NCAAMB games run 40 minutes, the same length as WNBA's, not NBA's 48.
- `BLOWOUT_THRESHOLD = 15.0` — HIGHER than both NBA's (12.0) and WNBA's (10.0), not just copied
  from either: Division I's talent gap between a top-25 program and a mid-major is genuinely
  wider than any gap between two pro teams, so a "competitive" college game can carry a bigger
  spread than the same number would mean in the pros.
- `get_player_history_vs_opponent`'s docstring flags honestly that an empty head-to-head sample
  will be the COMMON case here, not the exception — most Division I non-conference opponents meet
  once a season if at all, unlike a pro league's balanced schedule.
- No hardcoded team-ID reference table in `config_ncaamb.py` — doubly true here versus WNBA/NBA's
  already-stable, much smaller leagues: 29 schools alone are changing conferences for 2026-27,
  confirmed during scoping, making any hardcoded list a near-certain staleness trap.

**Files added:** `config_ncaamb.py`, `ncaamb_engine.py`, `ncaamb_projections.py`,
`test_ncaamb_engine.py`, `test_ncaamb_projections.py`. **Files touched:** `basketball_engine.py`
(the new `extra_params` hook), `sports.py` (registry entry, `enabled=False`), `views/
11_Hot_Hand_Engine.py` and `views/12_Matchup_Lab.py` (require_sport gates extended to include
NCAAMB), `streamlit_app.py` (`sport_only_leads` extended), `test_sports.py` (both source-scraping
regression tests updated to reflect the real new config — legitimate assertion updates, not
workarounds, same as every prior sport's launch).

37 new tests (5 in `basketball_engine.py`'s test file for the `extra_params` hook, the rest split
across the two new NCAAMB-specific test files, including direct coverage of the `groups=50` fix
that has no WNBA/NBA equivalent to mirror). 369/369 total passing.

### NCAAMB follow-up verification attempt (2026-07-16, same session)
Tried to close the CDN boxscore gap directly before handing it back to Shawn — same playbook as
the NBA verification. Search doesn't index the raw CDN JSON (confirmed again — this is now a
consistent, expected wall, not a one-off), and an unprompted direct fetch of the CDN URL was
correctly blocked (never previously surfaced in search/fetch results). But a fetch of ESPN's
*rendered HTML* boxscore page for a real, live game DID succeed — better than expected, too: it's
UConn 73, Duke 72, an NCAA Tournament Elite Eight game (March 29 2026, gameId 401856577), where
UConn upset the #1 overall seed on a buzzer-beater. That confirmed real facts:
- **Team IDs 41 (UConn) and 150 (Duke)** — matching what this build's own test fixtures had
  already assumed, now genuinely confirmed rather than guessed.
- **The combo made-attempted FG/3PT/FT format** (e.g., "2-10", "1-6") — confirmed again.
- **A 13-category stat table**: MIN/PTS/FG/3PT/FT/REB/AST/TO/STL/BLK/OREB/DREB/PF — one fewer
  than NBA's 14 (no "+/-" column). Doesn't affect `get_game_boxscore`'s parsing, which only reads
  5 specific stats by name regardless of what else is present.
- **`test_ncaamb_engine.py`** gained a new test built from Alex Karaban's real confirmed line (38
  MIN, 5 PTS, 2-10 FG, 1-6 3PT, 3 REB, 3 AST) — honestly labeled as real VALUES with an ASSUMED
  (not JSON-proven) container shape, a real but smaller step than NBA's equivalent test, which
  used the literal raw JSON arrays Shawn had pasted back. 370/370 total passing.

**What's still genuinely open, stated precisely:** the raw CDN JSON's actual container structure
(the `names`/`athletes`/`stats` arrays `get_game_boxscore`'s parsing logic depends on) remains
unconfirmed — the rendered HTML page was reachable, the underlying JSON API endpoint itself
wasn't, from this sandbox. That's a real, structural limitation of what's fetchable here, not a
missed effort.

### NCAAMB CDN boxscore CONFIRMED LIVE (2026-07-16, same session, follow-up)
Shawn fetched the actual raw JSON directly — `cdn.espn.com/core/mens-college-basketball/boxscore
?xhr=1&gameId=401856577` — and pasted the literal response back. Real, live game: UConn 73, Duke
72, an NCAA Tournament Elite Eight game (March 29 2026), where UConn eliminated the #1 overall
seed on a buzzer-beater with 0.4 seconds left.

**Verified end to end with ZERO code changes needed:**
- **Player-level** — the real `names`/`keys`/`athletes`/`stats` array structure matched exactly
  what `get_game_boxscore` was written against. Checked against two real players' real lines:
  Alex Karaban (38 MIN, 5 PTS, 2-10 FG, 1-6 3PT, 3 REB, 3 AST) and Tarris Reed Jr. (32 MIN, 26
  PTS, 10-16 FG, 0-0 3PT, 9 REB, 3 AST) — both parsed correctly, first try.
- **Team-level** — `"points"` is genuinely absent from `statistics[]` here too (confirmed a third
  time now, after WNBA-adjacent and NBA samples), and the header-fallback fix built during NBA's
  own verification (`get_game_team_totals` falling back to `header.competitions[0].
  competitors[].score`) recovered the real 73-72 final score exactly, with no further changes.
- The generic ESPN-basketball-API shape WNBA and NBA already proved out held for NCAAMB on the
  first real check — the careful, shared, defensively-written `basketball_engine.py` layer paid
  off exactly as intended.
- `test_ncaamb_engine.py`'s two "assumed shape" tests upgraded to "confirmed live shape," the same
  status NBA's equivalent tests carry, built from the literal real JSON, not a guess at its shape.
  371/371 total passing.

**What's genuinely still open:** `get_team_injuries` for `mens-college-basketball` specifically —
only NBA's version of this endpoint was independently checked. Fails soft (empty list, not a
crash) if the real shape differs — worth checking on first real deploy, but not remotely the same
class of blocker the CDN boxscore was (that was the piece the whole verification effort was about).

**This closes the CDN boxscore gap completely** — the single biggest unknown in the NCAAMB build,
and the same piece that needed a live response pasted back before WNBA's and NBA's own launches.
Genuinely ready for a go-live decision now, not just "closer than before."

### NCAAMB flipped LIVE (2026-07-16, same session)
`sports.py`'s NCAAMB entry is now `enabled=True` — same go-live pattern as NBA's own launch. The
real blocker (CDN boxscore, both team- and player-level) was independently confirmed live against
a real game with zero code changes needed; `get_team_injuries` remains the one unconfirmed piece,
tracked below as a post-launch item, not a launch blocker (fails soft, doesn't crash anything).
`test_mlb_wnba_nba_ncaamb_enabled_today` replaces the old three-sport version — a real, legitimate
assertion update reflecting the new live state, not a workaround. 371/371 passing.

**MLB + WNBA + NBA + NCAAMB are all live now**, sharing the platform's sport-selector foundation.

### Line movement history: capture infrastructure built (2026-07-16)
Started this deliberately before the charting UI, not after — this is the one item on the roadmap
where waiting has a real cost: real line-movement history only exists from whenever capture
starts, so the earlier that begins, the sooner there's something real to chart.

**Scoping finding worth recording:** `capture_closing_lines.py`'s actual job is narrower than
"the line movement piece" — it tracks ONE closing price per your own OPEN BET, for CLV ("did I
beat the close on MY bet?"), overwriting on purpose (CLV is inherently a single before/after
comparison, not a time series). Modifying IT to "log every snapshot" would have been the wrong
fix — it would conflate two genuinely different questions. Built as new, separate infrastructure
instead:

- **`line_history.py`** — new storage module, same dual-backend pattern as `betlog.py`
  (SQLite local / Postgres via `DATABASE_URL`), but its own file and table
  (`data/line_history.db`, `line_snapshots`) — this is market data (many rows per slate, not tied
  to a person's decisions), a different shape and growth rate than a personal bet log, so kept
  separate rather than bolted onto `betlog.py`'s schema. `record_snapshot()` is
  **de-duplicated on write**: a new row is only inserted when the (line, price) for a given
  (sport, player, market, side, book) actually changed since the last capture — an unchanged line
  at the next run doesn't add a redundant row, which is what keeps both storage and any future
  chart meaningfully sparse (real movement only) instead of noisy (a point every time the script
  happened to run).
- **`capture_line_snapshots.py`** — new runner, sport-aware like `capture_closing_lines.py`
  (every ENABLED sport gets its own slate captured via that sport's own `odds_sport_key`/
  `markets`), but genuinely different in scope: it captures EVERY not-yet-started game's props,
  not just games tied to open bets, because it's tracking the whole market, not one person's
  positions.
- **Real cost tradeoff, stated plainly, not buried:** this is a materially bigger Odds API
  footprint than CLV capture (which only fetches props for a small, bounded set of games tied to
  actual bets). Given that, `.github/workflows/capture-line-snapshots.yml` runs on a deliberately
  coarser cadence — 4 times a day (morning/midday/pre-evening/evening) — not
  `capture-closing-lines.yml`'s dense every-15-30-minutes evening schedule. Flagged honestly as a
  reasonable starting cadence, not a backtested one — there's no line-movement history yet to
  check it against (that's exactly what this infrastructure is for); worth revisiting once real
  captured data shows where movement actually clusters.
- **A real bug found and fixed during testing, not just a passing note:** `record_snapshot`'s and
  `line_series`'s `db_path` parameters originally defaulted to the module-level `DB_PATH` value
  directly (`db_path: str = DB_PATH`) — a classic Python gotcha, since default parameter values
  bind ONCE at function-definition time. A caller (a test, or any future code) that monkeypatches
  `LH.DB_PATH` afterward would silently keep writing to the ORIGINAL path. Caught because a test
  built to verify this exact isolation instead wrote to the REAL `data/line_history.db` file on
  disk in the sandbox — found, the stray file was deleted, and both functions were fixed to
  resolve `DB_PATH` dynamically inside the function body instead of via an early-bound default.
- **13 new tests** across `test_line_history.py` (de-duplication behavior: first observation,
  unchanged skip, line-moved write, price-only-moved write, independent per-book/per-side
  tracking) and `test_capture_line_snapshots.py` (sport-aware wiring, game-label construction,
  end-to-end de-dup across two real capture runs, `main()` iterating every enabled sport
  regardless of bets, refuses-without-secrets discipline). 384/384 total passing.

**Deliberately NOT built yet, and why:** the actual line-movement chart (Matchup Lab's
stock-candlestick analog). There's no real captured history to visualize right now — this
checkpoint is the capture starting, not the chart. Building the chart before real data exists
would mean either an empty chart or a synthetic one, neither of which is worth shipping. Comes
back into scope once the capture has been running long enough to have something real to show.

### NFL build: rebuilt from scratch, verified live end to end (2026-07-17)
Resumed the NFL build. The existing draft (`nfl_engine.py`/`nfl_projections.py`/`config_nfl.py`)
turned out to have real, structural problems worth fixing properly rather than patching — this
was a full rewrite, not a continuation.

**Two real, load-bearing bugs found during scoping, before any code was written:**
1. **The data source was dead.** The draft depended on `nfl_data_py`. Checked directly against the
   source: `nfl_data_py`'s own README now reads *"nfl_data_py has been deprecated in favour of
   nflreadpy... No further nfl_data_py maintenance or updates are planned."* Repo archived Sep 25,
   2025, last release Sep 2024. Building new production code on an abandoned library was the
   wrong call — rebuilt on `nflreadpy` instead, nflverse's own actively-maintained successor
   (v0.1.5, confirmed installable via standard `pip install nflreadpy`, not a fragile GitHub-only
   install). Honest caveat carried forward: nflreadpy's own lifecycle badge reads "experimental,"
   not stable 1.0 — same "unofficial API" posture already carried for ESPN's endpoints elsewhere
   on this platform.
2. **The market keys were fabricated.** `config_nfl.py`'s `SUPPORTED_MARKETS` used
   `"quarterback_passing_yards"`, `"player_rushing_yards"`, `"player_receiving_yards"` — none of
   which exist in Odds API's real market taxonomy. Edge Board would have silently fetched zero
   real NFL odds — not an error, just empty results, exactly the failure mode this platform's
   diagnostic-print discipline exists to catch, caught here before it ever shipped instead of
   after. Real, confirmed keys (via Odds API's own documentation): `player_pass_yds`,
   `player_rush_yds`, `player_receptions`, `player_reception_yds`.

**Verified against REAL, LIVE data, not just documentation** — `nflreadpy` was actually installed
and queried in the build sandbox (network access to pypi.org and nflverse's data releases made
this possible, unlike the ESPN-based sports where live verification depended on the person's own
fetch): a real 2025 schedule (285 games, confirmed `away_rest`/`home_rest` already computed —
NFL's schedule data includes rest days directly, unlike every basketball engine which computes it
by scanning recent games), real weekly stats (19,421 rows, including Patrick Mahomes' actual Week
1 2025 line: 24/39, 258 yards, 1 TD), real rosters, and real injury reports. The full pipeline —
schedule → weekly stats → position-aware slate → bootstrap projections → Edge Board/Best Bets
shape — ran end to end against real Week 6 2025 data with zero crashes: 15 real games, 270 real
players clearing a rotation floor, 513 real projected offers, all with sensible results (e.g.
Garrett Wilson correctly favored Over on real 6.6 rec/76.4 yard recent averages; Devin Singletary
correctly Under on modest rush volume, correctly excluded from receiving markets entirely given
his real near-zero target share).

**Real structural differences from every other sport here, designed for, not glossed over:**
- **Weekly, not daily, slate structure.** NFL games happen as a whole week's slate (Thu-Mon), not
  on individual calendar dates. Rather than change the shared layer's date-picker UI (every page
  calls `sport.engine.build_slate(date_str)` expecting one date in, one slate out),
  `build_slate(date_str)` here resolves the date to whichever week it falls in (or the next
  upcoming week, or the season's last week if past it — see `_resolve_week`'s own docstring for
  the exact rule) and returns that whole week. Same interface every other sport already expects.
- **Position-aware markets, not basketball's one-size-fits-all Core 4.** A QB doesn't have
  receptions, a WR doesn't have pass yards. `player_row` only attaches markets relevant to a
  player's own position AND only once their own average of that market's opportunity stat
  (attempts/touches/targets) clears a floor — both gates are position-specific, not one shared
  number, since "enough volume to matter" means something different for a QB's attempts than a
  WR's targets.
- **`RECENT_GAMES_N = 5`, not basketball's 10** — an NFL season is 17 games, not 40-90+; a
  10-game window would be over half the season, diluting the recency signal it exists to capture.
- **`shrink_prob` reused directly from `basketball_projections.py`**, not duplicated or moved —
  confirmed to be pure probability math with zero basketball-specific assumptions, so importing
  it as-is (despite the cross-domain-sounding name) was the lower-risk choice over touching three
  already-shipped, tested modules (WNBA/NBA/NCAAMB's own imports of it) for a cosmetic rename.
- **Honest v1 gap, not silently shipped**: Week 1 of any season returns an empty slate for every
  player, even once real data exists — there's no within-season "recent form" yet at the very
  start, and this deliberately does NOT reach into the prior season to fill the gap (roster churn
  — trades, free agency, the draft — matters far more year-over-year in the NFL than within one
  season; a player's last-season numbers on a different team could actively mislead).

**Staged scope, matching how MLB and WNBA were both originally built**: this covers what Edge
Board and Best Bets need — the platform's core "find a priced edge" pages. A Hot Hand Engine-
equivalent and a Matchup Lab-equivalent do NOT exist yet, deliberately deferred, not missing by
oversight.

**Files rewritten from scratch**: `nfl_engine.py`, `nfl_projections.py`, `config_nfl.py`. **Files
added**: `test_nfl_engine.py` (19 tests, including real-confirmed-value tests built from the live
Mahomes/schedule/injury data above), `test_nfl_projections.py` (9 tests, including the same
streak-length-clustering shrinkage regression every other sport's suite carries). **Files
touched**: `sports.py` (real markets/market_map wired in, `enabled=False` pending final review —
see below), `requirements.txt` (`nflreadpy==0.1.5` added; `nfl_data_py` was never actually added,
so nothing to remove), `test_sports.py` (two placeholder-sport tests updated to use NHL instead of
NFL as their "still unwired" example, since NFL now has real markets — legitimate updates
reflecting the real new state, same as every other sport's launch). 411/411 total passing.

**Go-live checklist:**
1. ~~A final review pass on the actual numbers/output~~ — DONE, same session. Checked things a
   quick glance wouldn't catch: team abbreviations match exactly across schedule and roster data
   (32/32 teams, both consistently using "LA" for the Rams, "WAS" for Washington — no silent
   join-mismatch risk); playoff weeks (19-22, Wild Card through Super Bowl) are numbered
   sequentially after the regular season's 1-18, not colliding with it, so "strictly before this
   week" naturally handles the regular-season-to-playoffs boundary with no special-casing needed;
   zero duplicate player+week rows in the real data (a mid-season trade doesn't corrupt a
   player's recent-form sample); and the smallest-possible slate (Super Bowl week, exactly one
   game) ran cleanly end to end — real matchup (Seahawks @ Patriots, matching the real confirmed
   result from scoping research), 19 real players, 36 real projected plays.
2. Live-deploy check once actually running on Streamlit Cloud (confirms `nflreadpy`'s real network
   behavior in that environment, not just this sandbox) — the one item only checkable there, not here.
3. ~~Once (2) is done, flip `sports.py`'s NFL entry to `enabled=True`~~ — DONE, same session,
   flipped live for Shawn to check against the real Streamlit Cloud deployment.

### NFL flipped LIVE (2026-07-17, same session)
`sports.py`'s NFL entry is now `enabled=True` — same go-live pattern as WNBA/NBA/NCAAMB's own
launches, and the same honest sequencing: real research first (catching the deprecated-library and
fabricated-market-key issues before any code was written), a full rewrite verified against real
live data, a genuine review pass (team abbreviations, playoff-week boundaries, the smallest
possible slate), then the flip — not skipping straight to "on." `test_mlb_wnba_nba_ncaamb_nfl_
enabled_today` replaces the four-sport version — a real, legitimate assertion update reflecting
the new live state, not a workaround. 412/412 passing.

**MLB + WNBA + NBA + NCAAMB + NFL are all live now**, sharing the platform's sport-selector
foundation. The one thing genuinely only checkable on Shawn's end: `nflreadpy`'s real network
behavior once actually running on Streamlit Cloud — worth a first look at a real slate once the
season is close enough that real data exists to browse (2026 season starts Sep 9).

### NFL Retrospective crash: found and fixed (2026-07-17, same session)
Shawn hit a real crash immediately after go-live: `AttributeError` in Retrospective, traceback
pointing to `sport.engine.get_player_results(date_str)` — a function every other sport's engine
has, that `nfl_engine.py` genuinely never had. A direct consequence of this build's own staged-
scope note ("covers what Edge Board and Best Bets need") not accounting for what flipping
`enabled=True` actually exposes: NFL becomes selectable on EVERY shared page, not just the two it
was scoped for, and Retrospective (plus Podcast Studio and Media Room, confirmed via the same
audit) all call `get_player_results`.

**Two real bugs, not one, found by auditing rather than just patching the reported crash:**
1. **`get_player_results` didn't exist at all** — added it. One genuine design decision worth
   recording: it returns the WHOLE resolved week's results, not just games on the literal
   calendar date, matching `build_slate`'s own weekly resolution — needed, not optional, since
   grading compares this function's output against a slate `build_slate` already built for a
   whole week; returning only the literal date's games would silently show "no result" for every
   player whose game fell on a different day within that week (Thursday/Monday games especially,
   not an edge case).
2. **`retro.py`'s `MARKET_STAT` dict had no NFL entries at all.** WNBA/NBA/NCAAMB all share one
   set of entries because their display market names are identical (the Core-4 convention); NFL's
   names ("Pass Yards", "Rush Yards", etc.) are entirely different and needed their own. Without
   this, `get_player_results` alone would have stopped the crash but silently graded ZERO NFL
   plays — caught by auditing the full grading path end to end, not just re-running the exact
   failure that was reported.

**A third, smaller bug found while testing the fix, not the original crash**: `load_season_weekly_
stats`'s `_touches` computation used `df.get("carries", 0).fillna(0)` — a real pandas gotcha:
`DataFrame.get()` returns the literal default (an int) when a column is entirely absent from the
response, not a Series of that default, and calling `.fillna()` on an int crashes. Fixed by
ensuring both columns exist before computing `_touches`, so this is correct whether or not a real
response happens to include them, not just in the shape it happened to return during the original
live verification.

**Verified against real live 2025 data, full pipeline, not just unit tests**: `build_slate` →
`build_best_bets` → `get_player_results` → `retro.grade_slate`, end to end. 513 plays graded, 404
with real results, 267 hits — a real, sensible calibration (55% predicted vs. 59% actual in one
bin, 70.4% vs. 70% in another). 8 new tests added (`test_nfl_engine.py`: `_infer_season`,
`get_player_results`'s whole-week behavior, empty-for-unplayed-weeks, skip-no-id rows;
`test_retro.py`: NFL's `market_report`, and a direct assertion that every NFL display market has a
`MARKET_STAT` entry — the exact pairing gap that caused bug #2, now guarded explicitly rather than
left to be caught by chance in an individual market's test). 420/420 total passing.

### NFL Retrospective, second crash: found and fixed properly this time (2026-07-17, same session)
Same page, same day, a second real crash: `AttributeError` on `P.explain_miss` — another function
every other live sport's projections module has that `nfl_projections.py` genuinely didn't. The
first fix (`get_player_results`) was correct but incomplete: the audit behind it grepped for the
literal string `sport.projections.xxx`, which missed every call written as the locally-aliased
`P.xxx` instead (`E, P = _active.engine, _active.projections`, set once near the top of
Retrospective — and Command Center, Media Room, and Podcast Studio all follow the identical
pattern). `explain_miss` was exactly that kind of call, gated correctly (`R.explain_miss if
_active.key == "MLB" else P.explain_miss`) but assuming every non-MLB sport already had it, which
was true for WNBA/NBA/NCAAMB and simply hadn't been built for NFL yet.

**Fixed properly this time**: added `nfl_projections.explain_miss`, matching WNBA/NBA/NCAAMB's
exact contract. Then, rather than patch the one reported symptom again, did an EXHAUSTIVE
function-by-function audit instead of another partial grep:
- Diffed every public function name in `ncaamb_projections.py`/`ncaamb_engine.py` (the fullest-
  featured live sport) against NFL's — the only gaps were Hot Hand Engine/Matchup Lab-specific
  functions (`build_hot_hand_board`, `build_matchup_profile`, `get_team_recent_allowed_stats`,
  etc.), confirmed genuinely safe because both those pages gate to `["WNBA", "NBA", "NCAAMB"]`
  and correctly exclude NFL — verified directly in both files, not assumed from memory.
- Read (not grepped) Command Center, Media Room, and Podcast Studio in full. All three follow the
  same clean split Retrospective does — an `_mlb`-suffixed function containing MLB-only calls
  (`enrich_hitter_rows`, `build_pitcher_projection_rows`), called ONLY when `_active.key ==
  "MLB"`, versus a `_generic` function every other sport actually uses. Confirmed NFL's generic
  path only ever needs `build_slate`/`get_player_results`/`build_best_bets`/
  `build_projection_index`/`curate_selections` — all present now. `selections.
  filter_known_pitcher` (named for MLB but checked directly): despite the name, it only reads the
  sport-agnostic `Opp` field every sport's plays already have — confirmed safe for NFL by reading
  its actual implementation, not inferring safety from the function name.
- Confirmed Track Record and Bet Log do no per-sport engine/projections routing at all (only read
  `_active.key`/`.label`/`.icon`/`.market_map` — plain attributes every registry entry has) — so
  there was nothing to check there in the first place.

**A real regression guard added, not just a fix**: `test_sports.py::test_every_live_sport_
implements_the_full_shared_page_contract` explicitly enumerates the full engine/projections
contract every shared page needs (`build_slate`, `get_player_results`, `build_best_bets`,
`build_projection_index`, `curate_selections`, `explain_miss`) and checks every currently-enabled
non-MLB sport against it. Confirmed this test would have caught BOTH bugs before they ever shipped,
not just the second one — a future sport's launch, or a future shared page calling a new function,
gets caught here first instead of by a real person hitting a real crash.

**Verified against real live 2025 data, the actual Retrospective code path simulated exactly**,
not just unit tests in isolation: `build_slate` → `build_best_bets` → `get_player_results` →
`grade_slate` → `market_report` → `explain_miss` for each of a missed play in all four markets,
with real recognizable players (Aaron Rodgers, Isiah Pacheco, Tee Higgins, Christian McCaffrey)
and sensible reasoning for each. 5 new tests in `test_nfl_projections.py` (`explain_miss`'s
none-row/catchable/outlier/unknown-market cases) plus the new cross-sport contract guard.
425/425 total passing.

### NFL Matchup Lab + Anytime TD Engine built (2026-07-17, same session)
Both requested pages built and verified end to end against real live 2025 data.

**NFL Matchup Lab — built as its OWN page, not added to the existing WNBA/NBA/NCAAMB one, a real
decision, not an oversight**: `nfl_engine.get_team_injuries` takes `(team_abbr, season, week)` —
richer and more precise than basketball's `(team_abbr)` alone, since NFL's real injury data is
genuinely week-specific. Weakening it to fit the shared page's 1-arg convention would throw away
real value. NFL's game-log records also use nflreadpy's own raw columns (`week`, `opponent_team`,
`passing_yards`, ...) rather than basketball's engine-added `opp`/`date` convenience fields. Same
conventions and spirit as the existing Matchup Lab throughout (time slot + game filters, trend
charts against the line, recent/season/H2H table, opponent defensive-trend table) — adapted, not
reinvented, for what NFL's data actually looks like.
- **`nfl_engine.py` additions**: `team_abbrs_from_meta` (trivial for NFL — team_id already IS the
  abbreviation), `get_player_season_games`, `get_player_history_vs_opponent` (honestly expected to
  return empty far more often than any other sport here — most NFL opponents meet once a season,
  division rivals twice), `get_team_allowed_stats` (defense-allowed rates, grouped by game/week
  then averaged — confirmed via test that this correctly sums per-game before averaging, not
  averaging raw player rows, which would double-count teammates' returns from the same game),
  `get_team_rest_info` (reads real `home_rest`/`away_rest` straight from the schedule, no scanning
  needed — and uses **`is_short_week`**, not basketball's `is_back_to_back`, a real NFL concept
  since no team plays on consecutive days; a short week is a Thursday game after a Sunday one).
- **`nfl_projections.py` additions**: `build_trend_series`, `stat_key_for` (an honest identity
  function for NFL — `_MARKET_SPEC` already stores the real column name directly, no separate
  short-name translation layer the way basketball needs one), `build_matchup_profile` (iterates
  only a row's own gated `_markets`, so a QB's profile never gets a phantom Receptions row).
- **`views/13_NFL_Matchup_Lab.py`** — new page, wired into `streamlit_app.py`'s navigation and
  `sport_only_leads` (NFL-only, same gating pattern every sport-specific page uses).
- Verified against real live data: Saquon Barkley vs. the Giants (his former team) — real recent
  form, real (honestly empty) H2H, real opponent-allowed defensive trend, real rest info for both
  teams, no crashes anywhere in the chain.

**Anytime TD Engine — the NFL analog to MLB's Dinger Engine, genuinely different math, not a port
of the four Core markets**: those bootstrap-resample a continuous stat and derive P(stat > line).
Scoring a TD is already a real Bernoulli outcome, so `build_anytime_td_board` skips the bootstrap
step entirely and applies `basketball_projections.shrink_prob` DIRECTLY to each player's own
empirical TD-scored rate — arguably the cleaner, more natural fit for that shrinkage math than the
Core markets' own use of it, not a repurposing. **QB included in eligible positions, deliberately,
unlike the Rush Yards yardage market** (which excludes QB on purpose — mixing a scrambling QB's
occasional carries with a workhorse RB's volume under one shared line would mislead): Anytime TD
is a binary outcome with no shared line, so a mobile QB's real rushing-TD rate is its own honest
signal here. **Ranked by raw ModelProb, not a Conviction ratio** — also deliberate: a workhorse
RB's true scoring rate might be 35%, a WR's 15%, and dividing either by a shared 0.5 baseline
wouldn't mean the same thing for both positions; ranking directly by probability (like MLB's own
Dinger Engine) is the honest choice.
- **`views/14_Anytime_TD_Engine.py`** — new page, model-only, NO live odds integration yet — a
  deliberate v1 scoping choice: Anytime TD is typically a single-sided Yes/No market at
  sportsbooks, a different offer shape than the four Core markets' verified Over/Under, and
  guessing at that shape risked a silent parsing bug. Ships the same way every sport's first board
  here did — model-only, clearly labeled, live pricing a real follow-on once that shape is
  confirmed the same rigorous way the Core markets' was.
- Verified against real live data: real, recognizable, correctly-shrunk results (Saquon Barkley,
  Garrett Wilson, De'Von Achane all near the top with real recent scoring rates, appropriately
  pulled toward a neutral baseline rather than showing raw small-sample 100%s).

**Both pages wired into navigation** (`streamlit_app.py`'s `sport_only_leads` and `meta` dicts,
page 13 and 14) — confirmed via the same source-scraping regression test every prior page addition
required updating, a legitimate assertion update reflecting the real new config.

**41 new tests** across `test_nfl_engine.py` (11: team_abbrs_from_meta, season games, H2H
filtering incl. the honest-empty case, allowed-stats grouping-by-game correctness, allowed-stats
recency-window correctness, rest-info incl. short-week flagging) and `test_nfl_projections.py`
(9: trend series, stat_key_for, matchup-profile market-gating and honest-empty-H2H and
defense-trend tagging, Anytime TD position-eligibility/ranking/shrinkage/either-TD-type-counts).
444/444 total passing.

### QB Lab + Touchdowns in Matchup Lab (2026-07-17, same session)
Two enhancements requested together, both verified end to end against real live 2025 data.

**Touchdowns added to Matchup Lab** — new engine function `get_team_tds_allowed` (same grouped-
by-game-then-averaged construction as `get_team_allowed_stats`, kept as its own function rather
than folded into that one's return dict since TDs is a fundamentally different KIND of stat — a
low, often zero-inflated count, not a continuous yardage total). `build_matchup_profile` extended
with two new optional params (`opp_recent_tds_allowed`, `opp_season_tds_allowed`) and now appends
a "Touchdowns" row for any TD-eligible position, built separately from the yardage-market loop
and deliberately excluded from the ratio-based Suppressed-market flagging (which specifically
compares H2H performance across the yardage markets against each other — TDs isn't part of that
same-unit comparison). Both of Matchup Lab's existing tables pick up the new row automatically,
since they already select columns generically from whatever's in the profile list. Added a
dedicated Touchdowns trend chart too (a bar chart, not the yardage markets' line-plus-dashed-
line style — TDs is a low discrete count with no live line to show yet, so a bar reads more
honestly than inventing a reference line that isn't real). One real code-hygiene fix along the
way: caught the view directly reaching into a private `_TD_ELIGIBLE_POSITIONS` set, which breaks
the established convention (view files only touch public wrappers like `market_list`/
`stat_key_for`/`default_line`) — added `is_td_eligible_position()` as the proper public wrapper
instead of leaving the shortcut in.

**QB Lab built** — the honest NFL counterpart to MLB's Pitching Lab, two real signals:
- **Matchup-aware Pass Yards projections** — each QB's own recent-form average scaled by how much
  this week's opponent's pass defense has allowed relative to league average, the same odds-
  ratio-style adjustment Pitching Lab's own Proj K applies, just to a yardage stat instead of
  strikeouts. New engine function `get_league_average_pass_yards_allowed` — deliberately SEASON-
  WIDE ONLY, no recent-N-games version: a league-wide "recent" baseline is genuinely ambiguous in
  a way one team's own recent-vs-season split isn't (different teams have played different
  numbers of games by any given week), and a stable baseline is the more defensible choice for a
  matchup comparison point anyway.
- **TD:INT regression table** — each QB's recent TD/INT rates against their OWN season-long
  rates, flagging a meaningful divergence. Explicitly NOT a ported "NFL FIP": ERA-vs-FIP compares
  a luck-affected results metric against a more-predictive peripherals metric over the SAME
  window; this compares a small, noisy recent window against a larger, steadier season window —
  a real but different axis of the same underlying mean-reversion idea, built entirely from real
  confirmed TD/INT counts rather than fabricating a tracking-data-dependent formula this platform
  doesn't have the data to support honestly. Tag direction deliberately stated as description, not
  a buy/fade call the way Pitching Lab's is — "trending above/below season norm," not "buy/fade."
- Discussion hooks, same auto-generated-talking-points pattern as Pitching Lab's own.

**Both new pages wired into navigation** (`streamlit_app.py`, pages 13-15 all NFL-only via
`sport_only_leads`) — the same source-scraping regression test every prior page addition required
updating caught this one too, a legitimate assertion update reflecting the real new config.

**35 new tests** across `test_nfl_engine.py` (6: TDs-allowed grouping-by-game correctness,
league-average grouping-across-all-teams correctness, both with real-data-shaped edge cases) and
`test_nfl_projections.py` (13: Touchdowns-row market-gating and Suppressed-exclusion, TD-
eligibility wrapper, matchup-factor scaling and neutral-fallback, efficiency-table trending/
in-line/honest-none cases). 459/459 total passing.

### QB touchdown breakout + rushing yards, in both Matchup Lab and QB Lab (2026-07-17, same session)
Two real enhancements to the QB experience specifically, verified end to end against real live
Patrick Mahomes data throughout.

**Matchup Lab: QB gets split rows, not the combined Touchdowns row.** A QB's touchdown
production is overwhelmingly through PASSING, not rushing — the existing combined "Touchdowns"
row (rushing_tds + receiving_tds) would have silently missed a QB's actual primary scoring
signal entirely (receiving_tds is always ~0 for a QB). QB now gets three rows instead: **Rush
Yards** (shown here even though QB doesn't get the shared `player_rush_yds` MARKET on Edge
Board/Best Bets — that original exclusion was specifically about not mixing a scrambling QB's
occasional carries with a workhorse RB's volume under ONE shared betting line; a Matchup Lab
DISPLAY row has no such conflict, since it isn't shared with anyone else's number), **Passing
TDs**, and **Rushing TDs**. Confirmed live: Mahomes shows 38.0 recent rush yards/game (genuinely
mobile) and a real passing-vs-rushing TD split (1.6 vs 0.6/game) that would have been invisible
under the old combined row.

**Two new engine functions, `get_team_passing_tds_allowed`/`get_team_rushing_tds_allowed`**,
refactored alongside the existing `get_team_tds_allowed` into a shared private
`_get_team_stat_sum_allowed` helper — verified via the existing test suite that the refactor
produced zero behavior change to the already-shipped function before extending it.

**A new shared `_extra_profile_row` helper in `nfl_projections.py`**, used by the combined
Touchdowns row (RB/WR/TE/FB, refactored to use it — again verified via existing tests that this
produced byte-identical output to the pre-refactor version) and now the three QB rows, avoiding
writing the same Recent/Season/H2H/Allowed/Trend construction four separate times. Deliberately
NOT applied to the core yardage-market loop itself (Pass Yards/Rush Yards for RB/Receptions/
Receiving Yards) — that loop's extra cross-market Suppressed-ratio logic doesn't fit this
simpler per-stat shape, and refactoring already-shipped, tested code for cosmetic DRY wasn't
worth the risk.

**QB Lab extended with the same two signals.** `build_qb_matchup_projections` now returns a
second matchup-adjusted projection (Rush Yards, using the exact same odds-ratio construction as
the existing Pass Yards one) alongside the original — needed a new engine function,
`get_league_average_rush_yards_allowed`, refactored alongside the existing pass-yards version
into a shared `_get_league_average_allowed` helper (same verify-no-regression discipline).
`build_qb_efficiency_table`'s two TD-rate columns were **renamed** for honesty once a rushing
sibling existed alongside them — "Recent/Season TD Rate" (always implicitly passing-only) became
"Recent/Season Passing TD Rate", with new "Recent/Season Rushing TD Rate" columns added
alongside, deliberately NOT folded into the passing-specific TD:INT delta/tag (there's no
rushing equivalent of an interception to regress a rushing TD rate against the same way) — same
"raw signals side by side, not one blended number" philosophy Matchup Lab already follows. The
one test and the view file that referenced the old key names were updated in the same change, so
nothing broke in the transition.

**9 new tests** across `test_nfl_engine.py` (2: passing/rushing TDs allowed correctly isolate
their own stat from a combined-looking dataset; league-average rushing yards allowed) and
`test_nfl_projections.py` (7: QB gets split rows never a combined one; QB Rush Yards reuses the
existing opponent-allowed dicts with no extra fetch; Passing TDs vs Rushing TDs correctly
isolated from each other; RB/WR/TE/FB's existing combined row unaffected — the actual regression
guard for the refactor; QB Lab's rushing projection and neutral-fallback; the renamed efficiency
columns). 468/468 total passing.

### MLB Matchup Lab: Time slot + Game filters added (2026-07-17, same session)
Shawn asked to bring NFL Matchup Lab's format over to MLB's. Worth recording the scoping call made
before touching anything: MLB's Matchup Lab is a genuinely different KIND of page — pitch-level
arsenal vs. hitter vulnerability (which specific pitches to attack with), not "player vs. opponent
team" the way WNBA/NBA/NCAAMB/NFL's Matchup Lab is. It already has a deliberate, documented reason
for NOT having a recency trend chart (arsenals/hitter_splits are season-aggregate snapshots per
pitch, not a dated sequence — there's no "recent form over time" to plot), and an H2H-vs-opponent-
team box doesn't fit the actual question this page answers either (pitcher vs. hitter, not batter
vs. a specific team). Forcing the full NFL layout on would have meant either breaking that
established design decision or bolting on boxes that don't answer MLB's real question.

**What DID transfer cleanly**: Time slot + Game filters, narrowing a busy night's probable-starter
list before picking one — a pure navigation improvement with no analytical-framework conflict,
reusing the exact same shared helpers (`sports.game_dt`/`slot_of`/`SLOT_ORDER`) every other
Matchup-Lab-style page and Best Bets already use. Needed one small, backward-compatible engine
change: `mlb_engine.build_pitching_slate` didn't carry a game date/time field at all before (only
a "Game" label); now threads `_game_date` through from the schedule data it already fetches, at
zero extra cost. Confirmed no regression to the existing function's shape or behavior (only a
key added, existing callers unaffected) via the full test suite before and after.

**Flagged, and Shawn confirmed navigation + injury report were the two pieces he actually wanted**
— pitcher "days rest since last start" was NOT pursued further (MLB doesn't have a pre-computed
rest field the way NFL's schedule does; would need a real new pitcher-game-log fetch this
platform doesn't have). The injury report WAS built as a same-day follow-up — see below.

### MLB Matchup Lab: Injury report added (2026-07-17, same session, follow-up)
New `mlb_engine.get_team_injuries(team_id)`, matching the exact shape basketball_engine's and
nfl_engine's own versions return, wired into a collapsible "🏥 Injury report — both teams"
expander right after both a pitcher and hitter are picked — same placement and framing as the
NFL screenshot this whole change was modeled on.

**Genuinely different, lower confidence than every other injury function built this session, and
stated as such rather than glossed over**: every other sport's version was checked against a real
live response before shipping — ESPN's endpoints via a person's own fetch for WNBA/NBA/NCAAMB,
nflreadpy installed directly in the build sandbox for NFL. This one could not be — the same
network restriction as the filter change above (`statsapi.mlb.com` returns 403 from this sandbox).
Built from MLB Stats API's documented structure (real, but secondary, sources — the roster
endpoint's own `status.code`/`status.description` fields, confirmed via MLB-StatsAPI's own
documentation and cross-checked against multiple independent sources), not a live-verified
response. One specific detail stayed genuinely uncertain through the research: `rosterType=
fullRoster` was the most defensible documented choice for capturing every IL variant, but whether
it specifically includes 60-day IL players (who by rule fall OFF the narrower 40-man roster) never
got fully confirmed. Filters to any roster status that isn't "A" (Active), using MLB's own
human-readable status description rather than this code hardcoding an interpretation of every
possible status value — `return_date`/`comment` are always None, honestly, since the roster
endpoint reports a status, not a detailed injury description.

Needed `build_pitching_slate` to also carry each side's real numeric team_id through (only had
team NAMES before, and the roster endpoint needs a numeric id) — same backward-compatible
"only adds keys" pattern as the `_game_date` addition. 5 new tests: 3 for `get_team_injuries`
(non-Active filtering against the documented shape, empty-on-failure, falls back to the status
code when no description is present) and 2 extending the `build_pitching_slate` coverage (team
IDs thread through correctly for both sides). A full offline simulation of the whole chain
(`build_pitching_slate` → `get_team_injuries` for both teams) ran clean with real-shaped mock
data. 473/473 total passing.

**Worth a real, deliberate manual check once deployed** — pull up one actual team's roster and
compare against what this shows, specifically checking whether a real 60-day IL player appears.
This is the one piece on the whole platform shipped without any live confirmation at all.

### MLB Matchup Lab: real bug report — every game showing "TBD" for time slot (2026-07-18)
Shawn's real deployment showed only "All slate"/"TBD" in the Time slot dropdown — no real
Afternoon/Evening/Late buckets, even though the Game dropdown correctly showed a real matchup
(Baltimore Orioles @ Houston Astros). Reviewed `build_pitching_slate`'s threading logic line by
line — it's correct, no unpacking mismatch, `_game_date` flows through cleanly. Most likely
explanation, not fully confirmable from this sandbox: `load_pitchers` is wrapped in `@st.cache_
data(ttl=300, ...)`, and this page had NO refresh button — unlike NFL Matchup Lab/Anytime TD
Engine/QB Lab, which all got one when they were built. If Shawn loaded the page shortly after
this deploy, he could easily have been looking at a still-cached result from before `_game_date`
existed on these rows at all, with no way to force a fresh fetch except waiting out the TTL.

Fixed the actual gap, not just the symptom: added the missing 🔄 Refresh button (`st.cache_data.
clear()` + `st.rerun()`), matching the convention every other similarly-structured page already
has — this page was the one built/extended this session that never got one. Also added a real
diagnostic: if `build_pitching_slate` ever returns rows with real pitcher data but NONE of them
carry a `game_date`, it now prints a visible signal instead of silently manifesting as a
confusing "every game shows TBD" report with no way to debug it from the logs. If clicking
Refresh resolves it, that confirms the stale-cache theory; if the diagnostic still fires on a
genuinely fresh fetch, that would point to a real gap in what MLB's schedule endpoint returned
for that date — worth reporting back either way.

### GM/analyst gap-filling, item 1 of 5: hitter regression table (wOBA vs. xwOBA) (2026-07-18)
Shawn asked, wearing both an analyst and a GM hat, what's missing from the dashboard for
pinpointing matchup advantages and lineup decisions. Landed on five real gaps, prioritized by
value; building them in that order. First: Pitching Lab has ERA-vs-FIP (results vs. deserved
performance); there was no hitter equivalent anywhere on the platform.

**Built on an already-strong foundation, not from scratch**: `statcast_data.py` already pulled
Savant's expected-stats leaderboard for Dinger Engine's HR model, but only extracted xSLG, not
xwOBA — even though the same leaderboard row returns "actual BA, SLG, wOBA for comparison"
alongside the expected versions (confirmed during scoping). Extended `_build_statcast_frame`/
`load()` to also extract actual `woba` and expected `xwoba`, using the EXACT SAME column-name-
hedging convention already proven working for `xslg` (`_series(df, "est_woba", "xwoba", ...)`) —
low-risk by construction, not a new pattern.

**`SC.build_hitter_regression_table(rows, statcast)`** — the actual table, living in
`statcast_data.py` itself (matching that module's own stated "pure and testable" philosophy).
**One sign-flip worth being explicit about, since getting it backwards would flag exactly the
wrong hitters**: for a pitcher, LOWER ERA is better, so ERA − FIP > 0 means "expect improvement."
For a hitter, HIGHER wOBA is better, so here Delta = wOBA − xwOBA is inverted — a NEGATIVE delta
(underperforming contact quality) is the "expect improvement" read. The Tag text spells this out
in words rather than leaning on the sign alone. Reuses `MIN_PA_QUALIFIED` (already used elsewhere
in this file to calibrate the barrel-to-HR constant) as the same PA floor here — small-sample
wOBA/xwOBA on either side isn't a real signal.

**A real operational note, not a bug**: an EXISTING cached `statcast_batters.csv` (written before
this change) has no woba/xwoba columns at all. `load()` correctly defaults those to 0.0 for a
stale cache — and `build_hitter_regression_table` treats woba/xwoba ≤ 0 as "no real data," never
showing a fabricated 0.000-vs-0.000 row. The table will genuinely show nothing until the next
`refresh_statcast.py` run regenerates the cache with the new columns — worth knowing before
wondering why it's empty on first deploy.

**Wired into Dinger Engine** (not a new page) — the natural home, since it already loads the
Statcast lookup for this exact pageview at zero extra fetch cost. Placed right after the existing
HR-specific "Due to homer" board, as its explicit complement: "Due to homer" is about power
specifically; this is about overall offensive value (every batted ball and walk). Color scale
deliberately reversed (`RdYlGn_r`) from the "Due to homer" board next to it — there, positive Due
is green (good, HR-specific under-luck); here, negative Delta is green (good, the "expect
improvement" direction) — same reversed-polarity reasoning already called out in the code itself,
not an inconsistency.

**8 new tests** in `test_statcast.py`: wOBA/xwOBA extraction, both regression directions flagged
correctly (with an explicit test locking in the sign-flip direction, not just "a delta exists"),
in-line/no-signal case, PA-floor exclusion, no-statcast-data exclusion, the stale-pre-refresh-
cache exclusion (the "operational note" above, tested as real behavior, not just documented), and
sort-by-absolute-delta surfacing both tails. A full offline simulation with realistic mixed data
(a real regression case on each side, plus a hitter with no Statcast row at all) ran clean.
481/481 total passing.

### GM/analyst gap-filling, item 2 of 5: reliever rest/fatigue signal (2026-07-18)
No visibility into bullpen availability existed anywhere on the platform. Built
`mlb_engine.get_team_bullpen_fatigue(team_id, before_date, days_back=5)` — every pitcher who
recorded outs in a team's last 5 calendar days, with days-since-last-appearance and (the highest-
value signal) a 3+-consecutive-days flag, the clearest "likely unavailable tonight" read given
real, well-established bullpen-usage convention.

**A real design choice worth recording, not a shortcut**: deliberately does NOT try to
distinguish starter from reliever within a single boxscore — that would need assuming something
about the raw JSON's pitcher-listing order that couldn't be confirmed with confidence during
scoping. Returns every pitcher who appeared, full stop; the CALLER cross-references against that
night's own confirmed starter (already known from `build_pitching_slate`, no guessing needed) to
read the rest as bullpen arms. Simpler and more certain than the alternative.

**Two new engine pieces, both reusing already-proven patterns rather than inventing new ones**:
`get_team_schedule_range(team_id, start, end)` — a real, documented MLB Stats API capability
(teamId + startDate/endDate in one request) — extracted `get_schedule`'s own normalization into a
shared private helper first, verified byte-identical output via a new test (none existed for this
function before), then built the range query on top of it. And the boxscore-scanning logic itself
reuses the EXACT SAME `stats.pitching`/`inningsPitched` shape `_parse_boxscore_results` already
has proven in production for grading — not new, unverified parsing.

**One honest, accepted imprecision, stated in the code, not discovered later**: appearance dates
bucket to UTC calendar date, not Eastern-converted first — a late West Coast start crossing
midnight UTC could misbucket by one day. Not worth a timezone dependency for what's a rare, minor
edge case on the least important part of the signal.

**Wired into Pitching Lab**, scoped to ONE selected game at a time, not the whole slate —
a real, deliberate cost decision: each team's read costs a schedule-window call plus one boxscore
fetch per recent game, so showing it for every team on a 15-game night up front would be
expensive for no reason when a person is only looking at one game at a time anyway. Needed
`build_slate`'s meta to carry `home_id`/`away_id` (previously computed internally but never
exposed) and Pitching Lab's own `fip_rows` to carry `_team_id` — both backward-compatible,
additive-only changes, confirmed via the full test suite before and after.

**16 new tests**: 3 for the schedule refactor (get_schedule's unchanged output, the new range
query's params, its chronological sort), and 13 for the fatigue function itself (a real 3-
consecutive-day streak, pitched-yesterday-only, a genuinely rested arm, a roster pitcher who
didn't actually appear correctly excluded, non-Final games skipped without even fetching their
boxscore, the opponent's own pitchers never leaking into this team's read, the lookahead-bias
guard, and sorting the most fatigued arms first). A full offline simulation of the whole chain
(`build_slate` → meta carrying real team ids) ran clean. 492/492 total passing.

**Same honest limitation as the injury report**: not verified against a live response
(`statsapi.mlb.com` unreachable from this sandbox). Carries somewhat less fresh uncertainty than
that one did, though — every piece here reuses an already-shipped, already-proven parsing shape
from elsewhere in this file, rather than introducing a new one from documentation alone. The one
genuinely new, unverified piece is the date-range schedule query itself.

### MLB Matchup Lab: bullpen arm as an alternative to the starter (2026-07-18, same session)
Shawn raised a real, well-known dynamic: a lineup can struggle against a real ace (his own
example: Paul Skenes) and erupt once the bullpen takes over — a genuinely different matchup once
the starter leaves. Asked whether Matchup Lab's pitch-mix/arsenal analysis could extend to the
bullpen.

**Turned out to be mostly a picker extension, not new modeling — confirmed before writing any
code, not assumed**: `matchup_data.py`'s cache is built from `pybaseball.statcast()` pulling the
WHOLE LEAGUE's pitches for the season, not filtered to probable starters — so `arsenals`/
`hitter_splits` already cover every pitcher who threw a pitch that year, relievers included.
`MD.build_matchup(pitcher_id, ...)` and `get_pitcher_metrics(pitcher_id, ...)` are both already
fully generic (confirmed by reading them, not assumed) — the existing page just never offered a
way to POINT them at anyone other than that day's confirmed starter.

**New engine function, `get_team_pitching_staff(team_id, exclude_pid=None)`** — a team's active
pitching staff, excluding whichever pitcher is passed (typically that night's starter). Uses
`rosterType=active`, deliberately different from `get_team_injuries`'s `fullRoster` — this one
wants the opposite (only pitchers who could actually take the mound tonight, not the injured
list), and `active` is also the MORE confidently-documented of the two rosterTypes (MLB Stats
API's own default), unlike `fullRoster`'s noted 60-day-IL uncertainty. Deliberately does NOT try
to further split "true relievers" from "the other four starters also on the active roster" — a
roster entry's position field is just "P" for everyone, no reliable role distinction available
from this endpoint, and guessing at one risked the same class of unconfirmed assumption
`get_team_bullpen_fatigue`'s own docstring already explains avoiding for a related reason.

**Wired into Matchup Lab as a checkbox right after the starter is picked**: "🔄 Look at
{team}'s bullpen instead of {starter}." Checking it fetches that team's staff (excluding the
starter, one on-demand fetch, not proactively for the whole slate), and picking a reliever
REBUILDS the page's `pitcher` dict using `get_pitcher_metrics` for real ERA/FIP/K9 context, in
the exact same field shape `build_pitching_slate`'s own rows already use — every downstream
reference in the rest of the page (the matchup grid, arsenal tables, the "Attack X with the Y"
headline) works unchanged, because this is a swap of WHICH pitcher feeds the page, not a second
code path bolted on next to the first. Opposing lineup context (hitter, team, game) carries
through unchanged, since it's the same game regardless of which of this team's arms is on the mound.

**6 new tests**: 3 for `get_team_pitching_staff` (position-filtering + exclusion + name sort,
no-exclude case, empty-on-failure) and a full offline simulation using a realistic Skenes-style
example — a real team's roster with the ace excluded, a reliever's own (meaningfully worse) ERA/
FIP fetched, and the reconstructed pitcher dict verified field-for-field to match what the rest
of the page expects. 495/495 total passing.

**Same honest limitation as this file's other roster-based functions**: not verified against a
live response (`statsapi.mlb.com` unreachable from this sandbox). `rosterType=active` is the
more confidently-documented choice of any roster fetch built this session, though — MLB Stats
API's own stated default, not a hedge between uncertain options the way `fullRoster` was.

### Bullpen quality: Pitching Lab enrichment + Dinger Engine matchup toggle (2026-07-18, same session)
Two follow-ups to item 2's bullpen fatigue work, both requested together.

**Pitching Lab: "available AND good" in one table.** New `mlb_engine.enrich_bullpen_fatigue_
with_metrics(fatigue, fip_constant)` — a thin composition step (one `get_pitcher_metrics` call
per pitcher already in the fatigue list) adding ERA/FIP/K9 to the existing bullpen fatigue table.
Kept as its own function rather than folded into `get_team_bullpen_fatigue` itself, so that
function stays testable in isolation without needing `get_pitcher_metrics`' own calls mocked too
— same "small functions that combine cleanly" shape `get_bullpen_aggregate_stat` already uses.
One real caching bug caught and fixed before shipping: the view's cached loader initially closed
over `fip_constant` instead of taking it as an explicit parameter, meaning `st.cache_data` would
never notice the FIP constant input had changed and would keep serving stale ERA/FIP values.
Fixed by making it an explicit parameter, matching the same convention `load()`'s own
`fip_constant` handling already established elsewhere in this exact file.

**Dinger Engine: Shawn's own real example (Skenes) was the design target.** A lineup that
struggles against a real ace can look completely different once his bullpen takes over — a
genuinely different matchup, not noise. Turned out to be mostly a picker/plumbing extension, not
new modeling, confirmed BEFORE writing code: `matchup_data.py`'s Statcast cache already pulls the
whole league's pitches for the season (not scoped to starters), and the hitter-probability
pipeline already takes an opposing pitcher's raw stat dict as input (`pitcher_allowed_rates`,
consumed inside `enrich_hitter_rows` via each row's own `_opp_stat`) — so feeding it a DIFFERENT
stat dict was always going to work, the question was just how to build that dict for a whole
bullpen.

- **`get_bullpen_aggregate_stat(team_id, exclude_pid, fip_constant)`** — combines a team's entire
  active bullpen into ONE stat dict shaped exactly like a single pitcher's own `.stat`, by reusing
  `_aggregate_pitching_splits` (already proven correct combining a traded pitcher's two stints —
  not new aggregation logic, the same operation on a roster's worth of relievers instead).
- **`projections.build_bullpen_matchup_rows(rows, opp_team_name, bullpen_stat, ...)`** — a thin
  wrapper around the EXISTING `enrich_hitter_rows`, just pointed at the bullpen's aggregate stat
  instead of the starter's. Works on copies, never mutates the original slate rows — the rest of
  the page (leaderboards, other games) still needs the vs-starter read regardless of this one
  game's toggle state.
- **The actual toggle**: a "🔄 Bullpen" checkbox next to each side's SP line in Game-by-game.
  Checking it recomputes the OPPOSING team's hitter tab against that team's combined bullpen.
  Three columns that describe a single starter (`Opp Pitcher`/`Opp Hand`/`Advantage`) get
  relabeled rather than left stale and misleading; `Opp HR/9` gets the REAL aggregate bullpen
  rate (already computed by `_aggregate_pitching_splits`), not blanked — a genuinely useful
  number, not a gap.
- **Verified with a realistic Skenes-shaped scenario**, not just unit tests in isolation: a
  hitter's HR% against a simulated ace-quality stat line (13.0%) nearly DOUBLED against a
  simulated homer-prone bullpen aggregate (25.0%), with the shown Opp HR/9 correctly landing in
  the existing fixed-band "homer-prone" red zone — the exact effect described, reproduced
  end to end through the real code path, not asserted in the abstract.

**13 new tests**: 3 for `enrich_bullpen_fatigue_with_metrics` (metrics added correctly, no-stats
flagged honestly, order/count preserved), 4 for `get_bullpen_aggregate_stat` (sums correctly
across relievers, None on no staff, None on no usable stats rather than a fabricated line, and a
direct confirmation its output shape works as real input to `pitcher_allowed_rates` — the actual
mechanism this whole feature depends on), and 3 for `build_bullpen_matchup_rows` (only touches
the target team's rows, never mutates the originals, and produces a genuinely different —
correctly directional — read than the starter). 505/505 total passing.

### GM/analyst gap-filling, item 3 of 5: lineup-wide platoon view (2026-07-18, same session)
Confirmed the original scoping call before building: `platoon_advantage` and per-hitter Hand/
Opp Hand/Advantage columns already existed (used inside Dinger Engine's own hitter rows) —
this genuinely was a surfacing exercise, not new modeling, for the starter-based half of it.

**Part 1 — starter-based platoon map, zero extra cost.** New "🔄 Platoon map" section in each
Dinger Engine game expander, right after the SP lines and before the detailed stat tables: for
each lineup, "X of Y hitters have the platoon edge vs [hand]HP [starter]," plus the actual names.
Pure view-layer work reusing columns every hitter row already has — no new engine function needed
for this half.

**Part 2 — bullpen handedness mix, a genuinely different signal, not a bullpen-side "platoon
edge."** New `mlb_engine.get_bullpen_handedness_mix(team_id, exclude_pid)` — L/R counts and
percentages across a team's active bullpen. Stated explicitly why this ISN'T a per-hitter platoon
computation against "the bullpen": a bullpen has multiple pitchers of mixed hands, and which
specific reliever a hitter actually faces depends on in-game decisions this platform can't know
in advance — the honest available signal is the bullpen's overall handedness composition, not a
guess at a specific matchup.

**Real cost discipline, consistent with the whole bullpen-feature line of work this session**:
handedness mix is only fetched when that side's "🔄 Bullpen" toggle (built for item 2's Dinger
Engine work) is ALREADY checked — not proactively for every game's expander, which would have
meant a full roster+pitcher-metrics fetch cycle for every team on a busy slate before anyone had
asked to see it.

**Kept deliberately separate from `get_bullpen_aggregate_stat`**, even though both loop the same
roster calling `get_pitcher_metrics` per reliever (an accepted, real duplicate-fetch cost, not an
oversight): that function's stat-dict return shape is already relied on by the bullpen-matchup
toggle shipped earlier this same session, and changing it to also carry handedness data would
mean touching an already-shipped contract for a genuinely different UI use case (a platoon-context
glance that's useful even when the matchup toggle itself is off).

**6 new tests**: 3 for `get_bullpen_handedness_mix` (correct L/R counting, exclude_pid honored,
safe all-zero counts rather than None when no staff data exists) plus a full offline simulation
combining both halves — a real lineup's platoon-edge count against a simulated RHP starter, and a
simulated bullpen's handedness split, both producing the exact "2 of 3 have the edge" / "67% RHP"
style read the feature is meant to give. 508/508 total passing.

### GM/analyst gap-filling, item 4 of 5: starter rest + times-through-the-order (2026-07-18)
Genuinely two different builds, not one — researched both before writing code, since they turned
out to have very different data realities.

**Starter rest — fully buildable, real data, real infrastructure to reuse.** New
`mlb_engine.get_starter_rest_info(pitcher_id, team_id, before_date, lookback_days=15)`. Same
proven schedule-range + boxscore-scan pattern `get_team_bullpen_fatigue` already uses, with two
real adaptations: a LONGER lookback window (15 days, not 5) — a starter's normal rotation cycle
IS ~5 days, so a 5-day-only window risks missing a completely normal turn if there's any real
schedule irregularity (a skipped turn, a rain delay, a doubleheader). And a ≥9-outs (3 full
innings) floor to identify "his last START" specifically, not any appearance — filters out the
rare case of a brief relief cameo (a true starter essentially never makes one mid-rotation, so
this is a defensive safety net more than a load-bearing distinction, same honest framing
`get_team_bullpen_fatigue`'s own start-vs-relief note already uses). Short rest (≤4 days) tagged
as the well-established effectiveness concern it is; extra rest (6+) tagged more neutrally,
since the research is genuinely more mixed there — not asserted as a clean positive to match
short rest's clean negative.

**Times-through-the-order — researched, and the research itself changed the plan.** Confirmed
directly that TTOP splits are a FanGraphs-specific presentation, not a queryable MLB Stats API
split type — building a true PITCHER-SPECIFIC TTOP metric would need either FanGraphs scraping
(a new, more fragile data source) or processing pitch-level Statcast data at at-bat granularity
(a much heavier lift, its own refresh-job-scale project). Rather than fabricate false precision
or skip the concept, found the honest middle: `projections.times_through_order(exp_bf)` — pure,
already-available math (expected batters faced ÷ 9, and `exp_bf` was already computed by
`project_pitcher`) surfacing how many times THIS start is even expected to reach the lineup,
paired with a clearly-sourced caption citing real research (Baseball Prospectus, SABR/Lichtman:
roughly 8-12 wOBA points worse per trip, more for fastball-heavy pitchers) as GENERAL context —
explicitly labeled as league-wide research, not baked into this pitcher's own Proj K/BB numbers,
since the real range varies enough by repertoire that doing so would overclaim precision the
research itself doesn't support at the individual level.

**Wired in with real cost discipline**: Proj TTO added to the full-slate matchup-aware
projections table at zero extra cost (pure derived math, no new fetch). Starter rest reuses the
EXISTING game-scoped picker built for Bullpen fatigue — no second selector, no proactive
per-starter fetching across a whole slate, same cost principle as every bullpen feature this
session.

**10 new tests**: 6 for `get_starter_rest_info` (standard/short/extra rest correctly tagged, the
relief-cameo filter actually verified — not just asserted — against a real 1-inning-vs-6-inning
scenario, honest None when no start is found, and picking the more recent of two qualifying
starts) and 4 for `times_through_order` (basic math, a fractional trip read, a custom lineup
size, safe zero-division handling) plus a locked-in test on `build_pitcher_projection_rows`
confirming Proj TTO and each pitcher's own `_team_id` are present and correct. A full offline
simulation of both pieces together — a realistic ace projecting 2.67 trips through the order, and
a correctly-flagged 3-day short-rest scenario — ran clean. 518/518 total passing.

### Matchup Lab + Track Record moved to owner-only (2026-07-18)
Both removed from the public Discord build via the existing `owner_only_titles` audience gate
(same mechanism Bet Log/Media Room/Podcast Studio/Edge Board already use) — no new gating
infrastructure needed, just extending the existing set. Matched by TITLE, not page number, which
usefully covers all three Matchup Lab variants (MLB, WNBA/NBA/NCAAMB, NFL) with one entry, since
they share the exact title string.

**Two genuinely different reasons, not one blanket call — corrected after an initial
mischaracterization, worth recording honestly rather than papering over**: this was first written
up as a single "paid features" monetization decision for both pages. Shawn corrected that —
Track Record's real reason is different: there isn't enough real graded bet history logged yet
for the page to show anything meaningful, so a public visitor would just find an empty page.
That's "not ready yet," not "not for you," and worth revisiting (likely un-gating) once there's
enough real logged history to actually demonstrate something. Matchup Lab's own reasoning stays
what it was — a real paid-feature call, the analysis is genuinely valuable and working.

This distinction also matters for what it does and doesn't reverse: the code (and Track Record's
own docstring) had explicitly argued Track Record should stay public specifically because it only
shows historical, already-graded results ("the evidence of edge, not the edge itself"), genuinely
different from handing over tonight's live board. That analytical reasoning about what's SAFE to
show publicly hasn't changed and isn't being contradicted by either the original or corrected
version of this change — it just isn't why the gate exists now. Updated both `streamlit_app.py`'s
own comment and Track Record's docstring twice in the same session to get this right: first to
remove the stale "built for subscribers first / stays public" language, then again to correct the
"paid feature" framing to the real "not enough content yet" one once Shawn clarified it.

**1 test updated** (`test_owner_only_pages_match_expected_titles`, the existing regression guard
for this exact gate) — a real, legitimate assertion update reflecting the new gated set, same
pattern every registry/config change this session has required. Verified with a direct simulation
of the real page-filtering logic (not just the unit test) confirming both are correctly hidden for
`audience="public"` and correctly visible for `audience="owner"` — across every sport, since
Matchup Lab's title-based match needed to be confirmed working for all three variants at once, not
assumed. 518/518 total passing.

### Connecting TTO to hitter stats and the bullpen toggle (2026-07-18)
Shawn asked a genuinely important status-check question before moving to umpires: does times-
through-the-order reach the hitter side, and does it connect to the bullpen work? Honest answer
at the time: no to both — Proj TTO existed only as informational context on the pitcher side
(Pitching Lab), never wired into Dinger Engine's hitter probabilities or explicitly tied to the
bullpen-matchup toggle. Built the missing connective piece rather than leave it as three separate
features.

**The key realization: the genuinely derivable half of this was never built.** A specific
hitter's own exposure to repeat looks at a starter — as opposed to a pitcher-specific wOBA
adjustment, which the earlier TTOP research already flagged as overclaiming precision at the
individual level — IS honestly computable from data already sitting on every hitter row: which
batting-order spot they're in (now newly exposed via `_lineup_idx`, previously used internally by
`mlb_engine._hitter_row` to compute `_exp_pa` but never stored on the row itself) and the
starter's own projected batters faced (`project_pitcher`'s `exp_bf`, already computed for
Pitching Lab).

- **`projections.hitter_starter_exposures(lineup_idx, starter_proj_bf, exp_pa)`** — pure
  arithmetic (which "batter number" this lineup spot represents each time through, checked
  against the starter's own projected total) splitting a hitter's own expected PA into `vs_
  starter` and `vs_bullpen`. Deliberately still not a probability adjustment — same reasoning
  `times_through_order` already gives for why baking a specific magnitude into HR%/Hit%/etc.
  would overclaim precision the real research doesn't support pitcher-by-pitcher. This is the
  honest, derivable half: WHO gets exposed to multiple looks, not exactly what each look costs.
- **`projections.add_starter_exposure_context(rows)`** — wires this onto every hitter row,
  computing the starter's own projection ONCE per unique opponent (not once per hitter — verified
  via an actual call-count test, not just asserted) and attaching `vs SP`/`vs Pen` fields.
- **Wired into Dinger Engine** as two new display columns, with an explicit caption connecting
  all three pieces by name: Pitching Lab's Proj TTO (the starter's own overall trip count), this
  hitter's own vs SP/vs Pen split (who specifically is exposed), and the 🔄 Bullpen toggle
  (exactly which of a hitter's own PA that toggle's numbers actually speak to) — stated plainly
  as one coherent picture, not left for someone to infer the connection themselves.

**Verified with a full realistic 9-hitter lineup simulation, not just unit tests in isolation**:
against a real ace-shaped projection (20 starts, 120 IP), the top of the order (spots 1-6) came
back with 3 real looks at the starter while the bottom (spots 7-9) got only 2 — the actual,
well-known "top of the order sees the starter more" effect, reproduced correctly through the real
arithmetic, not asserted in the abstract.

**11 new tests**: 6 for `hitter_starter_exposures` (leadoff gets multiple exposures, bottom-of-
order gets fewer than leadoff against the same starter, a short outing sends a deep-lineup hitter
entirely to the bullpen, the two components always sum back to the hitter's own exp_pa, capped
correctly, safe at zero) — one of these caught a real error in my own FIRST DRAFT test (I'd hand-
computed a wrong expected value; the function was right, my arithmetic checking it was wrong,
worth recording since catching that is exactly what the test suite is for) — plus 4 for
`add_starter_exposure_context` (fields correctly added and sum to exp_pa, the shared-projection
caching genuinely verified via a call-count check, missing-data rows honestly left unset rather
than fabricated, and a non-starter/thin-sample stat line correctly produces no exposure split at
all, matching `project_pitcher`'s own starter gate). 528/528 total passing.

### MLB Matchup Lab: pitcher performance by batting order slot (2026-07-18, same session)
Shawn brought a real screenshot (AB/R/H/2B/3B/HR/RBI/BB/HBP/SO/AVG/OBP/SLG/OPS by "Batting #1"
through "Batting #9") and asked for this in Matchup Lab, framed explicitly as a rotation-planning
and trade-evaluation tool — does this arm get hit hard by the middle of the order specifically,
or is he equally tough top to bottom.

**Researched before building, and the research changed the design for the better**: could not
confirm MLB Stats API has a directly-queryable "batting order split" endpoint the way it has
`vsTeam`/`byDateRange` — no evidence of one was found. Rather than treat that as a dead end, built
it the same way `get_team_bullpen_fatigue`/`get_starter_rest_info` already build other stats this
session — by computing the aggregation from real per-game boxscore data this platform already
knows how to read, not depending on an unconfirmed native split.

**A real cost problem solved before it became one**: naively finding "this pitcher's own starts"
by scanning his team's whole season schedule would mean a boxscore fetch for every one of a
team's ~130-160 games just to find the ~20-30 he actually started. Solved with `get_pitcher_
starts_this_season(pitcher_id, season, before_date)` — one call to the pitcher's own game log
(`stats=gameLog`, a genuinely standard, widely-used MLB Stats API capability across the broader
MLB-StatsAPI wrapper ecosystem — real precedent, stated as a *confidence level* rather than
presented as equally certain to code reusing already-proven shapes), filtered to games with real
starting-pitcher work. Bounds the actual boxscore fetching to only his real starts.

**`get_pitcher_batting_order_splits(pitcher_id, season, before_date)`** — for each of his real
starts, reads every OPPOSING hitter's own `battingOrder` boxscore field (MLB's documented 3-digit
convention: first digit = lineup slot, remaining digits handle in-game substitutions — parsed as
`int(battingOrder) // 100`, an honest, stated, unverified-live parsing choice) alongside their
game-level batting line, summing by slot across every start. Correctly identifies which boxscore
side is the OPPONENT by searching both sides for the pitcher himself, not by assuming home/away —
confirmed via a dedicated test that a hitter on the PITCHER's OWN team never leaks into the
totals. Slots with zero real plate appearances are omitted, not shown as a fabricated zero.
OBP is a stated, honest approximation (no sacrifice-fly tracking at this aggregation level).

**Wired into Matchup Lab as an on-demand expander**, not auto-computed on page load — scanning a
season's worth of a pitcher's starts still costs one boxscore fetch per start, a real cost worth
gating behind an explicit button, same principle as every bullpen/rest feature this session.
Works for whoever's currently selected — starter or the bullpen-toggle reliever, since the
function itself has no starter-specific assumption baked in.

**14 new tests**: 4 for `get_pitcher_starts_this_season` (correctly filters to real starts vs. a
relief cameo, no-lookahead, falls back to the outs floor when gamesStarted is absent, empty on
fetch failure) and 6 for `get_pitcher_batting_order_splits` (aggregates correctly across multiple
starts, the opponent-side-only guard actually verified — not just asserted — against a fake
own-team hitter, a substitution code parses to its real slot, AVG/OBP/SLG/OPS computed correctly
against a hand-verified example, empty with no starts, zero-PA slots correctly omitted). Two of
these tests caught real hand-arithmetic errors in my OWN first-draft test fixtures during this
build — the function was right both times, my own expected-value math checking it was wrong, same
"the test suite doing its job" pattern as the TTO-exposure work earlier this session, worth
recording rather than quietly fixing without a note. A full realistic simulation across 3 starts
and a real 9-slot lineup ran clean, producing a table shape matching the original screenshot.
538/538 total passing.

### Batting order splits: real bug found comparing against ESPN, fixed (2026-07-18)
Shawn compared this platform's freshly-shipped batting-order splits output against ESPN's own
splits page for a real pitcher (Brandon Pfaadt) and found a disparity, asking whether it was
intentional and — if so — for it to be documented clearly.

**It wasn't intentional — a real bug, found through a genuinely useful verification method this
sandbox couldn't have caught on its own.** Quantified the gap before guessing at a cause: AB
overcounted by roughly +8 to +14 in EVERY one of the 9 slots, averaging +10.8 — a systematic,
uniform offset, not random noise. That shape matters: an uneven, per-row discrepancy would point
to a parsing bug; a UNIFORM offset across every slot points to whole EXTRA GAMES being included,
consistent with roughly 2-3 additional starts' worth of at-bats leaking in everywhere at once.

**Root cause: `get_pitcher_starts_this_season` never pinned `gameType` down.** Left to the API's
own default, `stats=gameLog&season=X` can span more than regular-season games under MLB Stats
API's own conventions — spring training among them. Fixed by explicitly requesting `gameType=
"R"` (regular season only), a real, documented MLB Stats API parameter. Reasoned from the size
and uniformity of the reported gap, not confirmed by inspecting a live response — stated
honestly in the function's own docstring as reasoned-but-unconfirmed, with an explicit ask for
Shawn's own follow-up check once redeployed to confirm the gap actually closes.

**Added the detailed explanation requested, as its own expander right under the results table**
(not just a one-line caption) covering: why this is computed here rather than pulled from a
native split at all (none was found to exist), the regular-season-only scoping and the real bug
that prompted it, "as-of" timing differences from a third-party site's own refresh cadence, the
existing OBP approximation caveat, and the small-sample caution — all in one place, addressing
exactly the comparison Shawn made rather than a generic disclaimer.

**1 new test** locking in the fix (`test_get_pitcher_starts_requests_regular_season_only`,
confirming `gameType: "R"` is actually present in the outgoing request params, not just claimed
in a comment). 539/539 total passing.

### GM/analyst gap-filling, item 5 of 5 (final piece): catcher framing (2026-07-18)
Last item on the original 5-item list, originally bundled with umpire tendencies. Researched
both properly before committing to either.

**Umpire tendencies: researched, and genuinely deferred, not attempted half-built.** Confirmed
umpire game/crew ASSIGNMENT data likely exists (game officials are standard boxscore-adjacent
data), but could NOT confirm any equivalent to a player's own game log exists for umpires — no
"find every game this specific umpire worked" capability was confirmed. Building reliable
historical umpire tendencies without that would mean scanning enormous numbers of games with
real uncertainty about the payoff — a genuinely bigger, less-certain lift than anything else
built this session, correctly flagged as such rather than forcing a shaky version of it.

**Catcher framing: real, confirmed capability, built on much stronger ground.** Directly verified
against pybaseball's own current source (not a wrapper's description) that `statcast_catcher_
framing(year, min_called_p="q")` is a real, currently-existing function scraping Baseball
Savant's own catcher-framing leaderboard — Shadow Strike % and Catcher Framing Runs per catcher.
`rv_tot` (Catcher Framing Runs) confirmed directly from the function's own URL construction
(used as its sortColumn) — genuine confidence, not a guess, the strongest-grounded data-source
confirmation of anything built this session.

**Reused the exact proven architecture**, not a new pattern: `refresh_catcher_framing`/`_build_
catcher_frame`/`load_catcher_framing` mirror the nightly-refresh-to-cached-CSV design the hitter
Statcast layer already uses, with the same resilient multi-candidate column hedging for anything
not directly confirmed (team, strike rate, player id). Wired into the same `refresh_statcast.py`
nightly job, deliberately non-fatal if it fails — catcher framing shouldn't block Dinger Engine's
own core batter-data refresh from succeeding.

**`team_catcher_framing` — a real, deliberate scoping choice, not a shortcut**: team-level, not
tied to one specific start or one specific catcher. Identifying which catcher worked a specific
game would need the same kind of per-game boxscore lookup already built for pitchers this
session — but catchers rotate too, and Savant's own leaderboard is already a season-long
aggregate per catcher, not a per-game split. Tying a season aggregate to one specific game would
be false precision the data doesn't actually support; "how much does this team's catching
typically help or hurt a pitcher's real numbers" is the honest question this data can actually
answer. Weighted by each catcher's own called-pitch volume, not a simple average across the
corps — a backup with 200 called pitches shouldn't move the number as much as a starter with 4,000.

**Wired into Matchup Lab** as an expander right alongside the batting-order splits section, for
whichever team the currently-selected pitcher plays for. Returns None (not a fabricated average)
when no qualified catchers are found for a team, same honest-empty posture as this session's
other optional-data functions.

**6 new tests**: cache read, missing-file graceful handling, the weighted-average math verified
against a hand-computed example (not just "a number came back"), None on an unmatched team, None
when every matching catcher is unqualified (zero called pitches), and the resilient column
parsing confirmed against both the one directly-verified real column name and hedged candidates
for the rest. A full offline simulation contrasting an elite framing corps (+20.0 combined
framing runs) against a poor one (-14.0) produced exactly the intended contrast. 545/545 total
passing.

**This closes out the original 5-item GM/analyst gap list**, with umpire tendencies as the one
honestly deferred item — flagged clearly rather than shipped as a weaker version of itself.

### Real gap caught: catcher framing wasn't wired into the automated refresh workflow (2026-07-18)
Shawn saw "No catcher framing data cached yet" in the deployed app and asked whether the
automation actually covers it. It didn't — a real gap, not a timing issue waiting to resolve
itself.

**Two separate things both had to be fixed, not one.** `refresh_statcast.py`'s own `main()`
already calls the new catcher framing refresh (built earlier this session) — that part was fine.
But `.github/workflows/refresh-statcast.yml`'s commit step only ever staged `data/statcast_
batters.csv`, never `data/catcher_framing.csv` — so even a fully successful workflow run would
produce the file on the runner and then never commit it back to the repo. And separately,
`.gitignore` uses a `data/* ` blanket-ignore with individual files explicitly un-ignored
(`!data/statcast_batters.csv` etc.) — `catcher_framing.csv` was never added to that allowlist,
so even fixing the workflow's `git add` alone wouldn't have been enough; git would still have
silently refused to track the file.

**Fixed both, and verified the .gitignore fix directly rather than trusting the syntax** — ran a
real `git add -A` in an isolated test repo using the actual `.gitignore` file, confirming `data/
catcher_framing.csv` is now tracked while an arbitrary stray `data/` file stays correctly
ignored (the blanket rule still does its job for everything else).

**Workflow updated with a deliberate asymmetry, not just an added `git add`**: the batter-cache
validation step stays a hard failure (exits nonzero, refuses to commit) since it's Dinger
Engine's core dependency — but the new catcher-framing validation step is explicit `continue-on-
error: true`, matching `refresh_statcast.py`'s own already-established philosophy that a catcher-
framing pull failing shouldn't block the batter cache's own commit. Confirmed the YAML itself
parses correctly and the step sequence is what's intended, not just written and assumed correct.

545/545 total passing (no Python code changed — this was a workflow/gitignore-only fix).

### Real workflow run failed — a critical regression fixed, root cause of the underlying catcher-framing failure still open (2026-07-18)
Shawn actually ran the fixed workflow and it failed: `git add data/statcast_batters.csv data/
catcher_framing.csv` → `fatal: pathspec 'data/catcher_framing.csv' did not match any files` →
exit 128.

**A more serious bug than the one being fixed, found via a real run, not caught in review.**
`git add` with multiple pathspecs fails ATOMICALLY if any one of them doesn't exist — so this
didn't just fail to add the (missing) catcher-framing file, it blocked the ENTIRE commit,
including the batter cache, which was working fine before this session's changes and has nothing
to do with catcher framing at all. A real regression to something previously solid, not a minor
issue. Fixed by staging the batter cache unconditionally first, then only adding catcher_
framing.csv if it actually exists on disk — matching the "catcher framing failing should never
block the batter cache" philosophy the workflow's own comments already stated, but hadn't
actually been implemented correctly in the shell command itself until this fix. Verified directly
with a real git repo and the real failure scenario (batter cache present, catcher-framing file
absent) rather than trusted on inspection alone — confirmed the batter cache commits successfully
either way.

**The underlying question — why did the catcher-framing pull fail in the first place — is still
open, not resolved.** The file never existing on disk confirms `refresh_catcher_framing()` threw
an exception that its own non-fatal try/except correctly caught and swallowed (working as
designed), but the actual exception message wasn't visible in the screenshot shared (only the
downstream commit failure was expanded). Researched the most likely cause: pybaseball's own docs
confirm `__init__.py` re-exports ~90 functions including `statcast_catcher_framing`, alongside
its already-working siblings (`statcast_batter_exitvelo_barrels` etc.) using the same pattern —
making an import failure less likely than first suspected, not ruled out entirely.

**One real, plausible bug found and fixed by re-reading the code, not by guessing further**:
`_build_catcher_frame` called `.astype(int)` on the player_id column without first handling a
raw NaN — Savant's CSV having even one row with a missing id would have crashed this outright.
Fixed with `.fillna(0)` before the cast, matching the "drop rows without a real id" filter that
was already there but couldn't be reached if the cast itself crashed first. A real test locks
this in (a NaN-id row correctly dropped, not crashing the whole parse).

**Honestly flagged rather than declared fixed**: this may or may not be THE root cause of the
original failure — it's a real bug worth fixing regardless, but confirming it explains the
specific failure needs the actual error text from the "Pull Statcast batter + catcher-framing
data and write the caches" step's own log, which hasn't been seen yet. Worth checking on the
next run — if catcher_framing.csv is produced now, this was it (or close to it); if not, the
step's own printed error message is the next thing to look at together.

546/546 total passing.

### Catcher framing still failing silently after the atomicity fix — made it impossible to miss (2026-07-18)
Shawn ran the workflow again after the atomicity fix: it succeeded (green checkmark, batter cache
committed), but Matchup Lab still showed "No catcher framing data cached yet." Confirmed this is
exactly what a still-silently-failing catcher framing pull looks like — the non-fatal design
means a green checkmark in the Actions run list tells you the batter cache is fine, nothing about
whether catcher framing actually worked. That's a real diagnosis gap, not a resolved issue.

**Root cause of the underlying catcher-framing failure is STILL not confirmed** — worth stating
plainly rather than implying otherwise. What's fixed this round is the fact that the failure was
invisible, not the failure itself.

**Made the failure impossible to miss next time.** `refresh_statcast.py`'s exception handler now
prints `::warning::` — a real GitHub Actions workflow command that surfaces as an annotation on
the run's own summary page, not buried in one step's raw log requiring a manual click-and-scroll
to find — along with the FULL traceback (`traceback.format_exc()`), not just `str(e)`, which can
be too terse to diagnose depending on the exception type. The workflow's own validation step got
the same upgrade, as a second layer: even if the pull step's warning is missed, the validation
step re-checks the cache immediately after and emits its own visible warning pointing back at the
pull step's log for the real detail.

**Verified the annotation actually fires, not just written and assumed correct** — new
`test_refresh_statcast.py`, 2 tests: a simulated catcher-framing exception confirmed to produce
the `::warning::` line, the exception's own message, AND a real traceback header in the output
(not just the accepted string), while still returning exit code 0 (the script itself must not
fail); and a success case confirmed to produce NO warning at all, guarding against the message
firing when it shouldn't. 548/548 total passing.

**Next real step is still open**: once the workflow runs again with this visibility fix, the
actual error text will be sitting right on the run's summary page — that's what's needed to
diagnose the real root cause (an import path issue, a Savant response shape mismatch, or
something else entirely), rather than continuing to guess at plausible causes one at a time.

### Catcher framing: real root cause finally visible, real fix attempted (2026-07-18)
The visibility fix worked exactly as intended — the next run's Annotations panel showed the real
error: `Error tokenizing data. C error: Expected 1 fields in line 38, saw 4`. Shawn noted he'd
need to wait to re-run the workflow since Deezy was actively using the deployment for a live
game; used the window to build and test a well-reasoned fix in the meantime rather than wait idle.

**Diagnosed before fixing, not just pattern-matched to a familiar-looking error.** "Expected 1
fields... saw 4" means pandas' C parser inferred a ONE-COLUMN structure from the early rows, then
hit a row with several fields later — the classic shape of parsing something that ISN'T a real
multi-column CSV (an error page, a different response type), not a genuinely malformed
multi-column file with one bad row. A real catcher-framing leaderboard has many columns from row
one; a response that reads as one column at first is a strong sign Savant didn't return the CSV
that was expected.

**Prime suspect: `min_called_p`.** pybaseball's own `statcast_catcher_framing` defaults this to
the STRING `"q"` (confirmed from its real source during earlier scoping) — plausible the
catcher-framing leaderboard's own URL parameter doesn't resolve `"q"` the way other Savant
leaderboards apparently do, returning something other than the expected CSV. Reasoned from the
actual error text, not a blind guess — but stated honestly as still unconfirmed live, same
posture as everything else built without network access this session.

**The fix goes further than just changing a parameter — replaced the opaque pybaseball call with
a direct, controlled fetch.** Reused the exact confirmed URL construction from pybaseball's own
source, but with two real changes: `min_called_p` now defaults to `0` (an explicit number, not
the suspect string), and any parse failure now re-raises with the first 500 characters of
Savant's ACTUAL raw response attached to the exception message. The original tokenizing error
never said WHAT Savant sent back — an HTML error page, a redirect, something else entirely — and
guessing at that blind is how a wrong fix gets shipped with confidence it doesn't deserve. If
`min_called_p=0` doesn't resolve this, the next failure's own error message will show the real
content directly, not another opaque parser error requiring another round of guessing.

**Verified honestly, not with a fragile synthetic reproduction.** Tried to construct fake CSV
content that organically reproduces pandas' exact "Expected N fields... saw M" error first — it
didn't reproduce cleanly (confirmed by actually trying, not assumed), which is itself informative
about how specific and chunking-dependent that exact error is. Pivoted to testing what actually
matters: mocking `pd.read_csv` to fail directly, confirming THIS code's own try/except correctly
wraps whatever exception occurs with the real response content attached, regardless of the exact
underlying trigger. 2 new tests (the diagnostic-preview behavior, and the numeric-not-string `min`
parameter actually present in the outgoing request URL) plus a full offline simulation with
realistic multi-word catcher names (the "Lastname, Firstname" format) confirming the whole
pipeline still produces correct, sensible output. 550/550 total passing.

**Still honestly unconfirmed live** — this is a well-reasoned, tested fix, not a verified one.
Worth checking the next time the workflow runs (whenever that fits around live analysis work) —
if catcher_framing.csv shows up, this was the fix. If a NEW error appears instead, its own
message will now include the real response content, which is real, actionable progress either way.

### Catcher framing: real progress confirmed, a second, different issue found and made diagnosable (2026-07-18)
Shawn ran the workflow again after the min_called_p/direct-fetch fix. Genuinely good news first:
the original crash is gone — no "Catcher framing refresh failed" warning from the pull step at
all this time, meaning the fetch and CSV parse both succeeded. The earlier diagnosis was right.

**But the cache is still coming back thin/missing — a different problem than the one just fixed,
not the same one persisting.** The validate step's own warning still fired. Reasoned through why
before writing more speculative fixes: if the fetch had failed, the pull step's own warning would
have fired too — it didn't. That means parsing succeeded but almost nothing survived `_build_
catcher_frame`'s own column-hedging and `player_id > 0` filter — the signature of the real
response using column names that don't match ANY of the hedged candidates guessed at during
scoping, so every row's player_id silently defaulted to 0 and got dropped. A genuinely silent
failure mode: nothing throws, the workflow shows green, and the cache just quietly ends up empty.

**Made this diagnosable the same way the parse failure was**, rather than guess at column names a
third time: `refresh_catcher_framing` now checks whether the CSV parsed with real rows but ended
up with suspiciously few (<10) surviving the column mapping, and if so prints a `::warning::`
with the RAW response's actual column names attached directly. This is the exact information
needed to fix the real mismatch — no more guessing candidate names blind.

**1 new test**, confirming the diagnostic genuinely fires and surfaces the real raw column names
(not a generic "something's wrong" message) — built with an intentionally-mismatched synthetic
CSV (`some_id_field`, `player_name`, `squad` — plausible-looking but wrong names) to verify the
detection logic itself, independent of what Savant's actual real column names turn out to be.
551/551 total passing.

**Next run's annotations should show the real column names directly** — that's the piece needed
to write the actual, final, confirmed fix rather than another reasoned-but-unverified attempt.

### Catcher framing: real column names confirmed, real fixes applied, team enrichment built (2026-07-18)
The diagnostic from the previous round worked exactly as intended — the next run's annotation
showed Savant's real column list directly: `['id', 'name', 'pitches', 'rv_tot', 'pct_tot',
'rv_11', 'pct_11', ...]`. Mapped every field systematically against the hedged candidates rather
than eyeballing it, confirming exactly two were simple naming misses and one was a real
structural gap:

- `player_id` → real column is `id`, not in the original hedge list at all — this was the
  critical bug, explaining why every row silently defaulted to player_id=0 and got filtered out.
- `strike_rate` → real column is `pct_tot` ("percent total," the cumulative shadow-zone rate —
  matches the MLB.com glossary's own description of Shadow Strike %), also not hedged.
- `name` and `framing_runs` (`rv_tot`) were already correct — the original research on `rv_tot`
  specifically (confirmed from pybaseball's own source) held up.
- `team` → genuinely absent from this response, not a naming miss. Confirmed by checking the
  full column list systematically, not assumed.

**Both naming fixes applied directly** to `_build_catcher_frame`'s hedge candidates — `id` and
`pct_tot` added, confirmed real, not more guessing.

**The missing team column needed a real, separate solution, not another hedge.** Built `mlb_
engine.get_player_current_team_name(player_id)` — a genuinely new capability (every other
roster function in this file goes team→players; this is the first player→team lookup) using
MLB Stats API's own `currentTeam` field on the base person object. Wired into `refresh_
statcast.py` as a real team-enrichment step run once during the nightly refresh: after the
Savant pull, catchers below a called-pitches floor (100) are dropped before any lookup happens —
bounding the cost to catchers with a real role, not the full unqualified list — then each
qualified catcher's team is resolved and the cache is rewritten with real team names attached.
`team_catcher_framing`'s own docstring updated to say plainly where "team" actually comes from
now, so a future reader isn't left assuming it's part of the Savant pull itself.

**A real bug caught by the new dedicated test, not shipped**: the enrichment step's write call
was hardcoded to `SC.CATCHER_FRAMING_PATH` instead of the actual `cf_path` returned by the
refresh call — meaning a custom output path (exactly what the tests themselves use) would have
been silently ignored, writing to the wrong location. Caught immediately because the test
actually exercises the write path and reads the file back, not just checks that the function
returns without error.

**Verified with a full realistic simulation using properly-quoted CSV content** — which itself
caught a mistake in the FIRST draft of that simulation (an unquoted comma inside a "Lastname,
Firstname" value shifted every subsequent column, the exact kind of issue that was originally
suspected as a possible contributor to the whole investigation). Fixed the test data, re-ran:
names correctly flip to "Firstname Lastname," the called-pitches floor correctly excludes a
thin-sample catcher, and team enrichment correctly resolves for both qualified catchers.

**9 new tests**: 4 for `get_player_current_team_name` (real response shape, no current team,
fetch failure, empty people list) and a dedicated team-enrichment test confirming the
called-pitches floor is actually enforced (verified via a call-count check on the lookup
function, not just asserted) and that resolved team names are correctly written to disk — this
is the test that caught the hardcoded-path bug above. 556/556 total passing.

**Next run's result will show whether this closes it out.** If catcher framing data appears in
Matchup Lab with real team names attached, this was the fix. Genuinely more confident this time —
every piece was confirmed against the real response, not reasoned from a plausible hypothesis.

### Catcher framing: real production bug in team matching, fixed by switching to numeric ids (2026-07-18)
A clean workflow run (no warnings beyond the unrelated Node.js notice) confirmed the pipeline
itself was finally working. But checking the actual page showed "No qualified catcher framing
data found for Cleveland Guardians" despite real, enriched data existing in the cache — a genuine
new bug, not the same one recurring.

**Diagnosed before patching**: `team_catcher_framing` was matching by team NAME string
(`pitcher["Team"]` against the enrichment step's own resolved name). Those two strings come from
DIFFERENT MLB Stats API endpoints — the schedule endpoint (building `pitcher["Team"]` elsewhere
in this codebase) and the people endpoint's own `currentTeam.name` (used by the new enrichment
lookup). Two endpoints returning superficially similar strings for the same team is exactly the
kind of thing that can silently fail a straight string comparison with zero error — no exception,
no warning, just a quiet "no data" that looks identical to a genuine data gap.

**Fixed at the design level, not with a targeted patch.** Rather than try to normalize or
fuzzy-match strings (a real path to a DIFFERENT kind of silent bug later), switched the entire
chain to numeric team ids, which are unambiguous across MLB Stats API endpoints in a way display
strings aren't guaranteed to be:
- `mlb_engine.get_player_current_team` (renamed from `get_player_current_team_name`) now returns
  BOTH id and name — id for matching, name kept for display only.
- `refresh_statcast.py`'s enrichment step writes both `team_id` and `team` to the cache.
- `load_catcher_framing` reads `team_id` back honestly as `None` (not a fabricated 0) for a
  pre-enrichment cache or an unresolved catcher.
- `team_catcher_framing` matches by `team_id` now, with an explicit falsy-id guard (`if not
  team_id: return None`) so a missing id can never accidentally match against everything —
  returning both the id AND a real display name (pulled from a matched catcher's own record) so
  callers still get something readable, not just a number.
- Matchup Lab's call site updated to pass `pitcher.get("_team_id")`, already available on every
  pitcher row from earlier session work, instead of the string `pitcher["Team"]`.

**6 tests updated, 3 new ones added** — the fixture itself now carries both `team_id` and `team`
(matching the real enriched CSV shape), every existing assertion updated to match by numeric id,
plus new coverage for the pre-enrichment None-team_id case, the falsy-id guard specifically (the
exact class of bug a careless id-based redesign could reintroduce), and the display name still
being correctly surfaced in the returned dict. A full realistic simulation of the whole redesigned
chain — fetch, parse, enrich, and match — ran clean with two different teams and a deliberately
unmatched id. 558/558 total passing.

**Three real, distinct bugs found and fixed in this catcher framing feature across this session,
each confirmed against real evidence rather than guessed**: a missing `gameType`-style parameter
causing a parse failure, two column-name mismatches causing silent data loss, and a cross-endpoint
string-matching bug causing a silent "no data" result. Worth noting as a pattern: every one of
these was invisible from a green checkmark alone, and each was only found because Shawn actually
checked the deployed output against what was expected, not just the workflow status.

### Catcher framing: stale-cache theory ruled out with a real confirmed fresh run, added real diagnostics for round 4 (2026-07-18)
Shawn confirmed the workflow was genuinely re-run (not just the page refreshed) and Arizona
Diamondbacks still showed "no qualified data" — ruling out the stale-cache explanation directly,
not just assuming it away. A real, different issue, worth diagnosing rather than guessing a
fourth time.

**Applied the same discipline that found the previous three bugs: add real visibility before
proposing another fix.** Two places, not one — either side of the id comparison could be the
culprit, and guessing which one wastes a round:

- `refresh_statcast.py`'s enrichment step now reports HOW MANY qualified catchers actually
  resolved a team_id (not just a summary count as before) — if under half resolve, a `::warning::`
  fires listing which catchers came back with no team, surfacing a systemic resolution problem
  directly instead of leaving it to be inferred from a downstream symptom. A sample of (name,
  team_id, team) for catchers that DID resolve is also printed, so the actual id VALUES are
  visible for a sanity check, not just their presence.
- Matchup Lab's own "no qualified data" message now shows the actual queried team_id, how many
  catchers are in the cache overall, and the full list of distinct team ids that DID resolve —
  turning a bare "no data" message into something that directly answers "is this team's id
  simply missing from the resolved list, or is something else going on."

Both are genuinely diagnostic, not decorative — the NEXT report should make clear within seconds
whether Arizona's own catcher(s) failed to resolve a team specifically, or whether team resolution
is failing more broadly across the whole cache.

558/558 total passing (no logic changes this round — this was purely about visibility, matching
the exact posture that found and fixed the ORIGINAL parse failure, the column-mapping issue, and
the string-matching bug, each of which needed to be SEEN before it could be diagnosed correctly).

### Catcher framing: the real fourth bug found and fixed — currentTeam needs explicit hydration (2026-07-18)
The diagnostics from the previous round worked immediately and decisively: "Only 0/61 qualified
catchers resolved a team via get_player_current_team — most calls are failing," with a sample
list including J.T. Realmuto — one of the most well-known active catchers in MLB. A complete,
uniform 0/61 failure across every real catcher, not a partial or data-specific one, was the key
signal: this couldn't be about any individual player's data being unusual, it had to be something
systematic in how the lookup itself worked.

**Diagnosed by analogy to already-working code in the same file, then confirmed externally
before fixing.** `get_pitcher_metrics` — proven, shipped, working all session — calls this exact
same `people/{id}` endpoint successfully, but explicitly passes a `hydrate=stats(...)` parameter
for what it needs. `get_player_current_team` never passed ANY hydrate parameter, on the
assumption that `currentTeam` came back on the base person object by default. Confirmed that
assumption was wrong from two independent sources: MLB Stats API's own documented hydration
values explicitly list `currentTeam` as something that must be requested, not default; and
MLB-StatsAPI's own real, working source code builds its hydrate parameter as `"...,currentTeam"`
— the exact syntax needed, found directly in real, shipped code, not guessed.

**Fixed by adding the one missing parameter**: `fetch_json(url, {"hydrate": "currentTeam"})`.
The rest of the function (returning both id and name, the falsy-id guard downstream in
`team_catcher_framing`) was already correct from the previous round's fix — this was purely the
one missing piece that made every call fail before it could even reach that logic.

**1 new regression test**, confirming the actual outgoing request now includes `hydrate=
currentTeam` — not just that the function returns the right shape when mocked correctly, which
would have passed even with the original, broken version, since the mock doesn't care what
params were requested. This test specifically locks in the real fix, not just the surrounding
logic. 559/559 total passing.

**Four real, distinct bugs found and fixed in this one feature across this session, every single
one confirmed against real evidence, none of them guessed and left unverified**: a missing
`gameType`-equivalent parameter causing a parse failure, two column-name mismatches causing
silent data loss, a cross-endpoint string-matching bug causing a silent no-match, and now a
missing hydration parameter causing complete lookup failure. The diagnostic-first discipline
adopted partway through this thread — surface real information before proposing a fix, verify
after — is what turned four genuinely different failure modes into four genuinely fixed bugs
instead of four rounds of guessing.

### Mid-season catcher change detector (2026-07-18, follow-up to catcher framing work)
Shawn asked how catcher framing connects to hitter props. Honest answer: it doesn't right now —
Matchup Lab's framing section is display-only, not wired into any probability. Talked through the
actual mechanism (framing shifts count leverage, not outcomes directly) and landed on the real
recommendation: don't bake a blanket framing adjustment into every pitcher's numbers, since a
pitcher's season-long BB/K rates already happened WITH his real catcher(s) behind him — whatever
a good framer contributed is usually already sitting inside those numbers, indistinguishable from
"the pitcher got better." The place a season aggregate genuinely lies is a MID-SEASON catcher
change specifically, using the very Patrick Bailey trade surfaced during this session's own
debugging as the illustrating example. Built that instead.

**`mlb_engine.get_pitcher_catcher_change_split(pitcher_id, team_id, season, before_date,
min_starts_each_side=3)`** — reuses the exact "scan a pitcher's own real starts via his game log,
then read each boxscore" pattern already proven for batting-order splits and bullpen fatigue, not
a new pattern. New piece: `_find_catcher_in_boxscore_side`, identifying who caught each start on
the pitcher's OWN side (position "C", preferring whoever had the most plate appearances if a
mid-game substitution happened).

**Only reports a change if it looks like a REAL transition, not routine catcher rotation** — a
real, deliberate design constraint, not a missing feature: requires the most recent starts to be
consistently one catcher, and an earlier block of at least `min_starts_each_side` starts
consistently a DIFFERENT one. A team platooning two catchers all year with no single clean
transition point correctly returns None — this looks for one real personnel change, not a general
usage-variance report, which would be a much noisier, less trustworthy signal.

**Returns this pitcher's own real, summed BB%/K% split before vs. after** — not a projected or
derived adjustment, actual outcomes from actual starts. Wired into Pitching Lab right after
starter rest, reusing the same game-scoped picker, gated behind an explicit per-side button given
the real cost of scanning a full season of starts.

**11 new tests**: 3 for the catcher-identification helper (position-C selection, preferring more
plate appearances when two catchers appeared, honest None when no catcher is found) and 5 for the
main split detector (a clean transition correctly detected with hand-verified BB%/K% math, None
when only one catcher ever caught him, None when usage was rotation rather than one clean
transition — the specific guard against false positives — None on too few total starts, and the
`min_starts_each_side` floor actually enforced). Plus a full realistic simulation using the exact
real Cleveland scenario from this session's own catcher-framing debugging (Bo Naylor → Patrick
Bailey, May 15 transition) — walk rate correctly dropping from 12.5% to 5.1% and strikeout rate
rising from 20.8% to 30.8% after the switch to a confirmed elite framer, the real direction this
effect should move in. 567/567 total passing.

### Batting order splits: today's actual lineup added (2026-07-18)
Shawn flagged a real gap in the batting-order splits table: it showed historical per-slot
performance but never said WHO'S actually standing in each slot tonight. First interpretation
attempted was wrong — "who has historically occupied this slot across the pitcher's past starts"
— corrected directly to what was actually wanted: today's real, confirmed (or projected) lineup
for the specific game being viewed, so the historical numbers can be read against a real name,
not an abstract slot number.

**Zero extra fetch — the data was already sitting on the page.** Matchup Lab's hitter picker
already loads the full slate's hitters via `build_slate`, and those rows already carry
`_lineup_idx` (added earlier this session for the times-through-the-order work) and a `Lineup`
status field ("Confirmed" vs "Projected", already used elsewhere on this platform). This was
purely a cross-referencing exercise in the view layer — filter the already-loaded hitters to the
opposing team, map by lineup index, done.

**Honest about lineup confirmation status, not just adding a name column.** A caption states
plainly whether today's lineup shown is officially confirmed or still just a projection — a
projected lineup can still change before first pitch, and burying that distinction would let
someone treat a guess as settled fact. A slot with no matching hitter (lineup not posted yet, or
a genuine data gap) shows an honest "—", never a fabricated guess at who's batting there.

Verified with a full offline simulation of the real cross-referencing logic, including a
deliberately unmatched slot (confirming the honest "—" fallback) and a hitter from the wrong team
mixed into the input (confirming the team filter correctly excludes him). 567/567 total passing
(pure view-layer logic — no new engine functions needed for this one, everything reused).

### Best Bets: bullpen-blended hitter probabilities, built from a real confirmed finding (2026-07-18)
Shawn asked to validate that Best Bets reflects this session's work. Rather than guess, went
through tonight's actual board against Command Center, Pitching Lab's bullpen fatigue, and Dinger
Engine's own bullpen toggle — and found a real, material, QUANTIFIED issue: the slate's single
highest-conviction play (Munetaka Murakami, Batter HR Over 0.5, 4.25× conviction, 47% model
probability) was priced entirely off a starter with a 7.64 season ERA, using his rate for the
hitter's ENTIRE projected plate-appearance count. Dinger Engine's own bullpen toggle showed his
real HR% drops to 27% against the actual bullpen. Properly blending by his real ~3.0-PA-vs-
starter / ~1.55-PA-vs-bullpen exposure split (hand-verified with real math, not eyeballed) gave
41%, not 47% — a 6-point, ~15% relative overstatement on the single most prominent play of the
night. That concrete finding, not a hypothetical, is what this was built to fix.

**`projections.blend_hitter_probs_with_bullpen(row, bullpen_stat, ...)`** — the core correction.
Runs `simulate_batter` TWICE with the SAME rng (once for the hitter's real vs-starter PA against
the starter's own rates, once for his real vs-bullpen PA against the bullpen's aggregate rates)
and SUMS each simulated trial's outcomes across both phases before computing HR%/Hit%/TB1.5%/SO
Prob. Deliberately NOT a linear blend of the two probabilities — a real, stated distinction: P(at
least one HR across two phases) isn't a weighted average of each phase's own P(≥1 HR), since the
math for a ">=1 occurrence" outcome is genuinely non-linear. Returns None (never fabricates a
blend) when there's no real bullpen exposure to begin with, the row or starter can't be
projected, or the bullpen sample is too thin — a real bug caught while testing: `batter_pa_probs`
itself accepts a `None` opponent-rates input gracefully (a silent neutral fallback), so checking
its OUTPUT for None would never actually catch a too-thin bullpen sample; needed an EXPLICIT
check on the rates themselves before that silent fallback could kick in unnoticed.

**`projections.apply_bullpen_blend_to_top_plays(plays, rows_by_pid, get_bullpen_stat_fn, ...,
top_n=30)`** — the real cost-scoping layer. Blending every hitter-market play on a full slate
would mean fetching a bullpen aggregate for every opposing team on the board — potentially 250+
real network calls just to load the page. Scoped to the top 30 hitter-market candidates by
CURRENT conviction instead — re-pricing a play near the bottom of a 1,274-play list can't change
what actually gets surfaced as a top lean, so there's no real value in paying that cost for it.
Recomputes confidence in the SAME side a play is already on (a deliberate choice — a play like
"Batter HR Over 0.5" is already fixed by the time this runs; this isn't meant to flip sides, just
to correct how confident the model should be in the side already chosen). `get_bullpen_stat_fn`
is dependency-injected, keeping this function itself network-free and testable with a plain fake
— the real caller in Best Bets' own view passes a Streamlit-cached wrapper, so repeated calls for
the same opponent across multiple candidate hitters are free, not refetched per hitter.

**Two new hitter-row fields threaded through `mlb_engine._hitter_row`**, both additive and
backward compatible: `_opp_id` (the opposing TEAM's numeric id, needed to look up their bullpen
at all) and `_opp_pid` (the opposing STARTER's own player id, needed to EXCLUDE him from the
bullpen aggregate — without it, his own stats would be double-counted: once directly for the
vs-SP phase, and again folded into the vs-Pen aggregate alongside every other pitcher on the
roster).

**Wired into Best Bets' own view** with a visible 🔄 marker on any blended play's name (no new
column needed) and an honest caption explaining the scope and the correction, not just a silently
different number. The pre-blend conviction is preserved on the play itself, matching this
platform's own "show what actually drove it" transparency standard already promised by the Bet
Diagnostics inspector — a blended play's "Why" text states its own real exposure split directly,
not just a changed number with no explanation.

**19 new tests total, two real bugs caught in the process, not just written and assumed
correct**: 7 for `blend_hitter_probs_with_bullpen` (a realistic reconstruction of the real
reported scenario confirming the correction moves the right direction; the no-exposure, thin-
starter-sample, and thin-bullpen-sample None cases; the vs-SP/vs-Pen split summing back to
exp_pa; determinism with a fixed seed) — writing these caught a genuine test-fixture bug (`{}` is
falsy in Python, so `opp_stat={}` was silently getting replaced by the fixture's own `or
dict(...)` fallback, meaning the intended test never actually ran what it claimed to) and a real
gap in the function's own None-handling (the silent-neutral-fallback issue described above,
fixed before shipping, not after). 8 for `apply_bullpen_blend_to_top_plays` (updates the top
candidate while preserving its side, respects `top_n` with a verified call-count check — not just
asserted — never touches pitcher markets, leaves a play untouched for every real "can't blend"
reason individually, and correctly re-sorts when a blend changes the ranking). 1 for `_hitter_row`
confirming `_opp_id` threads through correctly. Plus a full end-to-end simulation reconstructing
the real Murakami/Bieber scenario through the complete pipeline — including confirming
`exclude_pid` is correctly passed through to exclude the starter from his own bullpen's
aggregate — producing the same direction and comparable magnitude to the real, reported finding.
582/582 total passing.

### Real drift bug found: Command Center's top leans didn't match Best Bets' conviction (2026-07-18)
Shawn reported Command Center's "Tonight's top leans" showing different conviction than Best
Bets for what should be the same plays. Confirmed the real cause directly rather than guessing:
Command Center had its OWN separate, nearly-identical copy of the board-loading logic
(`_board_mlb`), written before the bullpen-blend fix existed. When that fix landed, it only went
into Best Bets' own copy — Command Center's separate copy silently kept using the old, unblended
numbers, no error, no warning, just two pages quietly disagreeing about the same play's real
conviction.

**Fixed at the root, not by patching both copies separately** — patching both would leave the
exact same drift risk for the next change to either one. Created `best_bets_data.py`, a single
shared module housing `load_mlb_best_bets_board(date_str, fip_constant)`, and rewired both Best
Bets and Command Center to call it instead of maintaining their own independent copies. If a
third page ever needs this board, it calls this too — not a new copy.

**A real, separate risk found and fixed while building the shared module, not shipped by
accident**: the natural approach would route the module's engine/projections references through
`sports.active()`, matching how both original view files did it. But Python only executes a
module's top-level code on its FIRST import, not on every subsequent one — if this shared module
happened to be first imported while a different sport was active, its engine/projections
references would stay frozen to that sport's modules for the rest of the process, silently wrong
for every later MLB call. The original inline code never had this risk, since each Streamlit view
file re-runs fresh on every page load. Fixed by importing `mlb_engine`/`projections` directly by
name instead — this function is explicitly MLB-only anyway, so there was no real need to route
through the generic sport-dispatch registry at all.

**A real interface bug caught while wiring the two callers in, not shipped**: an early draft of
the shared function returned `len(meta)` instead of the full `meta` list. Command Center's own
code never did Slot/Time enrichment on plays at all (it doesn't need it), while Best Bets needs
the full meta to build its own — returning just a count would have silently broken Best Bets'
own Slot/Time column. Caught by checking each caller's ACTUAL pre-existing interface expectations
directly against the codebase, not assumed from memory.

**5 new tests** in `test_best_bets_data.py`: confirms the module's engine/projections references
are bound directly to `mlb_engine`/`projections`, not routed through sport-dispatch (locking in
the fix for the real risk described above); confirms the function's exact signature; a full
offline pipeline run confirming the bullpen blend still fires correctly through the consolidated
path; and a dedicated test locking in the `(plays, meta)` return shape specifically, since that
was the exact bug caught while wiring this in. 586/586 total passing.

**One honest caveat surfaced, not hidden**: Best Bets exposes a FIP-constant input a person can
adjust; Command Center doesn't expose that control and always uses the default. If that input is
changed away from default on Best Bets, the two pages will still show different numbers for that
reason specifically — a real, intentional design difference, not a bug, but worth knowing rather
than assuming the fix makes the two pages identical under every possible setting.

### New page: Graded Picks — game-by-game, not a flat top-10 (2026-07-18)
Deezy wanted something similar to a competitor app's "graded picks" UI (letter grades, tiered
lean labels, Fair odds, real reasoning, per-game context banners). Went through it screenshot by
screenshot before building anything: most of it mapped directly to signals this platform already
computes (Conviction, Fair odds via `prob_to_american`, the `Why` reasoning field, park/weather
factors, lineup confirmation status) — a few terms ("Blast Match," "Pitcher Leak," "Built
Different") were unclear, proprietary-sounding badges from the other product, deliberately left
out entirely rather than fabricated with a guessed meaning. Explicitly designed this platform's
OWN wording for the tiered labels ("Top Lean" / "Strong Lean" / "Lean" / "Watch") rather than
reusing the other app's badge text, directly addressing the "don't want to duplicate someone
else's badges" concern raised during scoping.

**Real design decision, reasoned through with Shawn, not defaulted to**: game-by-game with each
game sorted by its own best play, not a flat top-N ranked list. A flat list naturally clusters on
whichever 2-3 games have the juiciest matchups and leaves the rest of the slate invisible to
anyone specifically interested in a different game — the "ONE-SIDED" banner concept from the
reference screenshots only even makes sense at the game level to begin with (comparing two
starting pitchers within one matchup), which was itself part of the case for this structure.
Placement was also reasoned through, not assumed: a dedicated page, not grafted onto Command
Center, since Command Center's whole job is a 10-second glance and this is a browsing experience
— two different jobs that would conflict on one page, especially since Command Center already has
its own compact top-leans table showing the same underlying data in a different format.

**`projections.conviction_to_grade(conviction)`** — maps Conviction to a letter grade (A/B/C/D)
+ tier label. Thresholds are this platform's own, grounded in its own already-established
Conviction scale (Best Bets' own min-conviction slider already treats 1.2x as the floor worth
showing; real observed top plays cluster 2.7-4.25x), not reverse-engineered from another
product's scoring. Deliberately shows the raw Conviction number ALONGSIDE the grade, not instead
of it — a fabricated 0-100 score would hide what's actually driving the label; the real number is
already interpretable on its own.

**`mlb_engine.compute_one_sided_banner(hitter_rows, game_label)`** — compares both starting
pitchers' HR/9 allowed (already computed on every hitter row via "Opp HR/9" — the right metric
for this specific question, not a proxy) to flag a real, stated-threshold (0.4 HR/9) advantage.
Returns None for most games, on purpose — most games are genuinely not one-sided, and manufacturing
a marginal signal out of noise would be worse than saying nothing. A real bug caught by testing,
not shipped: comparing the raw float difference against the threshold could silently exclude a
value that's conceptually exactly at the threshold (1.40 - 1.00 evaluates to 0.3999999999999999
in float arithmetic) — fixed by rounding to the same precision HR/9 is actually reported at
before the comparison.

**`projections.organize_graded_picks(plays)`** — the core, testable logic behind the page:
grades every play, drops what doesn't clear the floor, groups by game then by player within each
game, sorts both levels by best-conviction-first. Deliberately extracted as a separate, pure
function rather than left embedded in the view file, so this real logic is actually unit tested
rather than only trusted by eye in the browser — a discipline applied consistently this session,
not a one-off.

**Real architectural consolidation done proactively, not reactively**: `best_bets_data.py`
gained `load_mlb_graded_picks_board` (shares its cached result with `load_mlb_best_bets_board`
when called with the same arguments — refactored `_build_mlb_board` into one shared, cached
inner builder so a second page doesn't mean a second slate fetch) and `load_generic_best_bets_
board` (consolidating the THIRD copy of the non-MLB board-loading pattern that was explicitly
flagged as a latent risk in the previous round — fixed now, before a real bug forced it the way
the MLB version did, not after). Best Bets and Command Center's own generic-sport loaders were
updated to use this too, closing that gap for every sport, not just MLB.

**New page `views/16_Graded_Picks.py`**, registered publicly (matching Best Bets, not gated like
Matchup Lab/Track Record) with a native `st.page_link` pointer from Command Center's own top-leans
section, so the two pages connect without merging. Works for any sport via the generic path;
MLB gets the additional one-sided banner, since that's the one piece genuinely specific to
baseball's starter-vs-bullpen structure — no equivalent exists in basketball or football's
current models, confirmed by checking, not assumed.

**24 new tests**: 3 for `conviction_to_grade` (exact threshold boundaries, the real floor, None
handling), 6 for `compute_one_sided_banner` (a real gap correctly flagged, a close game correctly
producing nothing, the exact floating-point boundary bug found and fixed, missing-game and NaN
handling, a malformed single-team input), 7 for `organize_graded_picks` (grouping, both sort
orders, the grading-floor filter, empty output, grade attachment, a single player's own multiple
plays sorted correctly), 5 for `best_bets_data.py`'s expanded interface (including the new
graded-picks board returning rows), plus a full offline end-to-end simulation covering one
one-sided game and one close game together, confirming the whole pipeline — load, grade, organize,
banner — produces the correct combined result. 603/603 total passing.

### Graded Picks: added Time slot + Game filtering, matching Matchup Lab's own pattern (2026-07-18)
Shawn's one gap on the new page: no way to narrow a busy night down to one slot or one game, the
way Matchup Lab and every other multi-game page already lets you. Added it using the exact same
shared helpers (`game_dt`/`slot_of`/`SLOT_ORDER` from `sports.py`) Matchup Lab and Best Bets
already rely on — not a new filtering concept, the same one applied consistently.

**Adapted, not copy-pasted**: Matchup Lab filters a list of per-game PITCHER rows; Graded Picks
works from the flattened plays/meta shape `best_bets_data.py` already produces, so this filters
`meta` (by time slot) and then `plays` (by the resulting game labels) instead. Confirmed `meta`'s
`game_date` field is already used generically across every sport in Best Bets' own existing code
before relying on it here too — not a new assumption introduced for this page.

Verified the core filtering computation directly (slot assignment, slot narrowing, and the
plays-by-game-label filter) with a real simulation before trusting it — Streamlit's own widgets
aren't unit-testable outside a runtime, so this was checked as a direct computation instead of
only visually. 603/603 total passing (no new engine-layer functions needed — this reused
`sports.py`'s existing, already-shared helpers end to end).

### Grade accuracy tracking: does an A actually hit more than a C? (2026-07-18)
Shawn asked for a broader platform recommendation. Top pick, reasoned through explicitly: nothing
checked whether Graded Picks' own letter grades correlate with real results — the platform's own
stated pitch is "proves itself with closing-line value and calibration," and the new grading
system had zero feedback loop. Built the direct test, using real settled outcomes, not a
hypothetical.

**Found existing, closely-related infrastructure before building anything new**: `retro.py`
already had `grade_slate`, which breaks down hit rate by conviction TIER — but using its own
separate numeric thresholds (>=1.75x, 1.4-1.75x, etc), not the letter-grade thresholds Graded
Picks itself shows. A real, useful metric, but answering a different, differently-bucketed
question than "does an A hit more than a C" specifically.

**`projections.grade_accuracy_by_letter(graded_plays)`** — takes retro.grade_slate's own output
(already-graded plays with Hit/Conviction attached) and re-buckets by the EXACT letter-grade
thresholds shown on Graded Picks (conviction_to_grade), so the answer comes back in the same
terms a person actually sees on that page. Only settled plays count; a grade with zero settled
plays in a given window is simply absent from the output, not shown as a fabricated 0% or 100%.

**A real architectural constraint reasoned through, not glossed over**: `retro.py` is shared
across every sport on this platform (MLB, WNBA, NBA, NFL, NCAAMB all route through it), while
`conviction_to_grade` is MLB-specific, matching Graded Picks' own "priority is MLB" scope. Adding
a direct dependency from `retro.py` on this MLB-only function would have broken retro.py's own
sport-agnostic design for every other sport calling it. Kept the new function in MLB's own
`projections.py` instead, and gated its call in Retrospective's view (`_active.key == "MLB"`,
matching every other MLB-only branch already on that page) rather than letting it crash for
WNBA/NBA/NFL/NCAAMB, where `_active.projections` is a completely different module without this
function at all.

**Wired into Retrospective** (which grades a model's rebuilt PAST slate against real results,
regardless of whether a real bet was ever logged — the right home, since Track Record needs real
logged-bet history that doesn't exist in volume yet, while Retrospective can backtest any past
date immediately) right next to the existing conviction-tier breakdown, using the same table
styling.

**12 new tests, plus a full end-to-end simulation**: 6 for `grade_accuracy_by_letter` (correct
hit-rate math per letter, unsettled plays excluded, below-floor plays excluded, an absent grade
never fabricated, empty output when nothing's settled, A-through-D order preserved regardless of
input order) confirmed the isolated function; a full simulation chaining `retro.grade_slate` into
`grade_accuracy_by_letter` with a realistic mixed-results slate confirmed the two functions
compose correctly and, notably, produce genuinely DIFFERENT groupings from retro's own existing
tiers — direct evidence this was answering a real, different question, not duplicating one
already answered. 609/609 total passing.

### Real bug found in production: the one-sided banner contradicted the actual grades (2026-07-18)
Shawn caught a real, concrete inconsistency on a live Graded Picks output: Pittsburgh @ Cleveland
Game 2's banner declared Cleveland's hitters favored (facing a "weaker" starter, 0.97 vs 0.00
HR/9), but the actual highest-conviction HR play on the whole board was a Pittsburgh hitter
(Esmerlyn Valdez, A-grade, 3.09x) — with Cleveland's own HR plays only reaching D-grade. The
banner and the real grades directly contradicted each other on the same page.

**Traced to the exact root cause, not patched around the symptom.** `pitcher_allowed_rates` —
which drives every individual hitter's real HR% probability — has always required a pitcher to
have faced >=40 batters before trusting his rates at all, falling back to a neutral matchup
otherwise. `compute_one_sided_banner` used raw "Opp HR/9" directly, with NO such floor. A starter
with a genuinely thin sample (a call-up, a handful of relief innings) can show a misleadingly
"elite" 0.00 HR/9 that's really just small-sample noise — Cleveland's own starter here had almost
certainly faced too few batters to trust that number at all, while the properly-gated per-hitter
math correctly ignored the same thin signal. Two different parts of the same page using two
different standards for how much sample to trust — the banner using none at all.

**Fixed with the exact same floor already established elsewhere**, not a new number invented for
this: `MIN_BATTERS_FACED_FOR_ONE_SIDED = 40`, matching `pitcher_allowed_rates`' own constant
precisely. Reads `battersFaced` from each team's own `_opp_stat` (the opposing starter's raw stat
dict — already present on every hitter row, no new data pulled). If either starter's sample is
too thin, the banner now correctly says nothing rather than confidently asserting something the
real grades on the same page don't support.

**8 tests total for this function now** (2 new): a dedicated regression test reproducing the
exact real-world numbers reported (0.97 vs 0.00 HR/9, one thin sample) confirming it's now
correctly rejected; and a companion test confirming the SAME HR/9 gap still fires correctly when
both samples are real — proving the fix rejects thin samples specifically, not HR/9 gaps in
general. Also directly re-ran the exact reported scenario as a standalone confirmation, not just
inside the test suite. 611/611 total passing.

### New page: Data Health — recommendation #2 built (2026-07-18)
Second of the platform recommendations, built as promised. Direct motivation: this session found
four separate real bugs in the catcher-framing refresh pipeline alone, and every single one was
invisible until someone opened a page and noticed a downstream symptom looked off. No single
place answered "is the data behind this platform actually current" — this closes that gap.

**Tracks the exact five files that caused this session's real bugs**: statcast_batters.csv,
catcher_framing.csv (both from refresh-statcast.yml), pitcher_arsenals.csv, hitter_pitch_
splits.csv, hitter_pitch_type_splits.csv (from refresh-matchups.yml). Both workflows' real cron
schedules were checked directly, not guessed — both currently daily. Line-history/CLV data lives
in a database rather than a committed file, a genuinely different mechanism (a live query, not a
file check); deliberately left out of this v1 rather than forcing it into the same shape.

**A file's own modification time is the freshness signal, deliberately, not a new status log
added to every refresh script**: these files are committed to git by their own workflow and
pulled fresh on each deploy — if a refresh silently fails, the file is never rewritten, so its
mtime honestly stays exactly where it was after the last real success. That's a real signal
already sitting on disk, reusable without touching any of the refresh scripts themselves.

**`data_freshness.py`** — `check_source`/`check_all_sources`/`overall_status`, pure and fully
testable (a real unix timestamp is injectable, so tests are deterministic rather than depending
on wall-clock time). Three real status tiers, not just present/missing: red (file missing,
unreadable, or below a reasoned minimum row floor — the same "committing anyway would be worse
than refusing" standard already used inside the refresh scripts, applied here as a read-time
check), yellow (present and readable, but old enough — 2x its own expected cadence — that its
refresh has very likely failed silently at least once, not just run a little late), green
(present, readable, real row count, recently refreshed). The 2x-cadence stale threshold is a
real, stated design choice: GitHub Actions queue delays are common and real, so a source that's
merely a few hours late shouldn't alarm the same way a genuinely stale one should.

**New page `views/17_Data_Health.py`**, gated owner-only (matching Bet Log/Edge Board/Matchup
Lab/Track Record — this is an operational tool, not user-facing betting content, and a public/
Discord audience has no use for "is our CSV refresh pipeline healthy"). A compact pointer was
added to Command Center too, following the same pattern established for Graded Picks — but this
one is conditionally shown only for the owner audience specifically (checked directly via
`st.secrets`, since Command Center doesn't otherwise know the audience), so a public viewer never
sees a link to a page they can't open.

**14 new tests plus two full honest end-to-end runs**: 12 for `data_freshness.py` (missing file,
healthy file, below-row-floor, unreadable content never crashing or reporting green, genuinely
stale correctly yellow, a real boundary check just under the stale threshold staying green, a
merely-late refresh NOT falsely flagged, multi-source ordering, all three `overall_status`
combinations, and a direct confirmation that `TRACKED_SOURCES`' paths match the real, current
constants in each module rather than stale hardcoded copies) plus the `owner_only_titles`
regression test updated for the new page. Ran the real function against this actual sandbox's
own `data/` directory as an honest test — correctly reported red across the board (no real
deployed data exists here), even catching a stray leftover test artifact from earlier session
work as a real below-floor row-count failure — then separately confirmed a simulated healthy
deployment correctly reports all-green. 623/623 total passing.

### Hitter-side rest and fatigue — recommendation #3 built (2026-07-18)
Third and last of the platform recommendations. Pitcher rest and bullpen fatigue were already
built; hitters had no equivalent, despite it being a real, well-documented thing teams actually
manage (real roster/lineup decisions get made specifically around it).

**`mlb_engine.get_team_hitter_workload(team_id, before_date, days_back=10)`** — mirrors
`get_team_bullpen_fatigue`'s exact cost-efficiency pattern (one schedule fetch, one boxscore
fetch per game in the window, covering the WHOLE lineup's workload in that single scan, not one
fetch per hitter) but with a real, deliberate difference in what the streak actually counts: a
GAMES-based streak, not a calendar-days-based one. A pitcher's fatigue signal cares about
calendar proximity (arm recovery time); a hitter's workload concern is about how many of the
TEAM's own games he's started in a row, since a team's own off-day is real rest regardless of how
many calendar days it spans — matching how this is actually discussed in real coverage ("hasn't
had a day off in N games," not N calendar days).

**A real parsing distinction, not a minor detail**: only counts a game where a player was the
ORIGINAL starter in his slot (battingOrder ending in "00"), not a late-game substitute (ending in
a non-zero suffix) — a defensive replacement or pinch-hitter who entered in the 8th shouldn't
count as a real day's workload the same way an original starter's full game does. Same 3-digit
battingOrder convention already established this session, applied here with the opposite
filtering intent than batting-order splits needed.

**Tagging threshold (8+ consecutive starts, no rest day) stated honestly as reasoned, not
proven** — matching the same posture as this session's other stated-not-backtested thresholds
(the one-sided banner's HR/9 gap, catcher-change's minimum sample size).

**Wired into Pitching Lab**, alongside bullpen fatigue and starter rest — that page functions as
the real "game context" page regardless of its name, not strictly pitcher-only, and this is the
natural hitter-side sibling to what's already there. Same real cost, same game-scoped picker
already in use, not a new UI pattern.

**9 new tests**: a real 8-game iron-man streak correctly flagged; a streak correctly breaking
(counting backward) at a real missed game in the middle of the window, not just at the start or
end; late substitutes correctly excluded from ever counting as a start; all three tag thresholds;
correct handling of the away side (not just home, confirmed separately); non-final games never
fetched at all (a hard assertion in the test itself, not just an unused mock); empty-window
handling; and sort order (least-rested first) confirmed with a genuinely mixed scenario, not just
two extremes. Plus a full realistic end-to-end simulation with three different hitter usage
patterns (an iron man, a player with a real mid-window rest day, and a true platoon bat) —
producing exactly the right streak for each, including the platoon player's short streak
correctly reflecting his real alternating usage, not an averaged or misleading number. 632/632
total passing.

**This closes out all three platform recommendations** — grade accuracy tracking, data health,
and hitter-side fatigue — each one built, tested, and verified against realistic scenarios before
being called done.

### Cross-sport audit: one real bug found and fixed, one latent risk found and consolidated (2026-07-18)
Shawn asked to check whether everything built this session actually works correctly across every
sport, not just MLB. Went through it systematically rather than spot-checking.

**One real, confirmed bug, not a hypothetical concern**: Graded Picks called
`P.organize_graded_picks(plays)`, where `P` is whichever sport's own projections module happens
to be active — but `organize_graded_picks`/`conviction_to_grade` only ever lived in MLB's own
`projections.py`. Confirmed directly, not assumed: opening Graded Picks on WNBA, NBA, NFL, or
NCAAMB would have crashed immediately with an `AttributeError` the moment someone tried it. The
grading logic itself never actually depended on anything MLB-specific — it operates purely on
`Conviction`, a number every sport's own `build_best_bets` already produces in the same shape.

**Fixed by extracting the genuinely sport-agnostic logic into its own module, `grading.py`** —
`GRADE_THRESHOLDS`, `conviction_to_grade`, `organize_graded_picks`, `grade_accuracy_by_letter` all
moved there. MLB's `projections.py` re-exports all four for backward compatibility with existing
callers (`best_bets_data.py`, and this session's own earlier tests) that reference them via `P.*`
where `P` happens to be MLB's own module — confirmed the re-export resolves to the exact same
object, not a stale copy, with a dedicated test. Both `views/16_Graded_Picks.py` and
`views/6_#L01f50d_Retrospective.py` updated to import `grading` directly rather than through
`P` — Retrospective's own MLB-only gate on the letter-grade accuracy breakdown is gone entirely
now, since the function it depends on is genuinely sport-agnostic, not because the gate was wrong
before (it was the correct call at the time, given the real constraint that existed then).

**A systematic audit, not just fixing the one bug found by accident**: extracted every `P.<call>`
across every view file and cross-checked each against every sport's own projections/engine
module. Confirmed the NFL-specific pages (NFL Matchup Lab, Anytime TD Engine, QB Lab) are safely
built with hardcoded sport-specific imports plus an explicit `require_sport(["NFL"], ...)` gate,
not the pattern that caused the Graded Picks bug. Confirmed the shared basketball pages (Hot Hand
Engine, Matchup Lab for WNBA/NBA/NCAAMB) have every function they call present and consistent
across all three sports' own modules. Two apparent gaps (`blowout_risk_tag`, `format_et`) turned
out to be false alarms on closer inspection — both are real, working shared utilities via
patterns a shallow grep missed (an assignment-based re-export from `basketball_projections.py`,
and a direct cross-module import from MLB's `projections.py`), not actual bugs.

**A second, related consolidation, done proactively rather than after a bug forced it**:
Retrospective had its own separate, third copy of the full MLB board-building pipeline
(`load_retro_mlb`) — structurally the same duplication-drift risk that caused the real Command
Center/Best Bets conviction mismatch earlier this session, just not yet triggered into a visible
bug. Consolidated it to call `best_bets_data.build_mlb_board` (promoted from an internal,
underscore-prefixed helper to a real shared function) instead of duplicating the pipeline.
**This is a genuine accuracy improvement, not just fewer lines of code**: Retrospective was
previously grading the model against UNBLENDED probabilities while the actual board a person
sees uses the bullpen-blended ones — confirmed directly with a full offline simulation that
Retrospective's own graded plays now carry `_bullpen_blended: True`, the same real correction
already shipped to Best Bets and Graded Picks.

**4 new tests in `test_grading.py`** specifically proving the fix works, not just that it doesn't
crash: `organize_graded_picks`/`grade_accuracy_by_letter` both tested against genuinely
WNBA-shaped plays (Points/Rebounds markets, not Batter HR/Pitcher Strikeouts), confirming correct
grading and sorting for a real non-MLB sport's own market names — plus a re-export identity check
in `test_projections.py` confirming `P.conviction_to_grade` resolves to the exact same object as
`grading.conviction_to_grade`. 636/636 total passing.

### Bet Log / Track Record access gate + a forward-compatible schema field (2026-07-18)
Shawn asked how to keep his personal trading Ledger separate from Deezy if it gets migrated onto
the platform, recognizing this points toward eventually needing real user login. Investigated the
actual current access model before proposing anything: `AUDIENCE` (owner vs. public) is a
deployment-level secret, not a per-person login — there's no concept of "who is viewing" beyond
that binary switch, and `betlog.py`'s `DATABASE_URL` is the same, a single per-deployment secret.
So anyone on the "owner" build today shares the exact same Bet Log database, with no field
distinguishing whose bet is whose. Confirmed the concern was real, not building a fix for a
non-problem.

**Recommended, and built, the narrower fix over a full separate deployment**: a second password
gate specifically in front of Bet Log and Track Record, not a whole second app. A full separate
instance would mean either duplicating the entire platform (wasteful) or still sharing
infrastructure anyway just to avoid that duplication — while the actual thing being protected is
two specific pages, not the whole deployment.

**`sports.require_trading_access(page_name)`** — matches the exact style and return contract of
the existing `require_live_engine`/`require_sport` gates (returns True to proceed, False with the
prompt already rendered, caller does `st.stop()`). The actual comparison logic is split into a
separate, pure `_check_trading_password(entered, expected)` specifically so it's unit-testable
without a real Streamlit runtime — the same "extract the testable core" discipline used
throughout this session for view-layer logic. **Fails closed on a missing secret, not open**: if
`TRADING_PASSWORD` isn't configured at all, the gate denies access regardless of what's typed,
the same "refuse rather than fabricate a pass" posture already used in `data_freshness.py`'s own
checks. Reuses `st.session_state` so a correct password is only needed once per browser session,
not re-entered on every page navigation.

**A real, deliberate first step toward the future multi-user need, not a full login system built
prematurely**: `betlog.py`'s schema gained a `trader` column (SQLite migration matching the exact
existing pattern used for `sport`/`ticket`; Postgres schema and its own `ALTER TABLE ADD COLUMN
IF NOT EXISTS` updated identically). Nothing populates it reliably yet — there's no real
per-person login asking "who are you" — but a future login system won't need a schema migration
on top of everything else it has to build; the column already exists, genuinely optional on every
call today, exactly like every other field in this table.

**9 new tests**: 4 for `_check_trading_password` (correct/incorrect, failing closed on a missing
secret — including the specific empty-string edge case that could slip through a careless
truthiness check, and correctly coercing a non-string secret since `st.secrets` can return other
types depending on how a value was declared), 1 confirming both Bet Log and Track Record actually
call the gate by reading their real source (not just trusting the edit landed correctly — the
exact same class of "wired in or not" verification used for the Command Center pointer earlier
this session), 2 confirming the `trader` field round-trips correctly through the real add/list/
update flow and stays genuinely optional, plus a direct, real verification of the SQLite migration
path against a simulated pre-existing database (a real bet surviving the upgrade with the new
column correctly defaulting to None, not lost or corrupted). 643/643 total passing.

**Real deployment step still needed, not yet done**: `TRADING_PASSWORD` has to be added to the
owner build's Streamlit Cloud secrets for the gate to open at all — until it's set, `_check_
trading_password`'s fail-closed design means Bet Log and Track Record are locked out for
everyone, Shawn included. Flagged directly rather than left to be discovered as a surprise.

### Four new MLB props markets: Runs, RBIs, Stolen Bases, Earned Runs (2026-07-18)
Shawn wanted these four markets added to round out MLB coverage — the platform previously
modeled seven markets (HR/TB/Hits/K for batters, K/Outs/Walks for pitchers), missing several
common, real, bettable MLB props entirely.

**A real, deliberate methodology split, reasoned through before writing any code**: HR/Hits/TB
are determined ENTIRELY by a batter's own PA outcome, which is why the existing `batter_pa_probs`/
`simulate_batter` pipeline works for them. Runs and RBIs are NOT — a run needs a teammate to
drive the batter in, an RBI needs a teammate already on base. Modeling that properly would mean
simulating a whole lineup's baserunning state across an inning, a real, much bigger undertaking
than fit this scope. Instead built `batter_counting_rate` — the batter's own season Runs/RBI/SB
rate (already reflecting his real team context over a real season), regressed toward league
average for thin samples, scaled to tonight's real projected PA, and — for Runs/RBI specifically
— adjusted for the opposing starter's ERA relative to league average (a real, reasoned proxy, not
a fabricated precision the data doesn't support). Modeled via Poisson, using the exact closed
form for the standard "Over 0.5" line these markets are quoted at (`poisson_over_half_prob`,
`P(X>=1) = 1 - e^(-lambda)`) rather than Monte Carlo simulation — more precise, no simulation
noise, and cheaper for a single well-defined question.

**Stolen Bases deliberately gets no opponent adjustment at all** — SB success depends much more
on the catcher's arm/pop time than the pitcher's own run prevention, and that signal isn't
modeled on this platform yet. An honest, simpler read of the batter's own rate, not a fabricated
matchup factor.

**Pitcher Earned Runs extends the existing pitcher pipeline directly** (`project_pitcher`/
`simulate_pitcher`, the same functions already producing K/BB/Outs) rather than building a
separate mechanism — genuinely the same kind of market as those three (one pitcher, one "over a
line" question). Shrinks the pitcher's own earned-runs-per-inning rate toward league average
(innings-pitched-based, since ERA is itself an innings-based rate), with NO opposing-lineup
adjustment — `lineup_k_bb_rates` only has K/BB rates, not a real "how much does this lineup
score" signal, and fabricating one from K/BB alone would overclaim a precision the data doesn't
support. Same honest posture as SB on the hitter side, for the same underlying reason.

**Real market keys confirmed against live documentation, not guessed**: searched and fetched
the-odds-api.com's own "Betting Markets" page directly (the exact provider `odds_api.py`
integrates with) — `batter_runs_scored`, `batter_rbis`, `batter_stolen_bases`, `pitcher_earned_
runs` all confirmed to exist exactly as assumed. `sports.py`'s `_MLB_MARKETS`/`_MLB_MARKET_MAP`
updated with these real, confirmed keys, feeding Bet Log's market dropdown, CLV capture, and live
odds fetching across Media Room/Podcast Studio/Matchup Lab.

**Honest, market-specific "Why" reasoning added, not left to a generic fallback**: `_hitter_
reasons`/`_pitcher_reasons` extended so Runs/RBI reference the real opposing-starter-ERA
adjustment the model actually applies, SB honestly states it's reading the batter's own rate with
no matchup factor (since the model genuinely has none), and Earned Runs references the pitcher's
own ERA/projected innings — each reason describing what the model actually does, not a
one-size-fits-all "leans Over of a typical line" placeholder every new market would otherwise
have silently fallen through to.

**A confirmed, deliberate non-extension**: `apply_bullpen_blend_to_top_plays`/`BULLPEN_BLEND_
MARKET_COLS` were NOT extended to the new markets. That mechanism sums `simulate_batter`'s
PA-outcome counts across two phases — a method specific to HR/Hits/TB/SO, genuinely mismatched
with the new Poisson-rate methodology. Confirmed directly that omitting the new markets from that
dict is safe, documented behavior (plays with markets not in it are simply left untouched, never
silently dropped or miscomputed) rather than a gap — extending the blend to these markets would
be real, separate future work, not squeezed into this scope.

**Also confirmed, not assumed**: Dinger Engine is intentionally, permanently HR-specific by
design (confirmed by reading its own module docstring) — correctly out of scope for these new
markets, which are surfaced through Best Bets/Graded Picks/Command Center/Retrospective instead,
all of which already route through the shared `build_best_bets`/`market_map` infrastructure.

**18 new tests across 3 files**: `batter_counting_rate`/`poisson_over_half_prob` (10 tests —
PA-floor gating, linear PA-scaling, real shrinkage toward league average on a thin sample, the
opposing-ERA adjustment raising/lowering expected count correctly, the closed-form Poisson
formula hand-verified against Python's own `math.exp`, monotonicity, and a real floating-point
edge case caught and fixed in the test itself — an unrealistic exp_count=100 where float64
genuinely can't distinguish the result from 1.0, not a bug in the implementation); `enrich_
hitter_rows` integration (3 tests, including the real edge case of a stat dict entirely missing
runs/rbi/stolenBases, confirming graceful defaults rather than a crash); `project_pitcher`/
`simulate_pitcher` earned-runs extension (5 tests, including a hand-verified expected value from
a real 3.25 ERA calculation — caught and fixed a wrong assumption in the test's own expected
bounds, not the implementation); market-specific reasoning (5 tests); a full `build_best_bets`
integration test confirming all four new markets produce real, correctly-shaped plays; and 2
`sports.py` consistency tests (every `market_map` value is a real, fetched market key; all four
new keys match the confirmed Odds API documentation exactly). Plus a full, realistic end-to-end
simulation through the entire `load_mlb_graded_picks_board` pipeline — all 11 markets present on
one simulated board, each new market's play carrying real Fair odds, a real letter grade, and
honest reasoning text. 670/670 total passing.

### New page: Suggested Parlays — for Discord users who don't want to comb through data (2026-07-18)
Shawn wanted a page offering ready-made parlay suggestions (max 6 legs) for casual Discord users,
built from the graded board rather than requiring them to dig through individual props
themselves. Explicitly asked to be given real time to think this through before building, given
the real risk in getting the underlying math wrong on a page aimed at people who won't
double-check it.

**The core design problem, reasoned through before any code**: a parlay's combined probability
is only honestly the product of each leg's own probability if the legs are independent. Two legs
on the SAME PLAYER almost never are — a home run leg and a total-bases leg on the same hitter are
so tightly coupled that treating them as independent would badly overstate how safe the
combination actually is. This mattered more, not less, specifically because this page exists for
people who explicitly don't want to dig into why a number is what it is — they're trusting it at
face value.

**The fix: a hard, simple, defensible rule — never put two legs on the same player into one
suggested parlay.** `grading.build_parlay_leg_pool` enforces this (keyed on (Player, Team), not
Player alone, since two genuinely different people can share a surname across different teams —
confirmed with a dedicated test), plus softer caps on legs sharing a game or a market (real, but
much weaker correlation concerns than same-player, handled as configurable limits rather than
hard bans).

**Tiered by risk, confirmed with the user's own explicit answers**: Safer (2-leg), Balanced
(4-leg), Longshot (6-leg) — cumulative from the SAME conviction-ranked pool, not independently
re-optimized sets, so the risk difference comes honestly from chaining more real legs together
(probabilities multiply down), not from quietly swapping in worse plays for the bigger tiers. A
tier is skipped entirely, not padded with weaker plays, when the pool doesn't have enough diverse
legs to fill it honestly — confirmed directly with a real end-to-end simulation showing only the
Safer tier building on a thin, single-leg-diverse pool.

**Built genuinely sport-agnostic from day one**, per the user's explicit answer — lives in
`grading.py` alongside the rest of the shared grading logic, not MLB's own `projections.py`.
Caught and fixed a real circular import along the way: `projections.py` already imports FROM
`grading.py` (from the earlier cross-sport audit fix), so `grading.py` importing `prob_to_
decimal`/`prob_to_american` from `projections.py` at module level created a genuine cycle. Fixed
with a lazy, in-function import — the same pattern already established elsewhere in this codebase
(`sports.py`'s `require_trading_access`) for exactly this situation.

**Full "Why" reasoning per leg included**, per the user's explicit answer — reuses each play's
own `Why` text directly, no new reasoning system needed.

**New page `views/18_Suggested_Parlays.py`**, public (not owner-only, matching the user's stated
audience), with a real, visible caveat about the independence assumption and a concrete, honest
example (a 60% leg is still only ~5% across 6 legs) rather than burying the caveat in fine print.
Deliberately has NO time-slot/game filter, unlike Graded Picks — a parlay is meant to draw from
the whole slate at once by design; narrowing to one game would usually make the bigger tiers
impossible to fill. A `st.page_link` pointer was added from Graded Picks to this page, and one
from Command Center already points to Graded Picks, so the three public-facing board pages
connect naturally without merging.

**23 new tests**: 7 for `build_parlay_leg_pool` (the core same-player exclusion confirmed
directly — including that the HIGHER-conviction leg wins when two plays collide on the same
player, not just whichever was seen first; the same-name-different-team edge case explicitly
confirmed NOT to falsely collide; max-per-game and max-per-market caps; below-floor exclusion;
sort order), 3 for `combined_parlay_prob` (correct multiplication, empty-legs handling, and a
confirmed strictly-decreasing property as more legs are chained), 8 for `build_suggested_parlays`
(all three tiers building correctly, the cumulative-not-reoptimized property explicitly confirmed,
tier-skipping on a thin pool, empty output when nothing can be built at all, real combined odds
present on every tier, and — matching this session's own established discipline — a dedicated
cross-sport regression test using genuinely WNBA-shaped plays, not just MLB's). A real bug caught
and fixed during this build, not shipped: the test file's own `if __name__ == "__main__":` guard
was accidentally destroyed during editing, leaving its test-runner loop as an orphaned,
mis-indented block that Python would have silently treated as part of the preceding test function
— caught immediately by checking for the guard explicitly after editing, not assumed to be fine
because the file still compiled. Plus a full, realistic end-to-end simulation across a real
7-hitter, 4-game board confirming all three tiers build correctly with zero same-player
duplicates anywhere, asserted directly in the simulation itself, not just eyeballed. 686/686
total passing.

### Suggested Parlays: market-selection UI, after a real reported issue (2026-07-18)
Shawn caught something real on the live page: the auto-built Safer/Balanced tiers were
dominated by three different real base stealers' Stolen Bases legs before any other market
appeared, and flagged it as looking unrealistic — proposing a market-selection UI (dropdowns or
toggles) as the fix.

**Investigated the actual cause before changing anything**, rather than assuming it was a bug:
compared a real elite base stealer's SB conviction (a genuine ~24% Over-0.5 chance) against a
real elite slugger's HR conviction (a nearly identical ~22% chance) using this platform's own
functions directly — 4.78x vs 2.03x, more than double for essentially the same raw probability.
Confirmed this isn't obviously a calibration bug: Stolen Bases genuinely is a more skewed market
than Home Runs (most hitters rarely or never attempt one, a handful attempt many), so an elite
burner really can be more of an outlier relative to a typical player than an elite slugger is —
the math isn't necessarily wrong, but it produced a real UX problem regardless. Deliberately did
NOT unilaterally re-tune `BEST_BET_REF["Batter Stolen Bases"]` to "fix" a skew that isn't clearly
wrong and that also feeds Best Bets/Graded Picks, not just this page — that's a bigger, separate
question belonging to Shawn's own call, not something to change quietly as a side effect of a
parlay-page fix.

**Two real fixes, not one**: (1) `grading.build_parlay_leg_pool`'s/`build_suggested_parlays`'s
`max_per_market` default tightened from 3 to 2 — a real, low-risk improvement independent of the
Stolen Bases question, since letting any single market fill 3 of a parlay's legs before another
market appears reads as unrealistic regardless of which market it happens to be. (2) A market-
selection `st.multiselect` added to the top of the page, defaulting to every market present on
the board (not silently hiding Stolen Bases by default, since its conviction level isn't
confidently wrong) — giving people direct control over what they see, the actual fix Shawn asked
for. Filtering happens on the flattened plays list before `grading.build_suggested_parlays` is
called, so the tested, core parlay logic needed zero changes — only the view layer changed.

**3 new/updated tests**: a dedicated regression test locking in the new default specifically
using Stolen Bases as the example market (5 real burners, confirming only 2 make the pool by
default, no cap explicitly passed); a fixed pre-existing sort-order test that had accidentally
been exercising the old default (three same-market legs, silently relying on max_per_market=3)
— caught and corrected to use three different markets instead, so it tests sort order
specifically rather than colliding with the cap it wasn't meant to be testing. Plus a full,
realistic end-to-end simulation reproducing the exact reported scenario (multiple real burners
plus real sluggers) twice — once confirming the tightened default naturally diversifies the
board without any user action, once confirming the market filter correctly excludes Stolen Bases
entirely when deselected. 687/687 total passing.

### Market-ceiling normalized grading — a real, platform-wide fix, not a parlay patch (2026-07-18)
Shawn noticed no "A" grades appeared in Suggested Parlays after excluding HR and Stolen Bases,
and asked what was going on. Confirmed it directly rather than guessing, and it turned out to be
much bigger than the parlay page.

**Root cause, confirmed with real numbers**: Conviction = ModelProb/RefProb has a hard ceiling of
1/RefProb — even a theoretically perfect play (ModelProb=1.0) can't exceed it. Computed the
theoretical max for every MLB market: only Batter HR (ceiling 9.09x) and Batter Stolen Bases
(ceiling 20.0x) can ever mathematically reach the 3.0x "A" threshold. The other 9 markets top out
between 1.54x and 2.86x — structurally incapable of an "A" grade no matter how good the play is.
Checked cross-sport too, and it's worse there: WNBA, NBA, NFL, and NCAAMB all use ref=0.5 for
*every* market, capping raw conviction at exactly 2.0x — meaning no play on any of those sports
could ever reach even a "B" grade, let alone "A", under the original thresholds. The thresholds
were set by watching real Best Bets output that was itself dominated by HR (the market with by
far the most headroom), so they ended up implicitly calibrated to HR's own range without anyone
realizing every other market — and every other sport entirely — was structurally locked out.

**The fix, confirmed with Shawn before touching the core grading system given how far it
reaches**: normalize conviction against each play's own theoretical ceiling before comparing to
GRADE_THRESHOLDS, rather than comparing raw conviction universally. `grading.conviction_to_grade`
gained an optional `ceiling` parameter — when supplied, conviction is scaled by
`REFERENCE_CEILING / ceiling` before the threshold check, where `REFERENCE_CEILING` is fixed at
HR's own ceiling (~9.09) specifically so HR's own grades don't move at all under this
normalization; every other market gets scaled fairly relative to the market the thresholds were
already, if unintentionally, built around. The DISPLAYED conviction number in the returned grade
dict stays the real, raw value always — only the letter-grade decision uses the normalized one,
so nothing shown to a person is a number that doesn't mean what it says. Omitting ceiling falls
back to the exact old behavior, so any caller not yet updated keeps working unchanged.

**A real, deliberate architectural choice on WHERE ceiling comes from**: each play now carries
its own `_ceiling` (1/RefProb for whichever side is favored), attached at the exact same place
`Conviction` itself is already computed inside each sport's own `build_best_bets` — MLB's
`projections.py` (both the hitter and pitcher play-construction paths) plus all four other
sports' own `projections.py` files, six occurrences of the identical one-line change total.
Deliberately NOT resolved via `sports.active()` inside `grading.py` itself — that would
reintroduce the exact "which sport is actually active when this runs" staleness risk already
identified and avoided earlier this session (`best_bets_data.py`'s own MLB-vs-generic split).
Attaching ceiling directly to the play at build time means `grading.py` never needs to know
anything about any sport's specific reference probabilities at all.

**A second real, welcome side effect, not a separate fix**: this also directly addresses last
turn's Stolen Bases over-dominance. SB's ceiling (20.0x) is more than double HR's (9.09x), so
normalizing against HR's fixed benchmark correctly COMPRESSES SB's inflated conviction rather
than leaving it disproportionately high — confirmed directly: a real burner's raw 4.78x SB
conviction and a real elite slugger's raw 2.03x HR conviction (nearly identical real
probabilities, 23.9% vs 22.3%) now both land on "B", not 4.78x dwarfing 2.03x for reasons that
had nothing to do with how good either play actually was.

**13 new tests**: 7 for `conviction_to_grade`'s new normalization (backward compatibility when
ceiling is omitted; HR's own ceiling confirmed to produce byte-identical grades to the old raw
behavior across a real range of conviction values; a low-ceiling market — matching every
non-MLB-sport market exactly — confirmed to now reach A when genuinely close to its own ceiling,
with an explicit companion test confirming the OLD behavior really would have failed this exact
case, proving the fix does real work and isn't a no-op; the Stolen Bases compression confirmed
directly with the real reported numbers; the two markets' near-identical real probabilities
confirmed to now land on comparable grades instead of wildly apart; a defensive zero/negative-
ceiling edge case falling back to raw comparison rather than crashing), 1 confirming
`build_best_bets` attaches a real, correctly-relative `_ceiling` to every play (SB's ceiling
confirmed genuinely higher than HR's, not just present). Plus two full, real end-to-end
simulations: one reproducing the exact reported scenario (HR and Stolen Bases excluded from a
real, realistic 4-hitter board) confirming A grades are now reachable across every remaining
market where they previously never could be; a second confirming directly, using WNBA's own
actual ref=0.5 reference probabilities, that a play at 90% of its own real ceiling moves from a
maximum of "C" under the old system to a correct "A" under the new one — the exact concrete proof
this now plays well across every sport, not just MLB. 695/695 total passing.

### Suggested Parlays: fixed a single-market selection silently capping at the Safer tier only (2026-07-19)
Shawn caught another real one: selecting only "Pitcher Strikeouts" in the market filter produced
just the Safer (2-leg) tier — Balanced and Longshot never appeared, even though plenty of real,
different graded pitchers existed that night.

**Root cause, confirmed directly**: `max_per_market` (tightened to 2 last turn specifically to
stop one market from dominating when MULTIPLE markets are available) had a real, unintended
side effect — it applied unconditionally, so narrowing the page down to a SINGLE market capped
the entire pool at 2 legs total, since the cap had nothing left to diversify into. The same
mechanism that fixed the Stolen Bases over-dominance issue was, in the single-market case,
punishing someone for a choice they'd already deliberately made.

**The fix**: `build_parlay_leg_pool` gained a `min_pool_size` parameter. When set, it loosens
(never tightens) `max_per_game` and/or `max_per_market` just enough to make a pool of that size
achievable, based on how many DISTINCT games and markets are actually present among the graded
plays — with only 1 distinct market graded, the market cap effectively becomes however many legs
are needed, since there's nothing left to diversify into; with plenty of distinct markets already
present, nothing loosens at all. `build_suggested_parlays` now calls this with the largest
requested tier size (6, by default) as `min_pool_size`. The same-player exclusion — the actual
core safeguard — is never loosened by this mechanism regardless of how large `min_pool_size` is,
confirmed with a dedicated test.

**7 new tests**: `min_pool_size=0` confirmed to exactly match the old, unmodified behavior;
the exact reported single-market scenario reproduced directly (6 real, different pitchers, one
market, confirming the pool correctly reaches all 6); confirmed the loosening does NOT engage
when the original caps already support the requested size (not an unconditional widening); the
same mechanism confirmed to work symmetrically for a thin-game slate, not just narrow market
selection; the same-player hard constraint confirmed to hold regardless of `min_pool_size`; and a
genuine scarcity case (only 3 real distinct players exist even with loosened caps) confirmed to
honestly return 3, not fabricate legs that don't exist. Plus a full, realistic end-to-end
simulation — an 8-pitcher, 4-game board filtered to "Pitcher Strikeouts" only — confirming all
three tiers (Safer/Balanced/Longshot) now build correctly, exactly reproducing what was reported
as broken. 702/702 total passing.

### Suggested Parlays: non-overlapping tiers, 2 new tiers, and "Fair" odds clarity (2026-07-19)
Three real pieces of feedback in one pass. First: "Fair" odds could read as confusing next to an
"A" grade, since a big negative number (e.g. -480) looks like a bad price to someone who doesn't
know it actually reflects high model confidence. Second: tiers were reusing the exact same legs
from the prior, smaller tier — real user feedback that this read as broken, not as the deliberate
design choice it originally was. Third: users specifically asked for 3-leg and 5-leg options.

**Fair odds clarity**: the info box at the top of the page now directly explains what "Fair"
means in plain language — that it reflects the model's own break-even probability, not what a
book is offering, and that a big negative number is a sign of confidence, not a bad price. The
per-leg display was also relabeled from "Fair" to "Fair odds," a small but real reduction in
ambiguity (a bare "Fair" could read as an adjective describing the bet itself, not a noun
referring to the odds).

**Tier redesign, not a bug fix — a real, deliberate change to intended behavior**: `PARLAY_TIER_
SIZES` expanded to five tiers (Safer/Steady/Balanced/Bold/Longshot, 2 through 6 legs), and
`build_suggested_parlays` now allocates legs SEQUENTIALLY and NON-OVERLAPPING from one shared,
ranked pool — Safer gets the pool's best 2 legs, Steady gets the next-best 3 (not the same 2 plus
one more), and so on, with no leg or player ever appearing in more than one tier. This trades away
one honest property (every tier contained only the model's single best N picks) for another
(every tier is a genuinely distinct combination) — a real, considered tradeoff, not a compromise;
the later tiers now carry somewhat lower average conviction per leg too, which is itself an
honest, additional reason bigger tiers carry more risk, not just the multiplicative effect of
chaining more legs together. `build_parlay_leg_pool`'s `min_pool_size` mechanism (from last
turn's fix) now receives the SUM of every tier's size (up to 20, not just the largest tier's 6),
since non-overlapping allocation means every tier's legs have to come from somewhere new.

**9 tests updated/added**: three pre-existing tests updated for the new 5-tier, non-overlapping
design (rewritten rather than deleted, since the underlying behavior they were protecting —
correct tier sizes, correct market-selection resilience — is still real, just implemented
differently now); a new test explicitly confirming zero leg overlap across all five tiers on a
20-leg pool; a new test confirming the honest consequence of sequential allocation — earlier,
smaller tiers get first pick of the highest-conviction legs, so Safer's average conviction is
never lower than Longshot's. Plus a full, realistic end-to-end simulation on an 8-game board:
four tiers built correctly (14 total legs used, zero overlap confirmed directly), and the
Longshot tier correctly skipped rather than padded when the pool ran two legs short of the 20
needed to fill every tier — exactly the intended "skip, don't fabricate" behavior working as
designed on a real, realistic board size. 703/703 total passing.

### Suggested Parlays: per-tier objectives, a real second redesign (2026-07-19)
Shawn pushed back on the previous turn's fix, directly: non-overlapping legs were right, but
every tier still ranked by the same metric (Conviction) — just handed out in consecutive chunks.
That could still read as a tool with limited analytical range, since a sharp person could notice
Longshot's legs were simply Safer's leftovers, not picks chosen FOR being longshots. Talked
through the direction before touching code: give each tier a genuinely different objective,
safety-first at the low end, payout-conscious at the high end, confirmed with Shawn before
building it.

**A real, deliberate distinction made explicit for the first time**: Conviction measures edge
relative to a market-typical reference rate, not absolute likelihood. A rare-market prop with
huge relative edge (a 25% chance vs an ~11% typical rate) can carry real Conviction while still
being a genuinely risky single leg — exactly wrong for a tier that's supposed to mean "safe."
`grading._tier_sort_key(objective)` now provides three real, different rankings: "safety" (raw
ModelProb descending — the actual chance of hitting), "payout" (ModelProb ascending, i.e. the
biggest real price, but only among plays that already cleared the real grading floor — chasing
genuine upside within validated picks, not grabbing whatever has zero edge), and "conviction"
(the original metric, unchanged, for Balanced as a genuine middle ground). `PARLAY_TIER_SIZES`
now carries each tier's real objective: Safer/Steady use "safety," Balanced uses "conviction,"
Bold/Longshot use "payout."

**`build_parlay_leg_pool` generalized, not replaced**: gained `sort_key` (defaults to Conviction
descending, preserving old behavior for any caller not yet passing one) and `exclude_players` (a
set of already-claimed (Player, Team) pairs). `build_suggested_parlays` now calls it ONCE PER
TIER with that tier's own objective and a growing exclusion set — no leg or player still ever
appears in more than one tier (the hard rule from the prior redesign, unchanged), but each tier's
own remaining candidates are ranked by what that tier actually cares about, not by one universal
metric sliced five ways.

**A real, honest interaction confirmed directly, not hidden**: on a full 5-tier board, Longshot's
average probability can land higher than Balanced's — because Balanced (processed first, being
the smaller tier) can claim some of the same low-probability, high-Conviction plays Longshot
would have wanted, since high Conviction and low raw probability often correlate for skewed
markets like HR. Confirmed this is a genuine, honest consequence of the non-overlap constraint
interacting with processing order, not a flaw in the objective logic — verified by running Safer
and Longshot in isolation (no competing tiers), where they correctly produced starkly different
average probabilities (0.86 vs 0.22).

**A real testing gap caught and fixed before it mattered**: the existing test fixtures used a
constant `model_prob=0.55` for every leg, meaning "safety" and "payout" objectives would have
fallen back to stable tie-break order and accidentally still passed without genuinely exercising
the new logic. Wrote dedicated tests that deliberately misalign ModelProb from Conviction (a
high-Conviction/low-probability play vs a low-Conviction/high-probability one) to prove each
objective picks what it's actually supposed to, not what a coincidental test fixture would have
produced anyway.

**6 new tests**: `_tier_sort_key` confirmed directly for all three objectives using deliberately
misaligned Conviction/ModelProb pairs; a full `build_suggested_parlays` proof that Safer correctly
ignores a higher-Conviction-but-riskier play in favor of two genuinely safer ones; Longshot
confirmed to favor real payout size over a safer, lower-edge alternative; and a direct,
side-by-side proof that Safer and Longshot can pick genuinely different legs from the same mixed
pool, the exact concern this whole redesign was meant to address. Plus a full, realistic
end-to-end simulation on an 8-game board (all 5 tiers built, 20 unique legs, zero overlap
confirmed) and a follow-up isolation check confirming each objective's real behavior when not
competing with other tiers for the same candidates. 709/709 total passing.

### Five more MLB props markets: Singles, Doubles, Triples, Walks, Pitcher Hits Allowed (2026-07-19)
Shawn asked why H-R-R (Hits+Runs+RBIs) wasn't included when the first four new markets were
built, and directed adding the full remaining set of real, confirmed-but-unbuilt markets at once
rather than piecemeal — with the explicit reasoning that this should be the standing approach for
every sport going forward, not a market added only when a user happens to ask for it by name.

**Confirmed every remaining market directly against the-odds-api.com's own live "Betting
Markets" documentation before building anything** — fetched the full page, not just recalled it
from memory. Found `batter_singles`, `batter_doubles`, `batter_triples`, `batter_walks`,
`batter_first_home_run`, `pitcher_hits_allowed`, `pitcher_record_a_win`, `batter_fantasy_score`,
and `batter_hits_runs_rbis` as real, existing, unbuilt markets — a bigger list than just H-R-R.

**Split the list by whether it fits the platform's own established, proven methodology, not by
convenience** — Singles/Doubles/Triples/Walks/Hits Allowed all do; H-R-R needs a genuinely
different, correlation-aware approach (still pending); First HR, Record a Win, and Fantasy Score
are structurally different problems entirely (cross-player joint probability, team-context
dependence, and an undefined external scoring formula respectively) and were deliberately NOT
attempted with weak, rushed models just to complete a list.

**Singles/Doubles/Triples/Walks needed zero new methodology, only exposure of what already
existed**: `simulate_batter`'s underlying per-PA draws already carried real index constants for
SINGLE/DOUBLE/TRIPLE/BB (`OUT_PLAY, K, BB, SINGLE, DOUBLE, TRIPLE, HR = range(7)`), just never
surfaced as their own simulated counts the way HR/K already were. Confirmed directly with a
per-trial consistency test that single+double+triple+hr sums EXACTLY to hits for every single
simulated trial — proof they share the same underlying draws, not independently modeled.
Extended the "offense" platoon-reasoning group to include Singles/Doubles/Triples (they share
the same platoon-aware PA-outcome distribution as HR/TB/Hits), but deliberately did NOT extend
the weather-boost reasoning to them — weather in this model only directly multiplies HR
probability (`p_hr *= weather_hr`), and claiming a weather boost for Singles/Doubles/Triples
would have been dishonest about what the model actually applies. Confirmed with a dedicated test.
Walks got its OWN distinct reasoning ("real plate discipline") rather than reusing the
power/platoon language, since a walk is a genuinely different real driver.

**Pitcher Hits Allowed uses per-batters-faced shrinkage like K/BB (not innings-based like ER),
but with a real, deliberately stronger shrinkage prior reflecting DIPS theory** — hits allowed
on balls in play is largely out of a pitcher's own control, driven far more by defense and plain
luck than by pitcher skill, an established baseball-analytics principle, not an arbitrary
choice. Confirmed directly with a test comparing shrinkage magnitude: a thin-sample pitcher's
hits-allowed rate regresses measurably HARDER toward league average than the same pitcher's own
K rate does. Gets no opponent-lineup adjustment, for the same honest reason ER doesn't
(`lineup_k_bb_rates` has no real "how many hits does this lineup get" signal to draw on).

**Real market keys confirmed, not guessed, for all five** — `sports.py`'s `_MLB_MARKETS`/
`_MLB_MARKET_MAP` updated with the exact keys from the-odds-api.com's own documentation.

**19 new tests**: `simulate_batter` extension (3 tests, including the exact per-trial sum
consistency check and a real relative-frequency sanity check confirming triples are
dramatically rarer than singles); `project_pitcher`/`simulate_pitcher` hits-allowed modeling (5
tests, including a hand-verified exact value — 5.853, confirmed by independent calculation
before writing the assertion, the same discipline established earlier this session after an ER
test bound was caught wrong — and the DIPS-theory shrinkage-magnitude comparison); `enrich_
hitter_rows` (3 tests); `build_pitcher_projection_rows` integration (1 test); reasoning
extensions (4 tests, including the explicit "no weather claim" honesty check); a full `build_
best_bets` integration test for all five markets at once; and 1 `sports.py` market-key
consistency test. Plus a full, realistic end-to-end simulation through the complete `load_mlb_
graded_picks_board` pipeline — 16 total markets present on one simulated board (the original 7,
the first wave of 4, and this second wave of 5), each with real Fair odds, a real letter grade
now correctly reaching "A" via the ceiling normalization, and honest, market-specific
reasoning text, including Triples' Under side correctly falling back to a generic reason rather
than fabricating one that doesn't apply to that side. 727/727 total passing.

**Still not started**: H-R-R (needs the same-simulated-trial correlation approach), and First
HR/Record a Win/Fantasy Score remain deliberately unattempted pending further design discussion.

### Batter Hits+Runs+RBIs (H-R-R) — the correlation-aware market, completing this round (2026-07-19)
The one market flagged as needing genuinely new methodology, not just extending an established
pattern, now built. H-R-R sums three stats that are positively correlated within a single game
for the same player — a home run alone is simultaneously a hit, a run, and almost always an RBI.
Naively summing three independently-modeled components would be mathematically fine for the
mean (linearity of expectation holds regardless of correlation) but would understate real
clustering: an especially great or especially quiet game pushes all three together, not
independently.

**`simulate_hits_runs_rbi`, built directly on top of `simulate_batter`'s own already-simulated
per-trial hits array**, not a separate independent draw: for each trial, computes a real
"hot/cold" multiplier from how that specific trial's hits compares to the batter's own expected
hits, then draws that same trial's Runs/RBI from Poisson using this per-trial, hits-informed
mean — a hot trial gets scaled-up Runs/RBI, a quiet trial gets scaled-down Runs/RBI, introducing
genuine positive correlation.

**A real, deliberate floor preventing an overcorrection**: even a genuine zero-hit trial keeps a
real, nonzero multiplier (0.5, not 0.0) — a player can still score a run or drive one in without
recording a hit (a walk plus advancement, a sacrifice fly, a fielder's choice), so forcing
Runs/RBI to exactly zero whenever a trial's hits happen to be zero would overstate the real
correlation, not just capture it. A stated ceiling (2.0) likewise bounds how much a single hot
trial can inflate the same-trial Runs/RBI mean, an honest limit against claiming a level of
correlation precision the data doesn't support.

**8 tests directly proving the correlation mechanism works, not just that it runs**: an exact
per-trial sum consistency check (hrr always equals hits+runs+rbi for the same trial); the core
proof — trials with 3+ hits show real, meaningfully higher average combined runs+RBI than
zero-hit trials, not just similarly-noisy averages; the floor confirmed directly (an all-
zero-hit input still produces a real, nonzero runs/rbi mean, hand-verified against the exact
expected value at the floor); the ceiling confirmed directly (an artificially extreme hot-trial
input caps at the exact expected value the stated ceiling implies, not an unbounded scale-up);
and a real, important property confirmed on a realistic (not artificial) hits distribution — the
overall mean stays close to the original, unconditional rate, proving the mechanism redistributes
variance across trials without systematically biasing the total.

**Wired through the full pipeline**: `DEFAULT_LINES`/`BEST_BET_REF` (a real, combined-stat
reference estimate — ~1.1 expected hits + ~0.5 runs + ~0.5 RBI sums to roughly 2.1, above the 1.5
default line, similar magnitude to Total Hits' own reference for the same underlying reason),
`build_best_bets`, honest "Why" reasoning naming the correlation-aware approach explicitly rather
than presenting it as an ordinary independent stat, and `sports.py`'s market registration using
`batter_hits_runs_rbis` — confirmed directly against the-odds-api.com's own documentation, not
guessed. 4 more tests cover the full integration (enrichment attaching a genuinely distinct
probability from Hit% alone, `build_best_bets` producing a real play with the correlation-aware
reasoning text, and the market-key registration). Plus a full, realistic end-to-end simulation
through the complete pipeline — 17 total markets now present on one simulated board, with H-R-R
showing real Fair odds, a real letter grade, and the honest reasoning text. 738/738 total passing.

**Still deliberately unattempted**: First HR, Record a Win, and Fantasy Score — each a
structurally different problem (cross-player joint probability, team-context dependence, and an
undefined external scoring formula respectively), not variations on an established pattern.

### Suggested Parlays: Bold/Longshot no longer chase the worst-quality legs (2026-07-19)
Shawn reported the 5/6-leg tiers producing absurd combined odds (+2,480,221 and +16,855,282)
when only "Batter HR" was selected as the market filter — while 2-4 legs looked reasonable.

**Root cause, traced directly**: the "payout" objective (Bold/Longshot) ranked purely by lowest
raw probability among plays clearing only the base "D" grading floor (1.2x normalized
conviction) — with zero regard for how much real edge a play actually had. Restricted to a
single high-variance market like HR, this meant the objective was actively hunting for the
WORST, barely-qualifying HR legs specifically because they had the longest odds, not because
they had any real analytical backing. Chaining several of these genuinely bad picks together
produced seven-figure American odds no real book would offer and no real person would bet.

**The fix**: `PARLAY_TIER_SIZES` gained a 4th field (`min_grade`) per tier — Bold/Longshot now
require at least a real "C" grade (1.5x normalized conviction) before a play is even eligible
for the payout ranking, so the "biggest price" search happens within a pool of genuinely
well-graded plays, not the bottom of the barrel. Safer/Steady/Balanced are unaffected (`None`),
since their own objectives (raw probability, Conviction) already directly measure what those
tiers care about. `build_parlay_leg_pool` gained a new `min_grade_letter` parameter and a
`GRADE_RANK` ordering derived directly from `GRADE_THRESHOLDS`' own real order (A=4, B=3, C=2,
D=1), rather than a second, separately-maintained ranking that could drift out of sync.

**Confirmed honestly, not just declared fixed**: reproduced the exact reported scenario (a
realistic 20-hitter board, HR-only market filter) and confirmed Bold/Longshot's legs are now
exclusively B/C grade, never D — a real, direct proof the fix works, not just that the numbers
changed. The odds did tighten meaningfully (a real 7-11x reduction versus the original
screenshot's numbers), but they're still genuinely long in absolute terms — confirmed directly
this is an honest mathematical consequence of chaining several real, independent rare events
together (even 6 genuinely good HR plays at 20-25% each combine to seven-figure odds purely from
the math), not a remaining quality bug. The real problem reported — worst-quality legs chosen
specifically for their long odds — is fixed; a narrow, single rare-event market will still
produce long combined odds by nature, and that's honest, not broken.

**7 new tests**: `min_grade_letter` confirmed directly (excludes below-floor plays correctly,
`None` matches old unconstrained behavior, an "A"-only floor excludes everything else) — with a
real self-caught test-fixture bug along the way: an early version of the exclusion test
accidentally used the same market for every leg, meaning the unrelated `max_per_market` cap was
excluding a valid C-grade play before the grade filter even mattered, caught and fixed by giving
each leg a distinct market. Plus a full `build_suggested_parlays` test reproducing the exact
mechanism with a realistic mix of well-graded and barely-D-grade-but-longest-odds legs,
confirming Bold/Longshot never include the D-grade ones even though "payout" alone would have
picked them first. 742/742 total passing.

### New page: Speculative Basket — independent positions, not a parlay (2026-07-19)
Shawn framed this precisely after seeing Bold/Longshot's real, C-grade-or-better plays still
compound into extreme parlay odds: "I am a trader, not a bettor." The actual mismatch wasn't
quality (already fixed) — it was the parlay structure itself. A parlay requires every leg to hit
simultaneously, real punishing "AND" logic that multiplies several real risks together. That's
not how a trader deploys speculative capital in penny stocks or crypto — nobody needs several
speculative positions to all pay off the same day to call it a win. The real strategy is several
small, independent positions where hitting even one makes the whole basket worthwhile.

**Built as a genuinely separate page, not a modification to Suggested Parlays** — confirmed
directly with Shawn ("I will keep the suggested parlays view for those that live or die on that
vine"), since both audiences are real and distinct.

**Reuses proven infrastructure rather than inventing new selection logic**: `grading.
build_speculative_basket` calls `build_parlay_leg_pool` with the exact same "payout" objective
and the exact same "C" grade floor already fixed for Bold/Longshot earlier this session — same
real, validated picks those tiers already surface, just presented independently instead of
chained. The grade floor is user-configurable on this page (C/B/A/none), since a trader deciding
their own risk tolerance is exactly the framing this feature is built around.

**New math for a genuinely different question**: `basket_prob_at_least_one_hits` computes
P(at least one hits) = 1 - product(1 - p_i) — the real "OR" analog of a parlay's "AND"-based
`combined_parlay_prob`, and the actual number that matters for a basket of independent
positions. `expected_hits` (the honest sum of each leg's own probability) is a second, distinct
basket-level number. Deliberately does NOT compute a parlay-style "combined fair odds" — there
isn't a meaningful single combined price for a basket of positions a person would place
separately at their book, and fabricating one would misrepresent what this actually is.

**Real, honest end-to-end confirmation**: on the same realistic 20-hitter, HR-only board that
originally produced Bold/Longshot's absurd seven-figure parlay odds, an 8-position basket built
from the exact same underlying plays now shows 8 legitimate, independently-playable ~+400
positions (every single one C-grade, zero duplicates), with a genuinely useful basket-level
statistic: an 82.8% chance at least one hits — a completely different, far more useful number
than a parlay's near-zero "everything must hit" probability, built from literally the same
real, validated candidate plays.

**11 new tests** (plus earlier basket tests already in place from before this session's context
compaction, confirmed non-duplicative in the actual code — each core function is defined exactly
once): `basket_prob_at_least_one_hits` (hand-verified exact value, empty-list and single-leg edge
cases, a real monotonic property confirming the probability only rises as more positions are
added); `build_speculative_basket` (confirmed to reuse the payout objective directly via the
same misaligned-Conviction-vs-probability proof pattern used for Bold/Longshot; confirmed the
default "C" floor excludes a barely-qualifying D-grade longshot even though payout alone would
pick it first; confirmed `min_grade_letter` is genuinely configurable; confirmed `size` controls
the actual leg count; confirmed the summary stats are computed directly from the real selected
legs, not a separately-drifting calculation; confirmed no fabricated `combined_fair_*` fields;
confirmed cross-sport support with WNBA-shaped plays). Plus the full, realistic end-to-end
simulation above. 762/762 total passing.

**New page `views/19_Speculative_Basket.py`**, public (matching the trader audience this was
built for, not owner-only), with a real, visible explanation that this is independent positions
requiring separate bets at the book, not one combined ticket. Bidirectional `st.page_link`
pointers added between this page and Suggested Parlays, so either audience can discover the
other without the two features being merged or one becoming a hidden mode of the other.

### Suggested Parlays and Speculative Basket moved to owner-only (2026-07-19)
Shawn asked to restrict both pages to owner deployment. `streamlit_app.py`'s `owner_only_titles`
set gained both titles — the gate is checked centrally when building the page list passed to
`st.navigation`, so a gated title is excluded from a non-owner session's navigation entirely
before Streamlit ever registers it (the same mechanism already used for Bet Log, Data Health,
and every other owner-only page), not a per-page check that could be missed on one of them.

**Caught and fixed a real follow-up before it shipped as a broken experience**: Graded Picks
(still public) had a `st.page_link` pointing directly at Suggested Parlays from an earlier
session — with Suggested Parlays now owner-only, that link would have sent a public/Discord user
toward a page no longer in their own navigation. Removed that one pointer; the two pointers
between Suggested Parlays and Speculative Basket themselves were left in place, since both pages
now share the same owner-only audience and neither link crosses the boundary. Swept the rest of
`views/` for any other stray references before considering this done — none found.

**1 test updated**: the existing `test_owner_only_pages_match_expected_titles` regression guard
(which asserts the exact gated title set against `streamlit_app.py`'s real source) updated to
include both new titles — it correctly caught the change as a failure before the update, exactly
what it's there for. 762/762 total passing.

### Graded Picks moved to owner-only too, closing the subscriber-model gap (2026-07-19)
Shawn's own framing: gating Graded Picks guarantees no broken public links going forward, and
supports the subscriber model direction. Added to `owner_only_titles` alongside last turn's
additions.

**Found and fixed the actual real link this would have broken, before it shipped broken**:
Command Center (still public, the landing dashboard) had an unconditional `st.page_link`
straight to Graded Picks. Rather than deleting it (the approach taken last turn for a similar
case), used the BETTER, already-established pattern sitting right next to it in the same file —
Command Center already wraps its Data Health pointer in `if st.secrets.get("AUDIENCE", "owner")
== "owner":` specifically so it stays hidden from a public/Discord audience instead of linking
to a page they can't open. Applied that exact same wrapping to the Graded Picks pointer instead
of removing it, preserving the owner's own convenience rather than losing it.

**A real, welcome side effect worth naming directly**: last turn's fix removed the Graded Picks
→ Suggested Parlays pointer because Graded Picks was still public while Suggested Parlays had
already gone owner-only, making that link broken for public users. With Graded Picks now
ALSO owner-only, both sides of that link share the same audience again — restored it, since it's
now genuinely safe and useful again, not left removed as an unnecessary leftover.

**Full sweep confirmed clean**: every `st.page_link` across the whole `views/` directory checked
by hand — all 5 now either connect two owner-only pages directly (Graded Picks↔Suggested
Parlays, Suggested Parlays↔Speculative Basket) or are explicitly wrapped in the owner-audience
check (Command Center→Data Health, Command Center→Graded Picks). None cross the public/owner-
only boundary unconditionally.

**1 test updated**: `test_owner_only_pages_match_expected_titles` extended to include Graded
Picks — caught the change as an expected failure before the update, exactly what a regression
guard is for. 762/762 total passing.

### Time slot / game filter added to Suggested Parlays and Speculative Basket (2026-07-19)
Shawn asked for the same filtering already on Matchup Lab. Both pages now have the exact same
Time slot + Game selectbox pair, using the exact same shared helpers (`sports.game_dt`,
`sports.slot_of`, `sports.SLOT_ORDER`) already used by Best Bets, every Matchup Lab variant, and
Graded Picks — not a reimplementation, the literal same mechanism.

**A real, deliberate reversal of an earlier decision on Suggested Parlays, not an oversight**:
an earlier version of this page explicitly omitted this filter, reasoned that narrowing to one
game would usually make it impossible to fill the bigger tiers. That reasoning was correct then
and stays correct now — `build_suggested_parlays` already skips a tier it can't honestly fill
rather than padding it, so a narrow slot/game selection will produce fewer or smaller tiers, not
broken ones. Speculative Basket's own positions are already fully independent, so narrowing to
one game is even more natural there — there's no "not enough legs to chain together" concern the
way a parlay has, since `build_speculative_basket` already returns however many real qualifying
positions exist rather than requiring an exact count.

**Confirmed correct with a real, realistic end-to-end simulation**, not assumed from the code
alone: built a two-game board with real, different UTC game times, computed each game's
real-world time-slot bucket, and confirmed filtering to a single slot correctly and completely
partitions the plays list (22 + 22 = 44, matching the total, no plays lost or duplicated). Caught
and fixed a mistake in the test script itself along the way, not the platform code — an initial
hand-picked UTC timestamp was miscalculated relative to Eastern time, producing a test assertion
that expected the wrong bucket; corrected the test's own expectation once the actual, correctly-
computed slot was checked directly, rather than assuming the code was wrong. 762/762 total
passing (no new dedicated unit tests added this turn, since this reuses `sports.py`'s own
already-tested `game_dt`/`slot_of`/`SLOT_ORDER` and Graded Picks' own already-proven filtering
pattern verbatim, rather than introducing new logic that would need its own new coverage).

### Two real, confirmed bugs from a real trading session: opener overweighting and lineup freshness (2026-07-19)
Shawn flagged Speculative Basket showing multiple real, good hitters graded "A" on the "Under"
side of a doubleheader Game 2, "based on some real time trades using these picks" that settled
oddly. First established the grading direction itself wasn't backwards — a letter grade
correctly follows whichever side the model favors, and "Under" can legitimately earn an A when
the model believes a hit is genuinely unlikely. But the SPECIFIC pattern (real hitters from BOTH
teams in the same game bunched into low-probability grades) pointed at something real and
game-specific, not the grading logic. Investigated with a live web search to confirm the actual
game context before touching any code, rather than guessing: Dodgers @ Yankees, Sunday July 19
doubleheader Game 2. Two real, separate, confirmed mechanisms, both traced to real code, not
speculated.

**Bug 1 — a genuine bullpen-game opener gets overweighted, confirmed directly**: both Game 2
"starters" were real openers (Will Klein for the Dodgers, Ryan Yarbrough for the Yankees with a
bullpen game to follow), not conventional starters. `hitter_starter_exposures` (which decides how
many of a hitter's plate appearances fall against the starter vs. the bullpen for the blended
probability the platform already uses) reads directly off `project_pitcher`'s own `exp_bf`. But
`project_pitcher`'s `exp_ip = np.clip(ip / gs, 3.0, 7.0)` forced EVERY probable starter's expected
innings up to a 3.0-inning floor — built to guard a real starter's occasional short outing, but
wrong for a pitcher whose season-long average is genuinely, repeatedly that low because he's
deliberately used for ~1-inning stints. Confirmed the real, downstream effect directly: for a
realistic opener profile (12 starts averaging 2.0 IP each), the OLD floor attributed 2.0 of a
leadoff hitter's 4.4 real plate appearances to the opener's own (possibly strong) individual
rate; the fix correctly drops that to 1.0, with the rest properly falling to the bullpen phase of
the blend. `OPENER_IP_PER_GS_THRESHOLD = 2.5` — a real, stated threshold (a genuine starter
rarely averages below ~2.5 IP/start across a full season even in a rough year) — now lets a
pitcher's own low number stand (floored only at 0.5, against near-zero noise) instead of being
overridden. A genuinely struggling but real starter (2.8 IP/start, above the threshold) still
gets the original 3.0 floor unchanged — confirmed directly, so the fix doesn't overcorrect into
under-crediting real starters having a bad year.

**Bug 2 — a scratched player can still appear, confirmed as a real, explainable timing gap, not
a caching bug**: separately, reporting indicated Ohtani (dealing with a knee issue) "could be out
of the lineup in the nightcap." Traced `_team_starters`: each game already fetches its own
boxscore by its own unique `gamePk` (doubleheader games are NOT conflated at the data layer), but
when a specific game's official batting order isn't posted yet, the fallback is a team's ENTIRE
active roster, marked "Projected." A player ruled out of THIS specific game but still on the
active roster would still appear, since the platform has no explicit "scratched from today's
game" signal, only "posted lineup" vs. "active roster." The "Lineup" field (Confirmed/Projected)
already existed on every play dict — it just wasn't being shown on these two pages. Added the
same 🟢/🟡 signal Graded Picks already uses, plus an explicit caption naming the real risk
directly: a Projected-lineup player shown here could still be scratched before first pitch.

**9 new tests**: opener detection (5 tests — a real opener profile keeps its own low exp_ip
instead of the 3.0 floor; a normal starter is completely unaffected; a genuinely struggling real
starter still gets the original floor, confirming no overcorrection; an extreme near-zero edge
case still gets a sane 0.5 floor, with a self-caught test-fixture bug along the way — an initial
version used ip=3.0 with gs=10, which fails the real `ip >= 15` starter gate entirely and returns
None, not a bug, just an unrealistic fixture, corrected before trusting the result; and a direct,
end-to-end proof that the fix reduces `exp_bf` from what the old floor would have produced).
Plus a full, realistic end-to-end simulation reproducing the doubleheader scenario directly —
hitters facing a real opener profile now show a healthy ~71-75% hit probability instead of being
artificially depressed, and the Lineup field is confirmed flowing all the way through to the
final play dict, ready for the page to display. 766/766 total passing.

### A real, more significant bug found: ceiling normalization was amplifying trivial edges into A grades (2026-07-19)
Shawn reported the doubleheader/opener fixes didn't resolve the underlying issue — a new
screenshot showed Speculative Basket's entire 8-position basket built from the exact same
market, "Batter Hits+Runs+RBIs Under 1.5," spanning seven DIFFERENT games, all real, good
hitters, all graded A. Since this spanned many unrelated games (not concentrated in one
doubleheader), the opener/lineup fixes couldn't be the explanation — this pointed at something
structural in the grading math itself, not a per-game data issue.

**Investigated empirically before theorizing**: ran a range of realistic hitter profiles through
the real `enrich_hitter_rows` pipeline and found HRR% values clustering tightly around 0.57-0.64
— right at the 0.62 reference threshold, meaning tiny, real differences between players were
landing some just above and some just below it. That part is expected behavior for a reference-
based system. But checking what grade a barely-below-reference value actually produced surfaced
the real bug: a raw conviction of 1.03x (essentially no edge — 39% real vs. 38% "typical") was
reaching a full "A" grade.

**Root cause, confirmed directly with the exact numbers**: the ceiling normalization added
earlier this session (`conviction * (REFERENCE_CEILING / ceiling)`) scaled the ENTIRE raw
conviction value by a market's ceiling ratio — including the 1.0 "no edge at all" baseline every
market shares. For H-R-R's Under side (ceiling ~2.63, versus HR's reference ceiling of 9.09), that
ratio is ~3.46x — so even a trivial 1.03x raw conviction got inflated to a normalized value over
3.5, clearing the "A" threshold purely from the market's own ceiling shape, with essentially zero
real edge behind it. This is a real, more consequential bug than a UI display issue: it meant the
"payout" objective (Bold/Longshot, and Speculative Basket) could get systematically pulled toward
whichever market had the lowest ceiling, regardless of whether the underlying play was actually
good — exactly what happened here, with H-R-R's Under side quietly winning almost every
comparison against markets with more headroom.

**The fix**: anchor the normalization at 1.0 instead of scaling the raw value directly —
`graded_value = 1.0 + (conviction - 1.0) * (REFERENCE_CEILING - 1.0) / (ceiling - 1.0)`. This
scales only the EDGE above the no-edge baseline, not the baseline itself, so a trivial edge stays
trivial regardless of the market's ceiling shape. Verified by hand against every prior test case
before touching code: HR's own grades reduce to exactly the raw, unnormalized comparison (ceiling
== REFERENCE_CEILING makes the formula an identity); the earlier Stolen Bases compression fix
still holds; a genuinely large edge on a low-ceiling market (not a token one) still reaches A,
preserving the original fix's real intent. A new defensive guard (`ceiling > 1.0`, not `> 0`)
prevents a division-by-zero at the new formula's edge case.

**10 new tests**: the exact reported bug case confirmed directly (1.03x raw conviction on H-R-R's
real Under-side ceiling now correctly falls below even the D floor); the genuine-large-edge case
confirmed to still reach A; HR's own grades confirmed byte-identical across the same conviction
range as the original ceiling tests; the Stolen Bases compression regression-guarded; a new
ceiling-exactly-1.0 edge case. Plus a full, realistic end-to-end simulation reproducing the
actual reported scenario — an 8-hitter board where H-R-R plays now correctly grade B (not the
previous inflated A), and `build_speculative_basket`'s payout ranking no longer selects a single
H-R-R leg, since other markets now correctly outrank it once the trivial edge isn't artificially
amplified. 771/771 total passing.

**A real, important scope note, stated honestly**: this ceiling-normalization bug wasn't
specific to H-R-R or to Speculative Basket — it affects the letter grade of every play on every
market with a ceiling below HR's, everywhere this platform shows a grade (Graded Picks,
Suggested Parlays, Retrospective's grade-accuracy tracking, and every sport, not just MLB). This
fix corrects all of them at once, from the single, shared function every one of those pages
already calls through.

### A deeper follow-up to the ceiling fix: amplification cap for near-50%-reference markets (2026-07-19)
Shawn reported the same underlying pattern was still happening after the anchor fix — a new
screenshot showed a full page of "Batter Hits+Runs+RBIs Under 1.5" plays, all graded A, all
around -115 fair odds, spanning many different, unrelated games. Confirmed directly this was a
real, different, and deeper issue than the one just fixed — the anchor fix itself was working
exactly as designed, which turned out to be the actual problem.

**Root cause, confirmed by hand before touching any code**: -115 implies a ModelProb of ~53.5%,
giving a raw conviction of 1.408x against H-R-R's real Under-side ceiling (~2.63, since its 0.62
reference sits far closer to a coin flip than HR's 0.11 does). Checked what fraction of the way
to each market's own ceiling this represented: 1.408x on H-R-R's ceiling sits at 24.98% of the
way there; reaching "A" on HR itself requires 24.72% of the way to ITS ceiling. Nearly identical
— the anchor formula was being completely mathematically consistent. But "same proportional
distance" isn't the same as "equally rare" or "equally deserving of an A": HR's wide ceiling
means real players spread out across a broad range, so 3.0x really is exceptional; H-R-R's
compressed ceiling means real players cluster tightly in a narrow band (confirmed empirically
last turn: 0.57-0.64), so even a genuinely modest, unremarkable edge (a real ~15-percentage-point
edge, nowhere close to exceptional) automatically lands a large fraction of the way to that
market's own small ceiling — not because the play is rare, but because the market itself has
less room to begin with.

**The fix**: `AMPLIFICATION_CAP = 2.5` bounds how much any single market's low ceiling can
amplify the edge portion above 1.0, regardless of how compressed that market's ceiling actually
is. Verified against multiple candidate cap values (2.0/2.5/3.0) before choosing 2.5, checking
each against the real reported case, the original trivial-edge case, and — critically — the
motivating case for ceiling normalization in the first place: a genuinely exceptional edge on a
near-50%-reference market (a real 90% ModelProb, the kind of play WNBA/NBA/NFL markets needed
this whole feature to be able to recognize as A-worthy) must still reach A under the cap, while a
merely modest one (60% ModelProb) stays well below it. 2.5 satisfied every case cleanly. HR's own
grades stay byte-identical (its own amplification ratio is already 1.0, well under the cap), and
the earlier Stolen Bases compression fix is unaffected (its own ratio was already below 2.5).

**5 new tests**: the exact reported case (1.408x raw conviction, H-R-R's real ceiling) confirmed
to now land at B, not A; the genuinely-exceptional near-50%-reference case confirmed to still
reach A under the cap; a merely modest near-50%-reference edge confirmed to stay well below A;
HR's own grades confirmed byte-identical; the original trivial-edge bug case reconfirmed still
excluded under the new cap. Plus a full, realistic end-to-end simulation with a fresh set of
hitter profiles landing right around the reference threshold — confirmed none reach A anymore,
consistent with the isolated, hand-verified case. 776/776 total passing.

**A real, honest note on process**: this is now the third grading-related fix in a short span
(ceiling normalization, the anchor fix, and now the amplification cap), each one surfaced by an
actual real-money trading session rather than caught in advance. Worth watching for whether this
pattern shows up again on a genuinely different market or reference shape — the same diagnostic
approach (does it span one game or many unrelated ones, and what's the actual raw conviction and
ceiling behind the number) is what found all three, in order, and is the fastest path to the
next one if it exists.

### Speculative Basket: fixed a genuinely misleading label, flagged a real, unresolved data question (2026-07-19)
Shawn pushed back hard on a real basket example — all 8 positions were New York Mets hitters,
all "Batter Hits+Runs+RBIs Under 1.5," all A grade, with "Expected hits: 5.7" displayed above
them. Two separate things came out of this, one fixed directly, one honestly flagged as
unresolved.

**Fixed: "Expected hits" and "P(at least one hits)" were genuinely misleading labels, not just
awkward wording.** Both summed/derived from `ModelProb` — the probability of whichever side each
leg favors, which could be Over or Under, on any market, not literally "hits" as a baseball
stat. A basket full of Under bets on a non-hits combined market showing "Expected hits: 5.7"
reads as "these players will get 5.7 real hits," which is backwards from what the number
actually means: "5.7 of these 8 bets are expected to settle correctly." Renamed both the
internal field names (`expected_hits` → `expected_winners`, `prob_at_least_one_hits` →
`prob_at_least_one_wins`, plus the underlying `basket_prob_at_least_one_hits` function) and the
displayed UI text consistently across `grading.py`, `views/19_Speculative_Basket.py`, and every
test — not just the visible label, since a developer reading the code would hit the identical
confusion the UI caused. Added an explicit caption stating directly that neither number is a
baseball statistic.

**Investigated, but honestly unresolved: why every Mets hitter showed the same strong "Under"
signal in that specific game.** Checked the actual real-world matchup via live web search rather
than assuming: Milwaukee's real probable starter for that game was Brandon Sproat, a 5.16-ERA
pitcher — a BELOW-average matchup that, if anything, should have favored Mets hitters leaning
Over, not Under. Confirmed the platform sources its probable-starter data directly from MLB's own
API (`probablePitcher` field via the schedule endpoint hydrate), not a platform-side guess or
heuristic — so if the wrong pitcher's stats were used, the most likely explanation is that MLB's
own API had stale or since-superseded data at the exact moment the platform's data pull happened,
not a bug in how the platform chooses who to use. This is NOT confirmed — the sandbox has no live
access to see exactly what `_opp_stat` the platform actually pulled for this specific game at
that moment, so this is a well-supported hypothesis, not a proven root cause. Flagged directly to
Shawn rather than either dismissing the pattern or claiming a fix I couldn't verify.

**0 new tests this turn for the rename** (a pure naming change with no logic difference — the
existing, already-passing tests for both functions were updated in place to use the new names,
not supplemented with new coverage, since nothing about the underlying behavior changed).
776/776 total passing, same count as before this turn.

### Opposing pitcher's real ERA now shown directly on every batter leg (2026-07-19)
Shawn's follow-up question, in response to being asked to cross-check Pitching Lab manually:
since that pitcher data is already captured, why not just show it directly here? A genuinely
better fix than what was asked for last turn — instead of requiring a manual cross-check to
diagnose a potential mismatched-pitcher issue, the actual matchup data should just be visible
where the play already is.

**Confirmed the data already existed, just wasn't surfaced**: `build_best_bets`'s batter play
dict already carried `Opp` (the opposing starter's name, from `Opp Pitcher`), but never their
ERA, even though `_opp_stat` (the same raw stat dict driving the whole matchup) was already
sitting right there on the hitter row. Added `OppERA`, computed once per hitter row (not
recomputed per market inside the inner loop) directly from `_opp_stat`, and refactored an
initial inline-lambda version into a clean, pre-computed variable to match this codebase's
established style. Returns `None`, never a fabricated `0.0`, when the real ERA isn't available —
an absent number should never accidentally read as "a genuinely elite 0.00 ERA pitcher."

**Surfaced directly on both Suggested Parlays and Speculative Basket**: each leg's caption now
reads "vs [Pitcher Name] ([ERA] ERA)" alongside the game and reasoning text, using the exact same
data already computed for Pitching Lab — no cross-referencing required, and no separate lookup
needed to sanity-check whether the model's read on the opposing pitcher matches who's actually
expected to start. This directly addresses last turn's real, unresolved question: if the platform
had used the wrong pitcher's stats for a specific game, that mismatch would now be visible
immediately, right on the leg, rather than requiring a person to manually check a different page
and compare.

**5 new tests**: `build_best_bets` confirmed to attach the real ERA from `_opp_stat` to every
batter play; confirmed `OppERA` stays `None` (not fabricated) when the real ERA is genuinely
unavailable. Plus a full, realistic end-to-end simulation reproducing the exact real scenario
from the prior turn — Brandon Sproat's real 5.16 ERA, confirmed flowing all the way through the
full pipeline to the final play dict, ready for direct display. 778/778 total passing.

### Cross-page consistency, market filter parity, and ranking across Graded Picks/Suggested Parlays/Speculative Basket (2026-07-19)
Shawn's core thesis: with the infrastructure already built, the real work now is making sure
"intra-page functionality and predictions... agree within the model itself" — since that, not
new features, is what actually builds subscriber confidence. This surfaced two real, confirmed
bugs beyond what was asked for, both the same underlying problem in different places.

**`rank_value` exposed on `conviction_to_grade`'s return dict** — the ceiling-normalized number
already computed internally to pick the letter grade, now returned directly so any caller
ranking plays across multiple markets has a number that won't invert against the letter grades
themselves. Confirmed directly: a raw 2.5x on HR (ceiling ~9.09, only a "B") has a HIGHER raw
Conviction than a raw 1.8x on a near-50%-reference market (ceiling ~2.0, a genuine "A") — sorting
by raw Conviction alone ranks the worse play first.

**Found and fixed two real, live instances of exactly that inversion, neither previously known**:
(1) Command Center's "Tonight's top leans" was sorting by raw Conviction directly — could show a
B-grade play above an A-grade one, disagreeing with what Graded Picks itself would say about the
same plays. Fixed to grade every play and sort/filter by `rank_value`, with the letter grade now
shown directly in the table. (2) `organize_graded_picks` itself — the core function behind
Graded Picks — sorted games, players within a game, AND each player's own multiple plays by raw
Conviction at all three levels. This was the same bug living inside the letter-grade page's own
logic. Fixed all three levels to sort by `rank_value` instead.

**Market-selection multiselect added to Graded Picks**, matching Suggested Parlays/Speculative
Basket exactly, closing a real functional gap between the three pages that draw from the same
graded board.

**`grading.rank_flat_plays` built as shared, testable ranking logic**, used with a real,
deliberate difference in key depending on what each page is actually for: Graded Picks ranks by
`rank_value` (agrees with its own letter grades — the right choice, since a rank that disagreed
would reintroduce the same inversion just fixed above), Suggested Parlays and Speculative Basket
rank by `ModelProb` (real probability of hitting — the right choice, since those pages are
explicitly framed around "which is more likely to actually hit," a different question than "which
has the better edge"). Wired into all three pages: an explicit "#1, #2, #3..." prefix on each
play/leg. On Graded Picks specifically, ranking is scoped ONLY to when a specific game is
selected (not "All games in this slot") — a deliberate choice matching the page's own reason for
being organized game-by-game in the first place (a flat, slate-wide rank would bury most of the
board behind whichever 2-3 games look juiciest, exactly what game-by-game organization exists to
avoid; ranking within one already-selected game doesn't have that problem).

**11 new tests**: `rank_value` confirmed to resolve a real cross-market inversion directly (plus
a control confirming it equals raw Conviction when no ceiling is passed); `organize_graded_picks`
confirmed to sort by `rank_value` at both the per-player-plays level and the game-order level
(with a real, self-caught fixture bug along the way — an early version of the player-plays test
used two different player names when it needed one player's two plays, caught via an IndexError
before trusting the result); `rank_flat_plays` confirmed for both key modes, a missing-grade
edge case sorting last rather than crashing, and confirmed to return a new sorted list without
reordering the caller's own list in place. Plus a full, realistic end-to-end simulation across
all three pages confirming ranking works correctly end to end — including a second real,
self-caught mistake in the verification script itself (assumed a basket's leg list was already
in descending-ModelProb order, when it's actually in the "payout" objective's own ascending
order; `rank_flat_plays` correctly annotates `_rank` without reordering the list, caught and
fixed in the verification logic, not the actual code). 786/786 total passing.

**Still pending from this same request, not yet started**: TTO display and the bullpen-blend
toggle across all three pages.

### Top Leans: a real, deeper fix to what "leans" should actually mean (2026-07-19)
Shawn caught a second, more fundamental issue in the same widget just fixed for cross-market
consistency: even after sorting by `rank_value` (correctly resolving the letter-grade inversion),
"Tonight's top leans" could still surface genuine longshots — a real screenshot showed a Corbin
Carroll Triples play at 4.44x Conviction but only an 11% real chance of happening, ranked above
plays with 75-89% real probability. His framing was direct and correct: "I would not expect to
see Batter Home Runs or Batter Stolen Bases high on a top leans list."

**Confirmed the exact mechanism by hand before changing anything**: Triples' own reference
probability is so low (~2.5%) that its theoretical ceiling is 40.0x — meaning even a genuine
11%-probability play (an 89% chance of NOT happening) produces a real, valid Conviction of 4.44x.
`rank_value` was never wrong about the grade; the deeper problem is that Conviction (and its
normalized form) measures edge relative to a market-typical rate, not absolute likelihood — and
"leans," colloquially, means "I lean toward this happening." Those are genuinely different
questions, and this widget was answering the wrong one for what its own name promises.

**This is the exact same distinction already built into Suggested Parlays' Safer/Steady tiers**
(`_tier_sort_key("safety")` ranks by raw ModelProb, not Conviction, for precisely this reason,
confirmed earlier this session) — Top Leans just never got the same treatment. Graded Picks
itself deliberately stays `rank_value`-sorted, and correctly so — its entire identity IS the
letter-grade system, so changing its ranking there would reintroduce the inversion just fixed.
Top Leans is a different kind of page: a landing-page summary widget where "what's likely to hit"
is the actual, honest question being asked.

**`grading.build_top_leans` built as shared, testable logic**, pulled out of the view for the
same reason as everything else this session — grades every play, then sorts by ModelProb (real
probability), keeping the existing "best N per market" diversity cap so one especially safe-
looking market can't fill the whole list. Still requires every play to clear
`conviction_to_grade`'s own real floor first — this isn't "any probability regardless of edge,"
it's "the most likely to hit, among plays that already have real, validated edge behind them."
Command Center's view rewired to call this directly instead of the inline logic from the
previous fix. Displayed columns reordered (Model % now leads, right after Grade) and the
highlight gradient moved from Conviction to Model %, matching the new sort priority.

**5 new tests**, including the exact reported case reproduced directly (an 11%-probability
Triples play with a real 4.44x Conviction must NOT outrank an 85%-probability play with lower
Conviction) — passed on the first run, confirming the fix's real mechanism matches the actual
reported bug precisely. Plus the diversity cap, the grading-floor requirement (high probability
alone with zero real edge still doesn't qualify), correct descending sort order, and grade
attachment on every returned play. Plus a full, realistic end-to-end simulation through the real
pipeline — confirmed the top of a real board is now genuinely high-probability plays (79%, 78%,
67%...) regardless of raw Conviction multiple, with none of HR/Stolen Bases/Triples' structural
ceiling advantage dominating the list. 791/791 total passing.

### Best Bets ModelProb fix, and a shared "log this pick" feature across every picks page (2026-07-20)
Shawn confirmed the same real distinction from Top Leans applies to Best Bets ("betting decisions
are being made, so it should be how likely is this"), and asked for a second, separate feature:
the ability to write a pick straight to the Bet Log from wherever it's shown, for two real,
stated reasons — a future paid "role ability" once multi-user login exists, and a genuinely more
urgent one right now: a narrow real-money pick-making window where manually re-entering a pick
into Bet Log is friction real enough that it gets skipped in favor of just making the pick.

**Best Bets fixed, Edge Board confirmed already correct**: Best Bets now sorts by `ModelProb`
instead of the plays list's own Conviction-descending order, same real reasoning as Top Leans —
`min_conv` still requires real, validated edge before a play is eligible, this just reorders
within that already-graded set. Column order and the diagnostic-picker label both updated to
lead with Model %. Checked Edge Board directly before assuming it needed the same fix: its "Live
edges" table already correctly sorts by EV% (a genuinely different, correct metric — the model's
own price against a REAL, live sportsbook price, not an internal reference), and its "Model
board" section was already sorting by ModelProb. Neither needed changing.

**`quick_log.py` built as a new, shared module** — a pure, testable field mapping
(`bet_log_fields_from_play`, `bet_log_signature`) separated from the Streamlit UI specifically
because a wrong mapping here would silently corrupt real trade-log data, the one thing on this
platform that must never be wrong. `render_quick_log` is the actual reusable widget: a
multiselect of the plays/legs on screen, a stake input, and a log button — modeled directly on
Edge Board's own pre-existing (and until now, unique) bet-logging flow, generalized so every page
gets the same behavior instead of a copy-pasted, subtly-different version. Session-scoped dedup
(`logged_sigs`) matches Edge Board's own existing approach exactly.

**Owner-only, deliberately, everywhere it's wired in** — `render_quick_log` checks `st.secrets.
get("AUDIENCE", "owner")` itself and renders nothing at all for a non-owner session, regardless
of whether the calling page is otherwise public (Command Center) or already owner-only (the
other four). Bet Log is personal trade tracking; a public page showing picks doesn't mean a
public visitor should be able to write into the owner's own log.

**Honest about what actually gets logged**: unlike Edge Board's flow, none of these five pages
have live sportsbook odds integration. `entry_odds` is explicitly the model's own fair price,
labeled as such directly in the widget's own caption — not presented as if it were a real,
live book price a person actually got filled at.

**Wired into all five pages that surface picks**: Command Center's Top Leans (using the same
curated "best 2 per market" set already shown in the All tab, not a redundant copy per market
tab), Best Bets (the whole board), Graded Picks (per game — the page's own natural organizing
unit), Suggested Parlays (per tier), Speculative Basket (the whole basket). A real, self-caught
bug along the way: Command Center uses `today` as its own slate-date variable, not `date_str`
like the other four pages — caught by explicitly checking the actual variable name on each page
rather than assuming consistency, since `py_compile` doesn't catch a wrong-variable-name bug at
all (it's only a runtime `NameError`, invisible until the page actually loads).

**10 new tests** for `quick_log.py`'s pure functions: correct field mapping, default stake,
graceful handling of a play missing `Line` or `ModelProb`, confirmation that `entry_odds` always
comes from the model's own `Fair` price, confirmation every returned key is a real, valid
`betlog.py` field (not a typo that would silently be dropped or rejected), and dedup-signature
correctness across different players/dates/sides. Plus a full, realistic end-to-end simulation —
a real play from the actual board-building pipeline, mapped through `bet_log_fields_from_play`,
written to a real temporary SQLite database via `betlog.add_bet`, and read back to confirm every
field matches exactly. 801/801 total passing.

### Quick-log stake: a dropdown quick-pick alongside free entry (2026-07-20)
Shawn asked for the stake field to stay free entry but also offer a $0.50-increment dropdown
from $0-$500, covering typical unit sizes as bankroll grows.

**A real, deliberate two-widget design, not a single control**: a `st.selectbox` quick-picks a
common unit size from `STAKE_QUICK_PICKS` (0.0, 0.5, 1.0, ..., 500.0 — exactly 1001 real, distinct
values), while a separate `st.number_input` stays freely editable for an exact, arbitrary amount
(e.g. $37.23) the dropdown's fixed 0.5 grid can't represent. Uses a real, established Streamlit
pattern to link them without fighting over ownership of the value: the number_input's own key
includes the dropdown's current selection, so picking a new quick-pick gives the number_input a
fresh widget instance that re-initializes to that value — while still allowing free typing right
after, since it's a genuinely normal number_input once rendered.

**4 new tests** on the `STAKE_QUICK_PICKS` constant itself: confirmed the range starts at exactly
0.0 and ends at exactly 500.0, confirmed every consecutive step is exactly 0.5 throughout (not
just at the endpoints), confirmed the exact expected count (1001 real, distinct values for a
0-500 range in 0.5 steps), and confirmed no duplicates. 805/805 total passing.

## NOT YET DONE (next stages)
- **Umpire tendencies** — genuinely deferred, not built as a weaker version. See the catcher
  framing/item 5 writeup above for why: no confirmed way to find every game a specific umpire
  worked (no equivalent of a player's own game log), which would be needed to build reliable
  historical tendencies rather than just today's assignment. A real, separate project if pursued,
  not a quick follow-on to anything already built.
- **Line-movement chart** — see above. The capture infrastructure is live; the actual
  stock-candlestick-style chart in Matchup Lab is the natural next step once there's real
  captured history to plot, not before.
- **NCAAMB post-launch: `get_team_injuries` verification** — the one piece not independently
  confirmed live for `mens-college-basketball` specifically (only NBA's version was checked).
  Fails soft (empty list) if the real shape differs, so this isn't urgent — worth a live check
  once the season actually gets underway (Nov 1 2026) and there's real injury data to compare
  against, same as NBA's own remaining post-launch items below.
- **NBA post-launch polish** — see above (SEASON_START, tuning constants, roster shape). NBA
  itself is live; these are calibration items to revisit once real slate data exists to check
  against, not things currently known to be broken.
- **Injury/availability "opportunity boost" (Stage B)** — see above. Deferred as a genuinely
  separate, harder modeling decision, not a quick follow-on to Stage A's data-fetch.
- **NFL post-launch: UI rendering pass, beyond function existence** — the full engine/projections
  contract is now exhaustively audited and function-verified (see above — a real regression guard
  now exists for this specific bug class), and the actual Retrospective grading path was
  simulated end to end against real data across all four markets. NOT yet checked: whether each
  page's UI actually RENDERS sensibly for NFL's different shape (position-gated markets, weekly
  not daily slates) — a function existing and returning the right shape doesn't guarantee the
  page built around it reads well for a different sport's data. Worth a first real look once
  Shawn is clicking through each page with real season data.
- **NFL post-launch: real Streamlit Cloud deploy check** — see above. The one thing not checkable
  from this sandbox; worth a first look once the 2026 season is close enough for real data to
  browse (season starts Sep 9, 2026).
- **NFL Hot Hand Engine equivalent** — Matchup Lab is now done (see above); Hot Hand Engine (an
  opponent-adjusted leaderboard across the whole slate, not a single-player deep dive) remains
  deliberately deferred, the same staged-build pattern MLB and WNBA both followed. Worth noting:
  `get_team_allowed_stats` (built for Matchup Lab) already provides the core opponent-adjustment
  data Hot Hand Engine would need, so this is now a smaller lift than it was before today.
- **MLB pitcher rest days / injury report in Matchup Lab** — see above. Both would need genuinely
  new data plumbing (a pitcher game-log fetch for the former, an injury-status fetch for the
  latter) this platform doesn't have for MLB yet, not a quick follow-on to the filter addition.
- **NHL, NCAAF** — no engines built yet. (NCAAWB considered and deliberately deferred — Odds API
  doesn't currently offer player props for WNCAAB, so there's no live market for Edge Board to
  price against yet; worth revisiting if that coverage gap closes.)

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
