"""
todays_best.py — the day's top-tagged picks across every sport, for the Home page's "Today's best" panel (Nov 6).

Two sources, neither of which spends extra Odds API credits:
  player props   saved whenever a Best Bets board is built (best_bets_data.load_generic_best_bets_board calls
                 save_props); Home's Refresh button builds the boards that haven't been built yet today
  game lines,    already saved by their capture jobs (model_store game_picks); tagged here with the SAME functions
  intl, tennis   their pages use (intl_picks.hoops_use / tennis_use), so Home never disagrees with the page

Only playable tags make the list -- 🔒 Most probable, 🎟️ Parlay + Single, 🎟️ Parlay leg, 🎯 Single only -- ranked
locks first, then by tag, then by chance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

import props_engine as PE

KEY = "todays_best:{sport}:{date}"
TOP_PER_SPORT = 40
PLAYABLE = (PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE)
RANK = {PE.USE_BOTH: 1, PE.USE_PARLAY: 2, PE.USE_SINGLE: 3}
GAME_LEAGUES = ("NCAAMB", "NBA", "NHL")          # Game Labs (game_picks rows tagged by intl_picks.hoops_use)


def _et_date(iso) -> Optional[str]:
    import pytz
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(pytz.timezone("US/Eastern")).date().isoformat()
    except (TypeError, ValueError):
        return None


def _et_time(iso) -> str:
    import pytz
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(pytz.timezone("US/Eastern")).strftime("%I:%M %p").lstrip("0")
    except (TypeError, ValueError):
        return "TBD"


# --------------------------------------------------------------------------- player props
def props_rows(sport: str, plays) -> List[Dict]:
    out = []
    for p in plays or []:
        lock = bool(PE.most_probable(p.get("ModelProb"), p.get("Cushion"), p.get("Gap")))
        if p.get("Use") not in PLAYABLE and not lock:
            continue
        if p.get("Use") == PE.USE_PASS:
            continue
        line = p.get("Line")
        out.append({"sport": sport, "kind": "Prop", "time": p.get("Time") or "",
                    "pick": f"{p.get('Player')} {p.get('Market')} {p.get('Side')}" + ("" if line is None else f" {line:g}"),
                    "game": p.get("Game") or "", "price": p.get("RealPrice"), "book": p.get("RealPriceBook") or "",
                    "chance": p.get("ModelProb"), "use": p.get("Use") or "", "lock": lock, "page": "Best Bets"})
    out.sort(key=_order)
    return out[:TOP_PER_SPORT]


def save_props(sport: str, date_str: str, plays, meta=None) -> None:
    """Called when a Best Bets board is built: keep its top-tagged picks for the Home panel."""
    try:
        import model_store as MS
        import sports
        when = {m.get("label"): sports.game_dt(m.get("game_date")) for m in (meta or [])}
        timed = []
        for p in plays or []:
            dt = when.get(p.get("Game"))
            timed.append(dict(p, Time=p.get("Time") or (dt.strftime("%I:%M %p").lstrip("0") if dt else "")))
        MS.save_setting(KEY.format(sport=sport, date=date_str),
                        {"at": datetime.now(timezone.utc).isoformat(), "rows": props_rows(sport, timed)})
    except Exception:                                           # noqa: BLE001 -- a bonus, never a failure
        pass


def load_props(sport: str, date_str: str) -> Optional[Dict]:
    try:
        import model_store as MS
        return MS.get_setting(KEY.format(sport=sport, date=date_str), None)
    except Exception:                                           # noqa: BLE001
        return None


# --------------------------------------------------------------------------- game lines, international, tennis
def game_rows(date_str: str, leagues=None) -> List[Dict]:
    import intl_hoops as H
    import intl_picks as IP
    import model_store as MS
    leagues = list(leagues) if leagues is not None else list(GAME_LEAGUES) + [k for k in H.LEAGUES if k not in GAME_LEAGUES]
    out = []
    for lg in leagues:
        try:
            recs = MS.load_game_picks(lg, ungraded=True)
        except Exception:                                       # noqa: BLE001
            continue
        for p in recs:
            if _et_date(p.get("kickoff")) != date_str:
                continue
            t = IP.hoops_use(lg, p)
            if t.get("use") not in PLAYABLE:
                continue
            if p.get("ml_pick"):
                pick = f"{p['home'] if p['ml_pick'] == 'home' else p['away']} moneyline"
            elif p.get("home_spread") is not None and p.get("edge") is not None:
                pick = (f"{p['home']} {p['home_spread']:+g}" if p["edge"] >= 0 else f"{p['away']} {-p['home_spread']:+g}")
            else:
                pick = "—"
            title = H.LEAGUES.get(lg, {}).get("title", lg)
            out.append({"sport": lg if lg in GAME_LEAGUES else "INTL", "kind": "Game line" if lg in GAME_LEAGUES else title,
                        "time": _et_time(p.get("kickoff")), "pick": pick,
                        "game": f"{p.get('away')} @ {p.get('home')}", "price": None, "book": "",
                        "chance": p.get("cover_est"), "use": t.get("use"), "lock": bool(t.get("lock")),
                        "page": "International Hoops" if lg not in GAME_LEAGUES else f"{lg} Game Lab"})
    try:
        recs = MS.load_game_picks("TENNIS", ungraded=True)
    except Exception:                                           # noqa: BLE001
        recs = []
    for p in recs:
        if _et_date(p.get("kickoff")) != date_str:
            continue
        t = IP.tennis_use(p)
        if t.get("use") not in PLAYABLE:
            continue
        out.append({"sport": "TENNIS", "kind": p.get("tournament") or "Tennis", "time": _et_time(p.get("kickoff")),
                    "pick": f"{t.get('player')} to win", "game": f"{p.get('away')} vs {p.get('home')}",
                    "price": None, "book": "", "chance": t.get("chance"), "use": t.get("use"), "lock": bool(t.get("lock")),
                    "need": t.get("need"), "untested": True, "page": "Tennis Lab"})
    return out


# --------------------------------------------------------------------------- together
def _order(r: Dict):
    return (0 if r.get("lock") else RANK.get(r.get("use"), 9), -(r.get("chance") or 0))


def collect(date_str: str, props_sports) -> Dict:
    """{"rows": [...], "props": {sport: saved-at or None}} for the Home panel."""
    rows, fresh = [], {}
    for sp in props_sports:
        saved = load_props(sp, date_str)
        fresh[sp] = (saved or {}).get("at")
        rows += (saved or {}).get("rows") or []
    try:
        rows += game_rows(date_str)
    except Exception:                                           # noqa: BLE001
        pass
    rows.sort(key=_order)
    return {"rows": rows, "props": fresh}


# --------------------------------------------------------------------------- most likely winners (Nov 6)
# For every game today, the side the model thinks is most likely to win, its chance, what the books say, the best
# price and whether that price is worth it -- so every sport on Home has a row even on a night with no tested picks.
# "Most likely" is not "good bet": a -400 favorite usually wins and usually isn't worth -400. The value column and
# the Use tag (where the sport has a tested rule) say which is which; the record line says how often the model's
# favorite has actually won.
WINNER_LEAGUES = ("NCAAMB", "NBA", "NHL", "NCAAF", "TENNIS")
NCAAF_MARGIN_SD = 15.5          # college football: final margin around the projection (ncaaf_projections)


def _home_p(p: Dict, league: str) -> Optional[float]:
    if p.get("model_p") is not None:
        return float(p["model_p"])
    if league == "NCAAF" and p.get("model_margin") is not None:
        import math
        return 0.5 * (1 + math.erf(float(p["model_margin"]) / (NCAAF_MARGIN_SD * math.sqrt(2))))
    return None


def _dec(a) -> Optional[float]:
    try:
        a = float(a)
    except (TypeError, ValueError):
        return None
    if -100 < a < 100:
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a)


# Nov 6: the best-value bet per game across moneyline, spread and total (the section only looked at moneylines, and
# most of those were heavy favorites priced worse than the model's chance). Where a backtest calibrated the chance
# (cover_est: NCAAMB and the international spread models) it is used as is and the bet is "tested"; otherwise the
# chance comes from the projected score with the spread of outcomes below, pulled halfway to 50% (UNTESTED_SHRINK)
# because nothing has checked it yet -- and labeled untested.
MARGIN_SD = {"NCAAMB": 11.0, "NBA": 12.5, "NHL": 2.3, "NCAAF": 15.5, "INTL": 11.0}
TOTAL_SD = {"NCAAMB": 17.0, "NBA": 18.0, "NHL": 2.3, "NCAAF": 16.0, "INTL": 16.0}
UNTESTED_SHRINK = 0.5
UNTESTED_MAX = 0.60             # a big untested disagreement is more often the model's error than the market's
STD_PRICE = -110
ML_PRICE_RANGE = (-250, 250)


def _phi(z: float) -> float:
    import math
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def best_line(p: Dict, lg: str, home_p: float) -> Dict:
    """Nov 6 (revised): one line per game.
    - A tested pick (the league's Game Lab / international rule tags it 🎟️/🎯, the same tag its page shows): the bet,
      its backtested chance, price and value.
    - Otherwise the model's LEAN: the spread or total it disagrees with most (in standard deviations of how games
      finish), with its own number beside the line -- no chance or value, because nothing has tested those.
    The first version priced untested spreads and totals and showed 65 of 86 games as "value" (none tested) and gave a
    puck line's +1.5 side the -1.5 side's price; leans don't pretend to that."""
    import intl_picks as IP
    fam = lg if lg in MARGIN_SD else "INTL"
    out = {"best": None, "best_chance": None, "best_price": None, "best_value": None, "best_tested": False,
           "lean_detail": ""}
    if lg not in ("TENNIS", "NCAAF"):
        t = IP.hoops_use(lg, p)
        if t.get("use") in PLAYABLE:
            if p.get("ml_pick"):
                home = p["ml_pick"] == "home"
                price = p.get("best_home") if home else p.get("best_away")
                ch = home_p if home else 1 - home_p
                label = f"{p['home'] if home else p['away']} moneyline"
            else:
                home = (p.get("edge") or 0) >= 0
                price = p.get("spread_price") if _dec(p.get("spread_price")) else STD_PRICE
                ch = p.get("cover_est")
                hs = p.get("home_spread")
                label = (f"{p['home']} {hs:+g}" if home else f"{p['away']} {-hs:+g}") if hs is not None else "—"
            d = _dec(price)
            out.update(best=label, best_chance=ch, best_price=price, best_tested=True,
                       best_value=(ch * d - 1) if (ch is not None and d) else None, use=t.get("use"))
            return out
    leans = []
    hs, mm = p.get("home_spread"), p.get("model_margin")
    if hs is not None and mm is not None:
        z = (float(mm) + float(hs)) / MARGIN_SD[fam]             # > 0: home covers by the model's margin
        home = z >= 0
        team, line = (p.get("home"), float(hs)) if home else (p.get("away"), -float(hs))
        model_line = -float(mm) if home else float(mm)
        leans.append((abs(z), f"{team} {line:+g}", f"model {team} {model_line:+.1f}"))
    lt, mt = p.get("line_total"), p.get("model_total")
    if lt is not None and mt is not None:
        z = (float(mt) - float(lt)) / TOTAL_SD[fam]
        leans.append((abs(z), f"{'Over' if z >= 0 else 'Under'} {float(lt):g}", f"model total {float(mt):.1f}"))
    if leans:
        z, label, detail = max(leans)
        out.update(best=label, lean_detail=detail, lean_z=z)
    return out


