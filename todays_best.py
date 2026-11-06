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
