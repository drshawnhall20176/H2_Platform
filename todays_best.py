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
from typing import Dict, List, Optional, Sequence

import props_engine as PE

KEY = "todays_best:{sport}:{date}"
TOP_PER_SPORT = 40
PLAYABLE = (PE.USE_BOTH, PE.USE_PARLAY, PE.USE_SINGLE)
RANK = {PE.USE_BOTH: 1, PE.USE_PARLAY: 2, PE.USE_SINGLE: 3}
GAME_LEAGUES = ("NCAAMB", "NBA", "NHL", "NFL")          # Game Labs (game_picks rows tagged by intl_picks.hoops_use)


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
        e = d.astimezone(pytz.timezone("US/Eastern"))
        if e.hour == 0 and e.minute == 0:                       # Nov 12: ESPN's "no time yet" (tennis order of play)
            return "time TBA"
        return e.strftime("%I:%M %p").lstrip("0")
    except (TypeError, ValueError):
        return "TBD"


# --------------------------------------------------------------------------- player props
MONEY_TOP = 8


def props_rows(sport: str, plays, cap: bool = True) -> List[Dict]:
    out = []
    for p in plays or []:
        lock = PE.play_is_lock(p)
        money = PE.play_is_money(sport, p)                   # Nov 19: 💰 shown whatever its Use tag
        if p.get("Use") not in PLAYABLE and not lock and not money:
            continue
        if p.get("Use") == PE.USE_PASS and not money:
            continue
        line = p.get("Line")
        try:                                                    # Nov 21: the chance the record has earned
            import props_money as _PMS
            earned = _PMS.play_earned(sport, p)
        except Exception:                                       # noqa: BLE001
            earned = None
        out.append({"sport": sport, "kind": "Prop", "time": p.get("Time") or "",
                    "pick": f"{p.get('Player')} {p.get('Market')} {p.get('Side')}" + ("" if line is None else f" {line:g}"),
                    "game": p.get("Game") or "", "price": p.get("RealPrice"), "book": p.get("RealPriceBook") or "",
                    # Nov 21 (owner: "proven edge A+"): "chance" is the EARNED chance where there's a fit -- the model's
                    # 60-80% picks hit ~55%, and the earned chance says so; the model's own stays in raw_chance
                    "chance": earned if earned is not None else p.get("ModelProb"), "raw_chance": p.get("ModelProb"),
                    "earned": earned, "use": p.get("Use") or "", "lock": lock, "page": "Best Bets",
                    # Nov 7: what the Home panel needs to log the pick
                    "player": p.get("Player"), "pid": p.get("PlayerId"), "market": p.get("Market"), "side": p.get("Side"),
                    "line": line, "market_key": p.get("MarketKey"),
                    # Nov 18: a line only a pick'em app posts -- no sportsbook price behind it, never a 🔒
                    "pickem_only": bool(p.get("Pickem")),
                    "money": money, "edge": p.get("EV"), "l10": p.get("L10"), "l5": p.get("L5")})
    out.sort(key=_order)
    if not cap:                                                 # Nov 21: every pick, for the shown-picks ledger
        return out
    # Nov 14: every 🔒 Most probable is kept; the cap only trims the other playable tags. Nov 19: the 💰 Money picks
    # are kept too, the MONEY_TOP biggest edges (the full list is on Best Bets under "💰 Money picks")
    money = sorted([r for r in out if r["money"] and not r["lock"]], key=lambda r: -(r.get("edge") or 0))[:MONEY_TOP]
    return ([r for r in out if r["lock"]] + money
            + [r for r in out if not r["lock"] and not r["money"]][:TOP_PER_SPORT])


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
                        {"at": datetime.now(timezone.utc).isoformat(),
                         "rows": keep_started(props_rows(sport, timed), (load_props(sport, date_str) or {}).get("rows"),
                                              on_board={p.get("Game") for p in timed if p.get("Game")})})
    except Exception:                                           # noqa: BLE001 -- a bonus, never a failure
        pass
    # Nov 21 (owner: "your 14-1 record is overstated"): the picks as SHOWN -- every 💰 prop the board shows and the
    # Command Center's strongest-15 -- kept the first time they appear (pick_ledger.py)
    try:
        import pick_ledger as PL
        PL.record_props(sport, date_str, [r for r in props_rows(sport, timed, cap=False) if r.get("money")])
        PL.record_strong(date_str)
    except Exception:                                           # noqa: BLE001
        pass


def keep_started(new_rows: List[Dict], old_rows: Optional[List[Dict]], game_key: str = "game",
                 on_board=None) -> List[Dict]:
    """Nov 19: a board rebuilt after tip-off leaves out the games that have started -- and the 11:25 PM rebuild on
    Nov 18 saved the NBA's picks as an empty list, so the day's picks (and their results) were gone by morning. The
    picks of any game no longer on the new board are kept as they were; games still on it take the new picks."""
    new_rows = list(new_rows or [])
    # Nov 21: a game still ON the new board (not started) whose pick dropped off stays dropped -- the old pick was
    # kept all day before (two college basketball picks the model had moved off, still on the strongest list)
    if on_board:
        new_rows = list(new_rows or [])
        live = {r.get(game_key) for r in new_rows} | set(on_board)
        return new_rows + [r for r in old_rows or [] if r.get(game_key) not in live]
    live = {r.get(game_key) for r in new_rows}
    return new_rows + [r for r in old_rows or [] if r.get(game_key) not in live]


