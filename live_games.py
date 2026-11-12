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
            "NCAAMB": I.NCAAMB_URL, "NBL": I.NBL_URL,
            "NFL": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
            "NCAAF": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"}
ESPN_PATH = {"NBA": "basketball/nba", "WNBA": "basketball/wnba", "NCAAMB": "basketball/mens-college-basketball",
             "NBL": "basketball/nbl", "NHL": "hockey/nhl", "NFL": "football/nfl",
             "NCAAF": "football/college-football"}
EL_COMP = {"EUROLEAGUE": "E", "EUROCUP": "U"}
EL_HEADER = "https://live.euroleague.net/api/Header"
ODDS = "https://api.the-odds-api.com/v4/sports/{key}/odds"
LEAGUES = ("NBA", "NCAAMB", "NHL", "WNBA", "EUROLEAGUE", "EUROCUP", "NBL", "NFL", "NCAAF")
TITLE = {"NBA": "NBA", "NCAAMB": "College basketball (men)", "NHL": "NHL", "WNBA": "WNBA",
         "EUROLEAGUE": "EuroLeague", "EUROCUP": "EuroCup", "NBL": "NBL (Australia)", "NFL": "NFL",
         "NCAAF": "College football"}
ODDS_KEY = {"NFL": "americanfootball_nfl", "NCAAF": "americanfootball_ncaaf"}


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
    if league == "NCAAF":
        params["groups"] = 80                                   # FBS
    data = fetch(ESPN_URL[league], params) or {}
    out = []
    for ev in data.get("events") or []:
        for c in ev.get("competitions") or []:
            st = c.get("status") or {}
            typ = st.get("type") or {}
            side, ids = {}, {}
            for t in c.get("competitors") or []:
                tm = t.get("team") or {}
                side[t.get("homeAway")] = (tm.get("displayName"), I._num(t.get("score")))
                ids[t.get("homeAway")] = (str(t.get("id") or tm.get("id") or ""), str(tm.get("abbreviation") or ""))
            if "home" not in side or "away" not in side:
                continue
            clock = st.get("clock")
            poss, ytg = _possession(c.get("situation"), ids)
            out.append({"league": league, "id": str(c.get("id") or ev.get("id")), "home": side["home"][0],
                        "away": side["away"][0], "home_score": side["home"][1] or 0.0,
                        "away_score": side["away"][1] or 0.0, "state": typ.get("state") or "pre",
                        "period": int(st.get("period") or 0),
                        "clock_left": None if clock is None else float(clock) / 60,
                        "detail": typ.get("shortDetail") or typ.get("detail") or "",
                        "kickoff": str(c.get("date") or ev.get("date") or ""),
                        "halftime": "half" in str(typ.get("name") or "").lower(),
                        "event_id": str(ev.get("id") or ""), "possession": poss, "yards_to_go": ytg,
                        "down_text": str((c.get("situation") or {}).get("downDistanceText") or "")})
    return out


def _possession(sit: Optional[Dict], ids: Dict) -> tuple:
    """Football: ('home' / 'away' / None, yards to the end zone) from ESPN's live situation ("KC 35" = at KC's 35)."""
    if not isinstance(sit, dict) or not sit.get("possession"):
        return None, None
    pid = str(sit.get("possession"))
    who = next((k for k, v in ids.items() if v[0] == pid), None)
    if who is None:
        return None, None
    txt = str(sit.get("possessionText") or "").strip()
    parts = txt.split()
    try:
        yl = float(parts[-1])
    except (IndexError, ValueError):
        return who, None
    own = ids[who][1]
    if len(parts) >= 2 and parts[0] == own:
        return who, 100 - yl                                    # on their own side
    return who, yl


def espn_pregame(league: str, event_id: str, fetch: Callable = I._http) -> Optional[Dict]:
    """The books' pre-game line from ESPN's pick center (spread = the home team's spread, total = over/under) -- the
    fallback pre-game projection when the Game Lab has none (and the one football uses: on past games the books'
    line beat our football models)."""
    path = ESPN_PATH.get(league)
    if not path or not event_id:
        return None
    s = fetch(f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary", {"event": event_id}) or {}
    for pc in s.get("pickcenter") or []:
        sp, ou = I._num(pc.get("spread")), I._num(pc.get("overUnder"))
        if sp is not None and ou is not None:
            return {"model_margin": -sp, "model_total": ou, "source": "books",
                    "provider": (pc.get("provider") or {}).get("name")}
    return None


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
    key = (I.LEAGUES.get(league) or {}).get("odds_key") or ODDS_KEY.get(league)
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
                    g["away_score"], period, clock, final=g["state"] == "post", possession=g.get("possession"),
                    yards_to_go=g.get("yards_to_go"))
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


