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

MONEY, BET, GAP, TRACK = "💰 Money pick", "🃏 Bet", "🧪 Close gap (paper)", "🧪 Other tracking"
KINDS = (MONEY, BET, GAP, TRACK)
DEFAULT_KINDS = (MONEY, BET, GAP)
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
        elif verdict.startswith(GP.BET_TRACK):
            out.append(_row(TRACK, sp, r, r["pick"], what="Tracked prop rule — paper only", **args))
    return out


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


def _num(v) -> float:
    return float("nan") if v is None else float(v)              # a blank cell, not the word "None"


def table(rows: Iterable[Dict]) -> List[Dict]:
    """Display rows. A price marked * is the standard -110, used when the boards saved no quote for that side."""
    out = []
    for r in rows:
        price = "—" if r["price"] is None else f"{r['price']:+.0f}" + ("*" if r.get("assumed") else "")
        out.append({"Time": r["time"], "Sport": r["sport"], "Type": r["kind"], "Pick": r["pick"],
                    "Price": price,
                    "Chance": _num(r["chance"]), "Needs": _num(r["need"]), "Edge": _num(r["edge"]),
                    "Line move": r["move"] or "", "Why it's here": r["what"], "Game": r["game"]})
    return out
