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


# --------------------------------------------------------------------------- look back (Nov 10)
# A past night has no saved "values" (the player's recent games), only what the props model said before tip-off
# (model_store snapshots): projection, main line, and its chance of the Over at that line. The spread is re-fitted so
# the model gives that same main-line chance, then the rungs above the line are priced from it. Close to what the
# page would have shown live, not identical.
COUNT_MARKETS = {"Rebounds", "Assists", "Blocks", "Steals", "Threes Made"}
LADDER = {"Points": 5, "PRA": 5, "PR": 5, "PA": 5, "PB": 5, "RA": 2, "Rebounds": 2, "Assists": 2,
          "Threes Made": 1, "Blocks": 1, "Steals": 1}
MAX_RUNGS = 6
# The saved main-line chance is shrunk toward 50% (calibration + market blend), so fitting a spread to it can make the
# tails far too fat. Cap it near the widest the live model uses (count variance x mean; normal sd x projection).
SPREAD_CAP = {"count": 1.8, "normal": 0.38}
MAIN_TO_ALT = {v: k for k, v in ALT_TO_MAIN.items()}


def fit(snap: Dict) -> Optional[Dict]:
    """{"projection", "dist", "spread"} reproducing the snapshot's main-line chance, or the model's default spread."""
    import props_engine as PE
    proj, line = snap.get("projection"), snap.get("line")
    if proj is None or line is None:
        return None
    proj, line = float(proj), float(line)
    dist = "count" if snap.get("market") in COUNT_MARKETS else "normal"
    p = snap.get("p_model")
    thr = PE.threshold(line)
    if dist == "count":
        spread = proj * 1.25                                    # the model's typical over-dispersion
        if p is not None and 0.02 < p < 0.98 and proj > 0:
            lo, hi = proj * 1.0001, proj * 6
            if (PE.count_sf(proj, lo, PE.k_needed(line)) - p) * (PE.count_sf(proj, hi, PE.k_needed(line)) - p) < 0:
                for _ in range(40):
                    mid = (lo + hi) / 2
                    f_lo = PE.count_sf(proj, lo, PE.k_needed(line)) - p
                    f_mid = PE.count_sf(proj, mid, PE.k_needed(line)) - p
                    lo, hi = (lo, mid) if f_lo * f_mid <= 0 else (mid, hi)
                spread = (lo + hi) / 2
        spread = min(spread, proj * SPREAD_CAP["count"])
    else:
        spread = max(0.25 * max(proj, 1.0), 1.0)
        if p is not None and 0.02 < p < 0.98 and abs(thr - proj) > 0.5:
            from statistics import NormalDist
            z = NormalDist().inv_cdf(1 - p)
            if z != 0 and (thr - proj) / z > 0:
                spread = max((thr - proj) / z, 0.5)
        spread = min(spread, max(SPREAD_CAP["normal"] * proj, 1.5))
    return {"projection": proj, "dist": dist, "spread": spread}


def rung_raw(f: Dict, n: float) -> float:
    import props_engine as PE
    if f["dist"] == "count":
        p = PE.count_sf(max(f["projection"], 0.0), f["spread"], int(n))
    else:
        p = PE.normal_sf(f["projection"], f["spread"], n - 0.5)
    return max(0.001, min(0.99, p))


def _dedupe(snaps: List[Dict]) -> List[Dict]:
    best = {}
    for s in snaps:
        k = (s.get("player"), s.get("market"), s.get("game"))
        if k not in best or str(s.get("ts") or "") > str(best[k].get("ts") or ""):
            best[k] = s
    return list(best.values())


def lookback(graded: List[Dict], quotes: Optional[List[Dict]] = None, norm=None) -> List[Dict]:
    """graded: postgame.grade() rows for one night (a snapshot + its "actual"). One row per rung above the main
    line: the honest chance, whether it happened, and (when that night's alternate prices were loaded) the price."""
    import props_engine as PE
    norm = norm or (lambda s: str(s or "").lower())
    prices = {}
    for q in quotes or []:
        main = ALT_TO_MAIN.get(q.get("market"))
        if main and str(q.get("name")).lower() == "over" and q.get("point") is not None:
            prices[(norm(q.get("description")), main, float(q["point"]) + 0.5)] = float(q["price"])
    out = []
    for s in _dedupe(graded):
        f = fit(s)
        mk = s.get("market") or ""
        if not f or (mk not in TAIL and mk not in COMBOS and mk not in LADDER):
            continue
        step = LADDER.get(mk, 1)
        start = PE.k_needed(float(s["line"]))
        first = (start // step + 1) * step if step > 1 else start + 1
        actual = s.get("actual")
        okey = _MAIN_KEY.get(mk)
        for i in range(MAX_RUNGS):
            n = first + i * step
            raw = rung_raw(f, n)
            real = honest(raw, mk)
            if real is None or real < MIN_REAL / 2:
                break
            price = prices.get((norm(s.get("player")), okey, float(n))) if okey else None
            row = {"Player": s.get("player"), "Game": s.get("game"), "Market": mk, "Bet": f"{n:g}+ {mk}",
                   "Honest chance": real, "Model raw": raw, "Fair price": PE.american(real),
                   "Price": price, "Book says": implied(price) if price else None,
                   "EV per $1": (real * (1 + (price / 100 if price > 0 else 100 / -price)) - 1) if price else None,
                   "Actual": actual, "Hit": None if actual is None else ("✅" if actual >= n else "❌"),
                   "Projection": f["projection"], "Main line": float(s["line"]), "_n": n}
            out.append(row)
    out.sort(key=lambda r: (r["Hit"] != "✅", r["Honest chance"]))
    return out


_MAIN_KEY = {"Points": "player_points", "Rebounds": "player_rebounds", "Assists": "player_assists",
             "Threes Made": "player_threes", "PRA": "player_points_rebounds_assists", "PR": "player_points_rebounds",
             "PA": "player_points_assists", "RA": "player_rebounds_assists"}


def night_summary(rows: List[Dict]) -> Dict:
    """How the honest chances held up: rungs graded, hits expected (sum of chances) vs hits that happened."""
    done = [r for r in rows if r["Hit"] is not None]
    return {"rungs": len(done), "expected": sum(r["Honest chance"] for r in done),
            "hits": sum(r["Hit"] == "✅" for r in done)}
