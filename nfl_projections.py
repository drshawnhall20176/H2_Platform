"""
nfl_projections.py — turns nfl_engine's slate rows into priced probabilities.

Matches projections.py's OUTPUT CONTRACT (build_projection_index / default_board_from_index /
DEFAULT_SIMS) — the same contract every other sport's projections module follows, which is what
lets Edge Board consume MLB, WNBA, NBA, NCAAMB, and now NFL through the same code path via
sports.active().projections. The genuinely sport-agnostic pieces (prob_over, prob_for_side,
normalize_name, format_et, prob_to_decimal, prob_to_american, curate_selections) are imported
straight from projections.py, not re-implemented — same convention every sport follows.

POSITION-AWARE, NOT ONE-SIZE-FITS-ALL: unlike basketball's Core 4 (every rotation player gets all
four markets), a market here only applies to the positions that actually generate that stat — see
nfl_engine.py's _MARKETS_FOR_POSITION and this module's own _MARKET_SPEC. build_projection_index/
build_best_bets both iterate a row's OWN `_markets` list (set by nfl_engine.player_row, already
gated per-position AND per-opportunity-floor), not a blanket set applied to everyone.

METHOD: same bootstrap-then-shrink approach as every basketball sport on this platform — each of a
player's last N games (config_nfl.RECENT_GAMES_N — 5, not basketball's 10; an NFL season is only
17 games, so a 10-game window would be over half the season, diluting the recency signal it exists
to capture) is treated as one draw from their true talent distribution, resampled with replacement,
then SHRUNK toward a neutral baseline by sample size before being clipped. shrink_prob is imported
directly from basketball_projections.py — not duplicated, and not moved into a differently-named
shared module either, despite the cross-domain-sounding import: the function itself is pure
probability math with zero basketball-specific assumptions (confirmed by reading it), and moving
it would mean touching three already-shipped, tested modules (WNBA/NBA/NCAAMB's own imports of it)
for a purely cosmetic rename. Reusing it as-is is the lower-risk choice.

STAGED SCOPE, HONEST ABOUT WHAT'S NOT HERE YET: this module covers what Edge Board and Best Bets
need — the platform's core "find a priced edge" pages. A Hot Hand Engine-equivalent (opponent-
adjusted leaderboard) and a Matchup Lab-equivalent (single-player deep dive vs. their own
head-to-head history) do NOT exist here yet — deliberately deferred, not silently missing, the
same staged-build pattern every other sport on this platform followed (MLB and WNBA both shipped
their core pricing pages before their own Hot Hand Engine/Matchup Lab equivalents).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from projections import (  # genuinely sport-agnostic — reused, not duplicated
    prob_over, prob_for_side, normalize_name, format_et,
    prob_to_decimal, prob_to_american, curate_selections,
)
import basketball_projections as BB_P   # shrink_prob only — see module docstring for why this
                                        # cross-domain-sounding import is the right call, not a mistake
import config_nfl as CFG

DEFAULT_SIMS = CFG.DEFAULT_SIMS

# odds_market_key -> (weekly-stats column, display name, default line for the model-only board).
# Default lines are round-number, model-only-board fallbacks (used only before a live line is
# fetched) — NOT calibrated book numbers, worth tuning empirically once real usage exists, same
# honest caveat every other sport's defaults on this platform carry. Anchored to real, confirmed
# 2025-season per-game norms for a rotation player at each position (not guessed from nothing):
# ~225 pass yards/game for a starting QB, ~45 rush yards for a rotation RB, ~3.5 catches / 40
# yards for a target-share WR/TE.
_MARKET_SPEC: Dict[str, Tuple[str, str, float]] = {
    "player_pass_yds":      ("passing_yards",   "Pass Yards",      224.5),
    "player_rush_yds":      ("rushing_yards",   "Rush Yards",      44.5),
    "player_receptions":    ("receptions",      "Receptions",      3.5),
    "player_reception_yds": ("receiving_yards", "Receiving Yards", 39.5),
}


def market_list() -> List[Tuple[str, str, str]]:
    """[(market_key, stat_column, display_name), ...] — public, iterable form of _MARKET_SPEC."""
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


def simulate_player_stat(recent_values: List[float], sims: int, rng: np.random.Generator) -> np.ndarray:
    """Bootstrap `sims` draws (with replacement) from a player's recent-game values for one stat.
    Values are rounded to the nearest non-negative integer (counting/yardage stats can't be
    fractional or negative). Returns an empty array if there's no game log to sample from."""
    if not recent_values:
        return np.array([], dtype=np.int64)
    draws = rng.choice(np.asarray(recent_values, dtype=np.float64), size=sims, replace=True)
    return np.clip(np.round(draws), 0, None).astype(np.int64)