def props_from_snapshots(sport: str, date_str: str, snaps=None) -> List[Dict]:
    """Nov 19: a day's Today's-best props rebuilt from the prop snapshots (each read's first bet tag, or its last read
    when it was a 🔒 / 💰) -- for a day whose saved picks were lost."""
    import model_store as MS
    snaps = MS.load_snapshots(sport, [date_str]) if snaps is None else snaps
    out = []
    for s in snaps or []:
        tag = PE.norm_use(s.get("bet_use_tag") or s.get("use_tag"))
        side = s.get("bet_side") or s.get("side")
        line = s.get("bet_line") if s.get("bet_line") is not None else s.get("line")
        chance = s.get("bet_chance") if s.get("bet_chance") is not None else s.get("chance")
        lock = PE.is_lock(s.get("chance"), s.get("cushion"), s.get("gap"), s.get("book"), ev=s.get("ev"))
        money = PE.snapshot_is_money(sport, s)
        if tag not in PLAYABLE and not lock and not money:
            continue
        out.append({"sport": sport, "kind": "Prop", "time": _et_time(s.get("kickoff")) or "",
                    "pick": f"{s.get('player')} {s.get('market')} {side}" + ("" if line is None else f" {float(line):g}"),
                    "game": s.get("game") or "", "price": s.get("price"), "book": s.get("book") or "",
                    "chance": chance, "use": tag or "", "lock": lock, "page": "Best Bets", "player": s.get("player"),
                    "pid": s.get("player_id"), "market": s.get("market"), "side": side, "line": line,
                    "market_key": None, "pickem_only": (s.get("book") or "") in PE.PICKEM_BOOKS, "money": money,
                    "edge": s.get("ev"), "rebuilt": True})
    out.sort(key=_order)
    return out


def load_props(sport: str, date_str: str) -> Optional[Dict]:
    try:
        import model_store as MS
        return MS.get_setting(KEY.format(sport=sport, date=date_str), None)
    except Exception:                                           # noqa: BLE001
        return None


# --------------------------------------------------------------------------- game lines, international, tennis
LOAD_ERRORS: List[str] = []          # Nov 7: leagues whose game picks failed to load on the last call


def game_rows(date_str: str, leagues=None, past: bool = False) -> List[Dict]:
    """TESTED, playable game-line picks only (NCAAMB spreads at 8+ points, EuroLeague spreads, NBL moneylines, tennis
    where tested). For every game's lean -- tested or not -- use winner_rows. LOAD_ERRORS lists leagues that failed."""
    LOAD_ERRORS.clear()
    import intl_hoops as H
    import intl_picks as IP
    import model_store as MS
    leagues = list(leagues) if leagues is not None else list(GAME_LEAGUES) + [k for k in H.LEAGUES if k not in GAME_LEAGUES]
    out = []
    for lg in leagues:
        try:
            recs = MS.load_game_picks(lg, ungraded=not past)
        except Exception as exc:                                # noqa: BLE001 -- one league failing never empties the list
            LOAD_ERRORS.append(f"{lg}: {type(exc).__name__}: {str(exc)[:120]}")     # Nov 7: said, not swallowed
            print(f"[todays_best] {lg} game picks failed to load ({type(exc).__name__}: {exc})")
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
            if p.get("ml_pick"):
                bet = _bet(p, lg, "Moneyline", p["ml_pick"], None, p.get("cover_est"))
            elif p.get("home_spread") is not None and p.get("edge") is not None:
                hs = float(p["home_spread"])
                bet = _bet(p, lg, "Spread", "home" if p["edge"] >= 0 else "away", hs if p["edge"] >= 0 else -hs,
                           p.get("cover_est"))
            else:
                bet = {}
            res = None
            if past and pick != "—":
                if p.get("ml_pick"):
                    res = grade_line(p, "Moneyline", p["ml_pick"], None)
                elif p.get("home_spread") is not None and p.get("edge") is not None:
                    hs = float(p["home_spread"])
                    res = grade_line(p, "Spread", "home" if p["edge"] >= 0 else "away", hs if p["edge"] >= 0 else -hs)
            out.append({"sport": lg if lg in GAME_LEAGUES else "INTL", "kind": "Game line" if lg in GAME_LEAGUES else title,
                        "time": _et_time(p.get("kickoff")), "pick": pick, "result": res,
                        "game": f"{p.get('away')} @ {p.get('home')}", "price": None, "book": "",
                        "chance": p.get("cover_est"), "use": t.get("use"), "lock": bool(t.get("lock")),
                        "page": "International Hoops" if lg not in GAME_LEAGUES else f"{lg} Game Lab", **bet})
    try:
        recs = MS.load_game_picks("TENNIS", ungraded=not past)
    except Exception:                                           # noqa: BLE001
        recs = []
    import tennis_calibration as TC
    k = TC.current_k()
    for p in recs:
        if _et_date(p.get("kickoff")) != date_str:
            continue
        t = IP.tennis_use(p, k)
        if t.get("use") not in PLAYABLE:
            continue
        tres = None
        if past and p.get("final_home") is not None and p.get("final_away") is not None and t.get("player"):
            won_home = float(p["final_home"]) > float(p["final_away"])
            tres = "win" if won_home == (t.get("player") == p.get("home")) else "loss"
        out.append({"sport": "TENNIS", "kind": p.get("tournament") or "Tennis", "time": _et_time(p.get("kickoff")), "result": tres,
                    "pick": f"{t.get('player')} to win", "game": f"{p.get('away')} vs {p.get('home')}",
                    "price": None, "book": "", "chance": t.get("chance"), "use": t.get("use"), "lock": bool(t.get("lock")),
                    "need": t.get("need"), "untested": True, "page": "Tennis Lab",
                    # Nov 19 (owner couldn't log Shelton / Zverev / Erjavec from Today: "missing the player, side or
                    # line"): the bet itself, so the log box can write it and capture-intl can settle it
                    **_bet(p, "TENNIS", "Moneyline",
                           None if not t.get("player") else ("home" if t["player"] == p.get("home") else "away"), None,
                           t.get("chance"))})
    return out


