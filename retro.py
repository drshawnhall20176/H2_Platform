"""
retro.py — grade the model's pre-game board against what actually happened.
 
This is a MODEL REVIEW, not an outlier-explainer. It scores the probabilities the model
assigned BEFORE the games against real results — it never hunts for new variables to
explain a specific surprise after the fact (that's overfitting, the thing that quietly
destroys a model). The headline view answers the honest version of "could we have caught
that surprise homer?": of the players who actually homered, where did the model rank them?
 
IMPORTANT CAVEAT (surfaced in the UI): rebuilding a past slate today uses CURRENT-season
rates, not point-in-time rates as of that date, so recent dates have little look-ahead but
older dates have more. For rigorous, point-in-time proof, the Bet Log (which captured the
model's probability at bet time) is the source of truth. This page is for exploration.
"""
 
from __future__ import annotations
 
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

import numpy as np


def trading_dates_ending_yesterday(n_days: int, as_of: Optional[str] = None) -> List[str]:
    """The last n_days real calendar dates, as "YYYY-MM-DD" strings, ending at YESTERDAY
    relative to as_of (defaults to today) -- added directly on request, for a "trend across
    recent nights" dashboard view.

    Ends at yesterday, not today, on purpose: today's slate is still in progress or hasn't been
    played yet at any point someone would realistically be checking this, so including it would
    mean rebuilding a night with an incomplete or entirely absent real result to grade against.

    Returns OLDEST FIRST (chronological order), matching how a trend is naturally read left to
    right. n_days <= 0 returns an empty list, not an error -- a real, honest "nothing to show"
    rather than a crash on a stray zero from a UI number input."""
    if n_days <= 0:
        return []
    anchor = datetime.strptime(as_of, "%Y-%m-%d") if as_of else datetime.now()
    yesterday = anchor - timedelta(days=1)
    return [(yesterday - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n_days - 1, -1, -1)]

 
MARKET_STAT = {
    "Batter HR": "hr", "Batter Total Bases": "tb", "Batter Total Hits": "hits",
    "Batter Strikeouts": "so", "Pitcher Strikeouts": "p_k", "Pitcher Outs": "p_outs",
    "Pitcher Walks": "p_bb", "Pitcher Hits Allowed": "p_h", "Pitcher Earned Runs": "p_er",
    # Hits+Runs+RBIs (H-R-R) -- combined-stat market, graded against mlb_engine.
    # get_player_results()'s own "hrr" field (real hits+runs+rbi from that night's boxscore),
    # the same 1.5-line Over/Under every other market here grades against via grade_play.
    "Batter Hits+Runs+RBIs": "hrr",
    # WNBA/NBA/NCAAMB — all three basketball sports share the same display market names (the
    # Core-4 convention), so one entry per name covers all of them; no separate NBA/NCAAMB rows
    # needed. Keys match wnba_engine.get_player_results()'s (and NBA's/NCAAMB's) result dict exactly.
    "Points": "pts", "Rebounds": "reb", "Assists": "ast", "Threes Made": "fg3m",
    # NFL — display names are entirely different from basketball's, so these DO need their own
    # entries (unlike the three basketball sports above). Keys match nfl_engine.get_player_
    # results()'s result dict exactly — confirmed the pairing explicitly, not just assumed, since
    # this dict is the one place a mismatch would silently grade zero plays rather than crash.
    "Pass Yards": "passing_yards", "Rush Yards": "rushing_yards",
    "Receptions": "receptions", "Receiving Yards": "receiving_yards",
}
 
 
def grade_play(market: str, side: str, line: float, actuals: Optional[Dict]) -> Optional[bool]:
    """Did the play hit? None if the player has no stat for that market (didn't appear)."""
    key = MARKET_STAT.get(market)
    if not actuals or key not in actuals:
        return None
    val = actuals[key]
    over_hit = val > line
    return over_hit if side == "Over" else (val < line)   # .5 lines -> no push


def settle_bet_result(market: str, side: str, line, actuals):
    """Real-world settlement status for ONE logged Bet Log entry -- "win"/"loss"/"push"/"void",
    a richer real vocabulary than grade_play's own True/False/None above.

    NOT a replacement for grade_play -- that function is scoped to the model's OWN generated
    board specifically (always real .5 lines, so an exact-tie push is structurally impossible
    there, and its own None just means "leave this out of the aggregate hit-rate," not a real
    settlement status). A Bet Log entry can carry ANY real line a person actually got from a
    sportsbook, including a genuine whole-number line where an exact tie is a real, if
    comparatively rare, push -- and "the player recorded nothing at all for this stat category
    despite the game being confirmed Final" is a real, distinct VOID case (the standard real
    sportsbook treatment for a late scratch or a DNP prop), not silently the same "insufficient
    data" grade_play's own None already represents for a different purpose.

    CALLER'S OWN RESPONSIBILITY, not this function's: confirming the game is actually Final
    before calling this at all. This function has no game-status awareness by design (same as
    grade_play) -- calling it against a game that's still in progress would read a not-yet-
    accumulated stat as a genuine miss or a scratch, which is simply wrong, not just premature.

    Returns None only when `market` isn't a real market this platform knows how to grade at all,
    or `line` itself is missing -- an honest "can't determine," never a guess."""
    key = MARKET_STAT.get(market)
    if key is None or line is None:
        return None
    if not actuals or key not in actuals:
        return "void"
    val = actuals[key]
    if val == line:
        return "push"
    over_hit = val > line
    hit = over_hit if side == "Over" else (val < line)
    return "win" if hit else "loss"


def settle_moneyline_result(side_team, home_team, away_team, home_score, away_score):
    """Real-world settlement for ONE logged MONEYLINE bet -- compares the bet's own logged team
    name against the real final score. A genuinely separate comparison from settle_bet_result
    above: a moneyline bet has no player and no line at all, just "did this team win," so there's
    no MARKET_STAT lookup or actuals dict involved here, just the schedule's own real score.

    CALLER'S OWN RESPONSIBILITY, same posture as settle_bet_result: confirming the game is
    actually Final before calling this.

    Returns "win"/"loss", or None (an honest "can't determine," never a guess) when: the scores
    themselves aren't real/usable (missing, or a genuine tie -- structurally rare for a completed
    MLB game, which resolves ties via extra innings, but not worth guessing at if it's ever seen
    in real data), or side_team doesn't match EITHER real team name at all (a real data mismatch,
    not something to silently resolve either way)."""
    if home_score is None or away_score is None or home_score == away_score:
        return None
    if side_team not in (home_team, away_team):
        return None
    winner = home_team if home_score > away_score else away_team
    return "win" if side_team == winner else "loss"


