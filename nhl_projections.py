"""
nhl_projections.py — turns nhl_engine's slate rows into priced probabilities.

Matches projections.py's OUTPUT CONTRACT exactly (build_projection_index / default_board_from_index
/ build_best_bets / explain_miss / DEFAULT_SIMS ...), which is what lets Edge Board, Best Bets,
Graded Picks, Retrospective and the rest consume NHL through the same code path via
sports.active().projections. The genuinely sport-agnostic pieces (prob_over, prob_for_side,
normalize_name, format_et, prob_to_decimal, prob_to_american, curate_selections) are imported
straight from projections.py, the same convention wnba/nba/ncaamb_projections follow.

BUILT AS A COPY-ADAPT OF nba_projections.py with the differences hockey actually forces:

  - SIX markets, split by ROLE. Skaters get Points, Assists, Goals, Shots on Goal and Blocked Shots;
    goalies get Saves only. A row's role (nhl_engine's "Role") decides which markets it is priced
    for — a goalie is never given a shots-on-goal line, a skater never a saves line. Market keys are
    the real Odds API keys (player_points, player_assists, player_goals, player_shots_on_goal,
    player_blocked_shots, player_total_saves), confirmed against the-odds-api.com's own NHL market
    list.
  - LOW-COUNT stats. Goals/assists/points are mostly 0 or 1 per game, so the "typical" over rate at
    the usual 0.5 line is nowhere near a coin flip (a regular skater scores in roughly one game in
    five). Basketball shrinks a small-sample probability toward 50/50; here each market shrinks
    toward ITS OWN typical rate (TYPICAL_OVER below) — otherwise a 10-game log with two goals
    would be dragged toward a fictional 50% and every goal prop would look like a huge Under edge.
    Those typical rates are starting-point estimates, NOT calibrated — same honest caveat the NBA
    module's default lines carry. They are also the Conviction reference when no live odds are
    fetched (BEST_BET_REF); with live odds, the real no-vig market probability replaces them.
  - No Hot Hand Engine / Matchup Lab (yet). Those pages are basketball-shaped (per-100-possession
    pace, minutes); a hockey version would be its own build. What NHL has is the shared pipeline.

METHOD (a documented v1): each of a player's last N games is one draw from his talent
distribution; the projection is an empirical bootstrap (resample with replacement `sims` times).
Known limits: a short log (early season, new team) cannot show tail outcomes it hasn't produced;
opponent strength, power-play time, line changes and — for goalies — the actual starter are NOT in
the probability. A goalie is projected only if he was his team's goalie of record in one of its last
few games; the real starter is confirmed on game day, so treat any Saves play as "if he starts".
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from projections import (  # genuinely sport-agnostic — reused, not duplicated
    prob_over, prob_for_side, normalize_name, format_et,
    prob_to_decimal, prob_to_american, curate_selections,
)
import basketball_projections as BB_P   # shrink_prob is sport-agnostic (takes a `reference`)
import odds_api as O                    # real_entry_price / real_market_prob — real price wiring

DEFAULT_SIMS = 10000

# Odds-API-market-key -> (row column, display name, default line, role, game-log key).
# Default lines are the model-only board's fallbacks (used only before live odds are fetched), not
# calibrated book numbers: the usual posted lines for a regular NHL skater / starting goalie.
_MARKET_SPEC = {
    "player_points":        ("PTS", "Points",        0.5,  "skater", "pts"),
    "player_assists":       ("AST", "Assists",       0.5,  "skater", "ast"),
    "player_goals":         ("G",   "Goals",         0.5,  "skater", "goals"),
    "player_shots_on_goal": ("SOG", "Shots on Goal", 2.5,  "skater", "sog"),
    "player_blocked_shots": ("BLK", "Blocked Shots", 1.5,  "skater", "blk"),
    "player_total_saves":   ("SV",  "Saves",         25.5, "goalie", "saves"),
}
_STAT_KEY = {col: skey for (col, _d, _l, _r, skey) in _MARKET_SPEC.values()}

# Typical P(Over the default line) for a rotation player — the shrinkage target AND the
# no-live-odds Conviction reference. Rough league-wide starting points, NOT calibrated.
TYPICAL_OVER = {"Points": 0.38, "Assists": 0.27, "Goals": 0.20, "Shots on Goal": 0.35,
                "Blocked Shots": 0.40, "Saves": 0.55}
BEST_BET_REF = dict(TYPICAL_OVER)


def market_list() -> List[Tuple[str, str, str]]:
    """[(market_key, row_column, display_name), ...] for all six markets, stable order."""
    return [(mkey, col, disp) for mkey, (col, disp, _l, _r, _s) in _MARKET_SPEC.items()]


def markets_for_role(role: str) -> List[str]:
    """The Odds API market keys a row of this role ("skater"/"goalie") is priced for."""
    return [mkey for mkey, spec in _MARKET_SPEC.items() if spec[3] == role]


def stat_key_for(col: str) -> str:
    """Row column ('PTS'/'AST'/'G'/'SOG'/'BLK'/'SV') -> game-log key ('pts'/'ast'/'goals'/...)."""
    return _STAT_KEY[col]


def default_line(market_key: str) -> Optional[float]:
    spec = _MARKET_SPEC.get(market_key)
    return spec[2] if spec else None


def build_trend_series(log: List[Dict]) -> List[Dict]:
    """Chronological (oldest-to-newest) copy of a most-recent-first game log."""
    return list(reversed(log))


def _dist(samples: np.ndarray) -> np.ndarray:
    """Normalized histogram: index i -> P(outcome == i). Same shape/semantics as projections._dist,
    so odds_api.compute_edges works identically for every sport."""
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
    """Bootstrap `sims` draws (with replacement) from a player's recent-game values for one stat,
    rounded to non-negative integers. Empty array if there is no game log to sample from."""
    if not recent_values:
        return np.array([], dtype=np.int64)
    draws = rng.choice(np.asarray(recent_values, dtype=np.float64), size=sims, replace=True)
    return np.clip(np.round(draws), 0, None).astype(np.int64)


def _clip_prob(p: float) -> float:
    """Keep probabilities strictly inside (0, 1) so prob_to_american never hits its exact-boundary
    None case (a real production crash on other sports)."""
    return min(max(p, 0.02), 0.98)


def _role_of(row: Dict) -> str:
    return row.get("_role") or row.get("Role") or "skater"


def _shrunk_over(raw: float, n_games: int, disp: str) -> float:
    """Small-sample shrinkage toward THIS market's typical rate (not 50/50 — see module docstring),
    then the final clamp."""
    return _clip_prob(BB_P.shrink_prob(raw, n_games, reference=TYPICAL_OVER.get(disp, 0.5)))


# --------------------------------------------------------------------------- projection index
def build_projection_index(rows: List[Dict], meta: List[Dict],
                           sims: int = DEFAULT_SIMS, seed: Optional[int] = None) -> Dict:
    """{(normalized_name, odds_market_key): {dist, mean, n_games, ctx}} for the slate — identical
    shape to projections.build_projection_index (plus n_games for shrinkage downstream). Each row
    is projected only for the markets its role is priced for."""
    rng = np.random.default_rng(seed)
    index: Dict = {}
    for r in rows:
        log = r.get("_game_log") or []
        if not log:
            continue
        nm = normalize_name(r["Player"])
        ctx = {"player": r["Player"], "team": r["Team"], "game": r["GameLabel"],
               "opp": r.get("Opp"), "lineup": "Active", "game_date": r.get("_game_date")}
        for mkey in markets_for_role(_role_of(r)):
            skey = _MARKET_SPEC[mkey][4]
            values = [g.get(skey, 0.0) for g in log]
            sim = simulate_player_stat(values, sims, rng)
            if sim.size == 0:
                continue
            index[(nm, mkey)] = {"dist": _dist(sim), "mean": float(sim.mean()),
                                 "n_games": len(values), "ctx": ctx}
    return index


def default_board_from_index(index: Dict) -> List[Dict]:
    """Model-only board (favored side at default lines) from the index — same shape/logic as the
    other sports' (every NHL market here is a plain Over/Under)."""
    out: List[Dict] = []
    for (nm, mkey), entry in index.items():
        _col, disp, line, _role, _skey = _MARKET_SPEC.get(mkey, (mkey, mkey, 0.5, "skater", ""))
        dist, ctx = entry["dist"], entry["ctx"]
        over = _shrunk_over(prob_over(dist, line), entry.get("n_games", 0), disp)
        side, prob = ("Over", over) if over >= 0.5 else ("Under", 1 - over)
        out.append(_signal(ctx["player"], ctx["team"], ctx["game"], disp, side, line, prob,
                           entry["mean"], Opp=ctx.get("opp"), Lineup=ctx.get("lineup"),
                           GameTime=ctx.get("game_date")))
    return out