def _bet(p: Dict, lg: str, market: str, side: Optional[str], line: Optional[float], chance) -> Dict:
    """Nov 19: what the log box needs to write a tested game-line / tennis pick (the same shape winner_rows gives)."""
    if not side:
        return {}
    return {"bet_market": market, "bet_side": side, "bet_line": line, "best_chance": chance,
            "best_tested": chance is not None,
            "_rec": {"sport": lg, "home": p.get("home"), "away": p.get("away"), "game_id": p.get("game_id"),
                     "kickoff": p.get("kickoff")}}


# --------------------------------------------------------------------------- looking back (Nov 7)
RESULT_ICON = {"win": "✅ won", "loss": "❌ lost", "push": "➖ push", "void": "void"}


def grade_line(p: Dict, market: str, side: str, line: Optional[float]) -> Optional[str]:
    """win / loss / push for a game-line bet on a graded game record, None while it isn't final."""
    fh, fa = p.get("final_home"), p.get("final_away")
    if fh is None or fa is None:
        return None
    fh, fa = float(fh), float(fa)
    if market == "Moneyline":
        if fh == fa:
            return "push"
        return "win" if (fh > fa) == (side == "home") else "loss"
    if line is None:
        return None
    if market == "Spread":
        m = (fh - fa) if side == "home" else (fa - fh)
        v = m + float(line)
    else:                                                       # Total
        v = (fh + fa - float(line)) * (1 if side == "over" else -1)
    return "push" if v == 0 else ("win" if v > 0 else "loss")


def prop_results(sport: str, date_str: str) -> Dict:
    """{(player, market, side, line): win / loss / push / void} for one date, from the kickoff snapshots graded
    against ESPN box scores (the Postgame Review's grading). The pick's side, not the snapshot's, decides win/loss."""
    import model_store as MS
    import pick_records as _PRK
    import postgame as PG
    snaps = MS.load_snapshots(sport, [date_str])
    if not snaps:
        return {}
    res = PG.fetch_results(sport, date_str, sorted({(s["team"], s["opp"]) for s in snaps}))
    out = {}
    for g in PG.grade(snaps, res):
        if g.get("actual") is None:
            continue
        lines = {float(g["line"])} | ({float(g["bet_line"])} if g.get("bet_line") is not None else set())
        for ln in lines:                                        # Nov 19: the bet tag's own line too
            thr = PE.threshold(ln)
            for side in ("Over", "Under"):
                r = "push" if g["actual"] == thr else ("win" if (g["actual"] > thr) == (side == "Over") else "loss")
                mk = _PRK.COMBO_KEY.get(g.get("market"), g.get("market"))
                out[(PE.norm_name(g.get("player") or ""), mk, side, ln)] = r
    return out


# --------------------------------------------------------------------------- together
def _order(r: Dict):
    return (0 if r.get("lock") else RANK.get(r.get("use"), 9), -(r.get("chance") or 0))


def collect(date_str: str, props_sports, past: bool = False) -> Dict:
    """{"rows": [...], "props": {sport: saved-at or None}} for the Home panel. past=True (Nov 7: looking back): the
    picks as they were saved that day, each graded ("result": win / loss / push / void / None)."""
    rows, fresh = [], {}
    for sp in props_sports:
        saved = load_props(sp, date_str)
        fresh[sp] = (saved or {}).get("at")
        got = [dict(r) for r in (saved or {}).get("rows") or []]
        if past and not got:                                    # Nov 19: the day's picks were lost -- rebuild them
            try:
                got = props_from_snapshots(sp, date_str)
            except Exception:                                   # noqa: BLE001
                got = []
        if past and got:
            try:
                res = prop_results(sp, date_str)
                import pick_records as _PRK
                for r in got:
                    if r.get("line") is not None:
                        # Nov 19: the board says "Pts+Reb", the snapshots "PR" -- 14 of 19 college picks found no result
                        mk = _PRK.COMBO_KEY.get(r.get("market"), r.get("market"))
                        r["result"] = res.get((PE.norm_name(r.get("player") or ""), mk, r.get("side"),
                                               float(r["line"])))
            except Exception:                                   # noqa: BLE001
                pass
        rows += got
    try:
        rows += game_rows(date_str, past=past)
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
WINNER_LEAGUES = ("NCAAMB", "NBA", "NHL", "NCAAF", "TENNIS", "NFL")
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
# Nov 18 (research/game_spread.py, 1,155 NBA games with a line, 2025-26 + this season): NBA finals land 14.2 points
# from the closing spread on average (SD), not 12.5 -- 20+ point margins happened 23.8% vs 18.9% at 12.5. The other
# leagues measured within half a point of these values (NCAAMB 11.3, NCAAF 15.1, NFL 12.1; totals all within 0.7).
MARGIN_SD = {"NCAAMB": 11.0, "NBA": 14.0, "NHL": 2.3, "NCAAF": 15.5, "INTL": 11.0, "NFL": 13.0}
TOTAL_SD = {"NCAAMB": 17.0, "NBA": 18.0, "NHL": 2.3, "NCAAF": 16.0, "INTL": 16.0, "NFL": 13.5}
UNTESTED_SHRINK = 0.5
UNTESTED_MAX = 0.60             # a big untested disagreement is more often the model's error than the market's
STD_PRICE = -110
NCAAMB_TOTAL_BACKTEST = {"Under": 0.453, "Over": 0.508}
NCAAF_SPREAD_BACKTEST = 0.481
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
                price = IP.spread_price_for(p, "home" if home else "away")
                price = price if _dec(price) else STD_PRICE
                ch = p.get("cover_est")
                hs = p.get("home_spread")
                label = (f"{p['home']} {hs:+g}" if home else f"{p['away']} {-hs:+g}") if hs is not None else "—"
            d = _dec(price)
            if p.get("ml_pick"):
                out.update(bet_market="Moneyline", bet_side="home" if home else "away", bet_line=None, bet_price=price)
            else:
                out.update(bet_market="Spread", bet_side="home" if home else "away",
                           bet_line=(float(p["home_spread"]) if home else -float(p["home_spread"]))
                           if p.get("home_spread") is not None else None, bet_price=price)
            out.update(best=label, best_chance=ch, best_price=price, best_tested=True,
                       best_value=(ch * d - 1) if (ch is not None and d) else None, use=t.get("use"),
                       lock=bool(t.get("lock")))
            return out
    leans = []
    hs, mm = p.get("home_spread"), p.get("model_margin")
    if hs is None and p.get("line") is not None:                # Nov 14: college football keeps the home's margin
        hs = -float(p["line"])
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
        if label.split()[0] in ("Over", "Under"):
            out.update(bet_market="Total", bet_side=label.split()[0].lower(), bet_line=float(lt),
                       bet_price=(p.get("over_price") if label.startswith("Over") else p.get("under_price")) or STD_PRICE)
        else:
            home = (float(mm) + float(hs)) >= 0
            out.update(bet_market="Spread", bet_side="home" if home else "away",
                       bet_line=float(hs) if home else -float(hs),
                       bet_price=IP.spread_price_for(p, "home" if home else "away") or STD_PRICE)
        # Nov 6 (research/backtest_ncaamb_totals.py, 2 seasons, 5,214 games, walk-forward): NCAAMB total leans 3+ points
        # off the line -- Unders hit 45.3% (558; 44.0% in November), Overs 50.8% (1,625). Shown as the lean's backtest so
        # the model's college Unders are never mistaken for an edge.
        if lg == "NCAAMB" and label.split()[0] in ("Over", "Under") and lt is not None and mt is not None \
                and abs(float(mt) - float(lt)) >= 3:
            out.update(backtest=NCAAMB_TOTAL_BACKTEST[label.split()[0]])
    # Nov 14 (research/ncaaf_hfa_fix.py): college football spread leans, fixed model, 2026 walk-forward at 4+ points of
    # disagreement: 50-54 (48%). The live record behind them came from the old home-biased model, so the backtest is
    # the honest grade.
    if lg == "NCAAF" and out.get("bet_market") == "Spread":
        out.update(backtest=NCAAF_SPREAD_BACKTEST)
    # Where a backtest measured how often spreads with this much disagreement covered (cover_est: NCAAMB and the
    # international models), that rate is the honest strength of the spread lean -- and it shows the model's biggest
    # disagreements (lopsided games) are coin flips (~51%), so they rank last, not first.
    if p.get("cover_est") is not None and p.get("edge") is not None and hs is not None:
        home = p["edge"] >= 0
        out.update(bet_market="Spread", bet_side="home" if home else "away",
                   bet_line=float(hs) if home else -float(hs), bet_price=IP.spread_price_for(p, "home" if home else "away"))
        out.update(best=(f"{p['home']} {float(hs):+g}" if home else f"{p['away']} {-float(hs):+g}"),
                   lean_detail=f"model {(p['home'] if home else p['away'])} {(-float(mm) if home else float(mm)):+.1f}"
                   if mm is not None else out.get("lean_detail", ""),
                   backtest=float(p["cover_est"]), backtest_n=p.get("cover_n"))
    return out


