"""
focus_list.py -- the owner's test list: every 🃏 Bet, 💰 Money pick and 🧪 close-gap pick of the day, across every
sport, in one place (Nov 26).

Owner: "there is no section on the site ... that gives me a filtered list of all the 'bet', 'money picks' and
paper-track the close gap picks in one visible section across all sports for a given day ... put it in the owner
office since that will help me focus my testing on only those picks. Obviously updated as lines move."

Reads only what the boards already saved (no new odds calls):
  * player props  -- todays_best.collect rows: 💰 when the row's money flag is on; 🃏 when its Bet? verdict
                     (game_previews.prop_bet, the earned-chance rule included) is a bet; other 🧪 prop rules on request;
  * game lines    -- todays_best.winner_rows: 💰 the Money Score pick; 🃏 a tested line pick (lock / playable Use);
                     🧪 close gap -- college basketball games where the model and the market are within 2 points
                     (candidate_rules' rule), the model's side of the spread at the CURRENT line: paper-track only.
The boards rebuild hourly and the game captures refresh the lines through the day, so the list follows the market.
"""
from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional

MONEY, BET, GAP, TRACK = "💰 Money pick", "🃏 Bet", "🧪 Close gap (paper)", "🧪 Prop rule (paper)"
PAUSED, HELD = "⏸ Paused / off rule (paper)", "📉 Tag held back (paper)"
KINDS = (MONEY, BET, GAP, TRACK, PAUSED, HELD)
REAL = (MONEY, BET)                                             # the rest are paper: tracked, never sized
# Nov 26 (owner: "include player props in all sports ... and any other rules that are paused. We need to keep testing
# all aspects until we can get to a baseline we agree is solid"): every kind on by default.
DEFAULT_KINDS = KINDS
CLOSE_GAP_MAX = 2.0


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def breakeven(price) -> Optional[float]:
    p = _f(price)
    if p is None or -100 < p < 100:
        return None
    return 100 / (p + 100) if p > 0 else -p / (-p + 100)


def _row(kind: str, sport: str, r: Dict, pick: str, price, chance, book=None, what: str = "", move: str = "",
         open_as: str = "player", src: Optional[Dict] = None, **how) -> Dict:
    """`how`: what the book check needs -- props: player, market_key, side, line; games: market, side, line,
    home, away."""
    be = breakeven(price)
    ch = _f(chance)
    return {"kind": kind, "sport": sport, "time": r.get("time") or "", "game": r.get("game") or "", "pick": pick,
            "price": _f(price), "book": book or "", "chance": ch, "need": be,
            "edge": None if ch is None or be is None else ch - be, "what": what, "move": move,
            "open_as": open_as, "src": src if src is not None else r, **how}


def prop_rows(rows: Iterable[Dict], bet_of: Optional[Callable] = None, track_of: Optional[Callable] = None) -> List[Dict]:
    """💰 / 🃏 / other-🧪 player props. `bet_of(row)` -> the Bet? verdict (default game_previews.prop_bet)."""
    import game_previews as GP
    if bet_of is None:
        def bet_of(r):
            use = ("💰 " if r.get("money") else "") + ("🔒 " if r.get("lock") else "") + str(r.get("use") or "")
            return GP.prop_bet(r.get("sport") or "", use, r)
    out = []
    for r in rows or []:
        if r.get("kind") not in (None, "Prop") or not r.get("pick"):
            continue
        sp = r.get("sport") or ""
        verdict = str(bet_of(r) or "")
        args = dict(price=r.get("price"), chance=r.get("chance"), book=r.get("book"), move=r.get("move") or "",
                    player=r.get("player"), market_key=r.get("market_key"), side=r.get("side") or "Over",
                    line=_f(r.get("line")))
        if r.get("money"):
            out.append(_row(MONEY, sp, r, r["pick"], what="Money pick (live test)", **args))
        elif verdict.startswith(GP.BET_YES):
            out.append(_row(BET, sp, r, r["pick"], what=str(r.get("use") or "Tested tag"), **args))
        elif r.get("money_band"):
            out.append(_row(PAUSED, sp, r, r["pick"], what="💰 rule — off for this sport or market today", **args))
        elif r.get("lock_rule") and not r.get("lock"):
            out.append(_row(PAUSED, sp, r, r["pick"], what="🔒 Most probable — market switched off by its record",
                            **args))
        elif _prop_rule(sp, r):
            out.append(_row(TRACK, sp, r, r["pick"], what="NFL / college football Under rule — tested forward",
                            **args))
        elif verdict.startswith(GP.BET_TRACK):
            short = GP.earned_short(r)
            what = (f"{r.get('use')} — earned {short['earned']:.0%}, the price needs {short['needed']:.0%}" if short
                    else "Tracked — paper only")
            out.append(_row(HELD if short else TRACK, sp, r, r["pick"], what=what, **args))
    return out


