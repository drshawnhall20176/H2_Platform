"""
soft_spots.py — tonight's softest defense-vs-position spots, NBA (Nov 25, second PropSeason pass).

PropSeason's Cheat Sheet lists the defenses that give up the most to a position and the players who line up there --
"context, not a call". H2's version keeps the context and adds what they don't have: each player's H2 pick on
tonight's board (if any) with its earned chance and Bet? verdict, so a soft spot never reads as a pick by itself.

The numbers come from the same league sample Position Matchups uses (position_data.load_bundle): every NBA defense's
average allowed per game to guards / forwards / centers over its recent games, ranked 1 (gives up the most) to 30.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

STATS = {"pts": "points", "reb": "rebounds", "ast": "assists", "fg3m": "threes"}
SLOT_NAME = {"G": "guards", "F": "forwards", "C": "centers"}
SOFT_PCT = 0.10          # at least 10% above the league average
MIN_GAMES = 3


def table(summary: Dict, stat: str) -> Dict[str, Dict[str, Tuple[float, int, float]]]:
    """{slot: {defense: (allowed per game, rank 1 = most, % above league average)}} for one stat, defenses with
    MIN_GAMES+ games."""
    out: Dict[str, Dict] = {}
    for slot in SLOT_NAME:
        rows = [(d, float((s.get(slot) or {}).get("stats", {}).get(stat) or 0.0))
                for d, s in summary.items() if (s.get(slot) or {}).get("games", 0) >= MIN_GAMES]
        if len(rows) < 5:
            continue
        avg = sum(v for _, v in rows) / len(rows)
        rows.sort(key=lambda r: (-r[1], str(r[0])))
        out[slot] = {d: (v, i + 1, (v / avg - 1) if avg else 0.0) for i, (d, v) in enumerate(rows)}
    return out


def spots(summary: Dict, tonight: Sequence[Tuple], depth_of: Callable, names: Dict,
          stats: Sequence[str] = tuple(STATS), slots: Sequence[str] = tuple(SLOT_NAME)) -> List[Dict]:
    """Tonight's soft spots, softest first. `tonight`: [(defense id, offense id, game label, time)]. `depth_of(team)`
    -> {slot: [{"name", "avg_min", ...}]} (most minutes first)."""
    out = []
    for st in stats:
        tb = table(summary, st)
        for de, off, label, when in tonight:
            for slot in slots:
                rec = (tb.get(slot) or {}).get(de)
                if not rec or rec[2] < SOFT_PCT:
                    continue
                try:
                    players = [p for p in (depth_of(off) or {}).get(slot) or [] if (p.get("avg_min") or 0) >= 10][:4]
                except Exception:                               # noqa: BLE001
                    players = []
                out.append({"defense": names.get(de, de), "offense": names.get(off, off), "slot": slot, "stat": st,
                            "allowed": rec[0], "rank": rec[1], "pct": rec[2], "of": len(tb[slot]), "game": label,
                            "time": when, "players": players})
    return sorted(out, key=lambda s: -s["pct"])


def ordinal(n: int) -> str:
    return "most" if n == 1 else f"{n}{'tsnrhtdd'[(n // 10 % 10 != 1) * (n % 10 < 4) * n % 10::4]} most"


def headline(s: Dict) -> str:
    return (f"{s['defense']} allows the {ordinal(s['rank'])} {STATS[s['stat']]} to {SLOT_NAME[s['slot']]} "
            f"({s['allowed']:.1f} a game, {s['pct']:+.0%} vs the average defense, of {s['of']} teams)")


def pick_for(name: str, rows: Sequence[Dict], stat: Optional[str] = None) -> Optional[Dict]:
    """The player's H2 pick on tonight's board: the one in this stat when there is one, else his strongest."""
    import re
    key = re.sub(r"[^a-z]", "", str(name or "").lower())
    mine = [r for r in rows or [] if r.get("kind") == "Prop"
            and re.sub(r"[^a-z]", "", str(r.get("player") or "").lower()) == key]
    if not mine:
        return None
    word = {"pts": "point", "reb": "rebound", "ast": "assist", "fg3m": "three"}.get(stat or "", "")
    same = [r for r in mine if word and word in str(r.get("market") or "").lower()]
    return max(same or mine, key=lambda r: r.get("chance") or 0)
