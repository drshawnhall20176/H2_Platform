"""
soccer_live.py — live soccer reads for Live Games (Nov 13).

Owner: activate the live option for soccer.

Pre-match, each side's expected goals come from the sharp line: the (home, away) goal rates whose score grid
reproduces Pinnacle's no-vig 1X2 (and its over/under when we have it) -- the market knows more than the goals model,
which lost to it in the backtest. Without a sharp line, the goals model's own xG.
Live, the rates scale with the time left (ESPN's match clock; ~4 minutes of stoppage assumed per half; a red card cuts
that side's rate by RED_CUT and lifts the other's by RED_BOOST), and the score so far is added on: who wins from here,
the draw, over/under the main total, and the next goal.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

import soccer_data as D
import soccer_model as M

MATCH_MIN = 94.0          # 90 + typical stoppage
RED_CUT = 0.67            # a side down to ten scores about a third less ...
RED_BOOST = 1.25          # ... and the other side about a quarter more
_GRID = [round(0.2 + 0.05 * i, 2) for i in range(70)]       # goal rates 0.2 .. 3.65


def rates_from_market(p_home: float, p_draw: float, p_away: float, p_over: Optional[float] = None,
                      line: Optional[float] = None) -> tuple:
    """(home, away) goal rates whose grid best matches the market's 1X2 (and over/under)."""
    best, err = (1.4, 1.1), 9.0
    for lh in _GRID:
        for la in _GRID:
            g = M.grid(lh, la)
            h, d, a = M.one_x_two(g)
            e = (h - p_home) ** 2 + (d - p_draw) ** 2 + (a - p_away) ** 2
            if p_over is not None and line is not None:
                e += (M.total_outcome(g, line)["win"] - p_over) ** 2
            if e < err:
                best, err = (lh, la), e
    return best


def pregame_rates(rec: Dict) -> Optional[tuple]:
    if rec.get("mkt_home") is not None:
        return rates_from_market(rec["mkt_home"], rec["mkt_draw"], rec["mkt_away"], rec.get("mkt_over"),
                                 rec.get("line_total"))
    if rec.get("xg_home") is not None:
        return float(rec["xg_home"]), float(rec["xg_away"])
    return None


def parse_live(data: Optional[Dict], league: str) -> List[Dict]:
    """ESPN scoreboard -> every match today: state pre / in / post, minute, score, red cards."""
    out = []
    for e in (data or {}).get("events") or []:
        st = (e.get("status") or {})
        typ = st.get("type") or {}
        comp = (e.get("competitions") or [{}])[0]
        cs = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        h, a = cs.get("home"), cs.get("away")
        if not h or not a:
            continue
        reds = {"home": 0, "away": 0}
        for det in comp.get("details") or []:
            if det.get("redCard"):
                tid = (det.get("team") or {}).get("id")
                side = "home" if tid == (h.get("team") or {}).get("id") else "away"
                reds[side] += 1
        try:
            clock = float(st.get("clock") or 0) / 60.0
        except (TypeError, ValueError):
            clock = 0.0
        minute = _minute(st.get("displayClock"), clock, typ.get("name"))
        out.append({"id": str(e.get("id")), "league": league, "kickoff": e.get("date"),
                    "state": typ.get("state"), "status": typ.get("name"), "detail": typ.get("shortDetail") or "",
                    "home": (h.get("team") or {}).get("displayName"), "away": (a.get("team") or {}).get("displayName"),
                    "home_score": _int(h.get("score")), "away_score": _int(a.get("score")), "minute": minute,
                    "red_home": reds["home"], "red_away": reds["away"]})
    return out


def _int(x) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def _minute(display: Optional[str], clock_min: float, status: Optional[str]) -> float:
    if status == "STATUS_HALFTIME":
        return 45.0
    txt = str(display or "").replace("'", "")
    try:
        if "+" in txt:
            a, b = txt.split("+", 1)
            return float(a) + float(b)
        return float(txt)
    except ValueError:
        return clock_min


def games(league: str, day: date, fetch: Callable = D._http) -> List[Dict]:
    return parse_live(fetch(D.ESPN.format(slug=D.LEAGUES[league]["slug"]), {"dates": day.strftime("%Y%m%d")}), league)


def remaining(minute: float) -> float:
    """Share of the match's goals still to come."""
    if minute <= 45:
        left = MATCH_MIN - minute
    elif minute <= 48:                                           # first-half stoppage / half time
        left = MATCH_MIN / 2
    else:
        left = MATCH_MIN - (minute + 2)                         # second half (+2 for the first half's stoppage)
    return max(0.01, min(1.0, left / MATCH_MIN))


def read(g: Dict, pre: tuple, line: Optional[float] = None) -> Dict:
    """Win / draw / win from here, the projected score, over/under and who scores next."""
    r = remaining(g.get("minute") or 0)
    lh, la = pre[0] * r, pre[1] * r
    if g.get("red_home"):
        lh, la = lh * RED_CUT ** g["red_home"], la * RED_BOOST ** g["red_home"]
    if g.get("red_away"):
        la, lh = la * RED_CUT ** g["red_away"], lh * RED_BOOST ** g["red_away"]
    rest = M.grid(lh, la, rho=0.0)                               # no low-score correction for a partial match
    hs, as_ = g.get("home_score") or 0, g.get("away_score") or 0
    n = rest.shape[0]
    i, j = np.indices(rest.shape)
    fh, fa = i + hs, j + as_
    p_home = float(rest[fh > fa].sum())
    p_draw = float(rest[fh == fa].sum())
    out = {"p_home": p_home, "p_draw": p_draw, "p_away": 1 - p_home - p_draw,
           "proj_home": hs + lh, "proj_away": as_ + la, "left": r,
           "next_home": lh / (lh + la) * (1 - math.exp(-(lh + la))) if lh + la > 0 else 0.0,
           "no_more": math.exp(-(lh + la))}
    out["next_away"] = 1 - out["next_home"] - out["no_more"]
    if line is not None:
        tot = fh + fa
        parts = M._half_lines(line)
        over = sum(float(rest[tot > L].sum()) for L in parts) / len(parts)
        push = sum(float(rest[tot == L].sum()) for L in parts) / len(parts)
        out.update(line=line, p_over=over, p_push=push)
    return out


def pregame_for(g: Dict, picks: Sequence[Dict]) -> Optional[Dict]:
    """The Soccer Lab's saved record for this match (same day, same teams)."""
    import soccer_picks as SP
    day = str(g.get("kickoff"))[:10]
    for p in picks:
        if abs((_d(str(p.get("kickoff"))[:10]) - _d(day)).days) > 1:
            continue
        if SP.team([g["home"]], p["home"]) and SP.team([g["away"]], p["away"]):
            return p
    return None


def _d(s):
    return date.fromisoformat(s)


def fair(p: float) -> str:
    if p <= 0.005:
        return "—"
    d = 1 / p
    a = M.to_american(d)
    return f"{a:+d}" if a is not None else "—"
