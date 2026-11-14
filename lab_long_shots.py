"""
lab_long_shots.py — long shots from the labs (tennis, international hoops, soccer), Nov 14. Tracking only.

Owner (Nov 14): Today's best should read hoops, soccer and tennis from their own labs, long shots included.

Two kinds:
  * Underdog moneylines (free -- read from the saved lab records, no Odds API credits): the side the model says LOSES,
    priced +300 or longer, where the model's own chance still beats the price (chance x decimal odds > 1).
      - Tennis: the calibrated chance (k applied), so the 70%+ favorite correction already pulls these in.
      - International hoops: every league's saved model chance.
      - Soccer: a single outcome (home / draw / away) from the goals model at +300 or longer.
  * Soccer anytime goalscorer (scanned a few times a day, ~3 Odds API credits per match, capped): priced +400 or
    longer, the player's per-start scoring rate (last 10 matches, ESPN) scaled to the opponent beats the price, at
    least MIN_STARTS starts in those 10.

Nothing here is tested: no backtest of underdog moneylines or goalscorer prices exists for these sports. The goals
model lost to the closing line in its backtest, and international hoops / tennis moneylines are tracking only, so
every row is labeled "untested — tracking" and the stakes advice is flat and tiny.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DOG_MIN = 300               # underdog moneylines: +300 or longer
SCORER_MIN = 400            # anytime goalscorer: +400 or longer
MIN_STARTS = 5              # of the last 10 matches -- a regular starter, not a thin sample
TOP_N = 4
SCORER_EVERY_H = 6.0
MAX_MATCHES = 24            # goalscorer scan: at most ~72 credits a run
SCORER_KEY = "longshots:SOCCER:{date}"
SCORER_LEAGUES = ("SOCCER_EPL", "SOCCER_LALIGA", "SOCCER_SERIEA", "SOCCER_BUNDESLIGA", "SOCCER_LIGUE1",
                  "SOCCER_UCL", "SOCCER_UEL", "SOCCER_MLS", "SOCCER_LIGAMX", "SOCCER_WCQ_UEFA", "SOCCER_NATIONS")
LABEL = "untested — tracking"


def _dec(a) -> Optional[float]:
    try:
        a = float(a)
    except (TypeError, ValueError):
        return None
    if -100 < a < 100:
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a)


def _et_date(iso) -> Optional[str]:
    import todays_best as TB
    return TB._et_date(iso)


def _et_time(iso) -> str:
    import todays_best as TB
    return TB._et_time(iso)


def _started(iso, now: datetime) -> bool:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d <= now


def dog_side(p: Dict, chance_home: float, min_price: int = DOG_MIN) -> Optional[Dict]:
    """The model's underdog in a two-way match, if it's priced +min_price or longer and its chance beats the price."""
    home = chance_home < 0.5
    ch = chance_home if home else 1 - chance_home
    price = p.get("best_home") if home else p.get("best_away")
    d = _dec(price)
    if d is None or float(price) < min_price or ch * d <= 1:
        return None
    return {"side": "home" if home else "away", "team": p.get("home") if home else p.get("away"), "chance": ch,
            "price": float(price), "book": p.get("best_home_book") if home else p.get("best_away_book"),
            "ev": round(ch * d - 1, 4)}


def soccer_dogs(p: Dict, min_price: int = DOG_MIN) -> List[Dict]:
    """Soccer: each of home / draw / away priced +min_price or longer whose goals-model chance beats the price."""
    out = []
    for side, pk, price, book in (("home", "p_home", "best_home", "book_home"), ("draw", "p_draw", "best_draw", "book_draw"),
                                  ("away", "p_away", "best_away", "book_away")):
        ch, d = p.get(pk), _dec(p.get(price))
        if ch is None or d is None or float(p[price]) < min_price or ch * d <= 1:
            continue
        out.append({"side": side, "team": {"home": p.get("home"), "away": p.get("away"), "draw": "Draw"}[side],
                    "chance": float(ch), "price": float(p[price]), "book": p.get(book), "ev": round(ch * d - 1, 4)})
    return out


def _row(sport: str, league_key: str, league_title: str, p: Dict, s: Dict, kind: str = "Moneyline") -> Dict:
    vs = "vs" if sport in ("TENNIS", "SOCCER") else "@"
    pick = (f"{s['team']} to win" if s["side"] != "draw" else "Draw") if kind == "Moneyline" else s["pick"]
    market = "Moneyline" if kind == "Moneyline" else kind
    bet_side = s["side"] if kind == "Moneyline" else "Yes"
    row = {"sport": sport, "league": league_title, "time": _et_time(p.get("kickoff")), "_ko": p.get("kickoff"),
           "game": f"{p.get('away')} {vs} {p.get('home')}", "pick": pick, "Pick": pick, "Price": s["price"],
           "price": s["price"], "Honest chance": s["chance"], "chance": s["chance"], "EV per $1": s["ev"],
           "book": s.get("book"), "Market": market, "market": market, "side": bet_side, "line": s.get("line"),
           "player": s.get("player"), "tested": False, "status": LABEL}
    if kind == "Moneyline":                 # logs through the lab's own bet fields, so it settles with the lab
        row.update(bet_market="Moneyline", bet_side=s["side"], bet_line=None, best_tested=False,
                   _rec={"sport": league_key, "home": p.get("home"), "away": p.get("away"),
                         "game_id": p.get("game_id"), "kickoff": p.get("kickoff")})
    else:                                   # a soccer prop: settles from the ESPN summary (soccer_props.settle_props)
        row.update(game=f"{p.get('away')} @ {p.get('home')}", notes_extra=f"soccer-props,sp:{league_key}")
    return row


def dog_rows(date_str: str, load: Optional[Callable] = None, now: Optional[datetime] = None,
             soccer_leagues: Optional[Sequence[str]] = None) -> Dict[str, List[Dict]]:
    """{"TENNIS": [...], "INTL": [...], "SOCCER": [...]}: today's value underdogs from the saved lab records (free)."""
    import intl_hoops as H
    import model_store as MS
    import soccer_data as D
    import soccer_picks as SP
    load = load or (lambda lg: MS.load_game_picks(lg, ungraded=True))
    now = now or datetime.now(timezone.utc)
    out: Dict[str, List[Dict]] = {"TENNIS": [], "INTL": [], "SOCCER": []}

    def _recs(lg):
        try:
            return [p for p in load(lg) or [] if _et_date(p.get("kickoff")) == date_str and not _started(p.get("kickoff"), now)]
        except Exception:                                       # noqa: BLE001
            return []

    for p in _recs("TENNIS"):
        if p.get("model_p") is None:
            continue
        s = dog_side(p, float(p["model_p"]))
        if s:
            out["TENNIS"].append(_row("TENNIS", "TENNIS", p.get("tournament") or "Tennis", p, s))
    for lg, meta in H.LEAGUES.items():
        for p in _recs(lg):
            if p.get("model_p") is None:
                continue
            s = dog_side(p, float(p["model_p"]))
            if s:
                out["INTL"].append(_row("INTL", lg, meta.get("title", lg), p, s))
    leagues = soccer_leagues if soccer_leagues is not None else (SP.slate_leagues() or list(D.LEAGUES))
    for lg in leagues:
        for p in SP.dedupe(_recs(lg)):
            for s in soccer_dogs(p):
                out["SOCCER"].append(_row("SOCCER", lg, D.LEAGUES.get(lg, {}).get("title", lg), p, s))
    for k in out:
        out[k].sort(key=lambda r: (-r["chance"], -r["EV per $1"]))
    return out