def _clip_prob(p: float) -> float:
    """Final safety net: keep probabilities strictly inside (0, 1) so `prob_to_american` never
    hits its exact-boundary None case. Runs AFTER basketball_projections.shrink_prob, which does
    the actual statistical correction for small-sample overconfidence — same division of labor
    every other sport's projections module uses."""
    return min(max(p, 0.02), 0.98)


def build_projection_index(rows: List[Dict], meta: List[Dict],
                           sims: int = DEFAULT_SIMS, seed: Optional[int] = None) -> Dict:
    """Return {(normalized_name, odds_market_key): {dist, mean, n_games, ctx}} for the slate —
    identical shape to every other sport's build_projection_index, so Edge Board doesn't need to
    know which sport it's looking at. Only iterates each row's OWN `_markets` — a QB's row never
    contributes a "player_receptions" entry, unlike basketball's blanket four-markets-for-everyone."""
    rng = np.random.default_rng(seed)
    index: Dict = {}

    for r in rows:
        log = r.get("_recent_games") or []
        markets = r.get("_markets") or []
        if not log or not markets:
            continue
        nm = normalize_name(r["Player"])
        ctx = {"player": r["Player"], "team": r["Team"], "game": r["GameLabel"],
              "opp": r.get("Opp"), "lineup": "Active", "game_date": r.get("_game_date")}
        for mkey in markets:
            col, _disp, _line = _MARKET_SPEC[mkey]
            values = [g.get(col) or 0 for g in log]
            sim = simulate_player_stat(values, sims, rng)
            if sim.size == 0:
                continue
            index[(nm, mkey)] = {"dist": _dist(sim), "mean": float(sim.mean()),
                                 "n_games": len(values), "ctx": ctx}
    return index


def default_board_from_index(index: Dict) -> List[Dict]:
    """Model-only board (favored side at default lines) from the index — every NFL market in
    _MARKET_SPEC is a plain Over/Under, no special-case needed. Probabilities are shrunk toward a
    neutral baseline by sample size before being clipped, same fix every other sport carries."""
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
# Reference (typical/coin-flip) hit-rate per market — 0.5 for all four, honest given the default
# lines above are round-number estimates, not book-calibrated (same reasoning every sport uses).
BEST_BET_REF = {"Pass Yards": 0.5, "Rush Yards": 0.5, "Receptions": 0.5, "Receiving Yards": 0.5}


def _favored_side(prob_over: float, ref: float):
    if prob_over >= ref:
        return "Over", prob_over, ref
    return "Under", 1.0 - prob_over, 1.0 - ref


def _player_reasons(values: List[float], line: float, side: str) -> str:
    """'Why' text built from the player's own recent-game log — no opponent/weather/game-script
    inputs exist in v1 (see module docstring's staged-scope note), so this leans on what's
    actually available: how consistently they've cleared this exact line recently, and whether
    their last couple games are trending away from their own average."""
    n = len(values)
    if n == 0:
        return "no recent-game data available"
    hits = sum(1 for v in values if v > line) if side == "Over" else sum(1 for v in values if v < line)
    avg = sum(values) / n
    recent = values[:2]     # most recent first (see nfl_engine.player_recent_games)
    recent_avg = sum(recent) / len(recent) if recent else avg
    trend = ""
    if recent and avg > 0 and abs(recent_avg - avg) >= max(1.0, avg * 0.20):
        trend = ", trending up" if recent_avg > avg else ", trending down"
    return f"cleared {line:g} in {hits} of last {n} games (avg {avg:.1f}{trend})"


def explain_miss(row: Optional[Dict], market: str = "Pass Yards") -> str:
    """NFL equivalent of retro.explain_miss's role: explain a result the model ranked LOW.
    `row` is a build_slate row looked up by player id; None means the player wasn't on the
    projected slate at all (didn't clear a rotation floor, or a late roster addition the model
    never saw). Same contract as WNBA/NBA/NCAAMB's own explain_miss — Retrospective calls this
    unconditionally for every non-MLB sport (`P.explain_miss` where P is whichever sport is
    active), so a missing implementation here is a real crash, not a cosmetic gap; this was
    exactly that crash, found live and fixed."""
    if not row:
        return ("Not on the projected slate (didn't clear a rotation floor, or a late roster "
                "addition) — the model never saw this player.")
    log = row.get("_recent_games") or []
    col = next((c for c, disp, _l in _MARKET_SPEC.values() if disp == market), None)
    if not log or not col:
        return "No recent-game data available for this player."
    values = [g.get(col) or 0 for g in log]
    avg = sum(values) / len(values)
    recent = values[:2]     # most recent first (see nfl_engine.player_recent_games)
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
    """Rank candidate plays across every position-relevant market by conviction (model prob vs
    the reference prob for that market), each with recent-form reasoning. No odds required — same
    output schema every sport's build_best_bets uses. Probabilities are shrunk toward a neutral
    baseline by sample size before being clipped, same fix every other sport carries."""
    rng = np.random.default_rng(seed)
    plays: List[Dict] = []

    for r in rows:
        log = r.get("_recent_games") or []
        markets = r.get("_markets") or []
        if not log or not markets:
            continue
        for mkey in markets:
            col, disp, line = _MARKET_SPEC[mkey]
            values = [g.get(col) or 0 for g in log]
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
                "Why": _player_reasons(values, line, side),
                "_stat_key": col, "_game_log": log,
            })

    plays.sort(key=lambda x: x["Conviction"], reverse=True)
    return plays


