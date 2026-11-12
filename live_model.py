"""
live_model.py — in-game projections (Nov 12). Owner: "I don't have an ability to understand the projection of live
events ... if I wanted to make a pick live based on how the game has been progressing, that option is not available."

Given the pre-game projection (the Game Lab ratings: home margin M0 and total T0) and the live state (score, period,
clock), it projects the final:

Basketball (NBA, WNBA, college, EuroLeague / EuroCup, NBL, FIBA leagues)
  * margin: final = current margin + M0 x (share of the game left); the uncertainty shrinks with the time left
    (a whole game's spread, `sd`, scaled by the square root of the share left -- the standard in-game model).
  * total: current points + minutes left x the scoring rate, where the rate starts at the pre-game rate and moves
    toward tonight's observed pace as the game goes on (weight = minutes played / (minutes played + PACE_K x game)).
  * win chance, and the chance of covering / going over any live line, follow from those two normals.
Hockey (NHL)
  * goals left for each team ~ Poisson(pre-game expected goals x share of the game left); win chance counts ties as
    overtime (a coin flip with a small home edge), totals and puck lines from the same counts.

Settings come from LIVE_CFG; the pace weight and spreads are checked on past games in research/live_backtest.py.
Everything here is pure math -- the feeds and the page live in live_games.py and views/54_Live_Games.py.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Sequence

# periods, minutes per period, overtime minutes, full-game margin sd, full-game total sd.
# Nov 12 backtest (research/live_backtest.py, ~1,800 NBA + college checkpoints from play-by-play): the pre-game
# spreads were too tight live -- the final landed inside one sd only 51-62% of the time (want 68%); x1.2 brought it
# to 63-71% and improved the win-chance scores, so the basketball spreads below are the pre-game ones x1.2. The end of
# a game adds its own noise (fouling, free throws), so every spread keeps a small floor (END_SD) however little time is
# left.
LIVE_CFG: Dict[str, Dict] = {
    "NBA": {"periods": 4, "minutes": 12, "ot": 5, "sd": 15.0, "total_sd": 21.6},
    "WNBA": {"periods": 4, "minutes": 10, "ot": 5, "sd": 14.4, "total_sd": 20.4},
    "NCAAMB": {"periods": 2, "minutes": 20, "ot": 5, "sd": 13.2, "total_sd": 20.4},
    "NBL": {"periods": 4, "minutes": 10, "ot": 5, "sd": 14.4, "total_sd": 21.6},
    "EUROLEAGUE": {"periods": 4, "minutes": 10, "ot": 5, "sd": 14.4, "total_sd": 19.2},
    "EUROCUP": {"periods": 4, "minutes": 10, "ot": 5, "sd": 14.4, "total_sd": 19.2},
    "FIBA": {"periods": 4, "minutes": 10, "ot": 5, "sd": 14.4, "total_sd": 20.4},
    "NHL": {"periods": 3, "minutes": 20, "ot": 5, "sd": 2.4, "total_sd": 2.3, "hockey": True},
    # Nov 12: football -- full-game spreads of the final vs the closing line (NFL ~13.5 / 13 points, college ~16)
    "NFL": {"periods": 4, "minutes": 15, "ot": 10, "sd": 13.5, "total_sd": 13.0, "football": True},
    "NCAAF": {"periods": 4, "minutes": 15, "ot": 5, "sd": 16.5, "total_sd": 16.0, "football": True},
}
END_SD = 2.0            # points of noise left in any basketball game while it's still being played
FOOTBALL_TOTAL_FLOOR = 4.0
# Nov 12 backtest: tonight's observed pace added nothing -- the projected total was most accurate using the pre-game
# scoring rate for the rest of the game (MAE 8.75 NBA / 8.54 college vs 9.16 / 8.86 at the weight first tried, and
# worse still leaning harder on the live pace). So the observed pace gets almost no weight.
PACE_K = 1000.0         # observed pace counts minutes_played / (minutes_played + PACE_K x game minutes)
NHL_OT_HOME = 0.52      # a tied NHL game: home wins OT / shootout a bit more than half the time


def cfg(league: str) -> Dict:
    return LIVE_CFG.get(league) or LIVE_CFG["FIBA"]


def game_minutes(league: str) -> float:
    c = cfg(league)
    return float(c["periods"] * c["minutes"])


def elapsed(league: str, period: int, clock_left: float) -> float:
    """Minutes played. `clock_left` is minutes left in the current period; periods past regulation are overtime."""
    c = cfg(league)
    period = max(int(period or 1), 1)
    if period <= c["periods"]:
        return (period - 1) * c["minutes"] + (c["minutes"] - max(0.0, min(clock_left, c["minutes"])))
    return game_minutes(league) + (period - c["periods"] - 1) * c["ot"] + (c["ot"] - max(0.0, min(clock_left, c["ot"])))


def minutes_left(league: str, period: int, clock_left: float) -> float:
    """Minutes still to play in regulation, or in the current overtime."""
    c = cfg(league)
    period = max(int(period or 1), 1)
    if period <= c["periods"]:
        return (c["periods"] - period) * c["minutes"] + max(0.0, min(clock_left, c["minutes"]))
    return max(0.0, min(clock_left, c["ot"]))


def _phi(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2))


def expected_points(yards_to_go: Optional[float]) -> float:
    """Football: points the team with the ball can expect from this drive, by distance to the end zone (the usual
    expected-points curve, straight-line fit: own 10 ~ -0.3, own 25 ~ 0.7, midfield ~ 2.3, opp 25 ~ 3.9, opp 10 ~ 4.9)."""
    if yards_to_go is None:
        return 0.0
    return 5.5 - 0.064 * max(1.0, min(99.0, float(yards_to_go)))


def project(league: str, pre_margin: float, pre_total: float, home: float, away: float, period: int,
            clock_left: float, final: bool = False, possession: Optional[str] = None,
            yards_to_go: Optional[float] = None) -> Dict:
    """The live read for one game. Margins are home minus away. Returns win chance, projected final margin / total
    and their spreads, plus the inputs that went in."""
    c = cfg(league)
    L = game_minutes(league)
    m = 0.0 if final else minutes_left(league, period, clock_left)
    e = elapsed(league, period, clock_left)
    share = m / L
    cur_margin, cur_total = home - away, home + away
    out = {"league": league, "minutes_left": m, "minutes_played": e, "share_left": share,
           "home": home, "away": away, "pre_margin": pre_margin, "pre_total": pre_total}
    if c.get("hockey"):
        return {**out, **_hockey(pre_margin, pre_total, home, away, share)}
    pre_rate = pre_total / L
    w = e / (e + PACE_K * L) if e > 0 else 0.0
    obs_rate = cur_total / e if e > 0 else pre_rate
    rate = (1 - w) * pre_rate + w * obs_rate
    mean_m = cur_margin + pre_margin * share
    ep = 0.0
    if c.get("football") and m > 0 and possession in ("home", "away"):
        # the drive in progress: its expected points go to the team with the ball (net of the average drive, which
        # the pre-game share already counts)
        ep = expected_points(yards_to_go) - 0.5
        mean_m += ep if possession == "home" else -ep
    floor = END_SD if m > 0 else 0.0
    sd_m = math.sqrt(c["sd"] ** 2 * share + floor ** 2)
    mean_t = cur_total + rate * m
    # Nov 12 football backtest: the drive in progress sharpened the win chance (NFL Brier 0.149 -> 0.139, most of it
    # late) but adding it to the total made the total worse, so it only moves the margin; and one score is 7 points,
    # so the total keeps a bigger floor late in a football game (the final landed inside the range only ~50% of the
    # time with 5 minutes left on the basketball floor).
    t_floor = FOOTBALL_TOTAL_FLOOR if (c.get("football") and m > 0) else floor
    sd_t = math.sqrt(c["total_sd"] ** 2 * share + t_floor ** 2)
    if sd_m < 1e-6:
        p = 1.0 if mean_m > 0 else 0.0 if mean_m < 0 else 0.5
    else:
        p = _phi(mean_m / sd_m)
    return {**out, "win_home": p, "margin": mean_m, "margin_sd": sd_m, "total": mean_t, "total_sd": sd_t,
            "pace": rate * L, "pace_weight": w}


def _pois(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


def _hockey(pre_margin: float, pre_total: float, home: float, away: float, share: float) -> Dict:
    lh = max(0.05, (pre_total + pre_margin) / 2) * share
    la = max(0.05, (pre_total - pre_margin) / 2) * share
    ph = [_pois(k, lh) for k in range(15)]
    pa = [_pois(k, la) for k in range(15)]
    win = tie = 0.0
    dist_margin: Dict[int, float] = {}
    dist_total: Dict[int, float] = {}
    for i, x in enumerate(ph):
        for j, y in enumerate(pa):
            pr = x * y
            d = int(home + i - away - j)
            dist_margin[d] = dist_margin.get(d, 0.0) + pr
            t = int(home + away + i + j)
            dist_total[t] = dist_total.get(t, 0.0) + pr
            if d > 0:
                win += pr
            elif d == 0:
                tie += pr
    return {"win_home": win + tie * NHL_OT_HOME, "tie_regulation": tie, "margin": home - away + lh - la,
            "margin_sd": math.sqrt(lh + la), "total": home + away + lh + la, "total_sd": math.sqrt(lh + la),
            "_dist_margin": dist_margin, "_dist_total": dist_total}


def cover_chance(read: Dict, home_spread: float, side: str = "home") -> float:
    """Chance the side covers a live spread (home_spread is the home team's line, e.g. -3.5). Pushes count half."""
    if "_dist_margin" in read:                                  # hockey: count goals exactly
        need = -home_spread
        p = sum(v for d, v in read["_dist_margin"].items() if d > need) + \
            0.5 * sum(v for d, v in read["_dist_margin"].items() if d == need)
        return p if side == "home" else 1 - p
    if read["margin_sd"] < 1e-6:
        p = 1.0 if read["margin"] + home_spread > 0 else 0.0 if read["margin"] + home_spread < 0 else 0.5
    else:
        p = _phi((read["margin"] + home_spread) / read["margin_sd"])
    return p if side == "home" else 1 - p


def over_chance(read: Dict, line: float) -> float:
    """Chance the final total goes over a live total line (a whole-number line pushes half the time)."""
    if "_dist_total" in read:
        return sum(v for t, v in read["_dist_total"].items() if t > line) + \
            0.5 * sum(v for t, v in read["_dist_total"].items() if t == line)
    if read["total_sd"] < 1e-6:
        return 1.0 if read["total"] > line else 0.0 if read["total"] < line else 0.5
    return 1 - _phi((line - read["total"]) / read["total_sd"])


def fair_spread(read: Dict) -> float:
    """The home spread the model calls a coin flip (rounded to the half point)."""
    return round(-read["margin"] * 2) / 2


def fair_total(read: Dict) -> float:
    return round(read["total"] * 2) / 2


def implied(price: Optional[float]) -> Optional[float]:
    if price is None:
        return None
    price = float(price)
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


def edge(chance: Optional[float], price: Optional[float]) -> Optional[float]:
    """Expected profit per $1 at the price (chance x payout - 1)."""
    if chance is None or price is None:
        return None
    price = float(price)
    dec = 1 + (price / 100 if price > 0 else 100 / -price)
    return chance * dec - 1


# --------------------------------------------------------------------------- tennis (Nov 12)
# ESPN's live tennis feed gives the games in each set (no point score, no server), so the read works from sets and
# games: each player's chance of winning a point on serve is backed out of the pre-match chance (tour-average serve
# around it, nudged apart until the match chance matches), then the standard point -> game -> set -> match model runs
# from the current score, averaging over who serves next.
SERVE_AVG = {"atp": 0.64, "wta": 0.56}
from functools import lru_cache as _lru


def hold(s: float) -> float:
    """Chance the server holds, winning each point with chance s."""
    q = 1 - s
    deuce = s * s / (s * s + q * q)
    return s ** 4 * (1 + 4 * q + 10 * q * q) + 20 * s ** 3 * q ** 3 * deuce


@_lru(maxsize=None)
def _tiebreak(sa: float, sb: float, a: int, b: int, n: int) -> float:
    """Chance A wins a tiebreak from a-b with point n next (A serves point 0, then they alternate in pairs)."""
    if a >= 7 and a - b >= 2:
        return 1.0
    if b >= 7 and b - a >= 2:
        return 0.0
    if a >= 6 and b >= 6 and a == b:                            # deuce-like: two serves each from here on average
        pa = sa * (1 - sb)
        pb = (1 - sa) * sb
        return pa / (pa + pb) if pa + pb > 0 else 0.5
    a_serves = (n % 4) in (0, 3)
    p = sa if a_serves else 1 - sb
    return p * _tiebreak(sa, sb, a + 1, b, n + 1) + (1 - p) * _tiebreak(sa, sb, a, b + 1, n + 1)


@_lru(maxsize=None)
def _set(sa: float, sb: float, ga: int, gb: int, a_serves: bool) -> tuple:
    """(chance A wins the set, expected games still to play) from ga-gb with A serving the next game if a_serves."""
    if (ga >= 6 and ga - gb >= 2) or ga == 7:
        return 1.0, 0.0
    if (gb >= 6 and gb - ga >= 2) or gb == 7:
        return 0.0, 0.0
    if ga == 6 and gb == 6:
        return _tiebreak(sa, sb, 0, 0, 0 if a_serves else 1), 1.0
    p = hold(sa) if a_serves else 1 - hold(sb)
    w1, e1 = _set(sa, sb, ga + 1, gb, not a_serves)
    w2, e2 = _set(sa, sb, ga, gb + 1, not a_serves)
    return p * w1 + (1 - p) * w2, 1 + p * e1 + (1 - p) * e2


def _set_avg(sa: float, sb: float, ga: int, gb: int) -> tuple:
    x, y = _set(sa, sb, ga, gb, True), _set(sa, sb, ga, gb, False)
    return (x[0] + y[0]) / 2, (x[1] + y[1]) / 2


@_lru(maxsize=None)
def _match(sa: float, sb: float, a_sets: int, b_sets: int, need: int) -> tuple:
    """(chance A wins, expected games still to play) from a set score, at the start of a set."""
    if a_sets >= need:
        return 1.0, 0.0
    if b_sets >= need:
        return 0.0, 0.0
    ps, es = _set_avg(sa, sb, 0, 0)
    w1, e1 = _match(sa, sb, a_sets + 1, b_sets, need)
    w2, e2 = _match(sa, sb, a_sets, b_sets + 1, need)
    return ps * w1 + (1 - ps) * w2, es + ps * e1 + (1 - ps) * e2


def serve_points(p_match: float, tour: str, best_of: int = 3) -> tuple:
    """Serve-point chances (A, B) that reproduce the pre-match chance for A."""
    base = SERVE_AVG.get(tour, 0.62)
    need = best_of // 2 + 1
    lo, hi = -0.35, 0.35
    for _ in range(50):
        d = (lo + hi) / 2
        sa, sb = round(base + d / 2, 6), round(base - d / 2, 6)
        if _match(sa, sb, 0, 0, need)[0] < p_match:
            lo = d
        else:
            hi = d
    d = (lo + hi) / 2
    return round(base + d / 2, 6), round(base - d / 2, 6)


def tennis(p_pre: float, tour: str, best_of: int, sets_a: Sequence[int], sets_b: Sequence[int],
           final: bool = False, a_serving: Optional[bool] = None) -> Dict:
    """Live read from the games in each set (the last set listed is the one in progress, unless it's finished).
    Returns the chance A wins, games played and the projected total games."""
    p_pre = min(max(float(p_pre), 0.02), 0.98)
    sa, sb = serve_points(p_pre, tour, best_of)
    need = best_of // 2 + 1
    a_sets = b_sets = 0
    played = 0
    cur = None
    for i, (x, y) in enumerate(zip(sets_a, sets_b)):
        x, y = int(x or 0), int(y or 0)
        played += x + y
        done = (max(x, y) >= 6 and abs(x - y) >= 2) or max(x, y) == 7
        if done:
            a_sets += x > y
            b_sets += y > x
        elif i == len(sets_a) - 1:
            cur = (x, y)
    if final or a_sets >= need or b_sets >= need:
        return {"win_a": 1.0 if a_sets > b_sets else 0.0, "games_played": played, "total_games": float(played),
                "serve": (sa, sb), "sets": (a_sets, b_sets)}
    if cur is None:
        w, e = _match(sa, sb, a_sets, b_sets, need)
    else:
        # Nov 12: ESPN says who's serving the game in progress -- use it when known, else average both ways
        ps, es = _set(sa, sb, cur[0], cur[1], a_serving) if a_serving is not None else _set_avg(sa, sb, *cur)
        w1, e1 = _match(sa, sb, a_sets + 1, b_sets, need)
        w2, e2 = _match(sa, sb, a_sets, b_sets + 1, need)
        w, e = ps * w1 + (1 - ps) * w2, es + ps * e1 + (1 - ps) * e2
    return {"win_a": w, "games_played": played, "total_games": played + e, "serve": (sa, sb),
            "sets": (a_sets, b_sets), "current_set": cur}
