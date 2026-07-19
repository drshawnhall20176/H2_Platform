"""
ncaamb_projections.py — turns ncaamb_engine's slate rows into priced probabilities.

Matches projections.py's OUTPUT CONTRACT exactly (build_projection_index / default_board_from_index
/ DEFAULT_SIMS), which is what lets Edge Board consume MLB, WNBA, NBA, and NCAAMB through the same
code path via sports.active().projections — see sports.py and views/3_..._Edge_Board.py. The
genuinely sport-agnostic pieces of that contract (prob_over, prob_for_side, normalize_name,
format_et, prob_to_decimal, prob_to_american — pure math on probabilities/integer count arrays,
nothing baseball-specific) are imported straight from projections.py rather than re-implemented
here — the same convention every other sport's projections module already follows.

BUILT AS A COPY-ADAPT OF nba_projections.py — see basketball_engine.py's module docstring for the
extraction plan this follows. The genuinely NCAAMB-specific difference from nba_projections.py is
_MARKET_SPEC's default lines: NCAAMB games run 40 minutes, the same length as WNBA's, not NBA's
48 — so this uses WNBA's default lines as the closer, more defensible anchor rather than NBA's
higher ones, the same reasoning already applied to config_ncaamb.MIN_AVG_MINUTES. These are
model-only-board fallback defaults (used only when no live odds have been fetched), not calibrated
book numbers, same caveat every other sport's defaults carry.

METHOD (deliberately simple — a v1, documented as such): each of a player's last N games
(config_ncaamb.RECENT_GAMES_N) for Points/Rebounds/Assists/Threes Made is treated as one draw from
their true talent distribution. The projection is an empirical bootstrap: resample those games
with replacement `sims` times and use the resulting distribution directly, then SHRUNK toward a
neutral baseline by sample size (basketball_projections.shrink_prob) before being clipped — the
same fix built after a real bug found live on WNBA/NBA (many different players all landing on an
identical clipped probability). Opponent defensive strength and pace are NOT incorporated into the
probability model itself (Edge Board/Best Bets stay recent-form-only, deliberately — see
build_projection_index/build_best_bets). A separate, transparent opponent-adjustment SIGNAL (not
folded into the probabilities) lives in build_hot_hand_board below, for the Hot Hand Engine page.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from projections import (  # genuinely sport-agnostic — reused, not duplicated
    prob_over, prob_for_side, normalize_name, format_et,
    prob_to_decimal, prob_to_american, curate_selections,
)
import basketball_projections as BB_P  # league-agnostic basketball logic, shared with wnba/nba_projections.py

DEFAULT_SIMS = 10000

# Odds-API-market-key -> (row column, display name, default line for the model-only board).
# WNBA-SCALE, not NBA-scale: NCAAMB games run 40 minutes, matching WNBA's game length, not NBA's
# 48 — the same reasoning already used for config_ncaamb.MIN_AVG_MINUTES. These are round-number
# model-only-board fallbacks (used only before a live line is fetched), not calibrated book
# numbers — worth tuning empirically once real NCAAMB slate data is available, same honest caveat
# every other sport's defaults on this platform carry.
_MARKET_SPEC = {
    "player_points":   ("PTS",  "Points",      12.5),
    "player_rebounds": ("REB",  "Rebounds",    5.5),
    "player_assists":  ("AST",  "Assists",     3.5),
    "player_threes":   ("FG3M", "Threes Made", 1.5),
}
_STAT_KEY = {"PTS": "pts", "REB": "reb", "AST": "ast", "FG3M": "fg3m"}


def market_list() -> List[Tuple[str, str, str]]:
    """[(market_key, row_column, display_name), ...] for all four Core markets, in a stable
    order — the public, iterable form of _MARKET_SPEC for callers outside this module (Matchup
    Lab's trend chart) that need to loop over markets without reaching into a private dict."""
    return [(mkey, col, disp) for mkey, (col, disp, _line) in _MARKET_SPEC.items()]


def stat_key_for(col: str) -> str:
    """Row-column ('PTS'/'REB'/'AST'/'FG3M') -> game-log dict key ('pts'/'reb'/'ast'/'fg3m').
    Public form of _STAT_KEY, for the same reason as market_list."""
    return _STAT_KEY[col]


def default_line(market_key: str) -> Optional[float]:
    """The model-only board's default line for one market (_MARKET_SPEC's third element),
    exposed as its own function so callers outside this module — Matchup Lab's trend chart, when
    no live odds have been fetched — don't need to reach into a private module-level dict
    directly. Returns None for an unrecognized market key rather than guessing."""
    spec = _MARKET_SPEC.get(market_key)
    return spec[2] if spec else None


def build_trend_series(log: List[Dict]) -> List[Dict]:
    """Chronological (oldest-to-newest) copy of a player's recent-game log, for a trend chart
    that reads left-to-right as time moving forward — the opposite of get_player_recent_games/
    get_player_season_games's own most-recent-first contract."""
    return list(reversed(log))


def _dist(samples: np.ndarray) -> np.ndarray:
    """Normalized histogram: index i -> P(outcome == i). Same shape/semantics as
    projections._dist, so odds_api.compute_edges works identically for either sport."""
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


def simulate_player_stat(recent_values: List[float], sims: int, rng: np.random.Generator) -> np.ndarray:
    """Bootstrap `sims` draws (with replacement) from a player's recent-game values for one stat.
    Values are rounded to the nearest non-negative integer (counting stats can't be fractional or
    negative). Returns an empty array if there's no game log to sample from."""
    if not recent_values:
        return np.array([], dtype=np.int64)
    draws = rng.choice(np.asarray(recent_values, dtype=np.float64), size=sims, replace=True)
    return np.clip(np.round(draws), 0, None).astype(np.int64)


def build_projection_index(rows: List[Dict], meta: List[Dict],
                           sims: int = DEFAULT_SIMS, seed: Optional[int] = None) -> Dict:
    """Return {(normalized_name, odds_market_key): {dist, mean, n_games, ctx}} for the slate —
    identical shape to projections.build_projection_index (plus n_games, needed for
    basketball_projections.shrink_prob downstream), so downstream code (Edge Board, odds_api.
    compute_edges) doesn't need to know which sport it's looking at."""
    rng = np.random.default_rng(seed)
    index: Dict = {}

    for r in rows:
        log = r.get("_game_log") or []
        if not log:
            continue
        nm = normalize_name(r["Player"])
        ctx = {"player": r["Player"], "team": r["Team"], "game": r["GameLabel"],
              "opp": r.get("Opp"), "lineup": "Active", "game_date": r.get("_game_date")}
        for mkey, (col, _disp, _line) in _MARKET_SPEC.items():
            values = [g[_STAT_KEY[col]] for g in log]
            sim = simulate_player_stat(values, sims, rng)
            if sim.size == 0:
                continue
            index[(nm, mkey)] = {"dist": _dist(sim), "mean": float(sim.mean()),
                                 "n_games": len(values), "ctx": ctx}

    return index


def _clip_prob(p: float) -> float:
    """Final safety net: keep probabilities strictly inside (0, 1) so `prob_to_american` never
    hits its exact-boundary None case (which breaks a strict `{:+d}` format string wherever a
    Fair price gets displayed — a real crash this caught in production). This runs AFTER
    basketball_projections.shrink_prob, which does the actual statistical correction for
    small-sample overconfidence (a short recent-game log can genuinely produce a raw 0.0 or 1.0);
    this function is just the last-resort clamp for whatever shrinkage doesn't fully catch."""
    return min(max(p, 0.02), 0.98)


def default_board_from_index(index: Dict) -> List[Dict]:
    """Model-only board (favored side at default lines) from the index — identical shape/logic
    to projections.default_board_from_index (every NCAAMB market in _MARKET_SPEC is a plain
    Over/Under, no MLB-style Yes/No special case needed here). Probabilities are shrunk toward a
    neutral baseline by sample size (see basketball_projections.shrink_prob) before being
    clipped — a 4-game "perfect" streak and a 30-game one no longer produce the identical number."""
    out: List[Dict] = []
    for (nm, mkey), entry in index.items():
        _col, disp, line = _MARKET_SPEC.get(mkey, (mkey, mkey, 0.5))
        dist, ctx = entry["dist"], entry["ctx"]
        raw = prob_over(dist, line)
        shrunk = BB_P.shrink_prob(raw, entry.get("n_games", 0))
        over = _clip_prob(shrunk)
        side, prob = ("Over", over) if over >= 0.5 else ("Under", 1 - over)
        out.append(_signal(ctx["player"], ctx["team"], ctx["game"], disp, side, line, prob,
                           entry["mean"], Opp=ctx.get("opp"), Lineup=ctx.get("lineup"),
                           GameTime=ctx.get("game_date")))
    return out


# --------------------------------------------------------------------------- Best Bets
# Reference (typical/coin-flip) hit-rate per market. All four NCAAMB markets use 0.5 rather than
# a calibrated figure — the default lines themselves (_MARKET_SPEC above) are round-number
# estimates, not book-calibrated, so treating them as genuinely even is the honest choice here.
BEST_BET_REF = {"Points": 0.5, "Rebounds": 0.5, "Assists": 0.5, "Threes Made": 0.5}


def _favored_side(prob_over: float, ref: float):
    """Return (side, prob_of_that_side, ref_for_that_side)."""
    if prob_over >= ref:
        return "Over", prob_over, ref
    return "Under", 1.0 - prob_over, 1.0 - ref


def _player_reasons(values: List[float], line: float, side: str) -> str:
    """'Why' text built from the player's own recent-game log — no park/weather/platoon inputs
    exist for basketball the way they do for MLB, so this leans on what's actually available:
    how consistently they've cleared this exact line recently, and whether their last few games
    are trending away from their own average (hot/cold streak)."""
    n = len(values)
    if n == 0:
        return "no recent-game data available"
    hits = sum(1 for v in values if v > line) if side == "Over" else sum(1 for v in values if v < line)
    avg = sum(values) / n
    recent = values[:3]                       # most recent first (see ncaamb_engine.get_player_recent_games)
    recent_avg = sum(recent) / len(recent) if recent else avg
    trend = ""
    if recent and avg > 0 and abs(recent_avg - avg) >= max(0.75, avg * 0.20):
        trend = ", trending up" if recent_avg > avg else ", trending down"
    return f"cleared {line:g} in {hits} of last {n} games (avg {avg:.1f}{trend})"


def explain_miss(row: Optional[Dict], market: str = "Points") -> str:
    """NCAAMB equivalent of retro.explain_miss's role: explain a result the model ranked LOW.
    `row` is a build_slate row looked up by player id; None means the player wasn't on the
    projected slate at all (below the rotation-minutes bar, or a late addition the model never saw)."""
    if not row:
        return ("Not on the projected slate (recent minutes below the rotation bar, or a late "
                "addition) — the model never saw this player.")
    log = row.get("_game_log") or []
    col = next((c for c, disp, _l in _MARKET_SPEC.values() if disp == market), None)
    stat_key = _STAT_KEY.get(col)
    if not log or not stat_key:
        return "No recent-game data available for this player."
    values = [g.get(stat_key, 0) for g in log]
    avg = sum(values) / len(values)
    recent = values[:3]
    recent_avg = sum(recent) / len(recent) if recent else avg
    if avg > 0 and recent_avg >= avg * 1.15:
        return (f"Catchable — trending up over the last {len(recent)} games (avg {recent_avg:.1f} "
                f"vs {avg:.1f} in the full recent sample) before this one; recency weighting "
                "hadn't fully caught up yet.")
    return (f"Genuine outlier — averaging {avg:.1f} over the last {len(values)} games with no "
            "recent uptick; this result sits above their established form. Variance, not a "
            "systematic miss.")


def build_best_bets(rows: List[Dict], sims: int = DEFAULT_SIMS,
                    seed: Optional[int] = None) -> List[Dict]:
    """Rank candidate plays across all four markets by conviction (model prob vs the reference
    prob for that market), each with recent-form reasoning. No odds required — output schema
    (Player/PlayerId/Team/Game/Opp/Versus/Market/Side/Line/ModelProb/Fair/Conviction/Why) matches
    projections.build_best_bets's so Best Bets, Command Center, Media Room, and Podcast Studio can
    render any sport's plays through the same code. Probabilities are shrunk toward a neutral
    baseline by sample size (see basketball_projections.shrink_prob) before being clipped —
    without this, a run of players who all cleared their line in every recent game (common early
    season with short logs) all land on the exact same clipped 98%/Conviction, collapsing the
    ranking among them into an arbitrary tie instead of a real ordering."""
    rng = np.random.default_rng(seed)
    plays: List[Dict] = []

    for r in rows:
        log = r.get("_game_log") or []
        if not log:
            continue
        for mkey, (col, disp, line) in _MARKET_SPEC.items():
            values = [g[_STAT_KEY[col]] for g in log]
            sim = simulate_player_stat(values, sims, rng)
            if sim.size == 0:
                continue
            raw = prob_over(_dist(sim), line)
            shrunk = BB_P.shrink_prob(raw, len(values))
            over = _clip_prob(shrunk)
            side, sp, ref_s = _favored_side(over, BEST_BET_REF.get(disp, 0.5))
            plays.append({
                "Player": r["Player"], "PlayerId": r.get("_pid"), "Team": r["Team"],
                "Game": r["GameLabel"], "Opp": r.get("Opp"), "Versus": r.get("Opp"),
                "Market": disp, "Side": side, "Line": line,
                "ModelProb": round(sp, 4), "Fair": prob_to_american(sp),
                "Conviction": round(sp / ref_s, 2) if ref_s > 0 else 0.0,
                # this play's own theoretical max conviction (1/RefProb) -- lets
                # grading.conviction_to_grade normalize fairly across markets with very
                # different reference rates, see that function's own docstring
                "_ceiling": round(1.0 / ref_s, 2) if ref_s > 0 else None,
                "Why": _player_reasons(values, line, side),
                "_stat_key": _STAT_KEY[col], "_game_log": log,
            })

    plays.sort(key=lambda x: x["Conviction"], reverse=True)
    return plays


# Thin alias — the actual logic lives in basketball_projections.py (shared with wnba/nba_projections.py).
blowout_risk_tag = BB_P.blowout_risk_tag

# NCAAMB-scale blowout threshold: HIGHER than NBA's 12.0 or WNBA's 10.0, not lower, despite the
# shorter/lower-scoring games — Division I has far larger talent gaps between a top-25 program and
# a mid-major or bottom-of-conference team than exist between any two pro teams, so a genuine
# "competitive" game can carry a bigger spread here than the same spread would mean in the pros.
# 15.0 is a starting adjustment reflecting that gap, NOT a backtested cutoff — worth tuning
# empirically once real NCAAMB slate/spread data is available, same honest caveat every other
# tuning constant on this platform carries.
BLOWOUT_THRESHOLD = 15.0


# --------------------------------------------------------------------------- Hot Hand Engine
def build_hot_hand_board(rows: List[Dict], opp_allowed: Dict[int, Dict[str, float]],
                         team_rest: Optional[Dict[int, Dict]] = None,
                         team_spreads: Optional[Dict[str, float]] = None) -> List[Dict]:
    """Matchup-adjusted leaderboard: each rotation player's recent-form average, scaled by how
    much their tonight's opponent has been allowing at that stat, RELATIVE to the average allowed
    rate across every opponent actually on tonight's slate. `opp_allowed` is
    {team_id: {pts,reb,ast,fg3m,poss}} from ncaamb_engine.get_team_recent_allowed_stats, one call
    per unique opponent on the slate — the caller's job, not this function's.

    PACE-ADJUSTED: the Matchup Factor compares PER-100-POSSESSION allowed rates, not raw per-game
    allowed totals — see wnba_projections.build_hot_hand_board's docstring for the full reasoning
    (identical here; this is a copy-adapt, not a different design). Pace adjustment likely matters
    MORE for NCAAMB than for the pros — Division I has genuinely wide pace variance, from
    deliberate slow-down/grind-it-out programs to up-tempo pressing ones, wider than the pace
    spread typically seen across NBA or WNBA teams.

    `team_rest` (optional) is {team_id: {rest_days, is_back_to_back, ...}} from ncaamb_engine.
    get_team_rest_info, keyed by the PLAYER'S OWN team. `team_spreads` (optional) is
    {team_name: spread} from odds_api.fetch_slate_spreads. Both surfaced as their own columns,
    deliberately NOT folded into Matchup Factor/Score — same philosophy as every other sport's board.

    This is a SEPARATE, clearly-labeled signal, not folded into build_best_bets/
    build_projection_index's probabilities — Edge Board and Best Bets stay recent-form-only."""
    team_rest = team_rest or {}
    team_spreads = team_spreads or {}
    baseline_samples = {"pts": [], "reb": [], "ast": [], "fg3m": []}
    for stats in opp_allowed.values():
        poss = stats.get("poss", 0)
        if poss <= 0:
            continue
        for k in baseline_samples:
            if stats.get(k, 0) > 0:
                baseline_samples[k].append(stats[k] / poss * 100)   # per-100-poss, not raw total
    baseline = {k: (sum(v) / len(v) if v else 0.0) for k, v in baseline_samples.items()}

    out: List[Dict] = []
    for r in rows:
        opp_id = r.get("_opp_id")
        opp_stats = opp_allowed.get(opp_id) if opp_id is not None else None
        opp_poss = (opp_stats or {}).get("poss", 0.0)
        rest = team_rest.get(r.get("_team_id")) or {}
        spread = team_spreads.get(r["Team"])
        for _mkey, (col, disp, _line) in _MARKET_SPEC.items():
            stat_key = _STAT_KEY[col]
            player_avg = r.get(col, 0.0)
            base_rate = baseline.get(stat_key, 0.0)          # per-100-poss, constant across rows
            allowed = (opp_stats or {}).get(stat_key, 0.0)   # raw per-game, for display context
            allowed_rate = (allowed / opp_poss * 100) if opp_poss > 0 else 0.0
            if base_rate > 0 and allowed_rate > 0:
                factor = allowed_rate / base_rate
            else:
                factor = 1.0   # no opponent/pace data yet -> neutral, never a fabricated boost/penalty
            if factor >= 1.08:
                tag = "🟢 Plus matchup"
            elif factor <= 0.92:
                tag = "🔴 Tough matchup"
            else:
                tag = "🟡 Neutral"
            out.append({
                "Player": r["Player"], "Team": r["Team"], "Opp": r.get("Opp"),
                "Game": r["GameLabel"], "Market": disp,
                "Recent Avg": player_avg,
                "Opp Allows": round(allowed, 1) if opp_stats else None,
                "Opp Pace": round(opp_poss, 1) if opp_poss else None,
                "Opp Allows /100 Poss": round(allowed_rate, 1) if allowed_rate else None,
                "Slate Avg /100 Poss": round(base_rate, 1) if base_rate else None,
                "Matchup Factor": round(factor, 2),
                "Matchup Score": round(player_avg * factor, 1),
                "Tag": tag,
                "Rest Days": rest.get("rest_days"),
                "B2B": bool(rest.get("is_back_to_back", False)),
                "Spread": round(spread, 1) if spread is not None else None,
                "Blowout Risk": blowout_risk_tag(spread, threshold=BLOWOUT_THRESHOLD),
            })

    out.sort(key=lambda x: -x["Matchup Score"])
    return out


# --------------------------------------------------------------------------- Matchup Lab
def build_matchup_profile(row: Dict, h2h_log: List[Dict], opp_recent_allowed: Dict[str, float],
                          opp_season_allowed: Dict[str, float],
                          season_log: Optional[List[Dict]] = None) -> List[Dict]:
    """One row per market (Points/Rebounds/Assists/Threes Made) for Matchup Lab's deep-dive on a
    single player vs their tonight's opponent — see wnba_projections.build_matchup_profile's
    docstring for the full reasoning behind each signal (identical here; copy-adapt, not a
    different design). One NCAAMB-specific note, more pronounced than NBA's own version of this
    same caveat: h2h_log will legitimately be EMPTY far more often here than in the pros — most
    Division I non-conference opponents play each other once a season if at all, unlike a pro
    league's balanced round-robin schedule, so an empty head-to-head sample is the common case
    for most matchups, not the exception. Reported honestly rather than padded with a guess."""
    season_avgs: Dict[str, Optional[float]] = {}
    h2h_avgs: Dict[str, Optional[float]] = {}
    ratios: Dict[str, float] = {}
    for _mkey, (col, _disp, _line) in _MARKET_SPEC.items():
        stat_key = _STAT_KEY[col]
        if season_log:
            svals = [g.get(stat_key, 0.0) for g in season_log]
            season_avgs[stat_key] = (sum(svals) / len(svals)) if svals else None
        else:
            season_avgs[stat_key] = None
        hvals = [g.get(stat_key, 0.0) for g in h2h_log]
        h2h_avgs[stat_key] = (sum(hvals) / len(hvals)) if hvals else None
        sa = season_avgs[stat_key]
        ha = h2h_avgs[stat_key]
        if sa and sa > 0 and ha is not None:
            ratios[stat_key] = ha / sa

    suppressed_key = None
    if len(ratios) >= 2:
        ranked = sorted(ratios.items(), key=lambda kv: kv[1])
        lowest_key, lowest_val = ranked[0]
        next_val = ranked[1][1]
        if lowest_val < 0.75 and (next_val - lowest_val) >= 0.15:
            suppressed_key = lowest_key

    out: List[Dict] = []
    for _mkey, (col, disp, _line) in _MARKET_SPEC.items():
        stat_key = _STAT_KEY[col]
        recent_avg = row.get(col, 0.0)
        season_avg = season_avgs.get(stat_key)
        h2h_avg = h2h_avgs.get(stat_key)

        hvals = [g.get(stat_key, 0.0) for g in h2h_log]
        h2h_spread = f"{min(hvals):.0f}\u2013{max(hvals):.0f}" if len(hvals) >= 2 else None
        high_variance = False
        if len(hvals) >= 2 and season_avg and season_avg > 0:
            spread = max(hvals) - min(hvals)
            high_variance = spread > season_avg * 0.75

        recent_allowed = opp_recent_allowed.get(stat_key, 0.0)
        season_allowed = opp_season_allowed.get(stat_key, 0.0)
        trend = (recent_allowed / season_allowed) if season_allowed > 0 else 1.0
        if trend >= 1.08:
            trend_tag = "📈 Looser lately"
        elif trend <= 0.92:
            trend_tag = "📉 Tighter lately"
        else:
            trend_tag = "➡️ Steady"

        out.append({
            "Market": disp,
            "Recent Avg": recent_avg,
            "Season Avg": round(season_avg, 1) if season_avg is not None else None,
            "H2H Games": len(hvals),
            "H2H Avg": round(h2h_avg, 1) if h2h_avg is not None else None,
            "H2H Spread": h2h_spread,
            "High Variance": high_variance,
            "Suppressed": stat_key == suppressed_key,
            "Opp Recent Allowed": round(recent_allowed, 1) if recent_allowed else None,
            "Opp Season Allowed": round(season_allowed, 1) if season_allowed else None,
            "Defense Trend": round(trend, 2),
            "Trend Tag": trend_tag,
        })
    return out
