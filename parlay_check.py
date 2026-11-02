"""
parlay_check.py — check a ticket before it's placed (Nov 2).

Paste the legs, give the payout, and each leg is read by the model (the same Player props read the boards use,
at the leg's own line -- a "50+" alt line is read at 49.5), turned into an HONEST chance (calibration.py), and the
ticket is priced: the chance it cashes, the chance it misses by exactly one leg, its value at the payout, the
weakest leg, and same-game legs whose game scripts pull against each other.

Leg lines: "Player | Market | Over | 49.5 | -300"  (price optional), or "Player | Market | 50+" for an alt line.
A leg the model has no read for uses the price you give (with the book's typical cut removed); with no price it's
priced as a coin flip and flagged.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

import props_engine as PE

STRONG_CHANCE = 0.65            # a leg in a 5+ leg ticket should be this likely ...
STRONG_CUSHION = 0.15           # ... with the projection this far past the line (the 🔒 Most probable bar)
LONG_TICKET = 5
BOOK_CUT = 0.045                # an alt / one-sided price carries roughly this much margin

# Which game script a leg needs, for its own team: "lead" (ahead, running the clock) or "trail" (behind, throwing).
_LEAD = {("RB", "Rush Attempts", "Over"), ("RB", "Rush Yards", "Over"), ("QB", "Pass Attempts", "Under"),
         ("QB", "Pass Completions", "Under"), ("QB", "Pass Yards", "Under")}
_TRAIL = {("QB", "Pass Attempts", "Over"), ("QB", "Pass Completions", "Over"), ("QB", "Pass Yards", "Over"),
          ("RB", "Rush Attempts", "Under"), ("RB", "Rush Yards", "Under")}


def parse(text: str) -> Tuple[List[Dict], List[str]]:
    legs, bad = [], []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            bad.append(f"“{line}” — needs Player | Market | Over 49.5 (or 50+)")
            continue
        player, market, rest = parts[0], parts[1], parts[2:]
        side, val, price = None, None, None
        m = re.match(r"^(\d+(?:\.\d+)?)\s*\+$", rest[0])
        if m:                                                     # "50+" = Over 49.5
            side, val = "Over", float(m.group(1)) - 0.5
            rest = rest[1:]
        else:
            m2 = re.match(r"^(over|under|o|u)\s*(\d+(?:\.\d+)?)?$", rest[0], re.I)
            if not m2:
                bad.append(f"“{line}” — the side should be Over / Under (or an alt like 50+)")
                continue
            side = "Over" if m2.group(1).lower() in ("over", "o") else "Under"
            if m2.group(2):
                val = float(m2.group(2))
                rest = rest[1:]
            elif len(rest) > 1:
                try:
                    val = float(rest[1])
                except ValueError:
                    bad.append(f"“{line}” — the line “{rest[1]}” isn't a number")
                    continue
                rest = rest[2:]
            else:
                bad.append(f"“{line}” — no line")
                continue
        if rest and rest[0]:
            try:
                price = float(rest[0].replace("−", "-"))
            except ValueError:
                bad.append(f"“{line}” — the price “{rest[0]}” isn't an American price")
                continue
        legs.append({"player": player, "market": market, "side": side, "line": val, "price": price})
    return legs, bad


def _find(reads: Dict, player: str, market: str) -> Optional[Dict]:
    pn, mk = PE.norm_name(player), str(market).strip().lower()
    best = None
    for row in (reads or {}).values():
        if str(row.get("market") or "").lower() != mk:
            continue
        rn = PE.norm_name(row.get("player"))
        if rn == pn:
            return row
        if best is None and pn and rn and pn.split()[-1] == rn.split()[-1] and pn[0] == rn[0]:
            best = row
    return best


def _implied(price: Optional[float]) -> Optional[float]:
    d = PE.decimal(price) if price is not None else None
    return None if d is None else min(max(1.0 / d - BOOK_CUT / 2, 0.01), 0.99)


def read_leg(leg: Dict, reads: Dict, sport: Optional[str]) -> Dict:
    """The leg with "p" (honest chance), "source", "projection", "cushion", "game", "team", "slot", "flags"."""
    import calibration as CAL
    row = _find(reads, leg["player"], leg["market"])
    out = dict(leg, source=None, projection=None, cushion=None, game=None, team=None, slot=None, flags=[])
    p = None
    if row is not None and row.get("projection") is not None and not row.get("out"):
        out.update(projection=row["projection"], game=row.get("game"), team=row.get("team_name") or row.get("team_id"),
                   slot=row.get("slot"))
        if row.get("line") is not None and abs(float(row["line"]) - leg["line"]) < 1e-9 and row.get("p_final") is not None:
            p = row["p_final"] if leg["side"] == "Over" else 1 - row["p_final"]
            out["source"] = "model + books (the board's line)"
        else:
            po = PE.prob_over(row["projection"], row.get("values") or [], leg["line"], row.get("dist") or "normal",
                              *(row.get("sd_floor") or (0.25, 1.0)))
            if po is not None:
                p = po if leg["side"] == "Over" else 1 - po
                out["source"] = "model (alt line)"
        out["cushion"] = PE.cushion(row["projection"], leg["line"], leg["side"])
        if row.get("gap") == "big" or row.get("lean") == "Check news":
            out["flags"].append("the books disagree with the model a lot here — check news")
    elif row is not None and row.get("out"):
        out["flags"].append("listed OUT")
        p = 0.0
        out["source"] = "ruled out"
    if p is None and leg.get("price") is not None:
        p = _implied(leg["price"])
        out["source"] = "your price (no model read)"
    if p is None:
        p = 0.5
        out["source"] = "no read and no price — counted as a coin flip"
        out["flags"].append("no model read: add the price")
    out["p_raw"] = p
    out["p"] = CAL.chance(sport, p, leg["market"]) if out["source"] and out["source"].startswith("model") else p
    return out


def _group(slot: Optional[str]) -> str:
    return "".join(c for c in str(slot or "") if c.isalpha())


def script_conflicts(legs: Sequence[Dict]) -> List[str]:
    """Same-team legs that need opposite game scripts (one needs the team ahead, another behind)."""
    need: Dict = {}
    for l in legs:
        key = (_group(l.get("slot")), l["market"], l["side"])
        team = l.get("team")
        if team is None:
            continue
        if key in _LEAD:
            need.setdefault(team, {}).setdefault("lead", []).append(l["player"])
        elif key in _TRAIL:
            need.setdefault(team, {}).setdefault("trail", []).append(l["player"])
    out = []
    for team, d in need.items():
        if d.get("lead") and d.get("trail"):
            out.append(f"{team}: {', '.join(d['lead'])} need(s) them ahead and running, "
                       f"{', '.join(d['trail'])} need(s) them behind and throwing — those rarely both happen.")
    return out


def check(legs: Sequence[Dict], payout_american: Optional[float] = None) -> Dict:
    """{"legs", "p_all", "p_miss_one", "dist", "ev", "fair_american", "weakest", "warnings"} for read legs."""
    import slip_lab as SL
    ps = [float(l["p"]) for l in legs]
    dist = SL.poisson_binomial(ps) if ps else [1.0]
    k = len(ps)
    p_all = dist[k] if k else 0.0
    p_miss1 = dist[k - 1] if k >= 1 else 0.0
    dec = PE.decimal(payout_american) if payout_american is not None else None
    warnings = []
    weakest = min(legs, key=lambda l: l["p"]) if legs else None
    if k >= LONG_TICKET:
        thin = [l for l in legs if l["p"] < STRONG_CHANCE or (l.get("cushion") is not None and l["cushion"] < STRONG_CUSHION)]
        if thin:
            warnings.append(f"{len(thin)} of {k} legs are below the bar for a long ticket "
                            f"({STRONG_CHANCE:.0%}+ to hit, {STRONG_CUSHION:.0%}+ cushion): "
                            + ", ".join(f"{l['player']} ({l['p']:.0%})" for l in thin))
    if any(l["p"] < 0.5 for l in legs) and k >= 3:
        warnings.append("a leg under 50% sinks most long tickets — play it as a single or in a 2-leg")
    warnings += script_conflicts(legs)
    games = {}
    for l in legs:
        if l.get("game"):
            games.setdefault(l["game"], []).append(l["player"])
    same = {g: ps_ for g, ps_ in games.items() if len(ps_) > 1}
    if same:
        warnings.append("Same-game legs move together, so the real chance can be well above or below the "
                        "multiplied one: " + "; ".join(f"{g} ({len(v)})" for g, v in same.items()))
    return {"legs": list(legs), "p_all": p_all, "p_miss_one": p_miss1, "dist": dist,
            "ev": (p_all * dec - 1) if dec else None, "fair_american": PE.american(p_all) if p_all else None,
            "weakest": weakest, "warnings": warnings}
