"""
projections.py — turns the season stats the engine already fetches into real
probabilities for the seven prop markets, plus model "fair odds" you can hold up
against a sportsbook price.
 
Batters: build a per-plate-appearance outcome distribution (K / BB / out-in-play /
1B / 2B / 3B / HR) from season rates, adjust for park, and Monte-Carlo the game's
plate appearances. One simulation yields HR, total bases, hits, and strikeouts.
 
Pitchers: project expected innings -> batters faced, then K and BB as Poisson and
recorded outs as a clipped normal.
 
Pure NumPy. No network, no Streamlit. The engine calls build_signals() with data it
already has, so projections add zero API calls.
 
IMPORTANT — what this is and isn't:
  * These are MODEL probabilities, not market-calibrated truth, and not edges.
  * "Fair odds" = the price implied by the model probability. Edge only exists once
    you compare it to a real book line (next build step). Until then, treat fair odds
    as "the number you'd need to beat to have value."
"""
 
from __future__ import annotations
 
import math
import re
import unicodedata
from typing import Any, Dict, List, Optional
 
import numpy as np
 
# ---- per-PA outcome model --------------------------------------------------
OUTCOMES = ["out_play", "k", "bb", "single", "double", "triple", "hr"]
OUT_PLAY, K, BB, SINGLE, DOUBLE, TRIPLE, HR = range(7)
TB_VALUE = np.array([0, 0, 0, 1, 2, 3, 4], dtype=np.int64)
HIT_FLAG = np.array([0, 0, 0, 1, 1, 1, 1], dtype=np.int64)
 
# Expected plate appearances by batting-order index (0 = leadoff ... 8 = nine-hole).
LINEUP_SPOT_PA = [4.65, 4.55, 4.45, 4.35, 4.25, 4.10, 4.00, 3.90, 3.80]
DEFAULT_UNKNOWN_PA = 4.25
 
# Park factors by MLB venue id (hr / hits multipliers). Unlisted -> neutral.
PARK_FACTORS = {
    1: {"hr": 1.18, "hits": 1.04}, 2: {"hr": 0.95, "hits": 1.00}, 3: {"hr": 0.96, "hits": 1.08},
    4: {"hr": 1.10, "hits": 1.02}, 5: {"hr": 1.10, "hits": 1.03}, 7: {"hr": 1.30, "hits": 1.10},
    9: {"hr": 0.92, "hits": 0.96}, 12: {"hr": 1.02, "hits": 1.00}, 14: {"hr": 1.05, "hits": 1.00},
    15: {"hr": 1.08, "hits": 1.02}, 17: {"hr": 1.06, "hits": 1.02}, 19: {"hr": 0.98, "hits": 1.01},
    22: {"hr": 1.07, "hits": 1.01},
}
NEUTRAL_PARK = {"hr": 1.0, "hits": 1.0}
 
# Default lines (placeholders until a live odds feed supplies the real book line).
DEFAULT_LINES = {
    "Batter Total Bases": 1.5,
    "Batter Total Hits": 0.5,
    "Batter Strikeouts": 0.5,
    "Pitcher Strikeouts": 5.5,
    "Pitcher Outs": 17.5,
    "Pitcher Walks": 1.5,
}
 
DEFAULT_SIMS = 12000
 
# Maps our model markets to The Odds API market keys (verify against their docs;
# keys occasionally change). HR is just Over 0.5 on batter_home_runs.
ODDS_MARKET_KEYS = {
    "batter_home_runs": "hr",
    "batter_total_bases": "tb",
    "batter_hits": "hits",
    "batter_strikeouts": "bk",
    "pitcher_strikeouts": "pk",
    "pitcher_outs": "outs",
    "pitcher_walks": "pbb",
}
 
 
def _f(stat: Dict, key: str, default: float = 0.0) -> float:
    try:
        return float(stat.get(key, default))
    except (TypeError, ValueError):
        return default
 
 
def _parse_ip(v) -> float:
    s = str(v or "0")
    if "." not in s:
        try:
            return float(s)
        except ValueError:
            return 0.0
    whole, frac = s.split(".", 1)
    try:
        return float(whole) + {"0": 0, "1": 1, "2": 2}.get(frac[:1], 0) / 3.0
    except ValueError:
        return 0.0
 
 
# ---- odds helpers ----------------------------------------------------------
def prob_to_decimal(p: float) -> Optional[float]:
    return round(1.0 / p, 2) if p > 0 else None
 
 
def prob_to_american(p: float) -> Optional[int]:
    if p <= 0 or p >= 1:
        return None
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))
 
 
# ---- regression to the mean (shrinkage) ------------------------------------
# Small samples lie. We pull every observed rate toward a league baseline by a weight
# tied to how much data backs it, so an 11-inning hot streak doesn't project like a skill.
# Per-PA league rates (approx. 2020s MLB) and per-stat "prior" weights (in PA / BF).
# Prior = the sample size at which observed and league get equal weight; bigger prior =
# more regression. Rates that stabilize slowly (HR, hits) get bigger priors than fast ones (K).
LG_BATTER = {  # rate, prior_pa
    "hr": (0.033, 170), "2b": (0.046, 140), "3b": (0.004, 120),
    "1b": (0.143, 140), "bb": (0.085, 110), "k": (0.225, 90),
}
LG_PITCHER = {  # rate per batter faced, prior_bf
    "k": (0.222, 150), "bb": (0.082, 350),
}
 
 
def _shrink(count: float, sample: float, lg_rate: float, prior: float) -> float:
    """Regress an observed rate toward league average. Returns a per-event probability."""
    return (count + lg_rate * prior) / (sample + prior) if (sample + prior) > 0 else lg_rate
 
 
# League per-PA rates as a flat lookup (for odds-ratio matchup math).
LG_RATE = {k: v[0] for k, v in LG_BATTER.items()}
LG_NONHR_HIT = LG_RATE["1b"] + LG_RATE["2b"] + LG_RATE["3b"]  # ~0.193
 
