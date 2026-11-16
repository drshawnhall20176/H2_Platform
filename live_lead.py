"""
live_lead.py — what the Live Games page leads with (Nov 16).

The live board listed games in start order: at 9 PM the one-point game with two minutes left could sit under four
blowouts. It now leads with a short summary and puts the closest game first; and when nothing is live it shows what
is coming next with the model's pre-game read, instead of a bare start-time list.

Pure helpers (no Streamlit, no network) so the ordering and the wording are testable.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, List, Optional

CLOSE = 0.65            # the leader under this win chance = a game still in the balance
NEXT_N = 8


def lead_chance(win_home: Optional[float]) -> Optional[float]:
    """The current leader's win chance (always 50-100%)."""
    return None if win_home is None else max(float(win_home), 1 - float(win_home))


def order_live(items: List[Dict]) -> List[Dict]:
    """Live games, the closest first. Each item: {"win_home": float or None, ...}; games with no live read keep
    their given (start-time) order at the end."""
    read = [it for it in items if it.get("win_home") is not None]
    rest = [it for it in items if it.get("win_home") is None]
    read.sort(key=lambda it: lead_chance(it["win_home"]))       # stable: start order within a tie
    return read + rest


def swing(win_home: Optional[float], start_home: Optional[float]) -> Optional[float]:
    """How far the home win chance has moved since the start (signed)."""
    if win_home is None or start_home is None:
        return None
    return float(win_home) - float(start_home)


def summary(items: List[Dict], n_later: int, n_done: int) -> List[Dict]:
    """Tiles for the top of the board: live count, the closest game, the biggest swing since the start, later / final.
    Each item: {"label": "Away @ Home", "leader": name, "win_home", "start_home"}."""
    tiles = [{"icon": "🔴", "value": str(len(items)), "label": "Live now"}]
    read = [it for it in items if it.get("win_home") is not None]
    if read:
        c = min(read, key=lambda it: lead_chance(it["win_home"]))
        tiles.append({"icon": "⚖️", "value": f"{lead_chance(c['win_home']):.0%}",
                      "label": f"Closest: {c['label']} ({c['leader']} ahead)"})
        moved = [(abs(swing(it["win_home"], it.get("start_home")) or 0), it) for it in read]
        size, m = max(moved, key=lambda x: x[0])
        if size >= 0.10:
            s = swing(m["win_home"], m["start_home"])
            who = m["home"] if s > 0 else m["away"]
            tiles.append({"icon": "📈", "value": f"+{size:.0%}", "label": f"Biggest swing: {who} ({m['label']})",
                          "trend": "good"})
    tiles.append({"icon": "🕐", "value": str(n_later), "label": "Still to start today"})
    tiles.append({"icon": "🏁", "value": str(n_done), "label": "Final"})
    return tiles


def starts_in(kick: Optional[datetime], now: datetime) -> str:
    if kick is None:
        return ""
    mins = int((kick - now).total_seconds() // 60)
    if mins <= 0:
        return "any minute"
    return f"{mins} min" if mins < 60 else f"{mins // 60} h {mins % 60:02d} min"


def next_up(later: List[Dict], pre_for: Callable[[Dict], Optional[Dict]], win_home_for: Callable[[Dict, Dict], Optional[float]],
            when: Callable[[Dict], Optional[datetime]], now: datetime, n: int = NEXT_N) -> List[Dict]:
    """Rows for the games still to start, earliest first, with the pre-game read where there is one (the first n;
    the rest list the start only, so a 60-game college Saturday doesn't make 60 look-ups)."""
    rows = []
    for i, g in enumerate(later):
        row = {"Start": g.get("detail") or g.get("kickoff"), "Starts in": starts_in(when(g), now),
               "Game": f"{g.get('away')} @ {g.get('home')}", "Pre-game favourite": "—", "Projected score": "—"}
        pre = pre_for(g) if i < n else None
        if pre and pre.get("model_margin") is not None and pre.get("model_total") is not None:
            m, t = float(pre["model_margin"]), float(pre["model_total"])
            row["Projected score"] = f"{(t - m) / 2:.0f}–{(t + m) / 2:.0f}"
            p = win_home_for(g, pre)
            if p is not None:
                row["Pre-game favourite"] = f"{g.get('home')} {p:.0%}" if p >= 0.5 else f"{g.get('away')} {1 - p:.0%}"
        rows.append(row)
    return rows