def winner_rows(date_str: str, leagues=None, past: bool = False) -> List[Dict]:
    import intl_hoops as H
    import model_store as MS
    leagues = list(leagues) if leagues is not None else list(WINNER_LEAGUES) + [k for k in H.LEAGUES if k not in WINNER_LEAGUES]
    out = []
    for lg in leagues:
        try:
            recs = MS.load_game_picks(lg, ungraded=not past)
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
            try:                                                # Nov 20: the Money Score (money_score.py)
                import money_score as MSC
                _ms = MSC.score_record(p, lg, hp, day=date_str).get("best")
            except Exception:                                   # noqa: BLE001
                _ms = None
            if _ms:
                best.update(money_score=_ms["score"], money_pick=MSC.label(p, _ms), money_price=_ms["price"],
                            money_chance=_ms["chance"], money_market=MSC.MARKET_NAME[_ms["mkt"]],
                            money_side=_ms["side"],
                            money_line=(None if _ms.get("line") is None else
                                        (_ms["line"] if _ms["side"] in ("home", "over") or _ms["mkt"] == "TOT"
                                         else -_ms["line"])),
                            money=MSC.is_money(lg, _ms, date_str))
                if past:
                    best["money_result"] = MSC.result(_ms)
            if past:                                            # Nov 7: how it went
                fh, fa = p.get("final_home"), p.get("final_away")
                best["final"] = None if fh is None or fa is None else f"{p.get('away')} {fa:g} – {p.get('home')} {fh:g}"
                best["winner_result"] = grade_line(p, "Moneyline", "home" if home else "away", None)
                best["best_result"] = (grade_line(p, best["bet_market"], best.get("bet_side"), best.get("bet_line"))
                                       if best.get("bet_market") else None)
            out.append({"sport": sport, "league": title, "time": _et_time(p.get("kickoff")),
                        "game": f"{p.get('away')} {'vs' if lg == 'TENNIS' else '@'} {p.get('home')}",
                        "winner": team, "chance": chance, "book": book, "price": price,
                        "price_book": p.get("best_home_book") if home else p.get("best_away_book"),
                        "value": value, "use": ml_tag, **best,
                        "_gaps": _lean_gaps(p, lg), **_line_text(p), **spread_move(p, lg),
                        "_rec": {"sport": lg, "home": p.get("home"), "away": p.get("away"), "game_id": p.get("game_id"),
                                 "kickoff": p.get("kickoff")},
                        "_full": dict(p, sport=p.get("sport") or lg)})        # Nov 20: to log any side (Home ticks)
    out.sort(key=lambda r: -r["chance"])
    return out