def top(rows: Sequence[Dict], n: int = TOP_N) -> List[Dict]:
    """The n most probable, one per game (or per player for props)."""
    out, seen = [], set()
    for r in sorted(rows, key=lambda r: (-(r.get("chance") or 0), -(r.get("EV per $1") or 0))):
        k = r.get("player") or r.get("game")
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
        if len(out) >= n:
            break
    return out


# --------------------------------------------------------------------------- soccer anytime goalscorer scan
def scorer_picks(read_rows: Sequence[Dict], min_price: int = SCORER_MIN, min_starts: int = MIN_STARTS) -> List[Dict]:
    """From soccer_props.read(): anytime goalscorer priced +min_price or longer, a regular starter, chance beats price."""
    out = []
    for x in read_rows:
        if x.get("market") != "Anytime Goal" or x.get("chance") is None or x.get("price") is None:
            continue
        if float(x["price"]) < min_price or (x.get("starts") or 0) < min_starts or (x.get("ev") or 0) <= 0:
            continue
        out.append(x)
    return out


def scan_scorers(day: str, api_key: str, now: Optional[datetime] = None, max_matches: int = MAX_MATCHES) -> Dict:
    from datetime import timedelta
    import model_store as MS
    import soccer_data as D
    import soccer_picks as SP
    import soccer_props as SPR
    now = now or datetime.now(timezone.utc)
    slate = SP.slate_leagues()
    leagues = [k for k in SCORER_LEAGUES if slate is None or k in slate]
    matches = []
    for lg in leagues:
        try:
            recs = SP.dedupe(MS.load_game_picks(lg, ungraded=True))
        except Exception:                                       # noqa: BLE001
            continue
        for p in recs:
            if str(p.get("game_id")).startswith("espn:") or _et_date(p.get("kickoff")) != day \
                    or _started(p.get("kickoff"), now):
                continue
            matches.append((lg, p))
    matches.sort(key=lambda m: str(m[1].get("kickoff")))
    rows, done = [], 0
    for lg, m in matches[:max_matches]:
        try:
            props = SPR.fetch_props(lg, m["game_id"], api_key)
            done += 1
            if not props:
                continue
            since = (now.date() - timedelta(days=200)).isoformat()
            res = MS.load_results(lg, since=since)
            for kk in D.pool_keys(lg):
                if kk != lg:
                    res += MS.load_results(kk, since=since)
            r = SP.ratings(lg, now.date())
            got = {}
            for ids in (SPR.team_matches(res, m["home"]), SPR.team_matches(res, m["away"])):
                for e in ids:
                    g = next((x for x in res if str(x["id"]) == e), None)
                    got.update(SPR.summaries(g.get("league", lg) if g else lg, [e]))
            read = SPR.read(props, m, r, SPR.rates(got, m["home"]), SPR.rates(got, m["away"]))
        except Exception:                                       # noqa: BLE001 -- one match never stops the scan
            continue
        for x in scorer_picks(read):
            s = {"side": "Yes", "pick": f"{x['player']} anytime goal", "player": x["player"], "chance": x["chance"],
                 "price": float(x["price"]), "book": x.get("book"), "ev": x["ev"], "line": 0.5}
            row = _row("SOCCER", lg, D.LEAGUES[lg]["title"], m, s, kind="Anytime Goal")
            row["starts"] = x.get("starts")
            rows.append(row)
    rows.sort(key=lambda r: -r["chance"])
    return {"at": now.isoformat(), "matches": done, "rows": rows[:200], "top": top(rows)}