def settle_team_total_result(side: str, line: Optional[float], team_runs: Optional[float]):
    """Real-world settlement for ONE logged TEAM TOTAL bet (e.g. "First 5 Innings Total") --
    compares the bet's own logged Over/Under side and line against the real runs that specific
    team actually scored in the window this market covers. A third, genuinely separate
    comparison alongside settle_bet_result (player-stat, MARKET_STAT-keyed) and settle_moneyline_
    result (whole-game win/loss, no line at all) above: this one has a real line like a player
    prop does, but no player and no MARKET_STAT/actuals dict involved -- just one real number
    (team_runs) against the line, the same bare comparison every real sportsbook total settles on.

    CALLER'S OWN RESPONSIBILITY, same posture as settle_bet_result/settle_moneyline_result:
    confirming BOTH that the game is actually Final AND that team_runs reflects a fully completed
    window for this specific market (e.g. all 5 real innings actually played, not a partial count
    from a suspended/shortened game) before calling this -- this function has no game-status or
    innings-completeness awareness by design, same as its two siblings above.

    Returns "win"/"loss"/"push" (an exact-tie push is genuinely possible here, unlike moneyline,
    since a real sportsbook total line can land on a whole number), or None (an honest "can't
    determine," never a guess) when line or team_runs itself is missing."""
    if line is None or team_runs is None:
        return None
    if team_runs == line:
        return "push"
    over_hit = team_runs > line
    hit = over_hit if side == "Over" else (team_runs < line)
    return "win" if hit else "loss"


def _calibration(graded: List[Dict], n_bins: int = 5) -> List[Dict]:
    settled = [g for g in graded if g["Hit"] is not None]
    if not settled:
        return []
    width, out = 1.0 / n_bins, []
    for i in range(n_bins):
        lo, hi = i * width, (i + 1) * width
        grp = [g for g in settled if (lo <= g["ModelProb"] < hi) or (i == n_bins - 1 and g["ModelProb"] == 1.0)]
        if not grp:
            continue
        out.append({"lo": round(lo, 2), "hi": round(hi, 2),
                    "predicted": round(sum(g["ModelProb"] for g in grp) / len(grp), 3),
                    "actual": round(sum(1 for g in grp if g["Hit"]) / len(grp), 3),
                    "n": len(grp)})
    return out


# ---- calibration-based recalibration (the closed feedback loop) ------------
# Confirmed directly with the person building this platform: 100 real graded plays in a market
# before ANY correction is even attempted -- below that, fit_market_calibration returns None and
# apply_calibration_correction is a no-op (raw_prob passed straight through, unchanged).
CALIBRATION_MIN_N = 100

# Same shrinkage-to-prior STRUCTURE as projections._shrink (this module's own sibling concept,
# not a new philosophy invented here) -- at exactly CALIBRATION_MIN_N real plays, the fitted
# correction is applied at HALF its own fitted strength (n / (n + prior) = 100/200 = 0.5), climbing
# toward full strength only as real n grows well past the floor (500 plays -> ~83%, 1000 -> ~91%).
# A hard cliff at the floor (0% correction at 99 plays, 100% at 100) would treat 100 real plays as
# meaningfully different from 99, which they aren't -- this ramps instead, the same real reasoning
# _shrink's own comment gives for why sample-size-weighted blending beats a hard threshold.
CALIBRATION_SHRINK_PRIOR = 100


def fit_market_calibration(graded_plays: List[Dict], min_n: int = CALIBRATION_MIN_N,
                           prior: float = CALIBRATION_SHRINK_PRIOR, n_bins: int = 10) -> Optional[Dict]:
    """Fit a real, SHRUNK linear correction (actual ~ slope * predicted + intercept) from a real
    pile of graded plays -- the actual mechanism behind the closed feedback loop: Retrospective's
    own grading, persisted by grading_history.py, periodically turned into a correction applied
    back onto tomorrow's own ModelProb via apply_calibration_correction below, at the ONE shared
    point (projections.build_best_bets) every page (Top Leans, Graded Picks, Suggested Parlays,
    Speculative Basket) already draws its plays from -- fix it once, here, and every one of those
    inherits the fix automatically, with no separate per-page wiring.

    DELIBERATELY A SIMPLE WEIGHTED LINEAR FIT ON _calibration'S OWN BUCKETS, not a logistic/Platt
    fit -- this platform doesn't depend on scikit-learn (confirmed: it's not in requirements.txt,
    despite appearing in a deploy log as someone else's transitive dependency), and a straight-
    line correction on real bucketed predicted-vs-actual data is exactly as auditable as every
    other piece of math on this platform already is: "our ~40% calls have actually been landing
    around 47%, so nudge accordingly" is a sentence a subscriber can follow. A hidden 2-parameter
    logistic fit would not meaningfully out-perform this at the sample sizes this floor is even
    considering, and would cost real explainability for no real accuracy gain.

    Returns None (an honest "not enough real evidence yet," never a guessed correction) when
    fewer than min_n real settled plays exist, or when fewer than 2 real calibration buckets have
    any data to fit a line through at all. Otherwise returns {"slope", "intercept" (the REAL,
    shrinkage-weighted values to apply), "raw_slope", "raw_intercept" (the un-shrunk fit, kept for
    audit/display so a person can see how much the shrinkage itself pulled the correction back),
    "n" (real settled plays this was fit on), "weight" (the real shrinkage weight applied, 0-1)}."""
    settled = [g for g in graded_plays if g.get("Hit") is not None]
    n = len(settled)
    if n < min_n:
        return None

    buckets = _calibration(settled, n_bins=n_bins)
    if len(buckets) < 2:
        return None   # can't fit a real line through fewer than 2 real points

    xs = np.array([b["predicted"] for b in buckets], dtype=float)
    ys = np.array([b["actual"] for b in buckets], dtype=float)
    ws = np.array([b["n"] for b in buckets], dtype=float)

    # Closed-form WEIGHTED simple linear regression (actual ~ slope*predicted + intercept),
    # written out explicitly rather than via a general matrix solve -- 2 real unknowns, plain
    # enough to read and verify by eye, matching every other formula on this platform.
    sw, swx, swy = ws.sum(), (ws * xs).sum(), (ws * ys).sum()
    swxx, swxy = (ws * xs * xs).sum(), (ws * xs * ys).sum()
    denom = sw * swxx - swx * swx
    if denom == 0:
        return None   # every real bucket sits at the identical predicted value -- no real slope to fit
    raw_slope = (sw * swxy - swx * swy) / denom
    raw_intercept = (swy - raw_slope * swx) / sw

    weight = n / (n + prior)
    slope = 1.0 + weight * (raw_slope - 1.0)
    intercept = 0.0 + weight * (raw_intercept - 0.0)

    return {"slope": round(float(slope), 4), "intercept": round(float(intercept), 4), "n": n,
           "raw_slope": round(float(raw_slope), 4), "raw_intercept": round(float(raw_intercept), 4),
           "weight": round(float(weight), 3)}