# --------------------------------------------------------------------------- Matchup Lab
def build_trend_series(log: List[Dict]) -> List[Dict]:
    """Chronological (oldest-to-newest) copy of a player's recent-game log, for a trend chart
    that reads left-to-right as time moving forward — the opposite of nfl_engine.
    get_player_recent_games's own most-recent-first contract. Same role as every other sport's
    build_trend_series."""
    return list(reversed(log))


def stat_key_for(col: str) -> str:
    """Row-column -> game-log dict key. An IDENTITY function for NFL, deliberately — unlike
    basketball's _MARKET_SPEC (which stores a short display column like "PTS" separately from the
    game-log dict key "pts"), NFL's _MARKET_SPEC already stores the real nflreadpy column name
    directly ("passing_yards"), so there's no separate short-name layer to translate through.
    Kept as its own function anyway, not inlined at call sites, purely for interface parity with
    WNBA/NBA/NCAAMB's own stat_key_for — Matchup Lab pages call this by name regardless of sport."""
    return col


def build_matchup_profile(row: Dict, h2h_log: List[Dict], opp_recent_allowed: Dict[str, float],
                          opp_season_allowed: Dict[str, float],
                          season_log: Optional[List[Dict]] = None) -> List[Dict]:
    """One row per market for Matchup Lab's deep-dive on a single player vs their upcoming
    opponent — see wnba_projections.build_matchup_profile's docstring for the shared reasoning
    behind each signal (identical spirit here; adapted, not copy-pasted, for two real NFL
    differences noted below, not a blind port).

    ONLY ITERATES `row["_markets"]` — a QB's profile never gets a phantom Receptions row, unlike
    basketball's blanket four-markets-for-everyone. Recent Avg is computed directly from `row
    ["_recent_games"]` here, not read off the row's own pre-formatted display fields (row["PassYds"]
    etc.) — those use different field names per market and would need their own translation layer
    for no real benefit, since the raw game log is already sitting right there.

    ONE GENUINELY NEW HONEST NOTE, MORE PRONOUNCED THAN EVEN NCAAMB'S OWN VERSION OF THIS CAVEAT:
    h2h_log will be empty far more often here than in ANY other sport on this platform — most NFL
    opponents meet exactly once a season (division rivals meet twice), unlike a college or pro
    basketball schedule that's still relatively balanced. An empty head-to-head sample is the
    OVERWHELMINGLY common case for most matchups here, not an edge case worth softening."""
    season_avgs: Dict[str, Optional[float]] = {}
    h2h_avgs: Dict[str, Optional[float]] = {}
    ratios: Dict[str, float] = {}
    markets = row.get("_markets") or []
    log = row.get("_recent_games") or []

    for mkey in markets:
        col, _disp, _line = _MARKET_SPEC[mkey]
        if season_log:
            svals = [g.get(col) or 0 for g in season_log]
            season_avgs[col] = (sum(svals) / len(svals)) if svals else None
        else:
            season_avgs[col] = None
        hvals = [g.get(col) or 0 for g in h2h_log]
        h2h_avgs[col] = (sum(hvals) / len(hvals)) if hvals else None
        sa, ha = season_avgs[col], h2h_avgs[col]
        if sa and sa > 0 and ha is not None:
            ratios[col] = ha / sa

    suppressed_key = None
    if len(ratios) >= 2:
        ranked = sorted(ratios.items(), key=lambda kv: kv[1])
        lowest_key, lowest_val = ranked[0]
        next_val = ranked[1][1]
        if lowest_val < 0.75 and (next_val - lowest_val) >= 0.15:
            suppressed_key = lowest_key

    out: List[Dict] = []
    for mkey in markets:
        col, disp, _line = _MARKET_SPEC[mkey]
        rvals = [g.get(col) or 0 for g in log]
        recent_avg = (sum(rvals) / len(rvals)) if rvals else 0.0
        season_avg = season_avgs.get(col)
        h2h_avg = h2h_avgs.get(col)

        hvals = [g.get(col) or 0 for g in h2h_log]
        h2h_spread = f"{min(hvals):.0f}\u2013{max(hvals):.0f}" if len(hvals) >= 2 else None
        high_variance = False
        if len(hvals) >= 2 and season_avg and season_avg > 0:
            spread = max(hvals) - min(hvals)
            high_variance = spread > season_avg * 0.75

        recent_allowed = opp_recent_allowed.get(col, 0.0)
        season_allowed = opp_season_allowed.get(col, 0.0)
        trend = (recent_allowed / season_allowed) if season_allowed > 0 else 1.0
        if trend >= 1.08:
            trend_tag = "📈 Looser lately"
        elif trend <= 0.92:
            trend_tag = "📉 Tighter lately"
        else:
            trend_tag = "➡️ Steady"

        out.append({
            "Market": disp,
            "Recent Avg": round(recent_avg, 1),
            "Season Avg": round(season_avg, 1) if season_avg is not None else None,
            "H2H Games": len(hvals),
            "H2H Avg": round(h2h_avg, 1) if h2h_avg is not None else None,
            "H2H Spread": h2h_spread,
            "High Variance": high_variance,
            "Suppressed": col == suppressed_key,
            "Opp Recent Allowed": round(recent_allowed, 1) if recent_allowed else None,
            "Opp Season Allowed": round(season_allowed, 1) if season_allowed else None,
            "Defense Trend": round(trend, 2),
            "Trend Tag": trend_tag,
        })
    return out