# --------------------------------------------------------------------------- Best Bets
def _favored_side(prob_over_: float, ref: float):
    """Return (side, prob_of_that_side, ref_for_that_side)."""
    if prob_over_ >= ref:
        return "Over", prob_over_, ref
    return "Under", 1.0 - prob_over_, 1.0 - ref


def _player_reasons(values: List[float], line: float, side: str, disp: str = "") -> str:
    """'Why' text from the player's own recent-game log: how consistently he has cleared this exact
    line, and whether the last few games trend away from his own average."""
    n = len(values)
    if n == 0:
        return "no recent-game data available"
    hits = sum(1 for v in values if v > line) if side == "Over" else sum(1 for v in values if v < line)
    avg = sum(values) / n
    recent = values[:3]                       # most recent first (nhl_engine.get_player_recent_games)
    recent_avg = sum(recent) / len(recent) if recent else avg
    trend = ""
    if recent and avg > 0 and abs(recent_avg - avg) >= max(0.5 if avg < 3 else 1.5, avg * 0.30):
        trend = ", trending up" if recent_avg > avg else ", trending down"
    verb = "cleared" if side == "Over" else "stayed under"
    extra = "; starter unconfirmed until game day" if disp == "Saves" else ""
    return f"{verb} {line:g} in {hits} of last {n} games (avg {avg:.1f}{trend}){extra}"