def winner_rows(date_str: str, leagues=None) -> List[Dict]:
    import intl_hoops as H
    import model_store as MS
    leagues = list(leagues) if leagues is not None else list(WINNER_LEAGUES) + [k for k in H.LEAGUES if k not in WINNER_LEAGUES]
    out = []
    for lg in leagues:
        try:
            recs = MS.load_game_picks(lg, ungraded=True)
        except Exception:                                       # noqa: BLE001
            continue
        for p in recs:
            if _et_date(p.get("kickoff")) != date_str:
                continue
            hp = _home_p(p, lg)
            if hp is None:
                continue
            home = hp >= 0.5
            team = p.get("home") if home else p.get("away")
            chance = hp if home else 1 - hp
            book = p.get("fair_home")
            book = None if book is None else (float(book) if home else 1 - float(book))
            price = p.get("best_home") if home else p.get("best_away")
            d = _dec(price)
            value = None if d is None else chance * d - 1
            ml_tag = ""
            if p.get("ml_pick") and ((p["ml_pick"] == "home") == home):
                ml_tag = PE.USE_SINGLE
            try:
                best = best_line(p, lg, hp)
            except Exception:                                   # noqa: BLE001 -- one bad record never breaks Home
                best = {"best": None, "best_chance": None, "best_price": None, "best_value": None, "best_tested": False}
            sport = lg if lg in WINNER_LEAGUES else "INTL"
            title = H.LEAGUES.get(lg, {}).get("title", lg) if sport == "INTL" else (p.get("tournament") or lg)
            out.append({"sport": sport, "league": title, "time": _et_time(p.get("kickoff")),
                        "game": f"{p.get('away')} {'vs' if lg == 'TENNIS' else '@'} {p.get('home')}",
                        "winner": team, "chance": chance, "book": book, "price": price,
                        "price_book": p.get("best_home_book") if home else p.get("best_away_book"),
                        "value": value, "use": ml_tag, **best})
    out.sort(key=lambda r: -r["chance"])
    return out