# --------------------------------------------------------------------------- tennis (Nov 12)
def tennis_matches(day: date, fetch: Callable = None) -> List[Dict]:
    """Singles matches on ESPN's ATP and WTA scoreboards: players, games in each set, state."""
    import tennis_model as T
    fetch = fetch or T._http
    out = []
    for tour in T.TOURS:
        data = fetch(T.ESPN.format(tour=tour), {"dates": day.strftime("%Y%m%d")}) or {}
        for ev in data.get("events") or []:
            tname = ev.get("name") or ev.get("shortName") or ""
            for g in ev.get("groupings") or []:
                if "singles" not in ((g.get("grouping") or {}).get("displayName") or "").lower():
                    continue
                for c in g.get("competitions") or []:
                    cps = sorted(c.get("competitors") or [], key=lambda x: x.get("order") or 0)
                    if len(cps) != 2:
                        continue
                    names = [((cp.get("athlete") or {}).get("displayName") or "") for cp in cps]
                    if not all(names):
                        continue
                    st = (c.get("status") or {}).get("type") or {}
                    sets = [[int(I._num(ls.get("value")) or 0) for ls in cp.get("linescores") or []] for cp in cps]
                    n = min(len(sets[0]), len(sets[1]))
                    out.append({"league": "TENNIS", "id": f"{tour}-{c.get('id')}", "tour": tour, "tournament": tname,
                                "round": (c.get("round") or {}).get("displayName"), "best_of": T.best_of(tname, tour),
                                "p1": names[0], "p2": names[1], "sets1": sets[0][:n], "sets2": sets[1][:n],
                                "state": st.get("state") or "pre", "detail": st.get("shortDetail") or "",
                                "kickoff": str(c.get("date") or ""),
                                "winner": 1 if cps[0].get("winner") else 2 if cps[1].get("winner") else None,
                                # Nov 12: who's serving (ESPN's "possession" flag) and each player's flag
                                "server": 1 if cps[0].get("possession") else 2 if cps[1].get("possession") else None,
                                # Nov 12: ESPN still marks a "winner" when a match ends by retirement / walkover, but
                                # the books void those -- so is the platform's own grading (intl_picks)
                                "void": _stands(_void_reason(st), sets[0][:n], sets[1][:n]),
                                "retired": _void_reason(st) == "retired",
                                "flags": [((cp.get("athlete") or {}).get("flag") or {}).get("href") for cp in cps],
                                "tiebreaks": [[ls.get("tiebreak") for ls in cp.get("linescores") or []]
                                              for cp in cps]})
    return out


def _stands(void: Optional[str], s1, s2) -> Optional[str]:
    """Nov 12: a retirement after a full set stands (the books pay the player who advances); earlier, it's void."""
    import tennis_model as T
    return None if void == "retired" and T.full_sets(s1, s2) >= 1 else void


def _void_reason(status_type: Dict) -> Optional[str]:
    name = str(status_type.get("name") or "").upper() + " " + str(status_type.get("detail") or "").upper()
    for key, label in (("RETIRED", "retired"), ("WALKOVER", "walkover"), ("DEFAULT", "default"),
                       ("ABANDON", "abandoned"), ("CANCEL", "canceled"), ("POSTPON", "postponed")):
        if key in name:
            return label
    return None


def trend(now: Optional[float], start: Optional[float]) -> Dict:
    """Up / down since the start of the match or game: arrow, colour and the change in points."""
    if now is None or start is None:
        return {"arrow": "", "color": None, "delta": None}
    d = now - start
    if abs(d) < 0.02:
        return {"arrow": "▬", "color": "#9aa4b2", "delta": d}
    return {"arrow": "▲" if d > 0 else "▼", "color": "#2ecc71" if d > 0 else "#e74c3c", "delta": d}


def tennis_pregame(m: Dict, picks: Sequence[Dict]) -> Optional[float]:
    """The saved pre-match chance for player 1 (the Tennis Lab's pick for this match), oriented to ESPN's order."""
    for p in picks:
        if p.get("model_p") is None:
            continue
        if I.same_team(p.get("home"), m["p1"]) and I.same_team(p.get("away"), m["p2"]):
            return float(p["model_p"])
        if I.same_team(p.get("home"), m["p2"]) and I.same_team(p.get("away"), m["p1"]):
            return 1 - float(p["model_p"])
    return None


def tennis_live_odds(api_key: str, fetch: Callable = I._http) -> List[Dict]:
    """In-play and upcoming tennis prices from every active ATP / WTA tournament key (2 credits a key)."""
    if not api_key:
        return []
    import intl_picks as IP
    out = []
    for key in IP.tennis_keys(api_key, fetch):
        out += fetch(ODDS.format(key=key), {"apiKey": api_key, "regions": "us", "markets": "h2h,totals",
                                            "oddsFormat": "american"}) or []
    return out


