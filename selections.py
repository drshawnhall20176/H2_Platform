"""
selections.py — shared helpers for the Media Room and Podcast Studio.

Two jobs:
  • filter_known_pitcher: drop plays whose opposing starter is undetermined (TBD). A
    matchup-aware model can't price a hitter against an unknown arm, so those plays must
    never headline a show. Name is MLB-flavored but the behavior generalizes cleanly: WNBA
    plays always carry a real opponent team name (no "unknown starter" concept in basketball),
    so this is a harmless no-op filter for WNBA rather than something that needs its own version.
  • attach_live_ev: join model plays (which carry the reasoning) to the Edge Board's live
    edges (which carry the real price and EV%), so a selection can show true value when the
    user opts to spend odds quota. Without odds, value is left blank — never faked.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from clv_capture import MARKET_TO_ODDS_KEY


def _norm(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


def filter_known_pitcher(plays: List[Dict]) -> List[Dict]:
    """Drop plays where the opposing pitcher is undetermined (TBD/blank)."""
    out = []
    for p in plays:
        opp = (p.get("Opp") or "").strip().upper()
        if opp in ("", "TBD"):
            continue
        out.append(p)
    return out


def attach_live_ev(plays: List[Dict], edges: List[Dict],
                   market_map: Optional[Dict[str, str]] = None) -> List[Dict]:
    """Annotate each play with LivePrice and EV from matching Edge Board edges.

    Edges use the Odds API market key and the live point/price; plays use the display market.
    HR is a single-line market, so its point is ignored when matching.

    `market_map` overrides MLB's default MARKET_TO_ODDS_KEY — pass sports.active().market_map
    for any non-MLB sport, the same pattern odds_api.compute_edges already uses."""
    mmap = market_map if market_map is not None else MARKET_TO_ODDS_KEY
    idx: Dict = {}
    for e in edges:
        idx.setdefault((_norm(e.get("Player")), e.get("Market"), e.get("Side")), []) \
            .append((e.get("Line"), e.get("Price"), e.get("EV%")))

    for p in plays:
        okey = mmap.get(p.get("Market"))
        cands = idx.get((_norm(p.get("Player")), okey, p.get("Side")), [])
        is_hr = okey == "batter_home_runs"
        price = ev = None
        for pt, pr, e in cands:
            if is_hr or pt == p.get("Line"):
                price, ev = pr, e
                break
        p["LivePrice"], p["EV"] = price, ev
    return plays