# --------------------------------------------------------------------------- Anytime TD
# Positions eligible for Anytime TD — includes QB, deliberately, unlike the four yardage markets
# above (which exclude QB rushing on purpose — see _MARKETS_FOR_POSITION's own docstring in
# nfl_engine.py: mixing a scrambling QB's occasional carries with a workhorse RB's volume under
# ONE yardage line would be misleading). Anytime TD doesn't have that problem — it's a binary
# outcome, not a shared line/market, so a mobile QB's real rushing-TD rate is its own honest
# signal here, not conflated with anyone else's number the way a shared yardage market would be.
_TD_ELIGIBLE_POSITIONS = {"QB", "RB", "WR", "TE", "FB"}


def build_anytime_td_board(rows: List[Dict], seed: Optional[int] = None) -> List[Dict]:
    """Rank players by their model probability of scoring ANY touchdown (rushing or receiving)
    this week — the NFL analog to MLB's Dinger Engine: a single, high-variance, boom/bust BINARY
    outcome, not a continuous-stat line like the four Core markets above.

    METHOD, DELIBERATELY DIFFERENT FROM THE FOUR CORE MARKETS, NOT AN OVERSIGHT: those bootstrap-
    resample a continuous stat and derive P(stat > line) from the resulting distribution. Scoring
    a TD is already a genuine Bernoulli outcome — did this game have one or not — so this skips
    the bootstrap step entirely and applies basketball_projections.shrink_prob DIRECTLY to the
    player's own empirical scoring rate (TD games ÷ games played). This is actually the CLEANER,
    more natural fit for shrink_prob's own mathematical foundation (a true binary rate) than the
    Core markets' use of it — not a repurposing of a tool built for something else.

    NO CONVICTION RATIO, RANKED BY RAW PROBABILITY INSTEAD — also deliberate: build_best_bets'
    Conviction (model prob ÷ a 0.5 reference) makes sense for a yardage Over/Under that naturally
    centers near a coin flip. Anytime TD has no equivalent single sensible reference — a workhorse
    RB's true scoring rate might be 35%, a WR's 15%, both can be a "good bet" relative to their
    OWN role, and dividing either by a shared 0.5 baseline wouldn't mean the same thing for both.
    Ranking directly by ModelProb (like MLB's own Dinger Engine) is the honest choice here."""
    out: List[Dict] = []
    for r in rows:
        position = r.get("Position")
        log = r.get("_recent_games") or []
        if position not in _TD_ELIGIBLE_POSITIONS or not log:
            continue
        n = len(log)
        td_games = sum(1 for g in log
                       if (g.get("rushing_tds") or 0) + (g.get("receiving_tds") or 0) > 0)
        raw_rate = td_games / n
        shrunk = BB_P.shrink_prob(raw_rate, n)
        prob = _clip_prob(shrunk)
        out.append({
            "Player": r["Player"], "PlayerId": r.get("_pid"), "Team": r["Team"],
            "Position": position, "Game": r["GameLabel"], "Opp": r.get("Opp"),
            "TDGames": td_games, "GamesPlayed": n,
            "ModelProb": round(prob, 4), "Fair": prob_to_american(prob),
            "Why": f"scored a TD in {td_games} of last {n} game(s) on file",
        })
    out.sort(key=lambda x: x["ModelProb"], reverse=True)
    return out