def read_tennis(m: Dict, p1: Optional[float], market: Optional[Dict] = None) -> Optional[Dict]:
    """Live read for one match + its live lines (moneyline both ways, total games) checked against it."""
    if p1 is None or m["state"] == "pre":
        return None
    rd = LM.tennis(p1, m["tour"], m["best_of"], m["sets1"], m["sets2"], final=m["state"] == "post",
                   a_serving=None if not m.get("server") else m["server"] == 1)
    out = {"read": rd, "bets": []}
    if not market or m["state"] != "in":
        return out
    bets = []
    for who, ch, price in ((m["p1"], rd["win_a"], market.get("p1_price")), (m["p2"], 1 - rd["win_a"], market.get("p2_price"))):
        if price is not None:
            bets.append({"bet": f"{who} to win", "market": "Moneyline", "chance": ch, "price": price,
                         "edge": LM.edge(ch, price)})
    tl = market.get("total")
    if tl is not None:
        sd = max(1.5, 0.45 * max(rd["total_games"] - rd["games_played"], 0.0) ** 0.5 * 2)
        po = 1 - LM._phi((tl - rd["total_games"]) / sd) if rd["total_games"] > rd["games_played"] else \
            (1.0 if rd["games_played"] > tl else 0.0)
        for side, ch, price in (("Over", po, market.get("over_price")), ("Under", 1 - po, market.get("under_price"))):
            bets.append({"bet": f"{side} {tl:g} games", "market": "Total games", "chance": ch, "price": price or -110,
                         "edge": LM.edge(ch, price or -110)})
    for b in bets:
        e = b["edge"]
        b["signal"] = "🟢 Worth a look" if e is not None and e >= MIN_EDGE else \
            "🟡 Close" if e is not None and e >= 0 else "🔴 Pass"
    out["bets"] = sorted(bets, key=lambda b: -(b["edge"] if b["edge"] is not None else -9))
    return out


def tennis_market(m: Dict, events: Sequence[Dict]) -> Optional[Dict]:
    """This match's live prices, oriented to ESPN's player order."""
    import intl_picks as IP
    for ev in events or []:
        h, a = ev.get("home_team"), ev.get("away_team")
        if I.same_team(h, m["p1"]) and I.same_team(a, m["p2"]):
            mk = IP.market(ev, h, a)
            return {"p1_price": mk.get("best_home"), "p2_price": mk.get("best_away"), "total": mk.get("total"),
                    "over_price": mk.get("over_price"), "under_price": mk.get("under_price")}
        if I.same_team(h, m["p2"]) and I.same_team(a, m["p1"]):
            mk = IP.market(ev, h, a)
            return {"p1_price": mk.get("best_away"), "p2_price": mk.get("best_home"), "total": mk.get("total"),
                    "over_price": mk.get("over_price"), "under_price": mk.get("under_price")}
    return None


def set_text(m: Dict) -> str:
    return "  ".join(f"{a}-{b}" for a, b in zip(m["sets1"], m["sets2"])) or "—"


# --------------------------------------------------------------------------- how the pre-game read did (Nov 12)
def grade_pick(fav_is_first: Optional[bool], first_won: Optional[bool]) -> str:
    if fav_is_first is None or first_won is None:
        return "—"
    return "✅ Win" if fav_is_first == first_won else "❌ Loss"


def tennis_result(m: Dict, p1: Optional[float]) -> Dict:
    """The model's pre-match pick for a finished match and whether it won (retirements / walkovers: void)."""
    import tennis_model as T
    if m.get("void") == "retired" and m.get("winner") and T.full_sets(m.get("sets1"), m.get("sets2")) >= 1:
        m = dict(m, void=None)                                   # Nov 12: a full set played -- the books stand it
    if m.get("void"):
        pick = "—" if p1 is None else (m["p1"] if p1 >= 0.5 else m["p2"])
        return {"pick": pick, "chance": None if p1 is None else max(p1, 1 - p1),
                "result": f"⚪ Void ({m['void']})"}
    if p1 is None or not m.get("winner"):
        return {"pick": "—", "chance": None, "result": "—"}
    fav1 = p1 >= 0.5
    return {"pick": m["p1"] if fav1 else m["p2"], "chance": p1 if fav1 else 1 - p1,
            "result": grade_pick(fav1, m["winner"] == 1)}


def game_result(g: Dict, pre: Optional[Dict]) -> Dict:
    """The pre-game pick to win (Game Lab, or the books' favourite for football) and whether it won."""
    if not pre or g["home_score"] == g["away_score"]:
        return {"pick": "—", "chance": None, "result": "—"}
    m = float(pre["model_margin"])
    if abs(m) < 1e-9:
        return {"pick": "—", "chance": None, "result": "—"}
    rd = LM.project(g["league"], m, float(pre["model_total"]), 0, 0, 1, LM.cfg(g["league"])["minutes"])
    home_fav = m > 0
    return {"pick": g["home"] if home_fav else g["away"],
            "chance": rd["win_home"] if home_fav else 1 - rd["win_home"],
            "result": grade_pick(home_fav, g["home_score"] > g["away_score"])}


def record(results: Sequence[Dict]) -> str:
    w = sum(r["result"].startswith("✅") for r in results)
    lo = sum(r["result"].startswith("❌") for r in results)
    return f"{w}–{lo}" if w + lo else ""