# Platoon splits stabilize slowly, so a vs-hand split is regressed toward the player's
# own (already league-stabilized) season rate using this prior, in PA.
SPLIT_PRIOR_PA = 150
 
 
# ---- odds-ratio (log5) matchup math ----------------------------------------
def _odds(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return p / (1 - p)
 
 
def odds_ratio(p_bat: float, p_pit: float, p_lg: float) -> float:
    """Tango's odds-ratio method: combine a batter's rate, the pitcher's rate of ALLOWING
    that event, and league average into a single matchup-specific probability.
    p = OR_bat * OR_pit / OR_lg, converted back from odds."""
    if p_lg <= 0:
        return p_bat
    o = _odds(p_bat) * _odds(p_pit) / _odds(p_lg)
    return o / (1 + o)
 
 
# ---- batter model ----------------------------------------------------------
def pitcher_allowed_rates(stat: Optional[Dict]) -> Optional[Dict]:
    """Shrunk per-batter rates of what a pitcher ALLOWS, for the matchup math.
    Returns None for missing/thin pitchers so the batter falls back to neutral."""
    if not stat:
        return None
    bf = _f(stat, "battersFaced")
    if bf < 40:
        return None
    hr = _f(stat, "homeRuns"); so = _f(stat, "strikeOuts"); bb = _f(stat, "baseOnBalls")
    hits = _f(stat, "hits")
    nonhr_hit = max(hits - hr, 0.0)
    return {
        "hr": _shrink(hr, bf, LG_RATE["hr"], 220),
        "k": _shrink(so, bf, LG_RATE["k"], 150),
        "bb": _shrink(bb, bf, LG_RATE["bb"], 350),
        "nonhr_hit": _shrink(nonhr_hit, bf, LG_NONHR_HIT, 180),
    }
 
 
def _rates_from_stat(stat: Dict) -> Optional[Dict]:
    """Raw (unshrunk) per-PA component rates from a hitting stat dict."""
    pa = _f(stat, "plateAppearances")
    if pa <= 0:
        return None
    hits = _f(stat, "hits"); doubles = _f(stat, "doubles"); triples = _f(stat, "triples")
    hr = _f(stat, "homeRuns"); bb = _f(stat, "baseOnBalls"); so = _f(stat, "strikeOuts")
    singles = max(hits - doubles - triples - hr, 0.0)
    return {"pa": pa, "hr": hr, "2b": doubles, "3b": triples, "1b": singles, "bb": bb, "k": so}
 
 
def batter_base_rates(season_stat: Dict, split_stat: Optional[Dict] = None,
                      xhr_pa: Optional[float] = None) -> Optional[Dict]:
    """Per-PA outcome rates for a hitter: season regressed to league (or, for HR, toward
    the Statcast contact-implied rate when supplied), then the vs-hand split regressed
    toward that stabilized season rate."""
    s = _rates_from_stat(season_stat)
    if s is None or s["pa"] < 20:
        return None
    pa = s["pa"]
    base = {}
    for o in ("hr", "2b", "3b", "1b", "bb", "k"):
        lg_rate, prior = LG_BATTER[o]
        # For HR, regress toward the barrel-implied expected rate if we have it — a far
        # better prior than league average for that specific hitter.
        target = xhr_pa if (o == "hr" and xhr_pa is not None) else lg_rate
        base[o] = _shrink(s[o], pa, target, prior)
 
    sp = _rates_from_stat(split_stat) if split_stat else None
    if sp and sp["pa"] >= 20:
        spa = sp["pa"]
        for o in ("hr", "2b", "3b", "1b", "bb", "k"):
            base[o] = _shrink(sp[o], spa, base[o], SPLIT_PRIOR_PA)  # regress split toward season
    return base
 
 
def batter_pa_probs(season_stat: Dict, park: Dict, opp_allowed: Optional[Dict] = None,
                    split_stat: Optional[Dict] = None, xhr_pa: Optional[float] = None,
                    weather_hr: float = 1.0) -> Optional[np.ndarray]:
    """Per-PA outcome distribution: matchup-, platoon-, Statcast-, and weather-aware.
 
    Order: stabilized base rates (handedness + barrel-implied HR) -> odds-ratio vs the
    pitcher -> park -> weather (temperature + wind on HR)."""
    base = batter_base_rates(season_stat, split_stat, xhr_pa)
    if base is None:
        return None
    p_hr, p_3b, p_2b, p_1b = base["hr"], base["3b"], base["2b"], base["1b"]
    p_bb, p_k = base["bb"], base["k"]
 
    # Matchup: combine batter rate with the pitcher's allowed rate via odds-ratio.
    if opp_allowed:
        p_hr = odds_ratio(p_hr, opp_allowed["hr"], LG_RATE["hr"])
        p_k = odds_ratio(p_k, opp_allowed["k"], LG_RATE["k"])
        p_bb = odds_ratio(p_bb, opp_allowed["bb"], LG_RATE["bb"])
        nonhr = p_1b + p_2b + p_3b
        if nonhr > 0:
            adj = odds_ratio(nonhr, opp_allowed["nonhr_hit"], LG_NONHR_HIT)
            scale = adj / nonhr
            p_1b *= scale; p_2b *= scale; p_3b *= scale
 
    # Park, then weather (temperature + out-to-CF wind act on home runs).
    p_hr *= park.get("hr", 1.0) * weather_hr
    p_3b *= park.get("hits", 1.0); p_2b *= park.get("hits", 1.0); p_1b *= park.get("hits", 1.0)
 
    probs = np.array([0.0, p_k, p_bb, p_1b, p_2b, p_3b, p_hr], dtype=np.float64)
    if probs.sum() >= 1.0:
        probs = probs / probs.sum()
    probs[OUT_PLAY] = max(1.0 - probs.sum(), 0.0)
    return probs
 
 
def simulate_batter(probs: np.ndarray, exp_pa: float, sims: int, rng) -> Dict[str, np.ndarray]:
    base = int(np.floor(exp_pa))
    extra_p = exp_pa - base
    max_pa = base + 1
    draws = rng.choice(len(OUTCOMES), size=(sims, max_pa), p=probs)
    valid = np.ones((sims, max_pa), dtype=bool)
    valid[:, base:] = (rng.random(sims) < extra_p)[:, None]
    tb = np.where(valid, TB_VALUE[draws], 0).sum(axis=1)
    hits = np.where(valid, HIT_FLAG[draws], 0).sum(axis=1)
    hr = np.where(valid, (draws == HR), 0).sum(axis=1)
    k = np.where(valid, (draws == K), 0).sum(axis=1)
    return {"tb": tb, "hits": hits, "hr": hr, "k": k}
 
 
# ---- pitcher model ---------------------------------------------------------
def lineup_k_bb_rates(stats_list: list) -> Optional[Dict]:
    """Aggregate a lineup's per-PA strikeout and walk rates (shrunk toward league).
 
    This is the symmetric input to the batter matchup: how often THIS lineup, as a group,
    strikes out and walks. Used to make pitcher K/BB projections matchup-aware."""
    tot_pa = tot_k = tot_bb = 0.0
    for s in stats_list:
        if not s:
            continue
        tot_pa += _f(s, "plateAppearances")
        tot_k += _f(s, "strikeOuts")
        tot_bb += _f(s, "baseOnBalls")
    if tot_pa < 200:  # not enough lineup data to trust
        return None
    return {
        "k": _shrink(tot_k, tot_pa, LG_RATE["k"], 300),
        "bb": _shrink(tot_bb, tot_pa, LG_RATE["bb"], 300),
    }
 
 
def build_lineup_rate_map(rows: list) -> Dict:
    """Map (game_label, team_name) -> that lineup's aggregate K/BB rates, for pitcher matchups."""
    groups: Dict = {}
    for r in rows:
        key = (r.get("GameLabel"), r.get("Team"))
        groups.setdefault(key, []).append(r.get("_stat"))
    return {k: lineup_k_bb_rates(v) for k, v in groups.items()}
 
 
def project_pitcher(stat: Dict, opp_lineup: Optional[Dict] = None) -> Optional[Dict]:
    """Project a STARTER's K / outs / walks. Returns None for non-starters or thin samples.
 
    Guards against the inflation bug:
      1. Starter gate: needs real starts, else it's a bullpen game/opener -> skip.
      2. Shrinkage: K and BB rates regress toward league average by batters faced.
      3. Clamps: expected counts capped at realistic ceilings as a backstop.
 
    When opp_lineup (the opposing lineup's K/BB rates) is supplied, K and BB are made
    matchup-aware via the odds-ratio method: a strikeout pitcher facing a whiff-prone
    lineup projects for more Ks; facing a contact lineup, fewer.
    """
    bf = _f(stat, "battersFaced")
    ip = _parse_ip(stat.get("inningsPitched"))
    gs = _f(stat, "gamesStarted")
    so = _f(stat, "strikeOuts")
    bb = _f(stat, "baseOnBalls")
 
    # 1. Starter gate. A genuine probable starter has multiple starts and real innings.
    if gs < 3 or ip < 15 or bf < 60:
        return None
 
    # Expected innings from this pitcher's own start length, bounded to realistic range.
    exp_ip = float(np.clip(ip / gs, 3.0, 7.0))
    bf_per_ip = float(np.clip(bf / ip if ip > 0 else 4.3, 3.9, 4.7))
    exp_bf = exp_ip * bf_per_ip
 
    # 2. Shrinkage: regress per-batter K and BB rates toward league average.
    k_rate = _shrink(so, bf, *LG_PITCHER["k"])
    bb_rate = _shrink(bb, bf, *LG_PITCHER["bb"])
 
    # 2b. Matchup: combine with the opposing lineup's rates via odds-ratio.
    if opp_lineup:
        k_rate = odds_ratio(k_rate, opp_lineup["k"], LG_RATE["k"])
        bb_rate = odds_ratio(bb_rate, opp_lineup["bb"], LG_RATE["bb"])
 
    # 3. Clamp expected counts to realistic ceilings (backstop against any residual noise).
    exp_k = float(min(k_rate * exp_bf, 0.45 * exp_bf))
    exp_bb = float(min(bb_rate * exp_bf, 0.25 * exp_bf))
 
    return {
        "exp_ip": exp_ip, "exp_outs": exp_ip * 3.0, "exp_bf": exp_bf,
        "exp_k": exp_k, "exp_bb": exp_bb,
    }
 
 
def times_through_order(exp_bf: float, lineup_size: int = 9) -> float:
    """Expected number of times a starter cycles through the lineup, given his own expected
    batters faced (exp_bf, already computed by project_pitcher above) — a simple derived read
    (exp_bf / lineup_size), not a new data source or a new model.

    POWERS PITCHING LAB'S TIMES-THROUGH-THE-ORDER CONTEXT, DELIBERATELY NOT A PER-PITCHER
    ADJUSTMENT TO exp_k/exp_bb THEMSELVES: the times-through-the-order penalty (TTOP) is real and
    well-documented (Baseball Prospectus, SABR/Lichtman) — roughly an 8-12 wOBA-point-against
    increase per additional trip through the order, more for fastball-heavy pitchers, less for
    pitchers who mix more — but that range varies enough by a pitcher's own repertoire that baking
    one specific number into every starter's projection would overclaim precision the underlying
    research itself doesn't support at the individual-pitcher level. This number — how many times
    THIS start is even expected to reach the order — is the honest, genuinely pitcher-specific
    piece: a start projecting under 2 trips carries much less TTOP exposure than one projecting a
    real 3rd trip, regardless of the exact per-point magnitude for that specific pitcher."""
    if lineup_size <= 0:
        return 0.0
    return exp_bf / lineup_size


def hitter_starter_exposures(lineup_idx: int, starter_proj_bf: float, exp_pa: float,
                             lineup_size: int = 9) -> Dict[str, float]:
    """How many of THIS hitter's own expected plate appearances (exp_pa) fall against the
    STARTER specifically, vs. against the bullpen once the starter's own projected work
    (starter_proj_bf, from project_pitcher's exp_bf) is exhausted — the genuine connective
    tissue between times_through_order (a STARTER-side number) and a SPECIFIC hitter's own
    exposure to it, and between the starter projection and Dinger Engine's own bullpen-matchup
    toggle: a hitter whose later PA fall past the starter's projected work are, correctly, facing
    a FRESH bullpen arm for those PA — not carrying the same repeat-look exposure a hitter who
    keeps seeing the starter would. This is the answer to "does TTO reach the hitter side, and
    does it connect to the bullpen toggle": yes to both, through this shared, derived number —
    not two disconnected features.

    DERIVED FROM REAL INPUTS ALREADY IN THE ROW, NOT A NEW FABRICATED NUMBER: lineup_idx (0 =
    leadoff, already stored on every hitter row) tells us which "batter number" (1st, 10th, 19th,
    ... for the leadoff hitter) this hitter is for the starter, each time through the lineup.
    starter_proj_bf (project_pitcher's own exp_bf, already computed for Pitching Lab) tells us
    how many total batters the starter is projected to face before being pulled. A hitter's own
    PA fall against the starter for as long as their own batter-number sequence stays within that
    window, and against the bullpen once it doesn't — pure arithmetic on numbers this platform
    already computes elsewhere, not a new assumption.

    Returns {"vs_starter": float, "vs_bullpen": float} summing to exp_pa (rounding may leave a
    negligible difference). DELIBERATELY DOES NOT RETURN A PROBABILITY ADJUSTMENT — same
    reasoning times_through_order's own docstring already gives: baking a specific per-pitcher
    wOBA adjustment into hitter probabilities would overclaim precision the underlying TTOP
    research doesn't support at the individual-pitcher level. This is the honest, genuinely
    derivable half of the question — WHO gets multiple looks at the starter and WHO mostly
    faces the bullpen instead — not exactly how much each look is worth."""
    if lineup_size <= 0 or exp_pa <= 0:
        return {"vs_starter": 0.0, "vs_bullpen": round(max(exp_pa, 0.0), 2)}
    if starter_proj_bf <= lineup_idx:
        # This hitter's own FIRST plate appearance already exceeds the starter's projected work
        # (a very short outing, or a hitter batting deep in the order) -> entirely bullpen.
        return {"vs_starter": 0.0, "vs_bullpen": round(exp_pa, 2)}
    exposures_to_starter = int((starter_proj_bf - lineup_idx - 1) // lineup_size) + 1
    vs_starter = min(float(exposures_to_starter), exp_pa)
    vs_bullpen = max(exp_pa - vs_starter, 0.0)
    return {"vs_starter": round(vs_starter, 2), "vs_bullpen": round(vs_bullpen, 2)}


def simulate_pitcher(proj: Dict, sims: int, rng) -> Dict[str, np.ndarray]:
    k = rng.poisson(proj["exp_k"], size=sims)
    bb = rng.poisson(proj["exp_bb"], size=sims)
    sigma = max(3.0, proj["exp_outs"] * 0.22)
    outs = np.clip(np.round(rng.normal(proj["exp_outs"], sigma, size=sims)), 0, 27).astype(np.int64)
    return {"k": k, "bb": bb, "outs": outs}
 
 
# ---- signal assembly -------------------------------------------------------
def _signal(player, team, game, market, side, line, prob, projection, **extra) -> Dict:
    prob = float(round(prob, 4))
    sig = {
        "Player": player, "Team": team, "Game": game, "Market": market,
        "Side": side, "Line": line, "ModelProb": prob, "Projection": round(float(projection), 2),
        "FairDec": prob_to_decimal(prob), "FairAm": prob_to_american(prob),
        # placeholders the odds-feed step will fill:
        "BookOdds": None, "Implied": None, "EdgePct": None,
    }
    sig.update(extra)
    return sig
 
 
def _favored(samples: np.ndarray, line: float):
    over = float(np.mean(samples > line))
    return ("Over", over) if over >= 0.5 else ("Under", 1.0 - over)
 
 
def build_signals(rows: List[Dict], meta: List[Dict], sims: int = DEFAULT_SIMS,
                  seed: Optional[int] = None) -> List[Dict]:
    """Produce one signal per (player, market) from data the engine already fetched.
 
    `rows` must carry the private fields the engine attaches: _stat, _exp_pa, _venue_id.
    `meta` pitchers come from PitcherMetrics (with a .stat dict)."""
    rng = np.random.default_rng(seed)
    signals: List[Dict] = []
 
    # Batters
    for r in rows:
        stat = r.get("_stat")
        if not stat:
            continue
        park = PARK_FACTORS.get(r.get("_venue_id"), NEUTRAL_PARK)
        opp_allowed = pitcher_allowed_rates(r.get("_opp_stat"))
        probs = batter_pa_probs(stat, park, opp_allowed, r.get("_split_stat"))
        if probs is None:
            continue
        sim = simulate_batter(probs, r.get("_exp_pa", DEFAULT_UNKNOWN_PA), sims, rng)
        player, team, game = r["Hitter"], r["Team"], r["GameLabel"]
 
        hr_p = float(np.mean(sim["hr"] >= 1))
        signals.append(_signal(player, team, game, "Batter HR", "Yes", None, hr_p, sim["hr"].mean(),
                               Opp=r.get("Opp Pitcher"), Lineup=r.get("Lineup")))
        for market, arr in (("Batter Total Bases", sim["tb"]), ("Batter Total Hits", sim["hits"]),
                            ("Batter Strikeouts", sim["k"])):
            line = DEFAULT_LINES[market]
            side, p = _favored(arr, line)
            signals.append(_signal(player, team, game, market, side, line, p, arr.mean(),
                                   Opp=r.get("Opp Pitcher"), Lineup=r.get("Lineup")))
 
    # Pitchers (matchup-aware: each starter projected vs the opposing lineup's K/BB rates)
    lineup_map = build_lineup_rate_map(rows)
    for m in meta:
        for pm, team, opp in ((m["home_pm"], m["home_name"], m["away_name"]),
                              (m["away_pm"], m["away_name"], m["home_name"])):
            if pm.id is None or not pm.stat:
                continue
            proj = project_pitcher(pm.stat, lineup_map.get((m["label"], opp)))
            if not proj:
                continue
            sim = simulate_pitcher(proj, sims, rng)
            for market, arr, key in (("Pitcher Strikeouts", sim["k"], "exp_k"),
                                     ("Pitcher Outs", sim["outs"], "exp_outs"),
                                     ("Pitcher Walks", sim["bb"], "exp_bb")):
                line = DEFAULT_LINES[market]
                side, p = _favored(arr, line)
                signals.append(_signal(pm.name, team, m["label"], market, side, line, p,
                                       proj[key], Opp=opp, Lineup="SP"))
    return signals
 
 
# ============================================================================
# Arbitrary-line evaluation for live-odds edge calculation
# ============================================================================
# The default-line board above answers "what does the model think?" To compute
# EDGE we must evaluate the model at the BOOK'S line, whatever it is. These build a
# compact discrete distribution per player+market so any half-line can be scored.
 
def normalize_name(name: str) -> str:
    """Lowercase, strip accents/punctuation/suffixes so model names match book names."""
    s = unicodedata.normalize("NFD", str(name))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()
 
 
def _dist(samples: np.ndarray) -> np.ndarray:
    """Normalized histogram: index i -> P(outcome == i)."""
    counts = np.bincount(samples.astype(np.int64)).astype(np.float64)
    total = counts.sum()
    return counts / total if total > 0 else counts
 
 
def prob_over(dist: np.ndarray, line: float) -> float:
    """P(X > line) for a half-line (e.g. 1.5 -> P(X >= 2))."""
    thresh = math.floor(line) + 1
    return float(dist[thresh:].sum()) if thresh < len(dist) else 0.0
 
 
def prob_for_side(dist: np.ndarray, line: float, side: str) -> float:
    over = prob_over(dist, line)
    return over if side.lower().startswith("o") else 1.0 - over
 
 
def build_projection_index(rows: List[Dict], meta: List[Dict],
                           sims: int = DEFAULT_SIMS, seed: Optional[int] = None,
                           statcast: Optional[Dict] = None, statcast_k: Optional[float] = None) -> Dict:
    """Return {(normalized_name, odds_market_key): {dist, mean, ctx}} for the slate.
 
    odds_market_key uses The Odds API names (batter_hits, pitcher_strikeouts, ...) so
    the odds matcher can join directly."""
    rng = np.random.default_rng(seed)
    index: Dict = {}
    label_to_time = {m["label"]: m.get("game_date") for m in meta}   # game start (ISO UTC) per game
 
    for r in rows:
        stat = r.get("_stat")
        if not stat:
            continue
        park = PARK_FACTORS.get(r.get("_venue_id"), NEUTRAL_PARK)
        opp_allowed = pitcher_allowed_rates(r.get("_opp_stat"))
        xhr = xhr_from_statcast(r.get("_pid"), statcast, statcast_k)
        probs = batter_pa_probs(stat, park, opp_allowed, r.get("_split_stat"), xhr, r.get("_weather_hr", 1.0))
        if probs is None:
            continue
        sim = simulate_batter(probs, r.get("_exp_pa", DEFAULT_UNKNOWN_PA), sims, rng)
        nm = normalize_name(r["Hitter"])
        ctx = {"player": r["Hitter"], "team": r["Team"], "game": r["GameLabel"],
               "opp": r.get("Opp Pitcher"), "lineup": r.get("Lineup"),
               "game_date": label_to_time.get(r["GameLabel"])}
        for key, arr in (("batter_home_runs", sim["hr"]), ("batter_total_bases", sim["tb"]),
                         ("batter_hits", sim["hits"]), ("batter_strikeouts", sim["k"])):
            index[(nm, key)] = {"dist": _dist(arr), "mean": float(arr.mean()), "ctx": ctx}
 
    lineup_map = build_lineup_rate_map(rows)
    for m in meta:
        for pm, team, opp in ((m["home_pm"], m["home_name"], m["away_name"]),
                              (m["away_pm"], m["away_name"], m["home_name"])):
            if pm.id is None or not pm.stat:
                continue
            proj = project_pitcher(pm.stat, lineup_map.get((m["label"], opp)))
            if not proj:
                continue
            sim = simulate_pitcher(proj, sims, rng)
            nm = normalize_name(pm.name)
            ctx = {"player": pm.name, "team": team, "game": m["label"], "opp": opp,
                   "lineup": "SP", "game_date": m.get("game_date")}
            for key, arr, mean in (("pitcher_strikeouts", sim["k"], proj["exp_k"]),
                                   ("pitcher_outs", sim["outs"], proj["exp_outs"]),
                                   ("pitcher_walks", sim["bb"], proj["exp_bb"])):
                index[(nm, key)] = {"dist": _dist(arr), "mean": float(mean), "ctx": ctx}
    return index
 
 
# Display name + default line per Odds API market, for the model-only board.
_MARKET_DISPLAY = {
    "batter_home_runs": ("Batter HR", 0.5),
    "batter_total_bases": ("Batter Total Bases", 1.5),
    "batter_hits": ("Batter Total Hits", 0.5),
    "batter_strikeouts": ("Batter Strikeouts", 0.5),
    "pitcher_strikeouts": ("Pitcher Strikeouts", 5.5),
    "pitcher_outs": ("Pitcher Outs", 17.5),
    "pitcher_walks": ("Pitcher Walks", 1.5),
}
 
 
def format_et(iso_utc: Optional[str]) -> str:
    """ISO UTC start (e.g. '2026-06-28T17:10:00Z') -> ET clock string like '1:10 PM'.
    Returns '' if the timestamp is missing or unparseable."""
    if not iso_utc:
        return ""
    try:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        s = str(iso_utc).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        et = dt.astimezone(ZoneInfo("America/New_York"))
        return et.strftime("%I:%M %p").lstrip("0")   # '01:10 PM' -> '1:10 PM' (portable)
    except Exception:
        return ""
 
 
def default_board_from_index(index: Dict) -> List[Dict]:
    """Build the model-only board (favored side at default lines) from the index,
    so we run the Monte Carlo just once and reuse it for both views."""
    out: List[Dict] = []
    for (nm, mkey), entry in index.items():
        disp, line = _MARKET_DISPLAY.get(mkey, (mkey, 0.5))
        dist, ctx = entry["dist"], entry["ctx"]
        over = prob_over(dist, line)
        if mkey == "batter_home_runs":
            side, prob = "Yes", over
        else:
            side, prob = ("Over", over) if over >= 0.5 else ("Under", 1 - over)
        out.append(_signal(ctx["player"], ctx["team"], ctx["game"], disp, side,
                           None if mkey == "batter_home_runs" else line, prob, entry["mean"],
                           Opp=ctx.get("opp"), Lineup=ctx.get("lineup"),
                           GameTime=ctx.get("game_date")))
    return out
 
 
def xhr_from_statcast(pid, statcast: Optional[Dict], k: Optional[float]) -> Optional[float]:
    """Contact-implied HR/PA for a player id, or None if unavailable."""
    if not statcast or k is None or pid is None:
        return None
    row = statcast.get(pid)
    if row is None:
        try:
            row = statcast.get(int(pid))
        except (TypeError, ValueError):
            row = None
    if not row:
        return None
    brl = row.get("brl_pa")
    return max(k * brl, 0.0) if brl is not None else None
 
 
def build_bullpen_matchup_rows(rows: List[Dict], opp_team_name: str, bullpen_stat: Dict,
                               sims: int = DEFAULT_SIMS, seed: Optional[int] = None,
                               statcast: Optional[Dict] = None,
                               statcast_k: Optional[float] = None) -> List[Dict]:
    """Recompute HR%/Hit%/TB1.5%/SO Prob for the hitters on opp_team_name — the team that WOULD
    face this bullpen — using bullpen_stat (an aggregate bullpen stat dict from mlb_engine.
    get_bullpen_aggregate_stat) as the opposing-pitcher input, instead of each hitter's own
    stored "_opp_stat" (that night's confirmed starter). Powers Dinger Engine's "flip to the
    bullpen read" toggle.

    NOT NEW MODELING — a thin wrapper around enrich_hitter_rows, the exact same function that
    already computes the "vs starter" read. The only change is which opposing-pitcher stat dict
    feeds pitcher_allowed_rates() inside it; every other input (park, platoon split, Statcast,
    weather, expected PA) stays identical to the hitter's own already-loaded row.

    WORKS ON COPIES, NEVER MUTATES THE ORIGINAL SLATE ROWS: those still need to reflect the
    vs-starter read for the rest of the page (leaderboards, season-long context, other games'
    tables) regardless of whether this one game's toggle happens to be on. enrich_hitter_rows
    mutates in place, so copying first is what keeps this toggle's effect scoped to just the
    table that asked for it."""
    target_rows = [dict(r) for r in rows if r.get("Team") == opp_team_name]
    for r in target_rows:
        r["_opp_stat"] = bullpen_stat
    return enrich_hitter_rows(target_rows, sims=sims, seed=seed, statcast=statcast, statcast_k=statcast_k)


def enrich_hitter_rows(rows: List[Dict], sims: int = DEFAULT_SIMS, seed: Optional[int] = None,
                       statcast: Optional[Dict] = None, statcast_k: Optional[float] = None) -> List[Dict]:
    """Attach matchup-aware model probabilities to each hitter row in place:
    HR%, Hit% (>=1), TB1.5% (>1.5 total bases), SO Prob (>=1 strikeout).
 
    When a Statcast lookup is supplied, HR regresses toward the barrel-implied rate and
    extra columns are added: Barrel%, xHR/PA, and Due (xHR minus actual HR rate = positive-
    regression dinger signal)."""
    rng = np.random.default_rng(seed)
    for r in rows:
        stat = r.get("_stat")
        if not stat:
            continue
        park = PARK_FACTORS.get(r.get("_venue_id"), NEUTRAL_PARK)
        opp_allowed = pitcher_allowed_rates(r.get("_opp_stat"))
        xhr = xhr_from_statcast(r.get("_pid"), statcast, statcast_k)
        probs = batter_pa_probs(stat, park, opp_allowed, r.get("_split_stat"), xhr, r.get("_weather_hr", 1.0))
        if probs is None:
            continue
        sim = simulate_batter(probs, r.get("_exp_pa", DEFAULT_UNKNOWN_PA), sims, rng)
        r["HR%"] = float(np.mean(sim["hr"] >= 1))
        r["Hit%"] = float(np.mean(sim["hits"] >= 1))
        r["TB1.5%"] = float(np.mean(sim["tb"] > 1.5))
        r["SO Prob"] = float(np.mean(sim["k"] >= 1))
        if xhr is not None:
            sc = statcast.get(r.get("_pid")) or {}
            actual_hr_pa = _f(stat, "homeRuns") / max(_f(stat, "plateAppearances"), 1)
            r["Barrel%"] = sc.get("brl_pct", 0.0)
            r["xHR/PA"] = xhr
            r["Due"] = xhr - actual_hr_pa   # positive = hitting better than HR results show
    return rows


def add_starter_exposure_context(rows: List[Dict]) -> List[Dict]:
    """Attach "vs SP" / "vs Pen" plate-appearance breakdown to each hitter row in place — the
    connective tissue tying times_through_order (a starter-side number) to the hitter side, and
    to Dinger Engine's own bullpen-matchup toggle, so the three pieces read as one coherent
    picture rather than three disconnected features:
      * times_through_order (Pitching Lab) says how many times THIS START overall is expected to
        cycle through the lineup.
      * This function says, for a SPECIFIC hitter at a SPECIFIC lineup spot, how many of THEIR
        OWN plate appearances actually fall against that starter vs. against the bullpen once his
        projected work is exhausted — reusing hitter_starter_exposures, which needs nothing this
        row doesn't already carry (_lineup_idx, _exp_pa, _opp_stat).
      * "vs Pen" PA are exactly the PA the bullpen-matchup toggle's own numbers apply to — a
        hitter with real "vs Pen" exposure genuinely has some of their night riding on the
        bullpen read, not just a hypothetical "what if" toggle.

    project_pitcher(opp_stat) is called ONCE PER UNIQUE OPPONENT STAT DICT (cached within this
    call, not per hitter row) — every hitter facing the same starter shares the same projection,
    so this doesn't redundantly recompute it 9 times per lineup. Pure, no network calls of its
    own — opp_stat is already sitting on every row from build_slate.

    Rows missing usable data (no _opp_stat, or project_pitcher can't project a real starter from
    it — a thin sample or genuine reliever) are left without vs SP/vs Pen fields, not given a
    fabricated split."""
    proj_cache: Dict[int, Optional[Dict]] = {}
    for r in rows:
        opp_stat = r.get("_opp_stat")
        exp_pa = r.get("_exp_pa")
        lineup_idx = r.get("_lineup_idx")
        if not opp_stat or exp_pa is None or lineup_idx is None:
            continue
        cache_key = id(opp_stat)
        if cache_key not in proj_cache:
            proj_cache[cache_key] = project_pitcher(opp_stat)
        starter_proj = proj_cache[cache_key]
        if not starter_proj:
            continue
        exposures = hitter_starter_exposures(lineup_idx, starter_proj["exp_bf"], exp_pa)
        r["vs SP"] = exposures["vs_starter"]
        r["vs Pen"] = exposures["vs_bullpen"]
    return rows
 
 
def blend_hitter_probs_with_bullpen(row: Dict, bullpen_stat: Dict, sims: int = DEFAULT_SIMS,
                                    seed: Optional[int] = None, statcast: Optional[Dict] = None,
                                    statcast_k: Optional[float] = None) -> Optional[Dict]:
    """Recompute a hitter's HR%/Hit%/TB1.5%/SO Prob as a BLEND of two real phases of his night —
    his own actual vs-starter and vs-bullpen plate-appearance exposure (hitter_starter_exposures),
    each simulated against its OWN real opposing pitching quality (the starter's own stat line
    for the vs-SP phase, bullpen_stat for the vs-Pen phase) — instead of the platform's own
    long-standing default of applying the starter's rate to ALL of a hitter's projected PA, which
    silently overstates (or understates) his real probability whenever the starter is projected
    for a short outing.

    WHY THIS EXISTS, CONFIRMED WITH REAL NUMBERS FROM A REAL SLATE, NOT A HYPOTHETICAL: checked
    directly by Shawn against Dinger Engine's own bullpen-toggle output — a hitter whose
    starter-only HR% showed 47% (driven by a starter with a 7.64 season ERA, a legitimately
    disastrous line) dropped to a properly-blended ~41% once his real ~1/3 exposure to a
    materially better bullpen was accounted for — a 6-point, ~15% relative overstatement on what
    was the single highest-conviction play on the whole slate that night. This function is that
    exact correction, generalized.

    METHOD: runs simulate_batter TWICE with the SAME rng — once for his vs-starter PA using the
    starter's own opp_allowed rates, once for his vs-bullpen PA using bullpen_stat's rates — then
    SUMS each simulated trial's outcomes across both phases before computing HR%/Hit%/TB1.5%/SO
    Prob. This is the statistically correct way to combine two phases with different PA counts
    and different matchup quality — NOT a linear blend of the two probabilities themselves, which
    would be a real approximation error for a ">=1 occurrence" outcome like HR% (the math isn't
    linear: P(at least one HR across two phases) != a weighted average of each phase's own P(>=1
    HR)).

    Returns None (not a fabricated blend) if: the row can't be projected at all (missing _stat/
    _venue_id/_opp_stat/etc — same gate enrich_hitter_rows itself uses), the starter can't be
    projected (project_pitcher's own gate), there's no real bullpen exposure to blend in the
    first place (vs_pen <= 0 — the starter-only read is ALREADY correct for that hitter, nothing
    to correct), or bullpen_stat itself is too thin a sample to trust (pitcher_allowed_rates'
    own >=40 batters-faced floor — checked EXPLICITLY here, not left to batter_pa_probs' own
    silent "no adjustment" fallback for a None opp_allowed, which would otherwise produce a
    blend that quietly dropped the bullpen adjustment entirely rather than honestly refusing).
    Callers should keep the existing enrich_hitter_rows output when this returns None, not treat
    a None as an error."""
    stat = row.get("_stat")
    lineup_idx = row.get("_lineup_idx")
    exp_pa = row.get("_exp_pa")
    if not stat or lineup_idx is None or exp_pa is None:
        return None
    starter_proj = project_pitcher(row.get("_opp_stat"))
    if not starter_proj:
        return None
    exposures = hitter_starter_exposures(lineup_idx, starter_proj["exp_bf"], exp_pa)
    vs_sp_pa, vs_pen_pa = exposures["vs_starter"], exposures["vs_bullpen"]
    if vs_pen_pa <= 0:
        return None   # no real bullpen exposure projected — the starter-only read is already correct

    park = PARK_FACTORS.get(row.get("_venue_id"), NEUTRAL_PARK)
    xhr = xhr_from_statcast(row.get("_pid"), statcast, statcast_k)
    weather_hr = row.get("_weather_hr", 1.0)
    split_stat = row.get("_split_stat")

    opp_sp_rates = pitcher_allowed_rates(row.get("_opp_stat"))
    opp_pen_rates = pitcher_allowed_rates(bullpen_stat)
    if opp_sp_rates is None or opp_pen_rates is None:
        # batter_pa_probs itself accepts opp_allowed=None gracefully (a silent, neutral,
        # unadjusted fallback) — checking ITS output for None would never actually catch a
        # too-thin sample here, since it would still happily return A probability, just one that
        # silently dropped the bullpen adjustment entirely. That's exactly the wrong failure mode
        # for a function whose whole purpose is providing a real bullpen-aware read — an explicit
        # check here, not a downstream one, is what actually prevents a silently-neutral "blend."
        return None
    probs_sp = batter_pa_probs(stat, park, opp_sp_rates, split_stat, xhr, weather_hr)
    probs_pen = batter_pa_probs(stat, park, opp_pen_rates, split_stat, xhr, weather_hr)
    if probs_sp is None or probs_pen is None:
        return None

    rng = np.random.default_rng(seed)
    sim_sp = simulate_batter(probs_sp, vs_sp_pa, sims, rng)
    sim_pen = simulate_batter(probs_pen, vs_pen_pa, sims, rng)
    combined_hr = sim_sp["hr"] + sim_pen["hr"]
    combined_hits = sim_sp["hits"] + sim_pen["hits"]
    combined_tb = sim_sp["tb"] + sim_pen["tb"]
    combined_k = sim_sp["k"] + sim_pen["k"]

    return {
        "HR%": float(np.mean(combined_hr >= 1)),
        "Hit%": float(np.mean(combined_hits >= 1)),
        "TB1.5%": float(np.mean(combined_tb > 1.5)),
        "SO Prob": float(np.mean(combined_k >= 1)),
        "vs SP": round(vs_sp_pa, 2), "vs Pen": round(vs_pen_pa, 2),
    }


def build_pitcher_projection_rows(rows: List[Dict], meta: List[Dict],
                                  sims: int = DEFAULT_SIMS, seed: Optional[int] = None) -> List[Dict]:
    """Matchup-aware starter projections for the Pitching Lab: expected IP/K/BB/outs plus
    the strikeout-over probability and fair odds at the default line."""
    rng = np.random.default_rng(seed)
    lineup_map = build_lineup_rate_map(rows)
    out: List[Dict] = []
    for m in meta:
        for pm, team, opp, team_id in ((m["home_pm"], m["home_name"], m["away_name"], m.get("home_id")),
                                       (m["away_pm"], m["away_name"], m["home_name"], m.get("away_id"))):
            if pm.id is None or not pm.stat:
                continue
            opp_rates = lineup_map.get((m["label"], opp))
            proj = project_pitcher(pm.stat, opp_rates)
            if not proj:
                continue
            sim = simulate_pitcher(proj, sims, rng)
            k_line = DEFAULT_LINES["Pitcher Strikeouts"]
            k_over = float(np.mean(sim["k"] > k_line))
            outs_over = float(np.mean(sim["outs"] > DEFAULT_LINES["Pitcher Outs"]))
            bb_over = float(np.mean(sim["bb"] > DEFAULT_LINES["Pitcher Walks"]))
            out.append({
                "Pitcher": pm.name, "Team": team, "Opp": opp, "Hand": pm.hand,
                "ERA": round(pm.era, 2), "FIP": pm.fip,
                "Proj IP": round(proj["exp_ip"], 1), "Proj K": round(proj["exp_k"], 1),
                "Proj BB": round(proj["exp_bb"], 1), "Proj Outs": round(proj["exp_outs"], 1),
                "Proj BF": round(proj["exp_bf"], 1), "Proj TTO": round(times_through_order(proj["exp_bf"]), 2),
                "K line": k_line, "K over%": round(k_over, 4), "K fair": prob_to_american(k_over),
                "Outs over%": round(outs_over, 4), "BB over%": round(bb_over, 4),
                "_opp_k": (opp_rates or {}).get("k"), "_opp_bb": (opp_rates or {}).get("bb"),
                "_game": m["label"], "_pid": pm.id, "_game_date": m.get("game_date"),
                "_team_id": team_id,
            })
    out.sort(key=lambda r: r["Proj K"], reverse=True)
    return out
 
 
# ===========================================================================
# BEST BETS — cross-market synthesis with transparent reasoning
# ===========================================================================
# Typical single-game over-probability at the default line for each market. "Conviction"
# is the model's probability for the favored side divided by this reference, so a play
# scores high only when the model diverges from a typical prop of that type. This is a
# CONVICTION measure, not expected value — true value needs the live price (Edge Board).
BEST_BET_REF = {
    "Batter HR": 0.11, "Batter Total Bases": 0.42, "Batter Total Hits": 0.65,
    "Batter Strikeouts": 0.62, "Pitcher Strikeouts": 0.50, "Pitcher Outs": 0.50,
    "Pitcher Walks": 0.45,
}
 
 
def _favored_side(prob_over: float, ref: float):
    """Return (side, prob_of_that_side, ref_for_that_side)."""
    if prob_over >= ref:
        return "Over", prob_over, ref
    return "Under", 1.0 - prob_over, 1.0 - ref
 
 
def _hitter_reasons(r: Dict, market: str, side: str) -> List[str]:
    why = []
    offense = market in ("Batter HR", "Batter Total Bases", "Batter Total Hits")
    if side == "Over" and offense and r.get("Advantage") == "Advantage":
        why.append(f"platoon edge ({r.get('Hand')} bat vs {r.get('Opp Hand')}HP)")
    if market in ("Batter HR", "Batter Total Bases") and (r.get("_weather_hr") or 1.0) >= 1.05:
        why.append(f"weather aiding power (+{(r['_weather_hr'] - 1) * 100:.0f}%)")
    if market == "Batter HR" and (r.get("Due") or 0) > 0.01:
        why.append("barrels imply more power than the HR count shows")
    if market == "Batter Strikeouts":
        why.append("elevated whiff risk in this matchup" if side == "Over"
                   else "strong contact profile (rarely strikes out)")
    if not why:
        why.append(f"model leans {side} of a typical line here")
    return why
 
 
def _pitcher_reasons(r: Dict, market: str, side: str) -> List[str]:
    why, opp_k, opp_bb = [], r.get("_opp_k"), r.get("_opp_bb")
    if market == "Pitcher Strikeouts":
        if side == "Over":
            if opp_k and opp_k > 0.23:
                why.append(f"{r['Opp']} whiff-prone ({opp_k * 100:.0f}% K rate)")
            why.append(f"projects {r.get('Proj K')} K")
        else:
            if opp_k and opp_k < 0.20:
                why.append(f"{r['Opp']} tough to strike out ({opp_k * 100:.0f}% K rate)")
            why.append(f"projects only {r.get('Proj K')} K")
    elif market == "Pitcher Walks":
        if side == "Over" and opp_bb and opp_bb > 0.09:
            why.append(f"{r['Opp']} patient lineup ({opp_bb * 100:.0f}% walk rate)")
        why.append(f"projects {r.get('Proj BB')} BB")
    elif market == "Pitcher Outs":
        why.append(f"projects {r.get('Proj IP')} IP ({r.get('Proj Outs')} outs)")
    if not why:
        why.append(f"model leans {side} of a typical line here")
    return why
 
 
def _hitter_diag(r: Dict) -> Dict:
    """Model inputs behind a hitter play, for the Bet Diagnostics inspector — so you can see
    exactly what drove the number (and catch a hallucination)."""
    park = PARK_FACTORS.get(r.get("_venue_id"), NEUTRAL_PARK)
    adv = r.get("Advantage")
    platoon = (f"{r.get('Hand', '?')} vs {r.get('Opp Hand', '?')}HP ({adv})"
               if adv else "no split edge")
    diag = {
        "PA": round(float(r.get("_exp_pa", DEFAULT_UNKNOWN_PA)), 2),
        "ParkHR": round(float(park.get("hr", 1.0)), 2),
        "WxHR": round(float(r.get("_weather_hr", 1.0)), 2),
        "Platoon": platoon,
        "Barrel%": r.get("Barrel%"),      # from Statcast enrichment (None if Statcast off)
        "xHR/PA": r.get("xHR/PA"),
        "OppHR9": r.get("Opp HR/9"),      # opposing starter's HR/9 allowed
    }
    # Weather decomposition — split the HR factor into temperature vs wind so the inspector can
    # say "the +8% is heat, not the crosswind." Present only when the page stored the breakdown
    # pieces on the row (temperature is robust; wind depends on the out-to-CF component).
    if r.get("_wx_temp") is not None or r.get("_wx_outwind") is not None:
        import weather as _W
        bd = _W.hr_factor_breakdown(r.get("_wx_temp"), r.get("_wx_outwind") or 0.0,
                                    r.get("_wx_roof") or "open")
        diag.update({"Temp": r.get("_wx_temp"), "WxDesc": r.get("_wx_desc"),
                     "WxTempPct": bd["temp_pct"], "WxWindPct": bd["wind_pct"],
                     "WxDriver": bd["driver"]})
    return diag
 
 
def _pitcher_diag(r: Dict) -> Dict:
    """Model inputs behind a pitcher play. Park/weather don't act on K/BB/outs in this model,
    so they're neutral (1.0); the real drivers are the projection and the opposing lineup."""
    return {
        "PA": r.get("Proj BF"),           # batters faced (the pitcher-side 'PA')
        "ParkHR": 1.0, "WxHR": 1.0,       # not applicable to pitcher props
        "ProjK": r.get("Proj K"), "ProjBB": r.get("Proj BB"),
        "ProjIP": r.get("Proj IP"), "ProjOuts": r.get("Proj Outs"),
        "OppK": r.get("_opp_k"), "OppBB": r.get("_opp_bb"),   # opposing lineup K/BB rates
    }
 
 
def build_best_bets(hitter_rows: List[Dict], pitcher_rows: List[Dict]) -> List[Dict]:
    """Rank model candidate plays across all markets by conviction (model prob vs the
    market-typical prob for that prop), each with transparent reasoning. No odds required.
 
    These are the model's strongest LEANS, not guaranteed value — check the live price on
    the Edge Board and let the proof layer (CLV/calibration) be the judge."""
    plays: List[Dict] = []
 
    batter_specs = [("Batter HR", "HR%", 0.5), ("Batter Total Bases", "TB1.5%", 1.5),
                    ("Batter Total Hits", "Hit%", 0.5), ("Batter Strikeouts", "SO Prob", 0.5)]
    for r in hitter_rows:
        for market, col, line in batter_specs:
            p = r.get(col)
            if p is None:
                continue
            side, sp, ref_s = _favored_side(p, BEST_BET_REF[market])
            if market == "Batter HR" and side == "Under":
                continue  # "won't homer" isn't a real play
            plays.append({
                "Player": r["Hitter"], "PlayerId": r.get("_pid"), "Team": r["Team"], "Game": r["GameLabel"],
                "Opp": r.get("Opp Pitcher"),
                "Versus": r.get("Opp Pitcher"),
                "Market": market, "Side": side, "Line": line,
                "ModelProb": round(sp, 4), "Fair": prob_to_american(sp),
                "Conviction": round(sp / ref_s, 2) if ref_s > 0 else 0.0,
                "Why": "; ".join(_hitter_reasons(r, market, side)),
                "Lineup": r.get("Lineup"),   # "Confirmed" / "Projected" -- real lineup-confidence
                                             # status, not previously exposed on a play
                **_hitter_diag(r),
            })
 
    pitcher_specs = [("Pitcher Strikeouts", "K over%", DEFAULT_LINES["Pitcher Strikeouts"]),
                     ("Pitcher Outs", "Outs over%", DEFAULT_LINES["Pitcher Outs"]),
                     ("Pitcher Walks", "BB over%", DEFAULT_LINES["Pitcher Walks"])]
    for r in pitcher_rows:
        for market, col, line in pitcher_specs:
            p = r.get(col)
            if p is None:
                continue
            side, sp, ref_s = _favored_side(p, BEST_BET_REF[market])
            plays.append({
                "Player": r["Pitcher"], "PlayerId": r.get("_pid"), "Team": r["Team"], "Game": r.get("_game", ""),
                "Opp": r.get("Opp"),
                "Versus": r.get("Opp"),
                "Market": market, "Side": side, "Line": line,
                "ModelProb": round(sp, 4), "Fair": prob_to_american(sp),
                "Conviction": round(sp / ref_s, 2) if ref_s > 0 else 0.0,
                "Why": "; ".join(_pitcher_reasons(r, market, side)),
                **_pitcher_diag(r),
            })
 
    plays.sort(key=lambda x: x["Conviction"], reverse=True)
    return plays
 
 
BULLPEN_BLEND_MARKET_COLS = {
    "Batter HR": "HR%", "Batter Total Bases": "TB1.5%",
    "Batter Total Hits": "Hit%", "Batter Strikeouts": "SO Prob",
}


def apply_bullpen_blend_to_top_plays(plays: List[Dict], rows_by_pid: Dict[Any, Dict],
                                     get_bullpen_stat_fn, statcast: Optional[Dict] = None,
                                     statcast_k: Optional[float] = None, seed: Optional[int] = None,
                                     top_n: int = 30) -> List[Dict]:
    """Re-price the top N hitter-market plays using their real vs-starter/vs-bullpen exposure,
    instead of leaving Best Bets' whole board priced off the starter's rate for every projected
    PA — the fix for a real, confirmed issue: a starter-only read on a real slate showed 47% for
    a market's single highest-conviction play, when properly blending the ~1/3 of that hitter's
    plate appearances that actually fall to a materially better bullpen brought it to ~41%, a
    6-point overstatement on the top play of the night.

    SCOPED TO THE TOP N CANDIDATES, NOT THE WHOLE SLATE — a real, deliberate cost decision, not
    a shortcut: blending every hitter-market play on a full slate would mean fetching a bullpen
    aggregate (itself several real calls) for every opposing team on the board, potentially 250+
    calls just to load the page. Only the plays that could plausibly rank at the top are worth
    that cost — re-pricing a play sitting at the bottom of a 1,274-play list can't change
    anything about what actually gets surfaced as a top lean.

    DOES NOT RE-DERIVE WHICH SIDE A PLAY IS ON — a real, deliberate design choice: the play
    (e.g. "Batter HR Over 0.5") is already fixed by the time this runs. This recomputes how
    confident the model is in that SAME side, using the blended probability, rather than letting
    a large swing flip a play to the opposite side of its own posted line, which would be a
    different, more disruptive kind of change than "how sure are we," not what this function is
    for.

    get_bullpen_stat_fn(team_id, exclude_pid) -> Optional[Dict] is DEPENDENCY-INJECTED, not
    called directly from here — keeps this function itself network-free and testable with a
    plain fake, the same "pure, testable, network calls injected by the caller" discipline this
    file already follows elsewhere. exclude_pid is the OPPOSING STARTER's own player id (from the
    row's own "_opp_pid"), passed through so the real implementation can exclude him from the
    bullpen aggregate — without it, his own stats would be double-counted, once directly for the
    vs-SP phase and again folded into the vs-Pen aggregate alongside every other pitcher on the
    roster. The real caller (Best Bets' own view) passes a Streamlit-cached wrapper around
    mlb_engine.get_bullpen_aggregate_stat, so repeated calls for the same opponent across
    multiple candidate hitters are free, not refetched per hitter.

    Plays that can't be blended (no matching row, no opponent id, bullpen data unavailable, or
    blend_hitter_probs_with_bullpen's own None cases — including "no real bullpen exposure to
    blend," the common, expected case for most plays) are left exactly as build_best_bets
    produced them — never silently dropped, never given a fabricated adjustment. Blended plays
    get a "_bullpen_blended": True marker and their pre-blend conviction preserved under
    "_pre_blend_conviction", so the UI can show what changed, not just the new number alone —
    the same "show what actually drove it" transparency this platform's Bet Diagnostics inspector
    already promises for the rest of the board.

    Returns the SAME plays list, mutated in place and re-sorted by the (possibly updated)
    Conviction — blending a top play can change its rank relative to plays that weren't blended."""
    candidates = sorted([p for p in plays if p.get("Market") in BULLPEN_BLEND_MARKET_COLS],
                        key=lambda x: x.get("Conviction") or 0, reverse=True)[:top_n]

    for play in candidates:
        pid = play.get("PlayerId")
        row = rows_by_pid.get(pid)
        if not row:
            continue
        opp_id = row.get("_opp_id")
        if not opp_id:
            continue
        bullpen_stat = get_bullpen_stat_fn(opp_id, row.get("_opp_pid"))
        if not bullpen_stat:
            continue
        blended = blend_hitter_probs_with_bullpen(row, bullpen_stat, seed=seed,
                                                   statcast=statcast, statcast_k=statcast_k)
        if not blended:
            continue

        market = play["Market"]
        col = BULLPEN_BLEND_MARKET_COLS[market]
        blended_prob_over = blended[col]
        side = play["Side"]
        ref = BEST_BET_REF[market]
        # Recompute confidence in the SAME side already chosen, not a fresh favored-side pick.
        new_side_prob = blended_prob_over if side == "Over" else (1.0 - blended_prob_over)
        ref_for_side = ref if side == "Over" else (1.0 - ref)

        play["_pre_blend_conviction"] = play.get("Conviction")
        play["_pre_blend_model_prob"] = play.get("ModelProb")
        play["ModelProb"] = round(new_side_prob, 4)
        play["Fair"] = prob_to_american(new_side_prob)
        play["Conviction"] = round(new_side_prob / ref_for_side, 2) if ref_for_side > 0 else 0.0
        play["Why"] = (play.get("Why", "") +
                       f"; bullpen-blended ({blended['vs SP']:.1f} PA vs starter, "
                       f"{blended['vs Pen']:.1f} vs pen)")
        play["_bullpen_blended"] = True

    plays.sort(key=lambda x: x.get("Conviction") or 0, reverse=True)
    return plays


# Conviction -> letter grade + tier label. Thresholds are this platform's OWN, grounded in its
# own already-established Conviction scale (Best Bets' own min-conviction slider already treats
# 1.2x as the floor worth showing at all, and real top plays observed on this platform's own
# slates cluster in the 2.7-4.25x range), not reverse-engineered from any other product's scoring.
# Labels are this platform's own wording, not copied badge text -- see the real reason this
# matters in GRADE_THRESHOLDS' own docstring-equivalent note below.
GRADE_THRESHOLDS = [
    (3.0, "A", "Top Lean"),
    (2.0, "B", "Strong Lean"),
    (1.5, "C", "Lean"),
    (1.2, "D", "Watch"),
]


def conviction_to_grade(conviction: Optional[float]) -> Optional[Dict[str, Any]]:
    """Map a play's Conviction number to a letter grade + tier label for quick visual scanning --
    NOT a fabricated 0-100 "score" that doesn't map to anything real. The raw Conviction number
    (e.g. "3.2x") is a genuinely interpretable value on its own -- "this hitter's real probability
    is 3.2x the market-typical rate for this prop" -- so the grade is presented ALONGSIDE it, not
    instead of it, honest about what's actually driving the label rather than hiding it behind an
    opaque score.

    A REAL, DELIBERATE NAMING CHOICE: labels here ("Top Lean" / "Strong Lean" / "Lean" / "Watch")
    are this platform's own wording, chosen specifically to describe the SAME underlying concept
    (a tiered conviction label) without reusing another product's specific badge text -- avoiding
    exactly the "duplicating someone else's badges" concern raised directly during scoping, not
    just applied to the genuinely unclear proprietary terms ("Blast Match" etc, deliberately left
    out entirely) but to the clearer ones too.

    Returns None for anything below the lowest real threshold (1.2x, matching Best Bets' own
    established "worth showing at all" floor) -- a play that isn't notable shouldn't get a grade
    that implies it is."""
    if conviction is None:
        return None
    for threshold, letter, tier in GRADE_THRESHOLDS:
        if conviction >= threshold:
            return {"letter": letter, "tier": tier, "conviction": conviction}
    return None


def organize_graded_picks(plays: List[Dict]) -> List[Dict[str, Any]]:
    """Grade every play, drop what doesn't clear the real floor, and organize what's left into a
    game-by-game structure ready to render -- the core, testable logic behind the Graded Picks
    page, deliberately kept separate from any Streamlit rendering code so it can be unit tested
    directly rather than only trusted by eye in the browser.

    WHY GAME-BY-GAME, NOT A FLAT RANKED LIST -- the real reasoning this was built from: a flat
    top-N naturally clusters on whichever 2-3 games happen to have the juiciest matchups that
    night, leaving the rest of the slate invisible to anyone specifically interested in a
    different game. Every game with at least one graded play gets its own section here; nothing
    is silently dropped for not being in a top-N cut.

    SORT ORDER, at both levels: games are ordered by their own single BEST play's Conviction
    (most interesting game first), and players within a game are ordered by their own best play's
    Conviction the same way -- "most interesting first," not alphabetical or arbitrary.

    Returns a list of {"game": str, "players": [{"player": str, "team": str, "plays": [play,...]}
    ]}, already sorted at both levels, with each play carrying its own "_grade" (from
    conviction_to_grade) already attached. A play with no real grade (below the floor) is not
    included anywhere in the output -- this function IS the grading floor, not just a display
    filter applied on top of it elsewhere."""
    graded = []
    for pl in plays:
        grade = conviction_to_grade(pl.get("Conviction"))
        if grade:
            graded.append({**pl, "_grade": grade})
    if not graded:
        return []

    games: Dict[str, List[Dict]] = {}
    for pl in graded:
        games.setdefault(pl["Game"], []).append(pl)

    game_order = sorted(games.keys(), key=lambda g: max(p["Conviction"] for p in games[g]), reverse=True)

    out = []
    for game_label in game_order:
        game_plays = games[game_label]
        by_player: Dict[str, List[Dict]] = {}
        for pl in game_plays:
            by_player.setdefault(pl["Player"], []).append(pl)
        player_order = sorted(by_player.keys(),
                              key=lambda pn: max(p["Conviction"] for p in by_player[pn]),
                              reverse=True)
        players = []
        for player in player_order:
            player_plays = sorted(by_player[player], key=lambda p: p["Conviction"], reverse=True)
            players.append({"player": player, "team": player_plays[0].get("Team", ""),
                           "plays": player_plays})
        out.append({"game": game_label, "players": players})
    return out


def grade_accuracy_by_letter(graded_plays: List[Dict]) -> List[Dict]:
    """Takes ALREADY-GRADED plays (each carrying "Hit": True/False/None and "Conviction" -- e.g.
    retro.grade_slate's own output) and breaks down REAL hit rate by letter grade
    (conviction_to_grade) -- the direct test of whether Graded Picks' own letter grades mean
    anything: does an A actually hit more often than a C, using real settled outcomes, not a
    hypothetical.

    WHY THIS EXISTS, THE ACTUAL QUESTION IT ANSWERS: Graded Picks shows a letter grade on every
    play, but nothing previously checked whether that grade correlates with real results.
    retro.grade_slate already breaks down hit rate by conviction tier using its own separate
    numeric thresholds (>=1.75x, 1.4-1.75x, etc) -- a real, useful metric, but a DIFFERENT one.
    This uses the SAME letter-grade thresholds Graded Picks itself shows, so the answer comes
    back in the exact terms a person actually sees on that page, not a parallel, differently-
    bucketed one that doesn't map onto what's displayed there.

    DELIBERATELY LIVES HERE, NOT IN retro.py: retro.py is shared across every sport on this
    platform (MLB, WNBA, NBA, NFL, NCAAMB all route through it), while conviction_to_grade is
    MLB-specific right now, matching Graded Picks' own "priority is MLB" scope. Adding a direct
    dependency from retro.py on this MLB-only function would break retro.py's own sport-agnostic
    design for every other sport. Callers (Retrospective's own view) are expected to call
    retro.grade_slate first, then pass its own "graded" list here -- and to gate the call itself
    to MLB specifically, the same way every other MLB-only branch on that page already does.

    Only settled plays (Hit is not None) count. A grade with zero settled plays in this window is
    simply absent from the output -- not shown as a fabricated 0% or 100%."""
    settled = [g for g in graded_plays if g.get("Hit") is not None]
    by_letter: Dict[str, List[Dict]] = {}
    for g in settled:
        grade = conviction_to_grade(g.get("Conviction"))
        if grade:
            by_letter.setdefault(grade["letter"], []).append(g)
    out = []
    for threshold, letter, tier in GRADE_THRESHOLDS:
        grp = by_letter.get(letter, [])
        if grp:
            out.append({
                "letter": letter, "tier": tier, "n": len(grp),
                "hit_rate": round(sum(1 for g in grp if g["Hit"]) / len(grp), 3),
            })
    return out


def curate_selections(plays: List[Dict], n: int = 6, per_market_cap: int = 2,
                      rank_key: str = "Conviction") -> List[Dict]:
    """Pick a tight, VARIED set of the most interesting plays for a media segment.
 
    Walks plays in rank order (conviction by default, or 'EV' when live odds are on) but caps
    how many come from any one market, so a segment isn't six home-run leans. Returns up to n."""
    ranked = sorted(plays, key=lambda x: (x.get(rank_key) is not None, x.get(rank_key) or 0),
                    reverse=True)
    chosen, counts = [], {}
    for p in ranked:
        m = p.get("Market")
        if counts.get(m, 0) >= per_market_cap:
            continue
        chosen.append(p)
        counts[m] = counts.get(m, 0) + 1
        if len(chosen) >= n:
            break
    return chosen
