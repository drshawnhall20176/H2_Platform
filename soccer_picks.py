"""
soccer_picks.py — the Soccer Lab's capture, grading, bet settling and record (Nov 13).

TRACKING ONLY. Backtest (research/soccer_backtest.py, 2023-26, 8 leagues, ~10,000 matches vs Pinnacle):
  * the goals model alone (soccer_model.py) is LESS accurate than the closing price in every league (1X2 log-loss
    0.966 vs 0.946 EPL ...) and its value picks lost 6-37% on match result, ~0 to -13% on Asian handicap;
  * a US-style book's price beating Pinnacle's no-vig line (research/soccer_value_backtest.py) beat the closing line
    by +2 to +16% but realized profit was about break-even over 4 seasons.
So every pick here is ⛔ Pass until the live record says otherwise. What the page adds: the model's read, the sharp
fair line, the best US price, and a 📈 flag when that price beats the sharp line by VALUE_EDGE -- tracked.

Records go to game_picks under the league key (SOCCER_EPL ...); results come from ESPN (soccer_data).
"""
from __future__ import annotations

import math
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Sequence

import intl_hoops as I
import soccer_data as D
import soccer_model as M

VALUE_EDGE = 0.02          # a US price this much above the sharp fair line gets the 📈 flag (tracked)
HISTORY_DAYS = 500
PASS = "⛔ Pass"
WHY = "tracking only: the backtest found no proven edge in soccer yet"


def _dec(a) -> Optional[float]:
    return D._dec(a)


ALIASES = {"los angeles fc": "LAFC", "lafc": "Los Angeles FC", "inter miami cf": "Inter Miami",
           "new york red bulls": "Red Bull New York", "red bull new york": "New York Red Bulls",
           "psg": "Paris Saint-Germain", "paris saint germain": "Paris Saint-Germain"}


def team(names, name: str) -> Optional[str]:
    """The ratings' (ESPN) name for an Odds API team name."""
    names = list(names)
    if name in names:
        return name
    alt = ALIASES.get(str(name).lower())
    if alt and alt in names:
        return alt
    return I.find_team(names, name) or I.find_team(names, name, loose=True)


def ratings(league: str, today: date, db_path: Optional[str] = None) -> Dict:
    """Domestic leagues fit on their own results; the European cups on every league's results together (that's how
    a Bundesliga side and a Ligue 1 side get on one scale)."""
    import model_store as MS
    since = (today - timedelta(days=HISTORY_DAYS)).isoformat()
    keys = list(D.LEAGUES) if D.LEAGUES[league].get("europe") else [league]
    rows = [g for k in keys for g in MS.load_results(k, since=since, db_path=db_path)]
    return M.fit(D.matches(rows), datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc))


def build(league: str, r: Dict, events: Sequence[Dict], now: datetime) -> List[Dict]:
    recs = []
    for ev in events:
        if str(ev.get("commence_time")) <= now.isoformat()[:19]:
            continue
        hn, an = ev.get("home_team"), ev.get("away_team")
        px = D.prices(ev, hn, an)
        if px.get("best_home") is None and px.get("mkt_home") is None:
            continue
        h, a = team(r["attack"], hn), team(r["attack"], an)
        rd = M.read(r, h, a) if h and a else None
        rec = {"sport": league, "game_id": str(ev.get("id")), "kickoff": ev.get("commence_time"), "home": hn,
               "away": an, "rated": bool(rd), "line": px.get("home_spread"), "edge": None, "use": PASS, "why": WHY}
        rec.update(px)
        if rd:
            g = rd.pop("grid")
            rec.update({k: float(v) for k, v in rd.items()})
            rec["model_p"] = rec["p_home"]                       # calibration rows (home win vs not)
            if px.get("line_total") is not None:
                rec["p_over"] = round(M.total_outcome(g, px["line_total"])["win"], 4)
            if px.get("home_spread") is not None:
                o = M.handicap_outcome(g, px["home_spread"], "home")
                rec["p_ah_home"] = round(o["win"] / max(o["win"] + o["loss"], 1e-9), 4)
        rec["value"] = value_flags(rec)
        rec["edge"] = max((v["ev"] for v in rec["value"]), default=None)
        recs.append(rec)
    return recs


