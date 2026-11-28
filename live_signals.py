"""
live_signals.py -- every live edge the Live page flags, kept at its first sighting and graded when the game ends (Nov 27).

Owner, Nov 27: "now we need to make sure the live game data is the best it can be so users can try and catch live
bets." A live edge is only worth trusting if we can show how live edges have done, so:
  * the first time a live line shows the model's edge of MIN_EDGE or more (🟢 Worth a look) -- a game line (spread,
    total, moneyline) or a player prop -- it is saved with the price, the model's chance and the game clock right then.
    Later refreshes never overwrite it (model_store.add_blobs_once), so the record is what a viewer could have bet at
    the moment it first showed, not the best price it reached.
  * when the game is final it is graded from the final score (game lines) or the final box score (props).
  * the record is paper: one unit per signal at the price it showed. Model signals only -- nobody's bets.
Stored in blob_cache, kind "live_signal", key "YYYY-MM-DD|league|game id|bet" so a day's signals are one key range.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Callable, Dict, Iterable, List, Optional

KIND = "live_signal"
# Nov 27: v2 = live props priced at one main line, blended toward the books' no-vig chance. The props kept on the first
# night (every alternate line at the best price anywhere, ~200 a game) are left out of the record -- noise, not edges.
VER = 2
MIN_EDGE = 0.05
STALE_EDGE = 0.20         # an edge this big usually means the book's line hasn't caught up with the game yet


def key(day: str, league: str, game_id, bet: str) -> str:
    return f"{str(day)[:10]}|{league}|{game_id}|{bet}"


def worth(b: Dict) -> bool:
    e = b.get("edge")
    return e is not None and e >= MIN_EDGE and b.get("price") is not None


def row(day: str, g: Dict, b: Dict, clock: str, now_iso: str) -> Dict:
    return {"day": str(day)[:10], "league": g.get("league"), "game_id": str(g.get("id")),
            "event_id": str(g.get("event_id") or ""), "game": f"{g.get('away')} @ {g.get('home')}",
            "home": g.get("home"), "away": g.get("away"), "type": b.get("market"), "bet": b.get("bet"),
            "side": b.get("side"), "line": b.get("line"), "player": b.get("player"), "stat": b.get("stat"),
            "price": b.get("price"), "chance": b.get("chance"), "edge": b.get("edge"), "clock": clock,
            "score": f"{g.get('away_score', 0):.0f}–{g.get('home_score', 0):.0f}", "seen_at": now_iso,
            "result": None, "ver": VER}


def _ms():
    import model_store as MS
    return MS


def record_new(day: str, g: Dict, bets: Iterable[Dict], clock: str, now_iso: str, seen: Optional[set] = None,
               save: Optional[Callable] = None) -> int:
    """Save each 🟢 bet not yet saved for this game. `seen` (a per-session set) skips the store for ones already sent."""
    items = {}
    for b in bets or []:
        if not worth(b) or not b.get("bet"):
            continue
        k = key(day, g.get("league"), g.get("id"), b["bet"])
        if seen is not None and k in seen:
            continue
        items[k] = json.dumps(row(day, g, b, clock, now_iso), default=str)
    if not items:
        return 0
    if save is None:
        MS = _ms()
        save = getattr(MS, "add_blobs_once", None)
        if save is None:                                        # an app that hasn't restarted since this shipped
            return 0
        save = lambda it, _s=save: _s(KIND, it)                 # noqa: E731
    n = save(items)
    if seen is not None and n:
        seen.update(items)
    return n


def load(since_day: str, get: Optional[Callable] = None) -> List[Dict]:
    """Every saved signal from since_day on, as rows (each with its "key")."""
    if get is None:
        f = getattr(_ms(), "blobs_since", None)
        if f is None:
            return []
        get = lambda s: f(KIND, s)                              # noqa: E731
    out = []
    for k, v in (get(str(since_day)[:10]) or {}).items():
        try:
            r = json.loads(v)
        except (TypeError, ValueError):
            continue
        r["key"] = k
        out.append(r)
    return sorted(out, key=lambda r: str(r.get("seen_at") or ""))


# --------------------------------------------------------------------------- grading
def _cmp(x: float) -> str:
    return "win" if x > 1e-9 else "loss" if x < -1e-9 else "push"


def grade(sig: Dict, g: Dict, box_value: Optional[float] = None) -> Optional[str]:
    """'win' / 'loss' / 'push' from the final game (and, for a prop, his final number); None if it can't be told."""
    if g.get("state") != "post":
        return None
    hs, as_ = float(g.get("home_score") or 0), float(g.get("away_score") or 0)
    t, side, line = sig.get("type"), sig.get("side"), sig.get("line")
    if t == "Spread" and side in ("home", "away") and line is not None:
        m = (hs - as_) if side == "home" else (as_ - hs)
        return _cmp(m + float(line))
    if t == "Total" and side in ("over", "under") and line is not None:
        d = hs + as_ - float(line)
        return _cmp(d if side == "over" else -d)
    if t == "Moneyline" and side in ("home", "away"):
        if hs == as_:
            return "push"
        return "win" if (hs > as_) == (side == "home") else "loss"
    if t == "Prop" and side in ("over", "under") and line is not None and box_value is not None:
        d = float(box_value) - float(line)
        return _cmp(d if side == "over" else -d)
    return None