def apply_calibration_correction(raw_prob: Optional[float], correction: Optional[Dict]) -> Optional[float]:
    """Apply a fitted correction (fit_market_calibration's own output) to ONE real ModelProb.
    correction=None (no real fit exists yet for this market -- the common case until real volume
    accumulates) is a genuine no-op: raw_prob passed straight through, unchanged, never a guessed
    adjustment. raw_prob=None also passes through unchanged (nothing to correct).

    Clamped to [0.01, 0.99] -- the SAME real floor/ceiling _shrink-derived probabilities are
    already clamped to elsewhere on this platform (a probability of exactly 0 or 1 is never
    honestly knowable), so a correction can nudge a number but can never produce a claimed
    certainty the model itself never actually has."""
    if correction is None or raw_prob is None:
        return raw_prob
    p = correction["slope"] * raw_prob + correction["intercept"]
    return min(max(p, 0.01), 0.99)


 
 
def grade_slate(plays: List[Dict], results: Dict[int, Dict]) -> Tuple[List[Dict], Dict]:
    """Attach Hit/Actual to every play and summarize. Returns (graded_plays, summary)."""
    graded = []
    for p in plays:
        actuals = results.get(p.get("PlayerId")) if p.get("PlayerId") is not None else None
        hit = grade_play(p["Market"], p["Side"], p["Line"], actuals)
        graded.append({**p, "Hit": hit,
                       "Actual": (actuals or {}).get(MARKET_STAT.get(p["Market"]))})
 
    matched = [g for g in graded if g["Hit"] is not None]
    # discrimination: hit rate by conviction tier (should trend up if the model ranks well)
    tiers = []
    for lo, hi, label in [(1.75, 99, "≥1.75×"), (1.4, 1.75, "1.4–1.75×"),
                          (1.2, 1.4, "1.2–1.4×"), (0, 1.2, "<1.2×")]:
        grp = [g for g in matched if lo <= g["Conviction"] < hi]
        if grp:
            tiers.append({"tier": label, "n": len(grp),
                          "hit_rate": round(sum(1 for g in grp if g["Hit"]) / len(grp), 3)})
 
    summary = {
        "total": len(plays), "graded": len(matched),
        "hits": sum(1 for g in matched if g["Hit"]),
        "hit_rate": round(sum(1 for g in matched if g["Hit"]) / len(matched), 3) if matched else None,
        "tiers": tiers,
        "calibration": _calibration(matched),
    }
    return graded, summary
 
 
def player_calibration(graded_plays: List[Dict], min_plays: int = 8) -> List[Dict]:
    """Groups ALREADY-GRADED, settled plays (grade_slate's own output -- each carrying "Hit",
    "ModelProb", "Player", "PlayerId") by PLAYER, and compares each player's own average
    ModelProb against their real, actual hit rate over the same window -- a systematic,
    data-driven answer to a real, recurring pattern: traders keeping an informal "ban list" of
    specific players who seem to keep missing on plays the model favored (Curtis Mead, Vlad Jr.,
    Mookie Betts, and similar real, repeated examples), almost always based on a handful of
    memorable misses, not a real sample. This either confirms a real, systematic gap for a
    specific player, or shows the "ban list" instinct doesn't hold up once more games are
    counted -- useful either way, and a genuine improvement over gut-feel alone.

    POOLED ACROSS EVERY MARKET AND SIDE FOR A GIVEN PLAYER, deliberately, not split out
    per-market -- matching how the "ban list" pattern itself actually works (a person doesn't
    separately track "Curtis Mead misses Hits props" vs "Curtis Mead misses Total Bases props,"
    they just stop trusting Curtis Mead). This is the same pooling _calibration itself already
    does across markets by ModelProb bin, not a new methodology invented for this function --
    each individual play's own (ModelProb - actual outcome) is already a comparable, market-
    agnostic 0-1 scale quantity (a calibration error), so averaging it across a player's mixed
    markets is sound, not apples-to-oranges, the same way _calibration's own cross-market
    pooling already is.

    min_plays: the real, stated floor against exactly the small-sample problem the "ban list"
    pattern itself is prone to -- a player with only 2-3 settled plays in the window is EXCLUDED
    entirely, not shown with a misleadingly precise hit rate from too small a sample to mean
    anything. Defaults to 8, not empirically fit -- enough real plays that one bad night doesn't
    single-handedly define the number, still low enough to surface a real signal without
    requiring a huge pooled window.

    Returns a list of {"player", "player_id", "n", "avg_model_prob", "actual_hit_rate", "gap"},
    one entry per player with at least min_plays real settled plays, sorted by "gap" DESCENDING
    (most model-OVERRATED player first). gap = avg_model_prob - actual_hit_rate: positive means
    the model expected more than actually happened (the real "ban list" direction -- a player
    who keeps missing plays the model favored); negative means the opposite (a player quietly
    outperforming what the model expected of them, the mirror-image, equally real finding)."""
    settled = [g for g in graded_plays if g.get("Hit") is not None and g.get("PlayerId") is not None]
    by_player: Dict[Any, Dict] = {}
    for g in settled:
        pid = g["PlayerId"]
        rec = by_player.setdefault(pid, {"player": g.get("Player"), "player_id": pid,
                                         "n": 0, "_sum_model_prob": 0.0, "_hits": 0})
        rec["n"] += 1
        rec["_sum_model_prob"] += g.get("ModelProb", 0.0)
        if g["Hit"]:
            rec["_hits"] += 1

    out = []
    for rec in by_player.values():
        if rec["n"] < min_plays:
            continue
        avg_prob = rec["_sum_model_prob"] / rec["n"]
        hit_rate = rec["_hits"] / rec["n"]
        out.append({"player": rec["player"], "player_id": rec["player_id"], "n": rec["n"],
                    "avg_model_prob": round(avg_prob, 3), "actual_hit_rate": round(hit_rate, 3),
                    "gap": round(avg_prob - hit_rate, 3)})
    return sorted(out, key=lambda r: -r["gap"])