def _line_text(p: Dict) -> Dict:
    """Nov 14: the book's spread and total, and the model's own numbers, as table text."""
    hs = p.get("home_spread")
    if hs is None and p.get("line") is not None:
        hs = -float(p["line"])
    mm, lt, mt = p.get("model_margin"), p.get("line_total"), p.get("model_total")
    out = {"spread_txt": "", "total_txt": "", "model_txt": ""}
    try:
        if hs is not None:
            fav_home = float(hs) <= 0
            out["spread_txt"] = f"{p['home'] if fav_home else p['away']} {-abs(float(hs)):+g}" if float(hs) else "Pick'em"
        if lt is not None:
            out["total_txt"] = f"{float(lt):g}"
        bits = []
        if mm is not None:
            bits.append(f"{p['home'] if float(mm) >= 0 else p['away']} by {abs(float(mm)):.1f}")
        if mt is not None:
            bits.append(f"total {float(mt):.1f}")
        out["model_txt"] = ", ".join(bits)
    except (TypeError, ValueError, KeyError):
        pass
    return out


def _lean_gaps(p: Dict, lg: str) -> Dict:
    try:
        import pick_records as PR
        return PR.gaps(p, lg)
    except Exception:                                           # noqa: BLE001
        return {}


def soccer_rows(date_str: str, leagues=None, past: bool = False) -> List[Dict]:
    """Nov 14: soccer in the game-lines table -- the goals model's most likely result beside the market's favourite.
    Tracking only (the backtest lost to the closing line), so no pick or value: a read, labeled as such."""
    import model_store as MS
    import soccer_data as D
    import soccer_picks as SP
    if leagues is None:
        leagues = SP.slate_leagues() or list(D.LEAGUES)
    out = []
    for lg in leagues:
        try:
            recs = SP.dedupe(MS.load_game_picks(lg, ungraded=not past))
        except Exception:                                       # noqa: BLE001
            continue
        for p in recs:
            if _et_date(p.get("kickoff")) != date_str or p.get("p_home") is None:
                continue
            probs = {"home": p["p_home"], "draw": p["p_draw"], "away": p["p_away"]}
            side = max(probs, key=probs.get)
            team = {"home": p.get("home"), "away": p.get("away"), "draw": "Draw"}[side]
            price = {"home": p.get("best_home"), "draw": p.get("best_draw"), "away": p.get("best_away")}[side]
            row = {"sport": "SOCCER", "league": D.LEAGUES.get(lg, {}).get("title", lg),
                   "time": _et_time(p.get("kickoff")), "game": f"{p.get('away')} vs {p.get('home')}",
                   "winner": team, "chance": float(probs[side]), "book": None, "price": price,
                   "price_book": p.get(f"book_{side}"), "value": None, "use": "",
                   "best": SP.projected(p), "lean_detail": "market: " + SP.market(p), "status": "tracking only",
                   "bet_market": "Moneyline", "bet_side": side, "bet_line": None, "bet_price": price,
                   "best_chance": None, "best_price": None, "best_value": None, "best_tested": False,
                   "_rec": {"sport": lg, "home": p.get("home"), "away": p.get("away"), "game_id": p.get("game_id"),
                            "kickoff": p.get("kickoff")}}
            if past:
                fh, fa = p.get("final_home"), p.get("final_away")
                row["final"] = None if fh is None or fa is None else f"{p.get('away')} {fa:g} – {p.get('home')} {fh:g}"
                res = p.get("result")
                row["winner_result"] = None if res not in ("home", "draw", "away") else ("win" if res == side else "loss")
                row["best_result"] = row["winner_result"]
            out.append(row)
    out.sort(key=lambda r: -r["chance"])
    return out


def soccer_flags(date_str: str, leagues=None) -> List[Dict]:
    """Nov 14: today's soccer 📈 flags (a US price above the sharp no-vig line by 2%+). Tracking, not tested."""
    import model_store as MS
    import soccer_data as D
    import soccer_picks as SP
    if leagues is None:
        leagues = SP.slate_leagues() or list(D.LEAGUES)
    out = []
    for lg in leagues:
        try:
            recs = SP.dedupe(MS.load_game_picks(lg, ungraded=True))
        except Exception:                                       # noqa: BLE001
            continue
        for p in recs:
            if _et_date(p.get("kickoff")) != date_str:
                continue
            for v in p.get("value") or []:
                side = v.get("side")
                if v.get("market") == "Moneyline":
                    pick = "Draw" if side == "draw" else f"{p.get(side)} to win"
                    line = None
                elif v.get("market") == "Total":
                    pick, line = f"{str(side).title()} {v.get('line'):g} goals", v.get("line")
                else:
                    line = v.get("line")
                    pick = f"{p.get(side)} {line:+g}" if line is not None else f"{p.get(side)} handicap"
                out.append({"sport": "SOCCER", "league": D.LEAGUES.get(lg, {}).get("title", lg),
                            "time": _et_time(p.get("kickoff")), "game": f"{p.get('away')} vs {p.get('home')}",
                            "pick": pick, "market": v.get("market"), "side": side, "line": line,
                            "bet_market": v.get("market"), "bet_side": side, "bet_line": line, "best_tested": False,
                            "price": v.get("price"), "book": v.get("book"), "chance": v.get("fair"),
                            "ev": v.get("ev"), "projected": SP.projected(p),
                            "_rec": {"sport": lg, "home": p.get("home"), "away": p.get("away"),
                                     "game_id": p.get("game_id"), "kickoff": p.get("kickoff")}})
    out.sort(key=lambda r: -(r.get("ev") or 0))
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


