"""
long_shots.py — alternate-line ("8+ assists at +1500") value finder (Nov 10).

The owner hit Jeremiah Fears 8+ assists at +1500 / +1840 and 6+ at +499 (Nov 9): the props model projected 6.0 assists
against a 4.5 line. The question was how to see an outlier like that coming. The model already computes the chance of
any milestone (props_engine.milestone_chance); the books post prices on those milestones (the "_alternate" player
markets). This compares the two.

HONEST CHANCES FIRST. The raw model is not honest in the tail (research/tail_calibration.py, NBA walk-forward,
~2,750 player-games per market, rungs above each projection): when it said 20-30% the rung happened ~16-20%; when it
said under 5% it happened 2-4x more often. So every chance is multiplied by the measured ratio for its market and
band (TAIL below) before it's compared with a price. Re-run that research to refresh the table.
"""
from __future__ import annotations

from typing import Dict, List, Optional

# market -> [(band low, band high, measured happened/said)] (NBA, Nov 10 walk-forward)
_BANDS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 0.30), (0.30, 0.40), (0.40, 0.55), (0.55, 1.01)]
TAIL = {
    "Points":      [2.0, 1.34, 0.86, 0.76, 0.65, 0.69, 0.72, 0.80],
    "Rebounds":    [2.0, 1.07, 0.83, 0.96, 0.76, 0.77, 0.87, 0.90],
    "Assists":     [1.73, 0.98, 1.00, 0.89, 0.78, 0.81, 0.78, 0.85],
    "Threes Made": [2.0, 1.08, 1.02, 0.84, 0.84, 0.81, 0.83, 0.88],
    "PRA":         [2.0, 1.29, 0.87, 0.69, 0.70, 0.63, 0.69, 0.78],
}
COMBOS = {"PR", "PA", "RA", "Pts+Reb", "Pts+Ast", "Reb+Ast", "Pts+Reb+Ast"}
ALT_TO_MAIN = {"player_points_alternate": "player_points", "player_rebounds_alternate": "player_rebounds",
               "player_assists_alternate": "player_assists", "player_threes_alternate": "player_threes",
               "player_points_rebounds_assists_alternate": "player_points_rebounds_assists",
               "player_points_rebounds_alternate": "player_points_rebounds",
               "player_points_assists_alternate": "player_points_assists",
               "player_rebounds_assists_alternate": "player_rebounds_assists"}
MIN_REAL = 0.04            # don't show rungs the honest chance puts under 4%
MAX_SHOWN_ODDS = 3000


def honest(p: Optional[float], market: str) -> Optional[float]:
    if p is None:
        return None
    key = "PRA" if market in COMBOS else market
    ratios = TAIL.get(key)
    if not ratios:
        return p
    for (lo, hi), r in zip(_BANDS, ratios):
        if lo <= p < hi:
            return max(0.0, min(0.99, p * r))
    return p


def implied(odds: float) -> float:
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)


def finder(reads: Dict, quotes: List[Dict], norm, prob_over) -> List[Dict]:
    """reads: the props model's slate reads {(pid, odds market key): row}; quotes: book_menu quotes for alternate
    markets. Returns one row per Over rung with a price, best value first."""
    by = {}
    for (_pid, mk), r in (reads or {}).items():
        by[(norm(r.get("player") or ""), mk)] = r
    out = []
    for q in quotes or []:
        main = ALT_TO_MAIN.get(q.get("market"))
        if not main or str(q.get("name")).lower() != "over" or q.get("point") is None:
            continue
        r = by.get((norm(q.get("description") or ""), main))
        if not r or r.get("projection") is None or r.get("out"):
            continue
        n = float(q["point"]) + 0.5                              # "Over 7.5" = 8+
        floor = r.get("sd_floor") or (0.25, 1.0)
        raw = prob_over(r["projection"], r.get("values") or [], n - 0.5, r.get("dist") or "normal", *floor)
        real = honest(raw, r.get("market") or "")
        price = float(q["price"])
        if real is None or real < MIN_REAL or price > MAX_SHOWN_ODDS:
            continue
        imp = implied(price)
        dec = 1 + (price / 100 if price > 0 else 100 / -price)
        ev = real * dec - 1
        main_line = r.get("line")
        gap = None if main_line is None else (r["projection"] - main_line)
        flags = []
        if r.get("gap") == "big" or r.get("lean") == "Check news":
            flags.append("projection far from the book's line — check news first")
        if len(r.get("values") or []) < 6:
            flags.append(f"only {len(r.get('values') or [])} recent games")
        out.append({"Player": r.get("player"), "Team": r.get("team"), "Game": r.get("game"), "Market": r.get("market"),
                    "Bet": f"{n:g}+ {r.get('market')}", "Price": price, "Book says": imp, "Model raw": raw,
                    "Honest chance": real, "Edge": real - imp, "EV per $1": ev, "Projection": r["projection"],
                    "Main line": main_line, "Gap": gap, "Flags": "; ".join(flags), "_n": n,
                    "player": r.get("player"), "market": r.get("market"), "side": "Over", "line": n - 0.5,
                    "game": r.get("game"), "chance": real, "price": price, "pid": r.get("player_id")})
    out.sort(key=lambda x: -x["EV per $1"])
    return out