def load_scorers(day: str, get=None) -> Optional[Dict]:
    try:
        import model_store as MS
        return (get or MS.get_setting)(SCORER_KEY.format(date=day))
    except Exception:                                           # noqa: BLE001
        return None


def run_scorers(day: Optional[str] = None, force: bool = False) -> Dict:
    import long_shots_scan as LSS
    import model_store as MS
    import pytz
    api = os.environ.get("ODDS_API_KEY", "")
    day = day or datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
    if not api:
        return {"skipped": "no Odds API key"}
    if not force and not LSS.stale(load_scorers(day), hours=SCORER_EVERY_H):
        return {"skipped": f"scanned under {SCORER_EVERY_H:g} hours ago"}
    try:
        res = scan_scorers(day, api)
        MS.save_setting(SCORER_KEY.format(date=day), res)
        return {"matches": res["matches"], "value_scorers": len(res["rows"]),
                "top": [f"{r['pick']} {int(r['Price']):+d} ({r['chance']:.0%})" for r in res["top"]]}
    except Exception as exc:                                    # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def collect(day: str, now: Optional[datetime] = None) -> Dict[str, Dict]:
    """What Today's best shows: {sport: {"top": [...], "n": count, "kind": text, "at": iso or None}}."""
    dogs = dog_rows(day, now=now)
    out = {}
    for sp, rows in dogs.items():
        if rows:
            out[sp] = {"top": top(rows), "n": len(rows), "kind": "underdog moneylines +300 or longer", "at": None}
    sc = load_scorers(day)
    if sc and sc.get("top"):
        out["SOCCER_SCORERS"] = {"top": sc["top"], "n": len(sc.get("rows") or []),
                                 "kind": "anytime goalscorers +400 or longer", "at": sc.get("at")}
    return out


if __name__ == "__main__":
    print("SOCCER scorers", run_scorers(force="--force" in sys.argv))