# --------------------------------------------------------------------------- logging from Home (Nov 7)
def _int_or_none(v):
    """Nov 15: the Bet Log's player_id is a number; NFL ids ("00-0039065") aren't -- the bet logs without one (it
    settles by player name and game) instead of failing to save."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def bet_rows(items: Sequence[Dict], stake: float, real: bool, tag: str, date_str: str) -> List[Dict]:
    """Bet Log rows for picked Today's-best items (props rows and game-line rows), each at its own (edited) price."""
    import betlog as B
    import intl_picks as IP
    out = []
    for it in items:
        price = it.get("price")
        if price is None:
            continue
        if it.get("_rec"):
            if str(it["_rec"].get("sport", "")).startswith("SOCCER_"):   # Nov 13: soccer's 3-way bets
                import soccer_picks as SP
                bf = SP.bet_fields
            else:
                bf = IP.bet_fields
            f = bf(it["_rec"], it["bet_market"], it["bet_side"], it.get("bet_line"), float(price), stake, real,
                              it.get("best_chance") if it.get("best_tested") else None)
            f["notes"] = ",".join(x for x in (tag, f.get("notes")) if x)
            out.append(f)
            continue
        if it.get("sport") == "UFC" and it.get("market") in ("Moneyline", "Fight Duration") and it.get("side"):
            # Nov 14: the fight card's ticked sides -- graded by ufc_review.bet_result (game "A vs. B")
            out.append({"slate_date": date_str, "sport": "UFC", "game": it.get("game"), "player": None,
                        "market": it["market"], "side": it["side"],
                        "line": 0.0 if it.get("line") is None else float(it["line"]), "entry_odds": float(price),
                        "entry_odds_source": "book", "model_prob": it.get("chance"), "stake": float(stake),
                        "book": it.get("book") or "draftkings", "is_real_bet": bool(real),
                        "category": B.default_category("UFC", from_model=False), "notes": tag or None})
            continue
        if not it.get("player") or not it.get("side") or it.get("line") is None:
            continue                            # Nov 9: never log a prop that can't be graded (no player/side/line)
        out.append({"slate_date": date_str, "sport": it["sport"], "game": it.get("game"), "player": it.get("player"),
                    "player_id": _int_or_none(it.get("pid")), "market": it.get("market"), "side": it.get("side"),
                    "line": None if it.get("line") is None else float(it["line"]), "entry_odds": float(price),
                    "entry_odds_source": "book", "model_prob": it.get("chance"), "stake": float(stake),
                    "book": it.get("book") or "draftkings", "is_real_bet": bool(real),
                    "category": B.default_category(it["sport"], from_model=True),
                    "notes": ",".join(x for x in (tag, it.get("notes_extra")) if x) or None})
    return out


def parlay_odds(prices: Sequence[float]) -> Optional[int]:
    dec = 1.0
    for pr in prices:
        d = _dec(pr)
        if d is None:
            return None
        dec *= d
    return int(round((dec - 1) * 100)) if dec >= 2 else int(round(-100 / (dec - 1)))


def log_selection(items: Sequence[Dict], mode: str, stake: float, parlay_stake: float, parlay_price: Optional[int],
                  real: bool, tag: str, date_str: str, ticket: str = "") -> Dict:
    """Write picked items to the Bet Log: mode "Singles", "Parlay" or "Both". Skips singles already logged today
    (same player, market, side, line). Returns {"singles": [ids], "ticket": header id or None, "skipped": n}."""
    import betlog as B
    rows = bet_rows(items, stake, real, tag, date_str)
    done = {"singles": [], "ticket": None, "skipped": 0}
    if mode in ("Singles", "Both"):
        have = {(b.get("player"), b.get("market"), b.get("side"), b.get("line"))
                for b in B.list_bets() if str(b.get("slate_date")) == date_str and not B._ticket(b)}
        for r in rows:
            k = (r.get("player"), r.get("market"), r.get("side"), r.get("line"))
            if k in have:
                done["skipped"] += 1
                continue
            done["singles"].append(B.add_bet(**r))
    if mode in ("Parlay", "Both") and len(rows) >= 2 and parlay_price is not None:
        legs = [{"player": r["player"], "market": r["market"], "side": r["side"], "line": r["line"], "game": r.get("game"),
                 "model_prob": r.get("model_prob"), "price": r.get("entry_odds"),
                 "note": ",".join(t for t in str(r.get("notes") or "").split(",") if t and t != tag) or None}
                for r in rows]
        sports = {r["sport"] for r in rows}
        name = ticket or f"{'/'.join(sorted(sports))} {len(rows)}-leg {date_str}"
        res = B.log_parlay_ticket(name, legs, int(parlay_price), float(parlay_stake), date_str,
                                  sport=next(iter(sports)) if len(sports) == 1 else "MULTI", book="draftkings",
                                  notes=tag or None)
        done["ticket"] = res.get("header_id")
    return done



# --------------------------------------------------------------------------- blowout watch (Nov 7)
# The Game Script feedback loop (script_learn.py) logs every game's pre-game scenario chances before it starts --
# favorite wins big / underdog wins big / close -- from the line curve that beat the old table on held-out games.
# This ranks a day's games by the chance one side wins big. Earlier dates show what happened (graded calls).
BLOWOUT_SPORTS = ("NBA", "NCAAMB", "NFL", "NCAAF", "NHL")


def _script_from_finals(sp: str, k: Dict, cache: Dict[str, List[Dict]], load=None) -> Optional[str]:
    """Nov 19: how a called game went, from the results archive, when the learning job hasn't graded it yet (on Nov 18
    GitHub skipped its overnight runs, so 7 of 8 games in yesterday's Blowout watch showed no result)."""
    try:
        import intl_hoops as IH
        import model_store as MS
        import scenario_model as M
        import script_effects as SE
        d = (SE.DATA.get(sp) or {})
        if not d.get("blow") or not k.get("fav") or not k.get("dog"):
            return None
        day = _et_date(k.get("kick")) or k.get("d")
        if sp not in cache:
            from datetime import date as _d0, timedelta as _td
            cache[sp] = (load or MS.load_results)(sp, since=(_d0.fromisoformat(str(day)[:10]) - _td(days=1)).isoformat()) or []
        from datetime import date as _date
        d0 = _date.fromisoformat(str(day)[:10])
        loose = sp in ("NCAAMB", "NCAAF")                       # pro teams: exact names only

        def _days(g):
            try:
                return abs((_date.fromisoformat(str(g.get("date"))[:10]) - d0).days)
            except ValueError:
                return 9
        # the same day first (a team plays at most once a day), then the next / previous day (late UTC dates)
        for g in sorted((g for g in cache[sp] if _days(g) <= 1), key=_days):
            hf = IH.find_team([g["home_team"]], k["fav"], loose)
            af = IH.find_team([g["away_team"]], k["fav"], loose)
            if hf and IH.find_team([g["away_team"]], k["dog"], loose):
                m = float(g["home_points"]) - float(g["away_points"])
            elif af and IH.find_team([g["home_team"]], k["dog"], loose):
                m = float(g["away_points"]) - float(g["home_points"])
            else:
                continue
            return M.label(m, d["close"], d["blow"])
    except Exception:                                           # noqa: BLE001 -- a missing result, never an error
        return None
    return None


