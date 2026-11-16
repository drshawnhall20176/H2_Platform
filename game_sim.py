"""
game_sim.py — the football Game Labs' two game-level sections, for every other Game Lab (Nov 16).

The NFL and college football Game Labs show, for one game, "Team scoring context" (recent scoring and points allowed
against the season) and "Moneyline / spread / total" from a 20,000-game Monte Carlo simulation. The basketball,
hockey and international Game Labs had neither. This adds both.

ONE MODEL, ONE ANSWER: these labs already have a model -- the ratings projection behind the slate table (its margin,
total and win chance). The simulation here is run AROUND that projection, not from a second set of numbers:
  * projected score, spread and total are the ratings model's own
  * the win chance shown is the ratings model's own (the stored, calibrated one)
  * the simulation adds what a single projection can't: how wide the range of finishes is -- each team's likely
    scoring range, how often the game is close, a blowout, or (hockey) goes to overtime

Basketball: the two scores are drawn together so that margins spread by the league's margin SD and totals by its
total SD (todays_best.MARGIN_SD / TOTAL_SD). Hockey: each team's goals are a Poisson count around its projection; a
tie after regulation is overtime, decided 50/50.

Nothing here is a tested edge or a pick: it describes the projection, and the pages say so.
"""
from __future__ import annotations

import zlib
from typing import Dict, Iterable, List, Optional

N_SIMS = 20000
RECENT_N = 5
HOCKEY = ("NHL",)
FOOTBALL = ("NFL", "NCAAF")
CLOSE = {"hockey": 1, "basketball": 5, "football": 3}          # "close" = decided by this many or fewer
BLOWOUT = {"hockey": 3, "basketball": 15, "football": 14}      # "blowout" = decided by this many or more


def family(league: str) -> str:
    return "hockey" if league in HOCKEY else "football" if league in FOOTBALL else "basketball"


def _sds(league: str):
    import todays_best as TB
    fam = league if league in TB.MARGIN_SD else "INTL"
    return float(TB.MARGIN_SD[fam]), float(TB.TOTAL_SD[fam])


def _seed(key) -> int:
    return zlib.crc32(str(key).encode()) & 0xFFFFFFFF


def simulate(league: str, margin: Optional[float], total: Optional[float], key="", n: int = N_SIMS) -> Optional[Dict]:
    """Simulate one game around the model's projection (margin = home minus away). None without a projection.
    `key` (the game id) fixes the random draw, so a game's numbers don't flicker between reruns."""
    import numpy as np
    if margin is None or total is None or total <= 0:
        return None
    margin, total = float(margin), float(total)
    hm, am = max((total + margin) / 2, 0.05), max((total - margin) / 2, 0.05)
    rng = np.random.default_rng(_seed(f"{league}:{key}:{margin:.2f}:{total:.2f}"))
    fam = family(league)
    if fam == "hockey":
        h, a = rng.poisson(hm, n).astype(float), rng.poisson(am, n).astype(float)
        ot = h == a
        home_ot = rng.random(n) < 0.5
        h = np.where(ot & home_ot, h + 1, h)
        a = np.where(ot & ~home_ot, a + 1, a)
        ot_rate = float(ot.mean())
    else:
        msd, tsd = _sds(league)
        var = (msd ** 2 + tsd ** 2) / 4.0                       # each team's score variance
        rho = (tsd ** 2 - msd ** 2) / (tsd ** 2 + msd ** 2)     # scores move together: totals spread more than margins
        cov = [[var, rho * var], [rho * var, var]]
        draws = rng.multivariate_normal([hm, am], cov, n)
        h, a = draws[:, 0], draws[:, 1]
        ot_rate = None
    d = h - a
    q = lambda x, p: float(np.percentile(x, p))                 # noqa: E731
    return {"n_sims": n, "family": fam,
            "proj_home_score": round(hm, 1), "proj_away_score": round(am, 1),
            "proj_spread": round(margin, 1), "proj_total": round(total, 1),
            "sim_home_win": round(float((d > 0).mean() + 0.5 * (d == 0).mean()), 4),
            "home_range": (q(h, 10), q(h, 90)), "away_range": (q(a, 10), q(a, 90)),
            "total_range": (q(h + a, 10), q(h + a, 90)), "margin_range": (q(d, 10), q(d, 90)),
            "close": round(float((abs(d) <= CLOSE[fam] + (0 if fam == "hockey" else 1e-9)).mean()), 4),
            "blowout": round(float((abs(d) >= BLOWOUT[fam]).mean()), 4),
            "overtime": None if ot_rate is None else round(ot_rate, 4)}


def scoring_context(games: Iterable[Dict], team: str, loose: bool = True, n: int = RECENT_N) -> Optional[Dict]:
    """A team's scoring from the results archive: {"scored": {recent_avg, season_avg}, "allowed": {...}, "games",
    "recent_n"} -- the same four numbers the football labs show. `games` should be this season's, oldest first."""
    import intl_hoops as I
    games = list(games or [])
    # the archive's own name for this team, matched the way the ratings model matches it (college: strict)
    mine = I.find_team({g.get(k) for g in games for k in ("home_team", "away_team") if g.get(k)}, team, loose)
    rows = []
    for g in games:
        hp, ap = I._num(g.get("home_points")), I._num(g.get("away_points"))
        if hp is None or ap is None or mine is None:
            continue
        if g.get("home_team") == mine:
            rows.append((str(g.get("date") or ""), hp, ap))
        elif g.get("away_team") == mine:
            rows.append((str(g.get("date") or ""), ap, hp))
    if not rows:
        return None
    rows.sort(key=lambda r: r[0])
    last = rows[-n:]
    avg = lambda xs: sum(xs) / len(xs)                          # noqa: E731
    return {"games": len(rows), "recent_n": len(last),
            "scored": {"recent_avg": avg([r[1] for r in last]), "season_avg": avg([r[1] for r in rows])},
            "allowed": {"recent_avg": avg([r[2] for r in last]), "season_avg": avg([r[2] for r in rows])}}


def unit(league: str) -> str:
    return "goals" if family(league) == "hockey" else "points"


def range_text(lo: float, hi: float, league: str) -> str:
    return f"{max(lo, 0):.0f}–{hi:.0f}"
