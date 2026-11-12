"""
live_games.py — live game feeds + the live read for each game (Nov 12). The math is live_model.py; the page is
views/54_Live_Games.py.

Live state (score, period, clock):
  * ESPN scoreboards -- NBA, WNBA, college (men), NBL, NHL
  * the EuroLeague's own live feed -- EuroLeague and EuroCup (Header: quarter, time left in it, score)
Pre-game projection: the Game Lab's saved pick for the game (model_store game_picks: model_margin / model_total, saved
before tip-off by the capture jobs).
Live lines: The Odds API keeps in-play games in its odds feed (moneyline, spread, total) -- 3 credits a call per
league, only when the page asks.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Sequence

import intl_hoops as I
import live_model as LM

ESPN_URL = {"NBA": I.ESPN_LEAGUE_URL["NBA"], "WNBA": I.ESPN_LEAGUE_URL["WNBA"], "NHL": I.ESPN_LEAGUE_URL["NHL"],
            "NCAAMB": I.NCAAMB_URL, "NBL": I.NBL_URL}
EL_COMP = {"EUROLEAGUE": "E", "EUROCUP": "U"}
EL_HEADER = "https://live.euroleague.net/api/Header"
ODDS = "https://api.the-odds-api.com/v4/sports/{key}/odds"
LEAGUES = ("NBA", "NCAAMB", "NHL", "WNBA", "EUROLEAGUE", "EUROCUP", "NBL")
TITLE = {"NBA": "NBA", "NCAAMB": "College basketball (men)", "NHL": "NHL", "WNBA": "WNBA",
         "EUROLEAGUE": "EuroLeague", "EUROCUP": "EuroCup", "NBL": "NBL (Australia)"}


def _min(txt) -> Optional[float]:
    """'4:12' / '04:12' -> 4.2 minutes; '34.5' (seconds, final minute) -> 0.575."""
    try:
        s = str(txt).strip()
        if ":" in s:
            mm, ss = s.split(":")[:2]
            return int(mm) + float(ss) / 60
        return float(s) / 60 if s else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- feeds
def espn_games(league: str, day: date, fetch: Callable = I._http) -> List[Dict]:
    params = {"dates": day.strftime("%Y%m%d"), "limit": 500}
    if league == "NCAAMB":
        params["groups"] = 50
    data = fetch(ESPN_URL[league], params) or {}
    out = []
    for ev in data.get("events") or []:
        for c in ev.get("competitions") or []:
            st = c.get("status") or {}
            typ = st.get("type") or {}
            side = {}
            for t in c.get("competitors") or []:
                side[t.get("homeAway")] = ((t.get("team") or {}).get("displayName"), I._num(t.get("score")))
            if "home" not in side or "away" not in side:
                continue
            clock = st.get("clock")
            out.append({"league": league, "id": str(c.get("id") or ev.get("id")), "home": side["home"][0],
                        "away": side["away"][0], "home_score": side["home"][1] or 0.0,
                        "away_score": side["away"][1] or 0.0, "state": typ.get("state") or "pre",
                        "period": int(st.get("period") or 0),
                        "clock_left": None if clock is None else float(clock) / 60,
                        "detail": typ.get("shortDetail") or typ.get("detail") or "",
                        "kickoff": str(c.get("date") or ev.get("date") or ""),
                        "halftime": "half" in str(typ.get("name") or "").lower()})
    return out


def euroleague_games(league: str, day: date, fetch: Callable = I._http, now: Optional[datetime] = None) -> List[Dict]:
    comp = EL_COMP[league]
    code = comp + I.season_of(league, day.isoformat())
    data = fetch(I.EL_URL.format(comp=comp, code=code)) or {}
    now = now or datetime.now(timezone.utc)
    out = []
    for g in data.get("data") or []:
        ko = str(g.get("utcDate") or "")
        try:
            kdt = datetime.fromisoformat(ko.replace("Z", "+00:00"))
        except ValueError:
            continue
        if abs((kdt - now).total_seconds()) > 14 * 3600:
            continue
        loc, road = g.get("local") or {}, g.get("road") or {}
        rec = {"league": league, "id": str(g.get("identifier") or g.get("gameCode")),
               "home": (loc.get("club") or {}).get("name"), "away": (road.get("club") or {}).get("name"),
               "home_score": I._num(loc.get("score")) or 0.0, "away_score": I._num(road.get("score")) or 0.0,
               "state": "post" if g.get("played") else "pre", "period": 0, "clock_left": None,
               "detail": "Final" if g.get("played") else "", "kickoff": ko, "halftime": False}
        if not g.get("played") and kdt <= now:
            h = fetch(EL_HEADER, {"gamecode": g.get("gameCode"), "seasoncode": code}) or {}
            q = str(h.get("Quarter") or "").strip()
            if h.get("Live") and q:
                per = int(q) if q.isdigit() else 5                 # anything past the 4th is overtime
                rec.update(state="in", period=per, clock_left=_min(h.get("RemainingPartialTime")),
                           home_score=I._num(h.get("ScoreA")) or 0.0, away_score=I._num(h.get("ScoreB")) or 0.0,
                           detail=f"Q{per} {h.get('RemainingPartialTime') or ''}".strip() if per <= 4 else "OT")
        out.append(rec)
    return out


def games(league: str, day: date, fetch: Callable = I._http) -> List[Dict]:
    if league in EL_COMP:
        return euroleague_games(league, day, fetch)
    return espn_games(league, day, fetch)


# --------------------------------------------------------------------------- pre-game projections and live lines
def pregame_for(g: Dict, picks: Sequence[Dict]) -> Optional[Dict]:
    """The Game Lab's saved pre-game projection for this game (same teams, kickoff within a day)."""
    best = None
    for p in picks:
        if p.get("model_margin") is None or p.get("model_total") is None:
            continue
        if not (I.same_team(p.get("home"), g["home"]) and I.same_team(p.get("away"), g["away"])):
            continue
        try:
            gap = abs((datetime.fromisoformat(str(p["kickoff"]).replace("Z", "+00:00")) -
                       datetime.fromisoformat(str(g["kickoff"]).replace("Z", "+00:00"))).total_seconds())
        except (KeyError, ValueError):
            gap = 0
        if gap <= 86400 and (best is None or gap < best[0]):
            best = (gap, p)
    return best[1] if best else None