def _prop_rule(sport: str, r: Dict) -> bool:
    """The NFL / college football Under rules (candidate_rules.PROP_RULES) on a saved row: the model's own chance and
    the books' no-vig chance of the side."""
    if r.get("p_market") is None:
        return False
    try:
        import game_previews as GP
        return GP.prop_tracking(sport, {"Side": r.get("side"), "ModelProb": r.get("raw_chance", r.get("chance")),
                                        "MarketProb": r.get("p_market"), "Line": r.get("line"),
                                        "PricedAt": r.get("book"), "PriceSource": r.get("price_src")})
    except Exception:                                           # noqa: BLE001
        return False


def merge_props(*groups: Iterable[Dict]) -> List[Dict]:
    """One row per prop across the saved lists (every read, and the playable list): the first copy wins, except that
    a copy carrying the paper-rule flags replaces one without them."""
    out: Dict[tuple, Dict] = {}
    for g in groups:
        for r in g or []:
            k = (r.get("sport"), r.get("pick"))
            if k not in out or ("money_band" in r and "money_band" not in out[k]):
                out[k] = r
    return list(out.values())


def close_gap(p: Dict) -> Optional[Dict]:
    """The close-gap pick of a college basketball game record at its current line, or None."""
    hs, mm = _f(p.get("home_spread")), _f(p.get("model_margin"))
    if hs is None or mm is None:
        return None
    d = mm + hs
    if d == 0 or abs(d) >= CLOSE_GAP_MAX:
        return None
    side = "home" if d > 0 else "away"
    line = hs if side == "home" else -hs
    price = None
    try:
        import intl_picks as IP
        price = IP.spread_price_for(p, side)
    except Exception:                                           # noqa: BLE001
        price = None
    return {"pick": f"{p.get(side)} {line:+g}", "price": price if price is not None else -110, "gap": abs(d),
            "assumed": price is None, "side": side, "line": line}


def game_rows(winners: Iterable[Dict]) -> List[Dict]:
    """💰 / 🃏 / 🧪 close-gap game lines from the day's game boards."""
    import todays_best as TB
    out = []
    for w in winners or []:
        sp = w.get("sport") or ""
        move = w.get("spread_move") or ""
        full = w.get("_full") or {}
        teams = dict(home=full.get("home"), away=full.get("away"))
        if not w.get("money") and w.get("money_pick") and _money_score_band(w):
            out.append(_row(PAUSED, sp, w, w["money_pick"], w.get("money_price"), w.get("money_chance"),
                            what=f"💰 game-line rule (paused) — Money Score {float(w['money_score']):+.0%}",
                            move=move, open_as="game", market=w.get("money_market"), side=w.get("money_side"),
                            line=_f(w.get("money_line")), **teams))
        if w.get("money") and w.get("money_pick"):
            out.append(_row(MONEY, sp, w, w["money_pick"], w.get("money_price"), w.get("money_chance"),
                            what=f"Money Score {w.get('money_score'):+.0%}" if _f(w.get("money_score")) is not None
                            else "Money pick (live test)", move=move, open_as="game",
                            market=w.get("money_market"), side=w.get("money_side"), line=_f(w.get("money_line")),
                            **teams))
        if w.get("best") and (w.get("lock") or w.get("use") in TB.PLAYABLE):
            if not (w.get("money") and w.get("money_pick") == w.get("best")):
                out.append(_row(BET, sp, w, w["best"], w.get("best_price"), w.get("best_chance"),
                                what="Tested line rule", move=move, open_as="game",
                                market=w.get("bet_market"), side=w.get("bet_side"), line=_f(w.get("bet_line")),
                                **teams))
        if sp == "NCAAMB":
            cg = close_gap(full)
            if cg:
                row = _row(GAP, sp, w, cg["pick"], cg["price"], None,
                           what=f"Model and market {cg['gap']:.1f} pts apart — paper-track", move=move, open_as="game",
                           market="Spread", side=cg["side"], line=cg["line"], **teams)
                row["assumed"] = cg["assumed"]
                out.append(row)
    return out