# Confirmed directly with the person building this platform: 20 real settled plays before ANY
# player-specific correction is even attempted -- deliberately lower than CALIBRATION_MIN_N=100
# above (market-level pools EVERY player together, so 100 real plays is realistic; one specific
# player accumulating 100 real settled plays in a season would be rare), but meaningfully higher
# than player_calibration's own display-only min_plays=8 default (or the as-low-as-2 that page's
# own real UI allows) -- that page is a real, deliberate EXPLORATORY tool for human judgment (its
# own on-page caption already says so: "worth watching, not automatically acting on"), and this
# is the opposite: a real, automatic correction reaching live predictions, which needs real,
# proven evidence behind it, not a hot week.
PLAYER_CALIBRATION_MIN_N = 20
PLAYER_CALIBRATION_SHRINK_PRIOR = 20   # same real structure as CALIBRATION_SHRINK_PRIOR above --
                                       # at exactly the floor, a correction applies at half its
                                       # own fitted strength, not full strength immediately


def fit_player_calibration(graded_plays: List[Dict], min_plays: int = PLAYER_CALIBRATION_MIN_N,
                           prior: float = PLAYER_CALIBRATION_SHRINK_PRIOR) -> Dict[Any, Dict]:
    """A real, second, STACKED correction layer -- per PLAYER, not per market -- added directly
    on request: a real, specific example (a hitter who's genuinely been a real "HR or bust" read
    over their last 20 real settled plays, surfacing as a top play far more consistently than
    that real pattern justifies) that the existing market-wide correction (fit_market_calibration
    above) can't reach, since it corrects a whole market the same way for every player in it, not
    one specific player's own real pattern within that market.

    DELIBERATELY REUSES player_calibration's OWN ALREADY-TRUSTED gap computation directly, not a
    new regression -- a player's own real settled-play count is far too thin (20-50, not the
    100+ fit_market_calibration needs) to reliably fit a real bucketed slope/intercept curve the
    way the market-level correction does; a single real, shrunk gap (avg_model_prob minus actual
    hit_rate, exactly what player_calibration already computes and displays for human review) is
    the honest, robust version of this at real player-level sample sizes, not a weaker
    approximation of the market-level method.

    Same real shrinkage STRUCTURE as fit_market_calibration (weight = n / (n + prior)) -- at
    exactly min_plays, a player's own real gap is applied at half its own real strength, growing
    toward full strength only as real n grows well past the floor, the same real reason a hard
    on/off threshold isn't used here either.

    Returns {player_id: {"player", "n", "weight", "raw_gap", "shrunk_gap"}} for every player with
    at least min_plays real settled plays -- a real, empty dict for a sport/window with no player
    clearing that floor yet, never a guessed correction. Pooled across every market for that
    player (player_calibration's own real pooling choice, reused here for the same real reason:
    a real "ban list" instinct doesn't split by market either)."""
    raw = player_calibration(graded_plays, min_plays=min_plays)
    out: Dict[Any, Dict] = {}
    for rec in raw:
        n = rec["n"]
        weight = n / (n + prior)
        raw_gap = rec["gap"]
        out[rec["player_id"]] = {
            "player": rec["player"], "n": n, "weight": round(weight, 3),
            "raw_gap": raw_gap, "shrunk_gap": round(weight * raw_gap, 4),
        }
    return out


def apply_player_calibration_correction(raw_prob: Optional[float],
                                        correction: Optional[Dict]) -> Optional[float]:
    """Apply a fitted player-level correction (fit_player_calibration's own output) to ONE real
    ModelProb -- meant to be applied AFTER apply_calibration_correction (the market-level layer),
    stacked, not instead of it. correction=None (no player-specific pattern proven yet -- the
    common case for most players, by design) is a genuine no-op, same real contract as the
    market-level version. gap = avg_model_prob - actual_hit_rate, so a POSITIVE gap means the
    model has been overrating this player (subtracting it pulls the number down, toward what
    actually happened); a negative gap means the opposite. Same real [0.01, 0.99] clamp as every
    other probability on this platform -- a correction can nudge a number, never claim a false
    certainty the model itself never actually has."""
    if correction is None or raw_prob is None:
        return raw_prob
    p = raw_prob - correction["shrunk_gap"]
    return min(max(p, 0.01), 0.99)


def _pearson_r(xs: List[float], ys: List[float]) -> Optional[float]:
    """Standard, textbook Pearson correlation coefficient -- hand-rolled rather than pulling in
    scipy/numpy for one formula. Returns None when either variable has zero variance (a constant
    series -- correlation is mathematically undefined, not 0.0) or fewer than 2 points are given."""
    n = len(xs)
    if n < 2:
        return None
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    return cov / ((var_x ** 0.5) * (var_y ** 0.5))


def slate_chalk_correlation(daily_points: List[Dict], min_days: int = 10) -> Dict:
    """Tests one specific, testable version of a real, one-time anecdotal claim from trader
    discussion: "a slate with a lot of higher-tier starters tends to run chalky" (favorites/
    high-probability plays hitting more as expected). Operationalized here as: does a day's
    AVERAGE probable-starter FIP (lower FIP = tougher, higher-tier pitching across the slate)
    correlate with that SAME day's overall observed prop hit rate (grade_slate's own summary
    ["hit_rate"] -- the most direct, already-computed proxy for "how chalky that day ran")?

    Takes daily_points: one entry per historical date -- {"date", "avg_starter_fip", "hit_rate"}
    -- and computes the real Pearson correlation between avg_starter_fip and hit_rate. Building
    that list itself requires real historical data (build_pitching_slate + a rebuilt, graded
    board, for each date) -- deliberately NOT this function's job. This function only does the
    correlation math on an already-assembled list, kept pure and testable, matching this
    codebase's established split between tested logic and network-dependent orchestration
    everywhere else (see player_calibration's own docstring for the same reasoning applied to a
    different hypothesis).

    THE EXPECTED SIGN IF THE HYPOTHESIS HOLDS IS NEGATIVE: lower avg_starter_fip (better, higher-
    tier pitching) should correlate with a HIGHER hit rate (a "chalkier" day) -- so a real
    negative r is CONSISTENT WITH (not proof of) the hypothesis, a positive r contradicts it, and
    an r near zero means no real linear relationship either way. This function reports the
    number; it does not interpret it as confirming or denying anything -- correlation from a
    modest number of days, on a real-world process this noisy, is suggestive at best, never
    proof, regardless of which way it comes out.

    min_days: a real, stated floor against reading anything into a correlation computed from too
    few days -- correlation coefficients from small samples are notoriously unstable, and this
    was flagged from the very start as "one hunch from one person, one time," exactly the kind
    of claim a tiny sample could spuriously "confirm." Below min_days, returns {"n_days": ...,
    "correlation": None, "note": "..."} rather than a precise-looking r from too few points.

    Returns {"n_days": int, "correlation": float or None, "note": str or None}."""
    n = len(daily_points)
    if n < min_days:
        return {"n_days": n, "correlation": None,
               "note": f"Only {n} day(s) of data — need at least {min_days} before a "
                      "correlation here means anything."}
    xs = [d["avg_starter_fip"] for d in daily_points]
    ys = [d["hit_rate"] for d in daily_points]
    r = _pearson_r(xs, ys)
    note = None if r is not None else "No real variation in one of the two series — correlation is undefined, not zero."
    return {"n_days": n, "correlation": round(r, 3) if r is not None else None, "note": note}