def blowout_rows(date_str: str, sports_=BLOWOUT_SPORTS, calls_by_sport: Optional[Dict] = None) -> List[Dict]:
    import model_store as MS
    import script_effects as SE
    out = []
    finals_cache: Dict[str, List[Dict]] = {}
    for sp in sports_:
        try:
            cs = (calls_by_sport or {}).get(sp) if calls_by_sport is not None else MS.get_setting(f"scenario_calls:{sp}", None)
        except Exception:                                       # noqa: BLE001
            cs = None
        if not cs:
            continue
        seen = set()
        for k in list(cs.get("pending") or []) + list(cs.get("graded") or []):
            day = _et_date(k.get("kick")) or k.get("d")
            if day != date_str or k.get("gid") in seen or not k.get("p"):
                continue
            seen.add(k["gid"])
            p = k["p"]
            fav_big, dog_big = float(p.get("fav_blowout") or 0), float(p.get("dog_blowout") or 0)
            team, chance, who = (k.get("fav"), fav_big, "favorite") if fav_big >= dog_big else (k.get("dog"), dog_big, "underdog")
            blow = (SE.DATA.get(sp) or {}).get("blow")
            unit = "goals" if SE.FAMILY.get(sp) == "hockey" else "pts"
            strength = k.get("strength")
            line = ("" if strength is None else
                    (f"{k.get('fav')} {float(strength):.0%} to win" if SE.strength_kind(sp) == "ml"
                     else f"{k.get('fav')} −{float(strength):g}"))
            happened = None
            y = k.get("y") or _script_from_finals(sp, k, finals_cache)
            # Nov 19 (owner: "you consider a model chance of <30% a blowout watch?"): a 27% blowout chance isn't a call
            # that the game will be a blowout -- it's the watch list's ranking. The CALL is the outcome the model
            # thought most likely (often "decided, not a blowout"); that is what's graded right or wrong. What
            # happened is stated plainly, with 💥 when it was a blowout.
            probs = {"fav_blowout": fav_big, "dog_blowout": dog_big, "close": float(p.get("close") or 0)}
            probs["middle"] = max(0.0, 1.0 - sum(probs.values()))
            likely = max(probs, key=probs.get)
            names = {"fav_blowout": f"{k.get('fav')} wins big", "dog_blowout": f"{k.get('dog')} wins big",
                     "close": "close game", "middle": "decided, not a blowout"}
            if y:
                happened = {"fav_blowout": f"💥 {k.get('fav')} won big", "dog_blowout": f"💥 {k.get('dog')} won big",
                            "close": "close game", "middle": "decided, not a blowout"}.get(y, y)
            game = (f"{k['away']} @ {k['home']}" if k.get("home") and k.get("away") else f"{k.get('dog')} vs {k.get('fav')}")
            out.append({"sport": sp, "time": _et_time(k.get("kick")), "game": game, "team": team, "who": who,
                        "chance": chance, "fav_big": fav_big, "dog_big": dog_big, "close": float(p.get("close") or 0),
                        "line": line, "margin": f"{blow}+ {unit}" if blow else "", "source": k.get("source") or "table",
                        "happened": happened, "fav_margin": k.get("margin"), "y": y,
                        "blowout_hit": None if not y else y == ("fav_blowout" if who == "favorite" else "dog_blowout"),
                        "likely": f"{names[likely]} ({probs[likely]:.0%})", "likely_chance": probs[likely],
                        "likely_result": None if not y else ("✅" if y == likely else "❌")})
    out.sort(key=lambda r: -r["chance"])
    return out


# --------------------------------------------------------------------------- UFC / MMA card (Nov 7)
def ufc_rows(date_str: str, api_key: Optional[str]) -> List[Dict]:
    """The day's MMA bouts (one odds request for the whole card), earliest first: the market's favorite, its no-vig
    chance and the best price on each fighter. No model: the market's read, labelled as such."""
    if not api_key:
        return []
    import ufc_engine as E
    out = []
    for b in E.main_card_only(E.get_card(api_key, date_str)):  # bouts a major US book prices; stale duplicates out
        ln = E.book_lines(b, "draftkings")
        fav_a = b["p_a"] is not None and b["p_a"] >= 0.5
        fav, dog = (b["a"], b["b"]) if fav_a else (b["b"], b["a"])
        out.append({"sport": "UFC", "time": _et_time(b["commence"]), "game": f"{b['a']} vs {b['b']}",
                    "fav": None if b["p_a"] is None else fav, "dog": None if b["p_a"] is None else dog,
                    "chance": None if b["p_a"] is None else (b["p_a"] if fav_a else 1 - b["p_a"]),
                    "fav_price": b["best_a"] if fav_a else b["best_b"], "dog_price": b["best_b"] if fav_a else b["best_a"],
                    "books": b["books"], "commence": b["commence"], "spread": ln["spread"], "total": ln["total"]})
    out.sort(key=lambda r: r.get("commence") or "")
    return out