def winner_record(leagues=None) -> Dict[str, Dict]:
    """{sport: {"n", "won", "by": [(label, n, won)]}} -- how often the model's favorite actually won, graded games."""
    import intl_hoops as H
    import model_store as MS
    leagues = list(leagues) if leagues is not None else list(WINNER_LEAGUES) + [k for k in H.LEAGUES if k not in WINNER_LEAGUES]
    acc: Dict[str, Dict] = {}
    bands = ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01))
    for lg in leagues:
        try:
            recs = MS.load_game_picks(lg)
        except Exception:                                       # noqa: BLE001
            continue
        sport = lg if lg in WINNER_LEAGUES else "INTL"
        a = acc.setdefault(sport, {"n": 0, "won": 0, "bands": {b: [0, 0] for b in bands}})
        for p in recs:
            fh, fa = p.get("final_home"), p.get("final_away")
            hp = _home_p(p, lg)
            if fh is None or fa is None or hp is None or fh == fa or hp == 0.5:
                continue
            won = (fh > fa) == (hp > 0.5)
            ch = max(hp, 1 - hp)
            a["n"] += 1
            a["won"] += won
            for lo, hi in bands:
                if lo <= ch < hi:
                    a["bands"][(lo, hi)][0] += 1
                    a["bands"][(lo, hi)][1] += won
    return {k: v for k, v in acc.items() if v["n"]}