def value_flags(rec: Dict) -> List[Dict]:
    """Outcomes whose best US price beats the sharp no-vig chance by VALUE_EDGE (tracked, not tested yet)."""
    out = []
    for side, mk, price, book in (("home", "mkt_home", "best_home", "book_home"),
                                  ("draw", "mkt_draw", "best_draw", "book_draw"),
                                  ("away", "mkt_away", "best_away", "book_away")):
        p, d = rec.get(mk), _dec(rec.get(price))
        if p and d and p * d - 1 >= VALUE_EDGE:
            out.append({"market": "Moneyline", "side": side, "price": rec[price], "book": rec.get(book),
                        "fair": p, "ev": round(p * d - 1, 4)})
    if rec.get("mkt_over") is not None:
        for side, p in (("over", rec["mkt_over"]), ("under", 1 - rec["mkt_over"])):
            d = _dec(rec.get(f"{side}_price"))
            if d and p * d - 1 >= VALUE_EDGE:
                out.append({"market": "Total", "side": side, "price": rec[f"{side}_price"],
                            "book": rec.get(f"{side}_book"), "fair": p, "ev": round(p * d - 1, 4),
                            "line": rec["line_total"]})
    if rec.get("mkt_ah_home") is not None:
        for side, p in (("home", rec["mkt_ah_home"]), ("away", 1 - rec["mkt_ah_home"])):
            d = _dec(rec.get(f"spread_price_{side}"))
            if d and p * d - 1 >= VALUE_EDGE:
                out.append({"market": "Spread", "side": side, "price": rec[f"spread_price_{side}"],
                            "book": rec.get(f"spread_book_{side}"), "fair": p, "ev": round(p * d - 1, 4),
                            "line": rec["home_spread"] if side == "home" else -rec["home_spread"]})
    return out


def grade(league: str, results: Sequence[Dict], db_path: Optional[str] = None) -> int:
    import model_store as MS
    n = 0
    for p in MS.load_game_picks(league, ungraded=True, db_path=db_path):
        day = str(p.get("kickoff"))[:10]
        for g in results:
            if abs((date.fromisoformat(g["date"]) - date.fromisoformat(day)).days) > 1:
                continue
            if team([g["home_team"]], p["home"]) and team([g["away_team"]], p["away"]):
                hp, ap = g["home_points"], g["away_points"]
            elif team([g["home_team"]], p["away"]) and team([g["away_team"]], p["home"]):
                hp, ap = g["away_points"], g["home_points"]
            else:
                continue
            res = "home" if hp > ap else ("away" if ap > hp else "draw")
            if MS.grade_game_pick(league, p["game_id"], hp, ap, res, db_path=db_path):
                n += 1
            break
    return n


# --------------------------------------------------------------------------- logging + settling bets
TAG = "gl"


def bet_fields(p: Dict, market: str, side: str, line: Optional[float], odds: float, stake: float, real: bool,
               model_prob: Optional[float] = None) -> Dict:
    import betlog as B
    team_ = {"home": p["home"], "away": p["away"]}.get(side)
    label = team_ or ("Draw" if side == "draw" else side.title())
    return {"slate_date": str(p.get("kickoff"))[:10] if p.get("kickoff") else None, "sport": "SOCCER",
            "game": f"{p['away']} @ {p['home']}", "player": team_ or ("Draw" if side == "draw" else "Match total"),
            "market": market, "side": label, "line": line, "entry_odds": float(odds), "entry_odds_source": "manual",
            "model_prob": model_prob, "stake": float(stake), "is_real_bet": bool(real),
            "category": B.default_category("SOCCER", from_model=True), "notes": f"{TAG}:{p['sport']}:{p['game_id']}"}