# --------------------------------------------------------------------------- is the market moving our way? (Nov 17)
# The owner: "how can we pull and showcase those specific opportunities" -- the ones where the model may be beating the
# book. The best early sign is the market itself moving toward the model's side after the first price (the line moves
# our way, or our side gets more expensive). Tested on graded reads (research/move_test.py, line_history captures):
#   NBA bet-tagged reads: market moved toward us 57.1% (n 84, +3.6% at the first price) vs away 53.4% (-1.6%)
#   NFL bet-tagged reads: toward 61.9% (n 42, +8.5%) vs away 53.1% (-5.9%); all NFL reads toward +5.0% vs away -7.3%
# Small samples -- a tracking signal, shown for NBA and NFL only (NHL's captures didn't match its markets cleanly).
MOVE_SPORTS = ("NBA", "NFL")
MOVE_MIN = 0.02                # 2 points of implied chance (a half point of line counts as 2)
MOVE_LINE_W = 0.04


def _implied(price) -> Optional[float]:
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    return 100 / (p + 100) if p > 0 else -p / (-p + 100)


def move_of(series: List[Dict], side: str) -> Optional[Dict]:
    """From one player/market's captures today: how the read's side moved from the first capture to the latest.
    {"toward": score, "line": (first, last), "chance": (first, last)} or None with fewer than two capture times."""
    rows = sorted([x for x in series if str(x.get("side") or "").lower() == side.lower()
                   and x.get("price") is not None], key=lambda x: str(x.get("captured_at")))
    if len(rows) < 2:
        return None
    t0, t1 = str(rows[0]["captured_at"]), str(rows[-1]["captured_at"])
    if t0[:13] == t1[:13]:
        return None
    first = [x for x in rows if str(x["captured_at"]) == t0]
    last = [x for x in rows if str(x["captured_at"]) == t1]
    def avg(xs, f):
        v = [f(x) for x in xs if f(x) is not None]
        return sum(v) / len(v) if v else None
    pf, pl = avg(first, lambda x: _implied(x["price"])), avg(last, lambda x: _implied(x["price"]))
    lf = avg(first, lambda x: None if x.get("line") is None else float(x["line"]))
    ll = avg(last, lambda x: None if x.get("line") is None else float(x["line"]))
    if pf is None or pl is None:
        return None
    dl = (ll - lf) if (lf is not None and ll is not None) else 0.0
    toward = (pl - pf) + MOVE_LINE_W * (dl if side.lower() in ("over", "yes") else -dl)
    return {"toward": toward, "line": (lf, ll), "chance": (pf, pl)}


def market_moves(sport: str, date_str: str, rows: List[Dict], index=None) -> None:
    """Adds "move" (📈 / 📉 / "") and "move_why" to each of `sport`'s prop rows, from today's line captures."""
    if sport not in MOVE_SPORTS:
        return
    if index is None:
        try:
            import line_history as LH
            index = LH.sport_index(sport, since=date_str)
        except Exception:                                       # noqa: BLE001
            return
    by_player: Dict[str, Dict[str, List[Dict]]] = {}
    for (pl, mk), ser in (index or {}).items():
        by_player.setdefault(PE.norm_name(pl or ""), {})[mk] = ser
    for r in rows:
        if r.get("sport") != sport or r.get("kind") != "Prop" or not r.get("side") or r.get("line") is None:
            continue
        mine = by_player.get(PE.norm_name(r.get("player") or ""), {})
        mk = r.get("market_key")
        if mk not in mine:                                      # older saves: the market whose line matches the pick
            cands = [k for k, ser in mine.items()
                     if any(x.get("line") is not None and float(x["line"]) == float(r["line"]) for x in ser)]
            mk = cands[0] if len(cands) == 1 else None
        m = move_of(mine.get(mk) or [], str(r["side"])) if mk else None
        if not m:
            r["move"], r["move_why"] = "", ""
            continue
        lf, ll = m["line"]
        pf, pl = m["chance"]
        why = (f"line {lf:g} → {ll:g}, " if lf is not None and ll is not None and abs(ll - lf) >= 0.25 else "") + \
              f"{r['side']} {pf:.0%} → {pl:.0%}"
        r["move"] = "📈 our way" if m["toward"] >= MOVE_MIN else ("📉 against" if m["toward"] <= -MOVE_MIN else "")
        r["move_why"] = why



# --------------------------------------------------------------------------- spread moving our way (Nov 17)
# College basketball game lines (research/gl_move.py, 519 graded games with an opening and closing spread): when the
# spread moved 1+ point toward the model's side between the open and the close, the model's side covered 65% at the
# opening number and still 54.7% at the closing number (n 143); when it moved against the model, 39.7% / 47.1% (n 156).
# NBA (99 games) and college football (128) showed no such pattern, so only NCAAMB is marked.
MOVE_GAME_LEAGUES = ("NCAAMB",)
MOVE_GAME_MIN = 1.0             # points of spread


def spread_move(p: Dict, lg: str) -> Dict:
    """{"spread_move": "📈 our way" / "📉 against" / "", "spread_move_why": "Duke -5 → -7"} from the saved opening
    spread to the latest one, judged against the model's side of the CURRENT spread. `line` = the market's expected
    home margin (home -7 -> 7)."""
    out = {"spread_move": "", "spread_move_why": ""}
    if lg not in MOVE_GAME_LEAGUES:
        return out
    try:
        o, l, mm = float(p["open_line"]), float(p["line"]), float(p["model_margin"])
    except (TypeError, ValueError, KeyError):
        return out
    if mm == l:
        return out
    home_side = mm > l
    move = (l - o) if home_side else (o - l)
    team = p.get("home") if home_side else p.get("away")
    sp_o, sp_l = (-o, -l) if home_side else (o, l)
    if abs(move) >= MOVE_GAME_MIN:
        out["spread_move"] = "📈 our way" if move > 0 else "📉 against"
        out["spread_move_why"] = f"{team} {sp_o:+g} → {sp_l:+g}"
    return out
