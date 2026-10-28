"""
form_policy.py — ONE definition of a player's recent form, used by every page that shows it (Position Matchups'
Player props, Hot Hand Engine, Matchup Lab), so the same player never shows three different "recent" numbers.

THE RULE
  * This season's regular-season games come first (preseason never counts unless there's nothing else).
  * While a player has fewer than MIN_CURRENT games this season, his log is topped up to MIN_CURRENT from the end of
    LAST regular season -- and those older games count half (PRIOR_WEIGHT): a different role, team or body.
  * Within that, newer games count more: half-life HALF_LIFE games (props_engine.recency_weights).
  * At most WINDOW games.

Why these numbers: three games is too few to trust on their own (a single 30-point night swings a three-game
average by 6), but last April's games describe last April's role. Five games with old ones at half weight is a
middle ground; the Scorecard tab is where this gets checked against results.

Each game line carries "src" ("current" / "prior" / "preseason"), the engines' own convention
(nba_engine.get_player_recent_games). A line without "src" counts as current.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import props_engine as PE

MIN_CURRENT = 5
PRIOR_WEIGHT = 0.5
WINDOW = 10
HALF_LIFE = PE.HALF_LIFE


def _src(line: Dict) -> str:
    return str(line.get("src") or "current")


def select(log: Sequence[Dict], window: int = WINDOW, min_current: int = MIN_CURRENT) -> List[Dict]:
    """The games form is built from, newest first: this season's, topped up from last season to `min_current`;
    preseason only when there is nothing else."""
    current = [g for g in log if _src(g) == "current"]
    prior = [g for g in log if _src(g) == "prior"]
    pre = [g for g in log if _src(g) == "preseason"]
    out = list(current[:window])
    if len(out) < min_current and prior:
        out += prior[: min_current - len(out)]
    if not out:
        out = pre[:window]
    return out


def weights(lines: Sequence[Dict]) -> List[float]:
    """Recency weight x source weight for each selected line (newest first)."""
    rec = PE.recency_weights(len(lines), HALF_LIFE)
    return [w * (PRIOR_WEIGHT if _src(g) == "prior" else 1.0) for w, g in zip(rec, lines)]


def form_avg(log: Sequence[Dict], key, window: int = WINDOW) -> Optional[float]:
    """Weighted form for `key` (a stat name, or a function of the line) over the selected games."""
    lines = select(log, window)
    if not lines:
        return None
    f = key if callable(key) else (lambda g: PE.num(g.get(key)))
    w = weights(lines)
    tot = sum(w)
    return sum(f(g) * x for g, x in zip(lines, w)) / tot if tot else None


def describe(log: Sequence[Dict], window: int = WINDOW) -> Dict:
    """{"games", "current", "prior", "note"} -- what the form number is made of, for a caption."""
    lines = select(log, window)
    cur = sum(1 for g in lines if _src(g) == "current")
    pri = sum(1 for g in lines if _src(g) == "prior")
    note = f"{cur} game{'s' if cur != 1 else ''} this season" + (f" + {pri} from last season (half weight)" if pri else "")
    return {"games": len(lines), "current": cur, "prior": pri, "note": note}


def window_avg(log: Sequence[Dict], key: str, n: int) -> Dict:
    """A plain last-N average (what a sportsbook's "last N" column shows), this season first and topped up from
    last season when this season is shorter than N. {"avg", "games", "prior"}; avg None with no games."""
    current = [g for g in log if _src(g) == "current"]
    prior = [g for g in log if _src(g) == "prior"]
    lines = current[:n] + (prior[: n - len(current)] if len(current) < n else [])
    if not lines:
        return {"avg": None, "games": 0, "prior": 0}
    vals = [PE.num(g.get(key)) for g in lines]
    return {"avg": sum(vals) / len(vals), "games": len(lines),
            "prior": sum(1 for g in lines if _src(g) == "prior")}


def rest_text(rest_days: Optional[int]) -> str:
    """The one way every page words rest: 'back-to-back', '1 day off', '2 days off', 'rest unknown'.
    rest_days is days since the last game (1 = played yesterday)."""
    if rest_days is None:
        return "rest unknown"
    if rest_days <= 1:
        return "back-to-back"
    off = rest_days - 1
    return f"{off} day{'s' if off != 1 else ''} off"