def _money_score_band(w: Dict) -> bool:
    """A game line the 💰 Money Score rule would flag if it weren't paused (money_score: BAND, MIN_CHANCE, markets)."""
    try:
        import money_score as MSC
        sc, ch = _f(w.get("money_score")), _f(w.get("money_chance"))
        names = {MSC.MARKET_NAME.get(m) for m in MSC.MONEY_MARKETS}
        return (w.get("sport") in MSC.MONEY_LEAGUES and sc is not None and MSC.BAND[0] <= sc < MSC.BAND[1]
                and ch is not None and ch >= MSC.MIN_CHANCE and w.get("money_market") in names)
    except Exception:                                           # noqa: BLE001
        return False


def build(prop_src: Iterable[Dict], winners: Iterable[Dict], kinds: Iterable[str] = DEFAULT_KINDS,
          sports: Optional[Iterable[str]] = None, parse_time: Optional[Callable] = None,
          bet_of: Optional[Callable] = None) -> List[Dict]:
    """The filtered list, earliest start first (the owner's rule), then 💰, 🃏, 🧪, then the biggest edge."""
    kinds = set(kinds or DEFAULT_KINDS)
    sports = set(sports) if sports else None
    rows = prop_rows(prop_src, bet_of) + game_rows(winners)
    rows = [r for r in rows if r["kind"] in kinds and (sports is None or r["sport"] in sports)]
    order = {k: i for i, k in enumerate(KINDS)}

    def key(r):
        t = None
        if parse_time is not None:
            try:
                t = parse_time(r.get("time"))
            except Exception:                                   # noqa: BLE001
                t = None
        return (t is None, str(t or r.get("time") or ""), order.get(r["kind"], 9), -(r["edge"] or -1))
    return sorted(rows, key=key)


def counts(rows: Iterable[Dict]) -> Dict[str, int]:
    out = {k: 0 for k in KINDS}
    for r in rows or []:
        out[r["kind"]] = out.get(r["kind"], 0) + 1
    return out


def pct(v, signed: bool = False) -> str:
    """A percent as text, "—" when missing (Streamlit draws any missing number as a grey "None")."""
    if v is None:
        return "—"
    return f"{float(v) * 100:+.1f}%" if signed else f"{float(v):.1%}"


def table(rows: Iterable[Dict]) -> List[Dict]:
    """Display rows. A price marked * is the standard -110, used when the boards saved no quote for that side."""
    out = []
    for r in rows:
        price = "—" if r["price"] is None else f"{r['price']:+.0f}" + ("*" if r.get("assumed") else "")
        out.append({"Time": r["time"], "Sport": r["sport"], "Bet or paper": "Bet" if r["kind"] in REAL else "Paper",
                    "Type": r["kind"], "Pick": r["pick"],
                    "Price": price,
                    "Chance": pct(r["chance"]), "Needs": pct(r["need"]), "Edge": pct(r["edge"], True),
                    "Line move": r["move"] or "", "Why it's here": r["what"], "Game": r["game"]})
    return out


# --------------------------------------------------------------------------- logging (Nov 26)
def log_item(r: Dict, book: str) -> Optional[Dict]:
    """One Test-list row as a todays_best.log_selection item, at the chosen book's current price when it posts the
    pick's line (else the boards' price and book). Each carries what kind of call it was, so the Bet Log and My Coach
    file it right: 💰 -> "money-pick", 🧪 close gap -> "close-gap-test", 🃏 -> a tested pick at its earned chance."""
    use_book = r.get("book_price") is not None and r.get("book_line") == r.get("line")
    price = r.get("book_price") if use_book else r.get("price")
    if price is None:
        return None
    src = r.get("src") or {}
    if r.get("open_as") == "game":
        rec = src.get("_rec")
        if not rec or not r.get("market") or not r.get("side"):
            return None
        return {"_rec": rec, "bet_market": r["market"], "bet_side": r["side"], "bet_line": r.get("line"),
                "price": float(price), "best_chance": r.get("chance"), "best_tested": r["kind"] in (BET, MONEY),
                "tracking": r["kind"] == GAP, "note": "💰" if r["kind"] == MONEY else "",
                "book": book if use_book else (r.get("book") or "draftkings")}
    if not src.get("player") or r.get("line") is None:
        return None
    return {"sport": r["sport"], "game": src.get("game"), "player": src.get("player"), "pid": src.get("pid"),
            "market": src.get("market"), "side": src.get("side") or r.get("side"), "line": r.get("line"),
            "price": float(price), "chance": r.get("chance"),
            "book": book if use_book else (src.get("book") or "draftkings"),
            "notes_extra": {MONEY: "money-pick", TRACK: "tracked-rule", PAUSED: "paused-rule",
                            HELD: "held-back"}.get(r["kind"])}