def explain_miss(row: Optional[Dict], market: str = "Points") -> str:
    """NHL equivalent of retro.explain_miss's role: explain a result the model ranked LOW. `row`
    is a build_slate row looked up by player id; None means the player wasn't on the projected
    slate at all (below the TOI bar / not a recent goalie of record / a late addition)."""
    if not row:
        return ("Not on the projected slate (recent ice time below the lineup bar, no recent game "
                "on file, or a goalie who wasn't a recent starter) — the model never saw this player.")
    log = row.get("_game_log") or []
    spec = next((s for s in _MARKET_SPEC.values() if s[1] == market), None)
    if not log or not spec:
        return "No recent-game data available for this player."
    skey = spec[4]
    values = [g.get(skey, 0) for g in log]
    avg = sum(values) / len(values)
    recent = values[:3]
    recent_avg = sum(recent) / len(recent) if recent else avg
    if avg > 0 and recent_avg >= avg * 1.25:
        return (f"Catchable — trending up over the last {len(recent)} games (avg {recent_avg:.1f} "
                f"vs {avg:.1f} in the full recent sample) before this one; recency weighting "
                "hadn't fully caught up yet.")
    return (f"Genuine outlier — averaging {avg:.1f} over the last {len(values)} games with no "
            "recent uptick; this result sits above their established form. Variance, not a "
            "systematic miss (hockey counting stats are especially lumpy).")


def build_best_bets(rows: List[Dict], sims: int = DEFAULT_SIMS,
                    seed: Optional[int] = None,
                    real_lines: Optional[Dict] = None,
                    offers: Optional[List[Dict]] = None,
                    preferred_book: Optional[str] = None) -> List[Dict]:
    """Rank candidate plays across every market by conviction (model prob vs the reference prob
    for that market), each with recent-form reasoning. Output schema (Player/PlayerId/Team/Game/
    Opp/Versus/Market/Side/Line/ModelProb/Fair/Conviction/Why ...) matches projections.
    build_best_bets's so Best Bets, Command Center, Media Room and Podcast Studio render any
    sport's plays through the same code.

    Real data, wired in the same way as MLB/WNBA/NBA: `real_lines` supplies the actual book line
    (else the _MARKET_SPEC placeholder; LineSource records which), `offers` supplies the real
    no-vig market probability as Conviction's reference (else TYPICAL_OVER; ConvictionSource) and a
    real captured price (else the model's own Fair price; PriceSource). None for all three keeps
    the always-placeholder, always-theoretical behavior for any caller that has no odds."""
    rng = np.random.default_rng(seed)
    plays: List[Dict] = []
    for r in rows:
        log = r.get("_game_log") or []
        if not log:
            continue
        norm_name = normalize_name(r["Player"])
        for mkey in markets_for_role(_role_of(r)):
            col, disp, dline, _role, skey = _MARKET_SPEC[mkey]
            values = [g.get(skey, 0.0) for g in log]
            line, line_src = dline, "default"
            if real_lines is not None:
                real = real_lines.get((norm_name, mkey))
                if real is not None:
                    line, line_src = float(real), "book"
            sim = simulate_player_stat(values, sims, rng)
            if sim.size == 0:
                continue
            over = _shrunk_over(prob_over(_dist(sim), line), len(values), disp)

            ref, ref_src = BEST_BET_REF.get(disp, 0.5), "model_typical"
            if offers:
                real_over_prob = O.real_market_prob(offers, r["Player"], mkey, "over",
                                                    preferred_book=preferred_book)
                if real_over_prob is not None:
                    ref, ref_src = real_over_prob, "book"
            # A reference of exactly 0/1 can't be a ratio's denominator on either side.
            ref = min(max(ref, 0.02), 0.98)
            side, sp, ref_s = _favored_side(over, ref)

            fair = prob_to_american(sp)
            real_price, real_price_book, price_src = None, None, "model_fair"
            if offers:
                real = O.real_entry_price(offers, r["Player"], mkey, side,
                                          preferred_book=preferred_book)
                if real is not None:
                    real_price, _real_point, real_price_book = real
                    price_src = "book"

            plays.append({
                "Player": r["Player"], "PlayerId": r.get("_pid"), "Team": r["Team"],
                "Game": r["GameLabel"], "Opp": r.get("Opp"), "Versus": r.get("Opp"),
                "Market": disp, "Side": side, "Line": line, "LineSource": line_src,
                "ModelProb": round(sp, 4), "Fair": fair,
                "RealPrice": real_price, "RealPriceBook": real_price_book, "PriceSource": price_src,
                "Conviction": round(sp / ref_s, 2) if ref_s > 0 else 0.0,
                "ConvictionSource": ref_src,
                # this play's own theoretical max conviction (1/RefProb) — lets
                # grading.conviction_to_grade normalize fairly across markets with very
                # different reference rates (hockey's are far from 50/50)
                "_ceiling": round(1.0 / ref_s, 2) if ref_s > 0 else None,
                "Why": _player_reasons(values, line, side, disp),
                "_stat_key": skey, "_game_log": log,
            })
    plays.sort(key=lambda x: x["Conviction"], reverse=True)
    return plays
