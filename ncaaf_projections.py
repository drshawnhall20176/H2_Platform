"""
ncaaf_projections.py — turns ncaaf_engine's slate rows into priced probabilities.

Matches projections.py's OUTPUT CONTRACT (build_projection_index / default_board_from_index /
DEFAULT_SIMS) — the same contract every other sport's projections module follows, which is what
lets Edge Board consume MLB/WNBA/NBA/NCAAMB/NFL and now NCAAF through the same code path via
sports.active().projections.

A REAL METHODOLOGICAL DIFFERENCE FROM EVERY OTHER SPORT HERE, NOT HIDDEN: every other sport's
simulate_player_stat BOOTSTRAPS from a player's real recent-game log (resample with replacement,
build an empirical distribution). NCAAF genuinely has no per-game log to bootstrap from — see
ncaaf_engine.py's own docstring: CFBD's cached season stats are SEASON TOTALS, not per-game
rows. This module instead draws from a PARAMETRIC (Normal) distribution centered on the row's
own season-average per-game rate (already computed by ncaaf_engine.player_row), with a fixed,
explicitly UNVALIDATED coefficient of variation as its spread (_RATE_CV below) — there's no real
game-to-game variance to calibrate against yet. This is worth remembering when reading any NCAAF
probability this module produces: the MEAN is a real, CFBD-sourced season average; the SPREAD
around it is an assumption, not measured. Upgradable once ncaaf_engine.py adds real per-game
logs (via CFBD's get_game_player_stats, at the extra API-call cost documented there).

STAGED SCOPE, HONEST ABOUT WHAT'S NOT HERE YET, same pattern nfl_projections.py's own docstring
uses: this covers what Edge Board and Best Bets need. A Hot Hand Engine-equivalent, Matchup
Lab-equivalent, anytime-TD board, and QB efficiency table do NOT exist here yet — deliberately
deferred, not silently missing.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from projections import (  # genuinely sport-agnostic — reused, not duplicated
    prob_over, normalize_name, prob_to_decimal, prob_to_american, curate_selections,
)
import basketball_projections as BB_P   # shrink_prob only — pure probability math, zero
                                        # basketball-specific assumptions, same reuse nfl_
                                        # projections.py's own docstring already justifies
import config_ncaaf as CFG

DEFAULT_SIMS = CFG.DEFAULT_SIMS

# The unvalidated spread assumption this module's own docstring is explicit about — see there
# for why. 0.45 is a middle-of-the-road guess for football-stat game-to-game noisiness, not a
# measured value; the first priority once real per-game logs exist is replacing this constant
# with an empirical estimate, not tuning it further as a guess.
_RATE_CV = 0.45
_MIN_SCALE = 0.5   # floor on the Normal's scale so a very small rate doesn't collapse to a
                   # near-deterministic (zero-variance) distribution

# odds_market_key -> (slate-row field, display name, default line for the model-only board).
# Row field names match ncaaf_engine.player_row's own output exactly (PassYds/RushYds/
# Receptions/RecYds — already season-average PER-GAME rates, not totals). Default lines are
# round-number, model-only-board fallbacks (used only before a live line is fetched) — rough
# placeholders informed by general football norms, NOT calibrated against confirmed real NCAAF
# season averages the way NFL's own defaults were — worth tightening once real usage exists.
_MARKET_SPEC: Dict[str, Tuple[str, str, float]] = {
    "player_pass_yds":      ("PassYds",    "Pass Yards",      219.5),
    "player_rush_yds":      ("RushYds",    "Rush Yards",      49.5),
    "player_receptions":    ("Receptions", "Receptions",      4.5),
    "player_reception_yds": ("RecYds",     "Receiving Yards", 54.5),
}

# The row-level field names above (PassYds/RushYds/...) are NOT the same strings as the raw CFBD
# per-game cache's own column names (passing_YDS/rushing_YDS/... -- ncaaf_engine.py's per-game
# cache, same confirmed columns as the season-stats cache). A real bug this mapping exists to
# prevent: _simulate_for_row reading a _recent_games entry with the WRONG key (e.g. "PassYds"
# instead of "passing_YDS") would silently get None -> 0 for every real game, bootstrapping from
# a set of zeros instead of the player's actual real values -- caught directly by testing this
# path against real per-game entries before shipping, not assumed correct.
_ROW_FIELD_TO_CFBD_COL: Dict[str, str] = {
    "PassYds": "passing_YDS", "RushYds": "rushing_YDS",
    "Receptions": "receiving_REC", "RecYds": "receiving_YDS",
}


def market_list() -> List[Tuple[str, str, str]]:
    """[(market_key, row_field, display_name), ...] — public, iterable form of _MARKET_SPEC."""
    return [(mkey, col, disp) for mkey, (col, disp, _line) in _MARKET_SPEC.items()]


def default_line(market_key: str) -> Optional[float]:
    spec = _MARKET_SPEC.get(market_key)
    return spec[2] if spec else None


def _dist(samples: np.ndarray) -> np.ndarray:
    """Normalized histogram: index i -> P(outcome == i). Same shape/semantics as
    projections._dist, so odds_api.compute_edges works identically for every sport."""
    counts = np.bincount(samples.astype(np.int64)).astype(np.float64)
    total = counts.sum()
    return counts / total if total > 0 else counts


def _signal(player, team, game, market, side, line, prob, projection, **extra) -> Dict:
    prob = float(round(prob, 4))
    sig = {
        "Player": player, "Team": team, "Game": game, "Market": market,
        "Side": side, "Line": line, "ModelProb": prob, "Projection": round(float(projection), 2),
        "FairDec": prob_to_decimal(prob), "FairAm": prob_to_american(prob),
        "BookOdds": None, "Implied": None, "EdgePct": None,
    }
    sig.update(extra)
    return sig


def simulate_player_stat_parametric(rate: float, sims: int, rng: np.random.Generator) -> np.ndarray:
    """PARAMETRIC FALLBACK simulation from a season-average per-game RATE, used only when no
    real per-game log exists for this player yet (refresh_player_game_stats hasn't been run, or
    this player/week has no cached rows) -- see this module's own docstring for why NCAAF needed
    this fallback at all, and simulate_player_stat_bootstrap below for the real, preferred path
    once per-game data exists. Draws from Normal(rate, max(rate * _RATE_CV, _MIN_SCALE)), clipped
    to non-negative integers. Returns an empty array for a non-positive rate."""
    if rate is None or rate <= 0:
        return np.array([], dtype=np.int64)
    scale = max(rate * _RATE_CV, _MIN_SCALE)
    draws = rng.normal(loc=rate, scale=scale, size=sims)
    return np.clip(np.round(draws), 0, None).astype(np.int64)


def simulate_player_stat_bootstrap(recent_values: List[float], sims: int,
                                   rng: np.random.Generator) -> np.ndarray:
    """Bootstrap `sims` draws (with replacement) from a player's REAL recent-game values for one
    stat -- identical method to nfl_projections.simulate_player_stat and every other sport's own
    bootstrap, now that ncaaf_engine.player_recent_games provides real per-game data (via CFBD's
    get_player_game_stats, added after NCAAF's initial parametric-only launch). This is the
    PREFERRED path; build_projection_index/build_best_bets use this whenever a row has real
    recent games, falling back to simulate_player_stat_parametric only when it doesn't. Returns
    an empty array if there's no game log to sample from."""
    if not recent_values:
        return np.array([], dtype=np.int64)
    draws = rng.choice(np.asarray(recent_values, dtype=np.float64), size=sims, replace=True)
    return np.clip(np.round(draws), 0, None).astype(np.int64)


def _simulate_for_row(r: Dict, col: str, sims: int, rng: np.random.Generator) -> np.ndarray:
    """Picks bootstrap (real per-game values) over the parametric fallback whenever real recent
    games actually exist for this row -- the single decision point both build_projection_index
    and build_best_bets share, so they can never drift apart on which method a given player uses.

    `col` is the ROW-level field name (e.g. "PassYds", matching player_row's own output) -- used
    directly for the parametric path (r.get(col)), but _recent_games entries use ncaaf_engine's
    raw per-game CFBD column names instead (e.g. "passing_YDS"), so those are read through
    _ROW_FIELD_TO_CFBD_COL, not `col` itself."""
    recent = r.get("_recent_games") or []
    if recent:
        cfbd_col = _ROW_FIELD_TO_CFBD_COL.get(col, col)
        values = [g.get(cfbd_col) or 0 for g in recent]
        return simulate_player_stat_bootstrap(values, sims, rng)
    return simulate_player_stat_parametric(r.get(col), sims, rng)


def _clip_prob(p: float) -> float:
    """Final safety net: keep probabilities strictly inside (0, 1) so prob_to_american never
    hits its exact-boundary None case — runs AFTER shrink_prob's actual statistical correction,
    same division of labor every other sport's projections module uses."""
    return min(max(p, 0.02), 0.98)


def build_projection_index(rows: List[Dict], meta: List[Dict],
                           sims: int = DEFAULT_SIMS, seed: Optional[int] = None) -> Dict:
    """Return {(normalized_name, odds_market_key): {dist, mean, n_games, ctx}} for the slate —
    identical shape to every other sport's build_projection_index, so Edge Board doesn't need to
    know which sport it's looking at. `n_games` here is the TEAM's games-played count used as
    the per-game-rate denominator (ncaaf_engine._team_games_played_for_stats_season), reused as
    shrink_prob's own sample-size input — a team with only 2-3 games played so far genuinely
    deserves more shrinkage toward a neutral baseline than one with a full season's data behind
    its rate, same reasoning shrink_prob already applies everywhere else, just fed a team-level
    game count here instead of an individual player's own game count."""
    rng = np.random.default_rng(seed)
    index: Dict = {}

    for r in rows:
        markets = r.get("_markets") or []
        n_games = r.get("_team_games_played") or 0
        if not markets or n_games <= 0:
            continue
        nm = normalize_name(r["Player"])
        ctx = {"player": r["Player"], "team": r["Team"], "game": r["GameLabel"],
              "opp": r.get("Opp"), "lineup": "Active", "game_date": r.get("_game_date"),
              "position": r.get("Position", "")}
        for mkey in markets:
            col, _disp, _line = _MARKET_SPEC[mkey]
            sim = _simulate_for_row(r, col, sims, rng)
            if sim.size == 0:
                continue
            recent = r.get("_recent_games") or []
            # Sample size for shrink_prob: the REAL number of games actually bootstrapped from
            # when that path is used (a 3-game bootstrap deserves more shrinkage than a full
            # team season would suggest), falling back to the team's games-played count only for
            # the parametric path, where there's no per-player sample size to speak of.
            n_sample = len(recent) if recent else n_games
            index[(nm, mkey)] = {"dist": _dist(sim), "mean": float(sim.mean()),
                                 "n_games": n_sample, "ctx": ctx}
    return index


def default_board_from_index(index: Dict,
                             real_lines: Optional[Dict] = None) -> List[Dict]:
    """Model-only board (favored side at real or default lines) from the index — every NCAAF
    market in _MARKET_SPEC is a plain Over/Under, no special-case needed. Probabilities are
    shrunk toward a neutral baseline by (team) sample size before being clipped, same fix every
    other sport carries.

    real_lines: same shape as build_best_bets -- when supplied, uses the real book line for each
    player/market where available, falling back to _MARKET_SPEC defaults otherwise."""
    out: List[Dict] = []
    for (nm, mkey), entry in index.items():
        _col, disp, default_ln = _MARKET_SPEC.get(mkey, (mkey, mkey, 0.5))
        dist, ctx = entry["dist"], entry["ctx"]
        line, line_src = real_line_or_default_ncaaf(disp, ctx["player"], real_lines, default_ln)
        raw = prob_over(dist, line)
        shrunk = BB_P.shrink_prob(raw, entry.get("n_games", 0))
        over = _clip_prob(shrunk)
        side, prob = ("Over", over) if over >= 0.5 else ("Under", 1 - over)
        out.append(_signal(ctx["player"], ctx["team"], ctx["game"], disp, side, line, prob,
                           entry["mean"], Opp=ctx.get("opp"), Lineup=ctx.get("lineup"),
                           GameTime=ctx.get("game_date"), LineSource=line_src))
    return out


# --------------------------------------------------------------------------- Best Bets
BEST_BET_REF = {"Pass Yards": 0.5, "Rush Yards": 0.5, "Receptions": 0.5, "Receiving Yards": 0.5}

# NCAAF display market name -> Odds API market key. MUST STAY IN SYNC with sports.py's own
# NCAAF market_map AND odds_api's NCAAF market list, same as NFL_MARKET_TO_ODDS_KEY.
NCAAF_MARKET_TO_ODDS_KEY: Dict[str, str] = {
    "Pass Yards":      "player_pass_yds",
    "Rush Yards":      "player_rush_yds",
    "Receptions":      "player_receptions",
    "Receiving Yards": "player_reception_yds",
}


def real_line_or_default_ncaaf(
        market_display: str,
        player_name: str,
        real_lines: Optional[Dict],
        default: float) -> Tuple[float, str]:
    """The one shared decision point for every NCAAF market's line -- real, live sportsbook line
    when available, this platform's own _MARKET_SPEC placeholder otherwise. Mirrors
    nfl_projections.real_line_or_default_nfl exactly. Returns (line, source), source is 'book'
    or 'default'."""
    if real_lines is not None:
        odds_key = NCAAF_MARKET_TO_ODDS_KEY.get(market_display)
        if odds_key is not None:
            real = real_lines.get((normalize_name(player_name), odds_key))
            if real is not None:
                return float(real), "book"
    return default, "default"


def _favored_side(prob_over: float, ref: float):
    if prob_over >= ref:
        return "Over", prob_over, ref
    return "Under", 1.0 - prob_over, 1.0 - ref


def _player_reasons(rate: float, n_games: int, line: float, side: str, mean_display: str,
                    recent_values: Optional[List[float]] = None) -> str:
    """'Why' text -- real per-game hit-rate reasoning (matching every other sport's own
    _player_reasons phrasing) when real recent games exist; the season-average-basis statement
    only as a fallback for a player/week with no per-game log yet."""
    if recent_values:
        n = len(recent_values)
        hits = (sum(1 for v in recent_values if v > line) if side == "Over"
               else sum(1 for v in recent_values if v < line))
        avg = sum(recent_values) / n
        return f"cleared {line:g} in {hits} of last {n} games (avg {avg:.1f})"
    if n_games <= 0 or rate is None:
        return "no season stat data available"
    return (f"averaging {rate:.1f} {mean_display.lower()}/game over {n_games} team game(s) "
           f"this season (parametric model, no per-game log for this player yet)")


def explain_miss(row: Optional[Dict], market: str = "Pass Yards") -> str:
    """NCAAF equivalent of every other sport's explain_miss role for Retrospective. `row` is a
    build_slate row looked up by player id; None means the player wasn't on the projected slate
    at all. Deliberately does NOT attempt a per-game trend explanation (no per-game log exists,
    see this module's own docstring) — states that honestly rather than fabricating one."""
    if not row:
        return ("Not on the projected slate (didn't clear a rotation floor, or a late roster "
                "addition) — the model never saw this player.")
    col = next((c for c, disp, _l in _MARKET_SPEC.values() if disp == market), None)
    if not col or not row.get(col):
        return "No season stat data available for this player/market."
    return (f"Season-average model ({row[col]:.1f}/game over {row.get('_team_games_played', 0)} "
           "team games) — no per-game log exists yet to say whether this specific result was a "
           "trend or an outlier; see module notes on this sport's current parametric-only scope.")


def build_best_bets(rows: List[Dict], sims: int = DEFAULT_SIMS,
                    seed: Optional[int] = None,
                    real_lines: Optional[Dict] = None,
                    offers: Optional[List[Dict]] = None,
                    preferred_book: Optional[str] = None) -> List[Dict]:
    """Rank candidate plays across every position-relevant market by conviction (model prob vs
    the reference prob for that market) — same output schema every sport's build_best_bets uses.
    Probabilities are shrunk toward a neutral baseline by (team) sample size before being
    clipped, same fix every other sport carries.

    real_lines: {(normalized_player_name, odds_api_market_key): point} from
    odds_api.market_lines_for_slate -- when supplied, each play's Line is the real book line for
    that specific player, not the _MARKET_SPEC placeholder. None (the default) preserves the
    always-placeholder behavior."""
    rng = np.random.default_rng(seed)
    plays: List[Dict] = []

    for r in rows:
        markets = r.get("_markets") or []
        n_games = r.get("_team_games_played") or 0
        if not markets or n_games <= 0:
            continue
        for mkey in markets:
            col, disp, default_ln = _MARKET_SPEC[mkey]
            rate = r.get(col)
            line, line_src = real_line_or_default_ncaaf(disp, r["Player"], real_lines, default_ln)
            sim = _simulate_for_row(r, col, sims, rng)
            if sim.size == 0:
                continue
            recent = r.get("_recent_games") or []
            n_sample = len(recent) if recent else n_games
            raw = prob_over(_dist(sim), line)
            shrunk = BB_P.shrink_prob(raw, n_sample)
            over = _clip_prob(shrunk)
            side, sp, ref_s = _favored_side(over, BEST_BET_REF.get(disp, 0.5))
            plays.append({
                "Player": r["Player"], "PlayerId": r.get("_pid"), "Team": r["Team"],
                "Game": r["GameLabel"], "Opp": r.get("Opp"), "Versus": r.get("Opp"),
                "Market": disp, "Side": side, "Line": line, "LineSource": line_src,
                "ModelProb": round(sp, 4), "Fair": prob_to_american(sp),
                "Conviction": round(sp / ref_s, 2) if ref_s > 0 else 0.0,
                "_ceiling": round(1.0 / ref_s, 2) if ref_s > 0 else None,
                "Why": _player_reasons(rate, n_sample, line, side, disp,
                                       recent_values=[g.get(_ROW_FIELD_TO_CFBD_COL.get(col, col)) or 0
                                                      for g in recent] if recent else None),
                "_stat_key": col, "_team_games_played": n_games,
            })

    plays.sort(key=lambda x: x["Conviction"], reverse=True)
    return plays


# --------------------------------------------------------------------------- QB Lab
def build_qb_matchup_projections(rows: List[Dict], opp_pass_yards_allowed: Dict[str, float],
                                 league_avg_pass_yards_allowed: float,
                                 opp_rush_yards_allowed: Optional[Dict[str, float]] = None,
                                 league_avg_rush_yards_allowed: float = 0.0) -> List[Dict]:
    """QB matchup-aware Pass Yards AND Rush Yards projections: each QB's own recent-form average
    for both stats, each scaled by how much this week's opponent allows relative to the league
    average for that stat -- direct port of nfl_projections.build_qb_matchup_projections' own
    odds-ratio-style matchup adjustment, adapted to NCAAF's confirmed per-game column names
    (passing_YDS/rushing_YDS, not NFL's passing_yards/rushing_yards).

    RUSH YARDS INCLUDED HERE DELIBERATELY, same reasoning as NFL's own version: a QB's own
    rushing-yards projection isn't shared with anyone else's betting line (unlike the shared
    player_rush_yds market, which deliberately excludes QBs to avoid mixing a scrambling QB's
    occasional carries with a workhorse RB's volume) -- no such conflict showing it here.

    opp_pass_yards_allowed / opp_rush_yards_allowed: {opp_team: season stat allowed}, the
    CALLER's job to build -- one ncaaf_engine.get_team_allowed_stats(opp, date, n=None) call per
    unique opponent covers BOTH stats at once. league_avg_*_allowed come from ncaaf_engine.
    get_league_average_pass_yards_allowed / get_league_average_rush_yards_allowed, also the
    caller's job (one call each covers the whole slate)."""
    opp_rush_yards_allowed = opp_rush_yards_allowed or {}
    out: List[Dict] = []
    for r in rows:
        if r.get("Position") != "QB" or "player_pass_yds" not in (r.get("_markets") or []):
            continue
        log = r.get("_recent_games") or []
        if not log:
            continue
        recent_pass_avg = sum(g.get("passing_YDS") or 0 for g in log) / len(log)
        opp_pass_allowed = opp_pass_yards_allowed.get(r.get("Opp"), 0.0)
        if league_avg_pass_yards_allowed > 0 and opp_pass_allowed > 0:
            pass_factor = opp_pass_allowed / league_avg_pass_yards_allowed
        else:
            pass_factor = 1.0   # no opponent/league data yet -> neutral, never a fabricated boost/penalty

        recent_rush_avg = sum(g.get("rushing_YDS") or 0 for g in log) / len(log)
        opp_rush_allowed = opp_rush_yards_allowed.get(r.get("Opp"), 0.0)
        if league_avg_rush_yards_allowed > 0 and opp_rush_allowed > 0:
            rush_factor = opp_rush_allowed / league_avg_rush_yards_allowed
        else:
            rush_factor = 1.0

        out.append({
            "Player": r["Player"], "Team": r["Team"], "Opp": r.get("Opp"), "Game": r["GameLabel"],
            "Recent Avg": round(recent_pass_avg, 1),
            "Opp Pass Yds Allowed (season)": round(opp_pass_allowed, 1) if opp_pass_allowed else None,
            "Matchup Factor": round(pass_factor, 2),
            "Proj Pass Yds": round(recent_pass_avg * pass_factor, 1),
            "Recent Rush Yds": round(recent_rush_avg, 1),
            "Opp Rush Yds Allowed (season)": round(opp_rush_allowed, 1) if opp_rush_allowed else None,
            "Rush Matchup Factor": round(rush_factor, 2),
            "Proj Rush Yds": round(recent_rush_avg * rush_factor, 1),
        })
    out.sort(key=lambda x: x["Proj Pass Yds"], reverse=True)
    return out


def build_qb_efficiency_table(rows: List[Dict], season_logs_by_pid: Dict[str, List[Dict]]) -> List[Dict]:
    """TD:INT regression signal: each QB's recent PASSING TD/INT rates against their own season-
    long rates, flagging a meaningful divergence -- direct port of nfl_projections.
    build_qb_efficiency_table, adapted to NCAAF's confirmed columns (passing_TD/passing_INT/
    rushing_TD -- NOT the separate "interceptions_*" category, which CFBD tracks from the
    DEFENDER's side of the play, not the passer's; passing_INT is the QB's own interceptions
    thrown, confirmed present in the real column list from a live refresh run).

    Built entirely from real confirmed data (TD/INT counts), not a fabricated "college football
    FIP" -- same honesty NFL's own version holds to. A DIFFERENT axis of regression than MLB's
    ERA-vs-FIP: that compares a luck-affected RESULTS metric against a more-predictive
    PERIPHERALS metric over the SAME window; this compares a small, noisy RECENT window against
    a larger, steadier SEASON window -- a recency-vs-stability axis, not a luck-vs-skill one.

    TAG DIRECTION stated plainly: a QB trending well ABOVE their season TD:INT rate is flagged as
    possibly NOT sustainable (their season rate is the larger, steadier sample) -- deliberately
    NOT a buy/fade recommendation, just a description of which number is the more reliable
    baseline. Rushing TD Rate shown alongside as its own raw signal, not blended into the
    passing-specific delta -- there's no rushing equivalent of an interception to regress it
    against the same way."""
    out: List[Dict] = []
    for r in rows:
        if r.get("Position") != "QB":
            continue
        log = r.get("_recent_games") or []
        if not log:
            continue
        pid = r.get("_pid")
        season_log = season_logs_by_pid.get(pid) or []
        recent_td = sum(g.get("passing_TD") or 0 for g in log) / len(log)
        recent_int = sum(g.get("passing_INT") or 0 for g in log) / len(log)
        season_td = (sum(g.get("passing_TD") or 0 for g in season_log) / len(season_log)
                    if season_log else None)
        season_int = (sum(g.get("passing_INT") or 0 for g in season_log) / len(season_log)
                     if season_log else None)
        recent_diff = recent_td - recent_int
        season_diff = (season_td - season_int) if season_td is not None and season_int is not None else None
        delta = (recent_diff - season_diff) if season_diff is not None else None

        recent_rush_td = sum(g.get("rushing_TD") or 0 for g in log) / len(log)
        season_rush_td = (sum(g.get("rushing_TD") or 0 for g in season_log) / len(season_log)
                          if season_log else None)

        tag = "—"
        if delta is not None:
            if delta >= 0.5:
                tag = "📈 Trending above season norm — may not be sustainable"
            elif delta <= -0.5:
                tag = "📉 Trending below season norm — may not be sustainable"
            else:
                tag = "➡️ In line with season norm"

        out.append({
            "Player": r["Player"], "Team": r["Team"], "Opp": r.get("Opp"),
            "Recent Passing TD Rate": round(recent_td, 2), "Recent INT Rate": round(recent_int, 2),
            "Season Passing TD Rate": round(season_td, 2) if season_td is not None else None,
            "Season INT Rate": round(season_int, 2) if season_int is not None else None,
            "TD-INT Delta (recent vs season)": round(delta, 2) if delta is not None else None,
            "Recent Rushing TD Rate": round(recent_rush_td, 2),
            "Season Rushing TD Rate": round(season_rush_td, 2) if season_rush_td is not None else None,
            "Tag": tag,
        })
    out.sort(key=lambda x: (x["TD-INT Delta (recent vs season)"]
                            if x["TD-INT Delta (recent vs season)"] is not None else 0), reverse=True)
    return out