def bet_result(bet: Dict, p: Dict) -> Optional[str]:
    """win / loss / push for a logged soccer bet; None until graded or for a quarter line (settle those by hand --
    the Bet Log has no half-win)."""
    fh, fa, res = p.get("final_home"), p.get("final_away"), p.get("result")
    if fh is None or fa is None or res is None:
        return None
    mk, side = bet.get("market"), str(bet.get("side"))
    line = bet.get("line")
    if line is not None and abs(float(line) * 2 - round(float(line) * 2)) > 1e-9:
        return None
    if mk == "Moneyline":
        pick = "draw" if side.lower() == "draw" else ("home" if side == p["home"] else "away")
        return "win" if pick == res else "loss"
    if mk == "Total":
        d = fh + fa - float(line)
        return "push" if d == 0 else ("win" if (d > 0) == (side.lower() == "over") else "loss")
    if mk == "Spread":
        d = (fh - fa if side == p["home"] else fa - fh) + float(line)
        return "push" if d == 0 else ("win" if d > 0 else "loss")
    return None


def settle_logged(league: str, db_path: Optional[str] = None) -> int:
    import betlog as B
    import model_store as MS
    graded = {p["game_id"]: p for p in MS.load_game_picks(league, db_path=db_path) if p.get("result")}
    n = 0
    for b in [x for x in B.list_bets() if not x.get("result")]:
        link = next((t.strip() for t in str(b.get("notes") or "").split(",")
                     if t.strip().startswith(f"{TAG}:{league}:")), None)
        if not link:
            continue
        p = graded.get(link.split(":", 2)[2])
        r = bet_result(b, p) if p else None
        if r:
            B.update_bet(int(b["id"]), result=r)
            n += 1
    return n


# --------------------------------------------------------------------------- the record
def record(picks: Sequence[Dict]) -> Dict:
    """How the model's favourite and the 📈 flags have done on graded matches."""
    g = [p for p in picks if p.get("result") in ("home", "draw", "away")]
    fav_n = fav_w = 0
    said = 0.0
    for p in g:
        if p.get("p_home") is None:
            continue
        probs = {"home": p["p_home"], "draw": p["p_draw"], "away": p["p_away"]}
        f = max(probs, key=probs.get)
        fav_n += 1
        fav_w += f == p["result"]
        said += probs[f]
    vn = vw = 0
    units = 0.0
    for p in g:
        for v in p.get("value") or []:
            if v["market"] != "Moneyline":
                continue
            vn += 1
            won = v["side"] == p["result"]
            vw += won
            units += (_dec(v["price"]) - 1) if won else -1
    return {"graded": len(g), "fav": (fav_w, fav_n), "fav_said": (said / fav_n) if fav_n else None,
            "value": (vw, vn), "value_units": round(units, 2)}


def capture(league: str, api_key: str, fetch: Callable = D._http, now: Optional[datetime] = None,
            db_path: Optional[str] = None) -> Dict:
    import model_store as MS
    now = now or datetime.now(timezone.utc)
    added = D.refresh(league, now.date(), fetch, db_path)
    r = ratings(league, now.date(), db_path)
    evs = D.fetch_odds(league, api_key, fetch) if api_key else []
    recs = build(league, r, evs, now)
    saved = MS.save_game_picks(recs, db_path=db_path)
    graded = grade(league, MS.load_results(league, since=(now.date() - timedelta(days=10)).isoformat(),
                                           db_path=db_path), db_path)
    try:
        settled = settle_logged(league, db_path)
    except Exception:                                           # noqa: BLE001
        settled = 0
    try:
        import soccer_props as SPR
        settled += SPR.settle_props(league, db_path, fetch)
    except Exception:                                           # noqa: BLE001
        pass
    return {"archive_added": added, "teams_rated": len(r["attack"]), "events": len(evs), "priced": len(recs),
            "flags": sum(len(x["value"]) for x in recs), "saved": saved, "graded": graded, "bets_settled": settled}


def main(argv=None) -> int:
    api = os.environ.get("ODDS_API_KEY", "")
    which = (argv or sys.argv[1:] or [",".join(D.LEAGUES)])[0].split(",")
    # the European cups are rated on every league's results: refresh the domestic leagues first
    which = sorted(which, key=lambda k: bool(D.LEAGUES.get(k, {}).get("europe")))
    for s in which:
        if s not in D.LEAGUES:
            continue
        try:
            out = capture(s, api)
        except Exception as exc:                                # noqa: BLE001 -- one league never stops the rest
            out = {"error": f"{type(exc).__name__}: {exc}"}
        print(s, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