def profit(result: Optional[str], price) -> float:
    if result == "win":
        p = float(price)
        return p / 100 if p > 0 else 100 / -p
    return -1.0 if result == "loss" else 0.0


def grade_rows(rows: List[Dict], final_game: Callable[[Dict], Optional[Dict]],
               prop_value: Callable[[Dict, Dict], Optional[float]]) -> Dict[str, str]:
    """{key: payload} for the ungraded rows whose game is now final."""
    out = {}
    for r in rows:
        if r.get("result"):
            continue
        g = final_game(r)
        if not g:
            continue
        res = grade(r, g, prop_value(r, g) if r.get("type") == "Prop" else None)
        if res is None and r.get("type") == "Prop" and g.get("state") == "post":
            res = "void"                                        # final, but no line for him in the box score
        if res:
            r2 = {k: v for k, v in r.items() if k != "key"}
            r2["result"] = res
            r2["final"] = f"{float(g.get('away_score') or 0):.0f}–{float(g.get('home_score') or 0):.0f}"
            out[r["key"]] = json.dumps(r2, default=str)
    return out


def prop_value_from(summary_for: Callable[[str, str], Dict]):
    def f(r: Dict, g: Dict) -> Optional[float]:
        import live_props as LP
        bx = LP.box(summary_for(r["league"], r.get("event_id") or g.get("event_id")))
        rec = bx.get(LP._norm(r.get("player")))
        if not rec or rec.get("dnp"):
            return None
        return LP.current(rec, r.get("stat"), r["league"])
    return f


def grade_pending(days: Iterable[str], games_for: Callable[[str, date], List[Dict]],
                  summary_for: Callable[[str, str], Dict], save: Optional[Callable] = None,
                  rows: Optional[List[Dict]] = None) -> int:
    """Grade every ungraded signal from `days` whose game has ended. Returns how many were graded."""
    days = sorted({str(d)[:10] for d in days})
    if not days:
        return 0
    rows = [r for r in (rows if rows is not None else load(days[0])) if r.get("day") in days and not r.get("result")]
    if not rows:
        return 0
    boards: Dict = {}

    def final_game(r):
        k = (r["league"], r["day"])
        if k not in boards:
            try:
                boards[k] = {str(g.get("id")): g for g in games_for(r["league"], date.fromisoformat(r["day"]))}
            except Exception:                                   # noqa: BLE001
                boards[k] = {}
        g = boards[k].get(str(r.get("game_id")))
        return g if g and g.get("state") == "post" else None
    out = grade_rows(rows, final_game, prop_value_from(summary_for))
    if out:
        if save is None:
            save = lambda it: _ms().save_blobs(KIND, it)        # noqa: E731
        save(out)
    return len(out)


# --------------------------------------------------------------------------- the record
def record(rows: Iterable[Dict]) -> Dict:
    """{"n", "w", "l", "p", "units", "roi", "by": {type: {...}}, "open"} -- graded signals at 1 unit each."""
    def blank():
        return {"n": 0, "w": 0, "l": 0, "p": 0, "units": 0.0}
    tot, by, open_ = blank(), {}, 0
    for r in rows:
        if r.get("type") == "Prop" and int(r.get("ver") or 1) < VER:
            continue
        res = r.get("result")
        if not res:
            open_ += 1
            continue
        if res == "void":
            continue
        for d in (tot, by.setdefault(r.get("type") or "?", blank())):
            d["n"] += 1
            d["w" if res == "win" else "l" if res == "loss" else "p"] += 1
            d["units"] += profit(res, r.get("price"))
    for d in [tot] + list(by.values()):
        d["roi"] = d["units"] / d["n"] if d["n"] else None
    tot["by"], tot["open"] = by, open_
    return tot


def record_text(rec: Dict) -> str:
    if not rec.get("n"):
        return "No live edges graded yet."
    s = f"{rec['w']}–{rec['l']}" + (f"–{rec['p']}" if rec["p"] else "")
    return f"{s} · {rec['units']:+.1f} units · {rec['roi']:+.1%} a bet"


def since(today: date, days: int = 30) -> str:
    return (today - timedelta(days=days)).isoformat()


def count_for_games(rows: Iterable[Dict], day: str) -> Dict[str, int]:
    """{game id: live edges flagged today} for the Today page's Live-now strip."""
    out: Dict[str, int] = {}
    for r in rows:
        if r.get("day") == str(day)[:10]:
            out[str(r.get("game_id"))] = out.get(str(r.get("game_id")), 0) + 1
    return out
