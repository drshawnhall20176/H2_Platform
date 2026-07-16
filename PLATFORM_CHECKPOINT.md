# H2 Sports Platform — Build Checkpoint

**This is the multi-sport platform build.** It is the live source of truth (MLB + WNBA + NBA on
one sport-selector foundation). MLB runs exactly as the standalone did originally; WNBA and NBA
are both real, priced sports now — not placeholders.

## What's in this checkpoint (all tested — 330/330 tests green)

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

## NOT YET DONE (next stages)
- **NBA post-launch polish** — see above (SEASON_START, tuning constants, roster shape). NBA
  itself is live; these are calibration items to revisit once real slate data exists to check
  against, not things currently known to be broken.
- **Injury/availability "opportunity boost" (Stage B)** — see above. Deferred as a genuinely
  separate, harder modeling decision, not a quick follow-on to Stage A's data-fetch.
- **Real line movement history (candlestick-proper)** — the Matchup Lab trend chart overlays a
  single CURRENT line on historical game values; a true line-movement view (the line itself
  moving over time, the closer stock-candlestick analog) still needs `capture_closing_lines.py`
  changed to log every snapshot instead of overwriting the latest one.
- **`nfl_engine.py`/`nfl_projections.py`** exist but are untested and `nfl_data_py` isn't in
  `requirements.txt` yet; markets/market_map in the registry are still empty. Flipping NFL on is
  Stage 4, not started.
- **NHL, NCAAF, NCAAMB** — no engines built yet.

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