# Deliberately a SEPARATE stat-key map from MARKET_STAT above, not a reuse of it -- confirmed by
# reading mlb_engine.get_hitter_recent_games' own real per-game dict: it uses total_bases/
# strikeouts, genuinely different real field names than the final-result grading path MARKET_
# STAT was built for (tb/so). Pretending the two are interchangeable would be a real, silent
# field-name bug (a KeyError-free .get() would just silently return 0 every time), not a
# harmless shortcut. Batter markets only -- get_hitter_recent_games has no pitcher-side
# equivalent on this platform yet, an honest scope limit, not an oversight.
L5_L10_BATTER_STAT_KEY = {
    "Batter HR": "hr", "Batter Total Bases": "total_bases", "Batter Total Hits": "hits",
    "Batter Strikeouts": "strikeouts", "Batter Hits+Runs+RBIs": "hrr",
}


def l5_l10_hit_rate(games: List[Dict], market: str, line: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
    """Real hit rate over a player's own last 5/10 real games (mlb_engine.get_hitter_recent_
    games' own output) for the SAME market/line a specific graded play was actually reviewed
    against -- NOT a fixed ">=1 hit" shortcut (Dinger Engine's own L5 Hit Rate checkbox is
    exactly that shortcut, correct for its own single "Hit%" column; this generalizes to every
    real batter market Retrospective grades, where "clearing the line" means something different
    for Batter HR than for Batter Total Bases). ADDED DIRECTLY ON REQUEST.

    games is expected ASCENDING by date (mlb_engine.get_hitter_recent_games' own real order --
    oldest first), so the most recent games sit at the END of the list -- games[-5:]/games[-10:]
    here, deliberately not games[:5]/games[:10].

    Returns (l5_rate, l10_rate) -- each an honest None (never a padded/guessed rate) when fewer
    than that many real games exist yet, or when market/line isn't a real batter market this
    function covers (see L5_L10_BATTER_STAT_KEY's own docstring above for that real scope limit)."""
    stat_key = L5_L10_BATTER_STAT_KEY.get(market)
    if stat_key is None or line is None or not games:
        return None, None

    def _rate(window: int) -> Optional[float]:
        sub = games[-window:]
        if len(sub) < window:
            return None
        hits = sum(1 for g in sub if g.get(stat_key, 0) > line)
        return hits / window

    return _rate(5), _rate(10)


def rank_within_market(plays: List[Dict]) -> Dict[Any, Tuple[int, int]]:
    """For every real play, its own real rank (1 = the model's own most confident pick) within
    JUST its own market that day, and that market's own real total play count that day --
    {PlayerId: (rank, of_total)}. Ranked by ModelProb descending, the SAME real ranking
    convention market_report already uses below (not a second, separately-invented one) --
    extracted here specifically so a caller can persist rank alongside a graded play (grading_
    history.py's own real column) without needing market_report's own "did it clear the line"
    framing, which intentionally only reports on players who actually hit, not every real play.

    Computed from the PRE-grading plays list (ModelProb doesn't change through grading), so this
    is meant to be called once, before grade_slate, with its result merged into each graded
    play's own dict afterward -- see views/16_Retrospective.py's own real usage."""
    result: Dict[Any, Tuple[int, int]] = {}
    by_market: Dict[str, List[Dict]] = {}
    for p in plays:
        by_market.setdefault(p.get("Market"), []).append(p)
    for _market, mkt_plays in by_market.items():
        ranked = sorted(mkt_plays, key=lambda x: -(x.get("ModelProb") or 0))
        total = len(ranked)
        for i, p in enumerate(ranked):
            pid = p.get("PlayerId")
            if pid is not None:
                result[pid] = (i + 1, total)
    return result


# Real, sensible rank buckets, not raw individual ranks past the top few -- ADDED DIRECTLY ON
# REQUEST. The top 3 ranks each get their own real resolution (that's exactly where "does the
# model's own #1 pick actually catch more often than its #5" is a real, answerable question);
# past that, individual-rank buckets thin out fast on an ordinary slate (rarely more than one or
# two real plays AT rank 11, say, per market per day), so the tail is pooled into two wider real
# bands that can accumulate enough real volume to mean something.
RANK_BUCKETS: List[Tuple[str, int, int]] = [
    ("Rank 1", 1, 1), ("Rank 2", 2, 2), ("Rank 3", 3, 3),
    ("Ranks 4-5", 4, 5), ("Ranks 6-10", 6, 10), ("Ranks 11+", 11, 10_000),
]


def catch_rate_by_rank(graded_plays: List[Dict], market: Optional[str] = None,
                       min_n: int = 20) -> List[Dict]:
    """Real hit rate per RANK_BUCKETS bucket, across real accumulated graded plays (meant to be
    called on grading_history.fetch_graded_plays' own output, the same "real accumulated history,
    zero new statistical logic" design retro.fit_market_calibration already established). ADDED
    DIRECTLY ON REQUEST: is there a real correlation between how confident the model's own
    pre-game rank was and whether it actually caught -- e.g. does the #1 pick in a market really
    hit more often than the #5?

    Requires plays to carry real Rank/OfTotal (added to grading_history's own schema for exactly
    this) -- plays without it (logged before this feature existed, or from a source that never
    computed rank) are silently excluded, not treated as rank-less zeros.

    ALWAYS RETURNS ALL 6 REAL RANK_BUCKETS, EVERY CALL -- A REAL, CONFIRMED FIX, not the original
    design: the original version silently DROPPED any bucket below min_n entirely, which meant a
    caller had no way to tell "this bucket has zero real plays" apart from "this bucket has 8 real
    plays, just not enough yet" -- both looked identical (absent). Confirmed directly from a real
    report: Rank 1/2/3 are structurally a ONE-PER-DAY-PER-MARKET event (only ever one real #1 pick
    in a market, per day) -- a real 10-day window can NEVER produce more than 10 real Rank-1
    observations, permanently below a min_n=20 floor no matter how much real backfill happens
    within that window, while "Ranks 11+" pools dozens of real plays per day and clears easily --
    which meant a scoped chart showed one giant bar and nothing else, with no way to tell the
    difference between "truly zero data" and "real data, just not enough of it yet." Every real
    bucket now comes back with its own real n; hit_rate is None (not a fabricated number, and not
    silent absence either) whenever n < min_n -- the caller (Retrospective's own chart) renders
    every real category always, visually distinguishing "a real, trustworthy bar" from "real data
    exists here, just not enough of it yet" rather than making an entire category vanish."""
    if market is not None:
        graded_plays = [p for p in graded_plays if p.get("Market") == market]

    out = []
    for label, lo, hi in RANK_BUCKETS:
        bucket_plays = [p for p in graded_plays
                        if p.get("Rank") is not None and p.get("Hit") is not None
                        and lo <= p["Rank"] <= hi]
        n = len(bucket_plays)
        if n < min_n:
            out.append({"bucket": label, "n": n, "hit_rate": None})
            continue
        hits = sum(1 for p in bucket_plays if p["Hit"])
        out.append({"bucket": label, "n": n, "hit_rate": round(hits / n, 3)})
    return out



def market_report(plays: List[Dict], results: Dict[int, Dict], market: str, top_n: int = 15,
                  default_line: Optional[float] = None) -> Dict:
    """Of players whose actual result CLEARED the model's line for `market`, where did the model
    rank them pre-game? Generic version of homer_report/pitcher_k_report/batter_tb_report/
    batter_hits_report below — those four differ only in which market/stat key/default line they
    use, so this single function covers any market present in MARKET_STAT (MLB or WNBA) rather
    than needing a fifth near-duplicate for every future sport's markets. grade_play/grade_slate
    were already market-agnostic; this brings the report layer to the same standard.

    default_line: threshold used ONLY for the 'unprojected' bucket (a player who cleared a
    plausible line but wasn't in a projected slate at all, so there's no play-specific line to
    check against). Defaults to the median Line among this market's plays when not given — a
    reasonable per-slate stand-in that doesn't require a market-specific constant."""
    stat_key = MARKET_STAT.get(market)
    if stat_key is None:
        return {"caught": [], "missed": [], "unprojected": 0, "cutoff": 0, "total_ranked": 0}

    mkt_plays = sorted([p for p in plays if p["Market"] == market], key=lambda x: -x["ModelProb"])
    total = len(mkt_plays)
    cutoff = max(top_n, int(total * 0.10))
    rank_by_pid = {p.get("PlayerId"): (i + 1, p["ModelProb"], p["Player"], p["Line"], p.get("Conviction"))
                   for i, p in enumerate(mkt_plays)}

    if default_line is None:
        lines = sorted(p["Line"] for p in mkt_plays)
        default_line = lines[len(lines) // 2] if lines else 0.5

    caught, missed, unprojected = [], [], 0
    for pid, actuals in results.items():
        val = actuals.get(stat_key, 0) or 0
        if pid in rank_by_pid:
            rank, prob, name, line, conv = rank_by_pid[pid]
            if val <= line:            # the over didn't clear -> not a catch/miss candidate
                continue
            entry = {"Player": name, "PlayerId": pid, "Value": val, "Line": line, "ModelProb": prob,
                     "Conviction": conv, "Rank": rank, "OfTotal": total, "HitLine": True}
            (caught if rank <= cutoff else missed).append(entry)
        elif val > default_line:
            unprojected += 1

    caught.sort(key=lambda x: x["Rank"])
    missed.sort(key=lambda x: x["Rank"])
    return {"caught": caught, "missed": missed, "unprojected": unprojected,
            "cutoff": cutoff, "total_ranked": total}


def homer_report(plays: List[Dict], results: Dict[int, Dict], top_n: int = 15) -> Dict:
    """Of the players who actually homered, where did the model rank them in HR probability?
 
    The honest 'could we have caught it' view: a homer-hitter in the model's top plays was
    catchable pre-game; one ranked deep in the list was, by the data, genuinely random."""
    hr_plays = sorted([p for p in plays if p["Market"] == "Batter HR"],
                      key=lambda x: -x["ModelProb"])
    total = len(hr_plays)
    cutoff = max(top_n, int(total * 0.10))
    rank_by_pid = {p.get("PlayerId"): (i + 1, p["ModelProb"], p["Player"], p.get("Conviction"))
                   for i, p in enumerate(hr_plays)}
 
    caught, missed, unprojected = [], [], 0
    for pid, actuals in results.items():
        if (actuals.get("hr", 0) or 0) < 1:
            continue
        if pid in rank_by_pid:
            rank, prob, name, conv = rank_by_pid[pid]
            entry = {"Player": name, "PlayerId": pid, "HR": actuals["hr"], "ModelProb": prob,
                     "Conviction": conv, "Rank": rank, "OfTotal": total}
            (caught if rank <= cutoff else missed).append(entry)
        else:
            unprojected += 1   # not in a lineup we projected (sub, call-up, etc.)
 
    caught.sort(key=lambda x: x["Rank"])
    missed.sort(key=lambda x: x["Rank"])
    return {"caught": caught, "missed": missed, "unprojected": unprojected,
            "cutoff": cutoff, "total_ranked": total}
 
 
def _plat(row) -> Optional[str]:
    if row.get("Advantage") == "Advantage":
        return f"had the platoon edge ({row.get('Hand')} vs {row.get('Opp Hand')}HP)"
    return None
 
 
def _opp_hr9(row):
    try:
        h = float(row.get("Opp HR/9"))
        return h if h == h else None      # filter NaN (no-stats pitcher)
    except (TypeError, ValueError):
        return None
 
 
def explain_miss(row: Optional[Dict], market: str = "Batter HR") -> str:
    """Explain an outcome the model ranked LOW: what — if anything — could it have leaned on?
 
    Market-aware, because what makes an outcome 'catchable' differs by prop: homers key on
    barrels + power + a homer-prone matchup; total bases on slugging; hits on contact +
    hittable pitching; pitcher strikeouts on the opposing lineup's whiff rate. Deliberately
    honest: it separates a *catchable* miss (a real signal the ranking under-weighted, worth
    reviewing) from plain *variance* (no edge — the model was right to rank it low, and chasing
    these is the overfitting we avoid). `row` is the enriched board row (hitter or pitcher)
    looked up by player id; None means the player wasn't in a projected lineup at all."""
    if not row:
        return ("Not in a projected lineup (late change, call-up, or pinch-hit) — the model "
                "never saw this player.")
 
    # ---- Pitcher strikeouts: driven by the opposing lineup's whiff rate + projection -------
    if market == "Pitcher Strikeouts":
        signals: List[str] = []
        opp_k = row.get("_opp_k")
        proj_k = row.get("Proj K")
        if isinstance(opp_k, (int, float)) and opp_k >= 0.23:
            signals.append(f"opposing lineup whiff-prone ({opp_k * 100:.0f}% K rate)")
        if isinstance(proj_k, (int, float)) and proj_k >= 5.5:
            signals.append(f"model already projected a healthy {proj_k:.1f} K")
        if signals:
            return "Catchable — model had signal it under-weighted: " + "; ".join(signals) + "."
        pk = float(proj_k) if isinstance(proj_k, (int, float)) else 0.0
        return (f"Genuine over — projected only {pk:.1f} K against a contact lineup; the strikeouts "
                "landed above a low expectation. Not a systematic miss.")
 
    # ---- Batter Strikeouts: the batter's own real K rate vs the opposing pitcher's real allowed rate
    if market == "Batter Strikeouts":
        signals = []
        season_k = row.get("_season_k_rate")
        opp_k_allowed = row.get("_opp_k_allowed")
        if isinstance(season_k, (int, float)) and season_k >= 0.24:
            signals.append(f"his own real {season_k:.0%} K rate this season")
        if isinstance(opp_k_allowed, (int, float)) and opp_k_allowed >= 0.23:
            signals.append(f"faced a pitcher who allows Ks at a real {opp_k_allowed:.0%} rate")
        if signals:
            return "Catchable — model had signal it under-weighted: " + "; ".join(signals) + "."
        if isinstance(season_k, (int, float)) and season_k < 0.16:
            return (f"Genuine variance — his own real K rate this season is only {season_k:.0%}, "
                   "a real contact bat having an off night, not a signal the model missed.")
        return "Landed just outside the top tier — no specific signal the model missed; normal strikeout variance."

    # ---- Batter Walks: the batter's own real BB rate vs the opposing pitcher's real allowed rate
    if market == "Batter Walks":
        signals = []
        season_bb = row.get("_season_bb_rate")
        opp_bb_allowed = row.get("_opp_bb_allowed")
        if isinstance(season_bb, (int, float)) and season_bb >= 0.11:
            signals.append(f"his own real {season_bb:.0%} walk rate this season")
        if isinstance(opp_bb_allowed, (int, float)) and opp_bb_allowed >= 0.09:
            signals.append(f"faced a pitcher who allows walks at a real {opp_bb_allowed:.0%} rate")
        if signals:
            return "Catchable — model had signal it under-weighted: " + "; ".join(signals) + "."
        if isinstance(season_bb, (int, float)) and season_bb < 0.06:
            return (f"Genuine variance — his own real walk rate this season is only {season_bb:.0%}, "
                   "a genuinely free-swinging bat drawing one anyway, not a signal the model missed.")
        return "Landed just outside the top tier — no specific signal the model missed; normal walk variance."

    # ---- Batter Stolen Bases: the batter's own real season SB rate, the one real signal that
    # actually matters here (no real opposing-catcher-arm/pitcher-hold data available yet)
    if market == "Batter Stolen Bases":
        season_sb = row.get("_season_sb")
        season_pa = row.get("_season_pa_for_sb")
        if isinstance(season_sb, (int, float)) and isinstance(season_pa, (int, float)) and season_pa > 0:
            rate_per_100 = (season_sb / season_pa) * 100
            if rate_per_100 >= 2.0:
                return (f"Catchable — model had signal it under-weighted: {season_sb:.0f} SB in "
                       f"{season_pa:.0f} PA this season ({rate_per_100:.1f} per 100 PA) is a real, "
                       "active basestealer, not a rare event for this specific player.")
            return (f"Genuine variance — only {season_sb:.0f} SB in {season_pa:.0f} PA this season "
                   f"({rate_per_100:.1f} per 100 PA); a real, rare opportunistic steal, not a signal "
                   "the model missed.")
        return "Landed just outside the top tier — no specific signal the model missed; stolen bases are inherently rare."

    # ---- Every other market: an honest "not built yet" message, never a silently wrong one.
    # A real, pre-existing safety fix, found while extending this function: the old unconditional
    # fallback below applied HR-specific reasoning (ISO, home run count) to ANY unmatched market
    # -- nonsensical for, say, a Runs/RBI/Doubles miss. Better to say "not built yet" honestly
    # than show a number that has nothing to do with the actual market.
    if market not in ("Batter Total Bases", "Batter Total Hits", "Batter HR"):
        return ("No specific miss explanation built for this market yet — the real season/matchup "
                "numbers behind it aren't wired into this function. Not a claim about whether the "
                "model was right or wrong, just an honest gap in this specific explanation.")

    # ---- Offensive markets: shared skeleton, market-specific signal + power floor -----------
    signals = []
    wx = row.get("_weather_hr") or 1.0
    hr9 = _opp_hr9(row)
    plat = _plat(row)
 
    if market == "Batter Total Bases":
        if (row.get("Due") or 0) > 0.01:
            signals.append("Statcast barrels imply extra-base power the HR count hides")
        if hr9 is not None and hr9 >= 1.30:
            signals.append(f"faced a homer-prone starter (Opp HR/9 {hr9:.2f})")
        if wx >= 1.05:
            signals.append(f"park/weather favored power (+{(wx - 1) * 100:.0f}%)")
        if plat:
            signals.append(plat)
        slg = float(row.get("SLG") or 0.0)
        low, low_msg = (slg < 0.400), f"modest slugging (SLG {slg:.3f})"
        tail = "extra-base variance"
 
    elif market == "Batter Total Hits":
        if plat:
            signals.append(plat)
        if hr9 is not None and hr9 >= 1.30:
            signals.append(f"faced a hittable starter (Opp HR/9 {hr9:.2f})")
        avg = float(row.get("AVG") or 0.0)
        low = avg < 0.250
        low_msg = f"contact bat (AVG {avg:.3f}) — with a hit landing well over half the time anyway"
        tail = "hit variance (1+ hits is closer to a coin flip than a called shot)"
 
    else:  # Batter HR
        if (row.get("Due") or 0) > 0.01:
            bp = row.get("Barrel%")
            extra = f" (barrel {bp * 100:.0f}%)" if isinstance(bp, (int, float)) and bp else ""
            signals.append(f"Statcast barrels ran ahead of the HR count{extra} — the buy-the-dip "
                           "power signal was there")
        if hr9 is not None and hr9 >= 1.30:
            signals.append(f"faced a homer-prone starter (Opp HR/9 {hr9:.2f})")
        if wx >= 1.05:
            signals.append(f"park/weather favored power (+{(wx - 1) * 100:.0f}%)")
        if plat:
            signals.append(plat)
        iso = float(row.get("ISO") or 0.0)
        hr = int(float(row.get("HR") or 0.0))
        low = iso < 0.15 or hr <= 6
        low_msg = f"modest season power (ISO {iso:.3f}, {hr} HR)"
        tail = "home-run variance"
 
    if signals:
        return "Catchable — model had signal it under-weighted: " + "; ".join(signals) + "."
    if low:
        return (f"Genuine long shot — {low_msg} and no matchup edge. Correctly ranked low; "
                "variance, not a systematic miss.")
    return f"Landed just outside the top tier — no specific signal the model missed; normal {tail}."
 
 
def explain_pick_miss(model_prob: Optional[float], market: str = "", side: str = "") -> str:
    """Why did a graded PICK (the model's lean) NOT hit? Different question from explain_miss:
    that one asks why a result the model ranked low still happened; THIS asks why a play the
    model liked didn't come in.
 
    The honest, dominant answer is usually the base rate — the model's own probability favored a
    miss. This reframes a cold slate of 'misses' as the expected outcome for a high-variance
    market, not a model error. HR is the extreme case: a 2.5-3x conviction is still only ~30%
    model probability, so most such plays are *supposed* to miss on any given night."""
    try:
        p = float(model_prob)
    except (TypeError, ValueError):
        return ""
    if p != p:                       # NaN
        return ""
    pct, miss_pct = p * 100, (1 - p) * 100
    if p < 0.40:
        msg = (f"Long shot by design — model gave only {pct:.0f}%, so a miss was the "
               f"~{miss_pct:.0f}% base case.")
        if market == "Batter HR":
            msg += (" HR is the highest-variance market; even top plays sit near 30%, so most "
                    "miss on any given night — a cold HR slate is normal, not a model failure.")
        return msg
    if p < 0.55:
        return (f"Coin-flip lean — model was only mildly on the {(side or 'over').lower()} "
                f"({pct:.0f}%); a miss is well within range.")
    return (f"Real lean that lost — model favored it at {pct:.0f}%, so this was a genuine adverse "
            "result (variance), not a low-probability play.")
 
 
def pitcher_k_report(plays: List[Dict], results: Dict[int, Dict], top_n: int = 15,
                     default_line: float = 5.5) -> Dict:
    """Of pitchers whose strikeouts CLEARED their line, where did the model rank them?"""
    k_plays = sorted([p for p in plays if p["Market"] == "Pitcher Strikeouts"],
                     key=lambda x: -x["ModelProb"])
    total = len(k_plays)
    cutoff = max(top_n, int(total * 0.10))
    rank_by_pid = {p.get("PlayerId"): (i + 1, p["ModelProb"], p["Player"], p["Line"], p.get("Conviction"))
                   for i, p in enumerate(k_plays)}
 
    caught, missed, unprojected = [], [], 0
    for pid, actuals in results.items():
        k_val = actuals.get("p_k", 0) or 0
        if pid in rank_by_pid:
            rank, prob, name, line, conv = rank_by_pid[pid]
            if k_val < line:            # the over didn't hit -> not a catch/miss candidate
                continue
            entry = {"Player": name, "PlayerId": pid, "K": k_val, "Line": line, "ModelProb": prob,
                     "Conviction": conv, "Rank": rank, "OfTotal": total, "HitLine": True}
            (caught if rank <= cutoff else missed).append(entry)
        elif k_val >= default_line:     # cleared a typical line but wasn't in a projected slate
            unprojected += 1
 
    caught.sort(key=lambda x: x["Rank"])
    missed.sort(key=lambda x: x["Rank"])
    return {"caught": caught, "missed": missed, "unprojected": unprojected,
            "cutoff": cutoff, "total_ranked": total}
 
 
def batter_tb_report(plays: List[Dict], results: Dict[int, Dict], top_n: int = 15,
                     default_line: float = 1.5) -> Dict:
    """Of batters whose total bases CLEARED their line, where did the model rank them?"""
    tb_plays = sorted([p for p in plays if p["Market"] == "Batter Total Bases"],
                      key=lambda x: -x["ModelProb"])
    total = len(tb_plays)
    cutoff = max(top_n, int(total * 0.10))
    rank_by_pid = {p.get("PlayerId"): (i + 1, p["ModelProb"], p["Player"], p["Line"], p.get("Conviction"))
                   for i, p in enumerate(tb_plays)}
 
    caught, missed, unprojected = [], [], 0
    for pid, actuals in results.items():
        tb_val = actuals.get("tb", 0) or 0
        if pid in rank_by_pid:
            rank, prob, name, line, conv = rank_by_pid[pid]
            if tb_val < line:
                continue
            entry = {"Player": name, "PlayerId": pid, "TB": tb_val, "Line": line, "ModelProb": prob,
                     "Conviction": conv, "Rank": rank, "OfTotal": total, "HitLine": True}
            (caught if rank <= cutoff else missed).append(entry)
        elif tb_val >= default_line:
            unprojected += 1
 
    caught.sort(key=lambda x: x["Rank"])
    missed.sort(key=lambda x: x["Rank"])
    return {"caught": caught, "missed": missed, "unprojected": unprojected,
            "cutoff": cutoff, "total_ranked": total}
 
 
def batter_hits_report(plays: List[Dict], results: Dict[int, Dict], top_n: int = 15,
                       default_line: float = 0.5) -> Dict:
    """Of batters whose hits CLEARED their line, where did the model rank them?"""
    hit_plays = sorted([p for p in plays if p["Market"] == "Batter Total Hits"],
                       key=lambda x: -x["ModelProb"])
    total = len(hit_plays)
    cutoff = max(top_n, int(total * 0.10))
    rank_by_pid = {p.get("PlayerId"): (i + 1, p["ModelProb"], p["Player"], p["Line"], p.get("Conviction"))
                   for i, p in enumerate(hit_plays)}
 
    caught, missed, unprojected = [], [], 0
    for pid, actuals in results.items():
        h_val = actuals.get("hits", 0) or 0
        if pid in rank_by_pid:
            rank, prob, name, line, conv = rank_by_pid[pid]
            if h_val < line:
                continue
            entry = {"Player": name, "PlayerId": pid, "Hits": h_val, "Line": line, "ModelProb": prob,
                     "Conviction": conv, "Rank": rank, "OfTotal": total, "HitLine": True}
            (caught if rank <= cutoff else missed).append(entry)
        elif h_val >= default_line:
            unprojected += 1
 
    caught.sort(key=lambda x: x["Rank"])
    missed.sort(key=lambda x: x["Rank"])
    return {"caught": caught, "missed": missed, "unprojected": unprojected,
            "cutoff": cutoff, "total_ranked": total}