def live_odds(league: str, api_key: str, fetch: Callable = I._http) -> List[Dict]:
    key = (I.LEAGUES.get(league) or {}).get("odds_key")
    if not key or not api_key:
        return []
    return fetch(ODDS.format(key=key), {"apiKey": api_key, "regions": "us", "markets": "h2h,spreads,totals",
                                        "oddsFormat": "american"}) or []


# --------------------------------------------------------------------------- the read for one game
MIN_EDGE = 0.05          # a live line worth a look: model's chance x payout beats the price by 5%+


def read_game(g: Dict, pre: Optional[Dict], market: Optional[Dict] = None) -> Optional[Dict]:
    """Live read + the live lines checked against it. None when there's no pre-game projection or no clock."""
    if not pre or g["state"] == "pre":
        return None
    if g["state"] == "in" and g.get("clock_left") is None:
        return None
    period = g["period"] or 1
    clock = g.get("clock_left") or 0.0
    if g.get("halftime"):
        c = LM.cfg(g["league"])
        period, clock = (c["periods"] // 2) + 1, float(c["minutes"])
    rd = LM.project(g["league"], float(pre["model_margin"]), float(pre["model_total"]), g["home_score"],
                    g["away_score"], period, clock, final=g["state"] == "post")
    out = {"read": rd, "fair_spread": LM.fair_spread(rd), "fair_total": LM.fair_total(rd), "bets": []}
    if not market or g["state"] != "in":
        return out
    bets = []
    hs = market.get("home_spread")
    if hs is not None:
        for side, line, price in (("home", hs, market.get("spread_price")), ("away", -hs, market.get("spread_price"))):
            ch = LM.cover_chance(rd, hs, side)
            team = g["home"] if side == "home" else g["away"]
            bets.append({"bet": f"{team} {line:+g}", "market": "Spread", "chance": ch, "price": price or -110,
                         "edge": LM.edge(ch, price or -110)})
    tl = market.get("total")
    if tl is not None:
        po = LM.over_chance(rd, tl)
        bets.append({"bet": f"Over {tl:g}", "market": "Total", "chance": po, "price": market.get("over_price") or -110,
                     "edge": LM.edge(po, market.get("over_price") or -110)})
        bets.append({"bet": f"Under {tl:g}", "market": "Total", "chance": 1 - po,
                     "price": market.get("under_price") or -110, "edge": LM.edge(1 - po, market.get("under_price") or -110)})
    for side, price in (("home", market.get("best_home")), ("away", market.get("best_away"))):
        if price is None:
            continue
        ch = rd["win_home"] if side == "home" else 1 - rd["win_home"]
        team = g["home"] if side == "home" else g["away"]
        bets.append({"bet": f"{team} to win", "market": "Moneyline", "chance": ch, "price": price,
                     "edge": LM.edge(ch, price)})
    for b in bets:
        e = b["edge"]
        b["signal"] = "🟢 Worth a look" if e is not None and e >= MIN_EDGE else \
            "🟡 Close" if e is not None and e >= 0 else "🔴 Pass"
    out["bets"] = sorted(bets, key=lambda b: -(b["edge"] if b["edge"] is not None else -9))
    return out


def clock_text(g: Dict) -> str:
    if g["state"] == "post":
        return "Final"
    if g["state"] == "pre":
        return "Not started"
    if g.get("halftime"):
        return "Halftime"
    c = LM.cfg(g["league"])
    per = g["period"]
    name = ("H" if c["periods"] == 2 else "P" if c.get("hockey") else "Q") + str(per) if per <= c["periods"] else \
        "OT" if per == c["periods"] + 1 else f"{per - c['periods']}OT"
    cl = g.get("clock_left")
    if cl is None:
        return name
    m, sec = divmod(int(round(cl * 60)), 60)
    return f"{name} {m}:{sec:02d}"
