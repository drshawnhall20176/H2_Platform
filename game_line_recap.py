"""
game_line_recap.py — the game-line results for the Analyst Desk reports (Nov 24).

Owner: "the analyst desk reports do not include the game lines results. since most sports books do not have NCAAMB
player props we are relegated to game lines." The Analyst Desk's locked calls are player props; this grades the
model's game-line board for a day (todays_best.winner_rows, past=True) in the same four groups the boards show:

- 💰 Money picks (the tested money tag) at the price shown,
- ✅ Model & market agree games (the tracked candidate rule's games), the model's Pick,
- the Pick column (every game's model pick),
- the Likely winner column, at the moneyline price.

Units are 1 unit per pick at the price shown on the board. Nothing here writes anything; the publisher posts the text
once per sport and day (analyst_publisher, kind "recap:lines").
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Dict, List, Optional

LINE_SPORTS = ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB")
GROUPS = [("money", "💰 Money picks"), ("agree", "✅ Model & market agree (Pick)"), ("pick", "Pick column"),
          ("winner", "Likely winner")]


def _units(result: Optional[str], price) -> float:
    if result == "loss":
        return -1.0
    if result != "win":
        return 0.0
    try:
        a = float(price)
    except (TypeError, ValueError):
        return 100 / 110                                        # no price on the record: a standard -110
    return a / 100 if a > 0 else 100 / -a


def _agrees(r: Dict, league: str) -> bool:
    try:
        import game_previews as GP
        p = r.get("_full") or {}
        return bool(p) and GP.agreement(p, league).startswith("✅")
    except Exception:                                           # noqa: BLE001
        return False


def grade_day(league: str, day: str, rows: Optional[List[Dict]] = None) -> Dict[str, Dict]:
    """{group: {w, l, p, units, items: [(result, label)]}} for one league's graded board on `day`."""
    if rows is None:
        import todays_best as TB
        try:
            rows = TB.winner_rows(day, leagues=[league], past=True)
        except Exception:                                       # noqa: BLE001
            rows = []
    out = {k: {"w": 0, "l": 0, "p": 0, "units": 0.0, "items": []} for k, _ in GROUPS}
    # games not final yet: the recap waits for them, but a postponed game or two (never final) can't hold it forever
    _open = sum(1 for r in rows if not r.get("final"))
    out["_pending"] = _open if _open > max(1, len(rows) // 10) else 0

    def add(k, res, price, label):
        if res not in ("win", "loss", "push"):
            return
        g = out[k]
        g[{"win": "w", "loss": "l", "push": "p"}[res]] += 1
        g["units"] += _units(res, price)
        g["items"].append((res, label))

    for r in rows:
        if r.get("money") and r.get("money_pick"):
            add("money", r.get("money_result"), r.get("money_price"), f"{r['money_pick']} ({r.get('game')})")
        if r.get("best"):
            add("pick", r.get("best_result"), r.get("best_price"), r["best"])
            if _agrees(r, league):
                add("agree", r.get("best_result"), r.get("best_price"), f"{r['best']} ({r.get('game')})")
        add("winner", r.get("winner_result"), r.get("price"), f"{r.get('winner')} ML")
    return out


def record_txt(g: Dict) -> str:
    if not (g["w"] or g["l"] or g["p"]):
        return "—"
    return f"{g['w']}–{g['l']}" + (f"–{g['p']}" if g["p"] else "") + f" ({g['units']:+.1f}u)"


def recap_text(league: str, day: str, grade: Optional[Callable] = None, label: Optional[str] = None) -> str:
    """The Discord-ready game-lines recap for one league and day; empty when nothing on the board was graded."""
    gd = (grade or grade_day)(league, day)
    if gd.get("_pending") or not any(gd[k]["w"] or gd[k]["l"] or gd[k]["p"] for k, _ in GROUPS):
        return ""                                               # wait until every game on the day's board is final
    lines = [f"📏 **H2 Sports — game lines recap · {label or league}, {day}**"]
    lines.append(" · ".join(f"{name} {record_txt(gd[k])}" for k, name in GROUPS if record_txt(gd[k]) != "—"))
    icon = {"win": "✅", "loss": "❌", "push": "➖"}
    for k, head in (("money", "💰 Money picks"), ("agree", "✅ Agree games")):
        if gd[k]["items"]:
            lines.append(f"{head}: " + ", ".join(f"{icon[res]} {lab}" for res, lab in gd[k]["items"][:12]))
    lines.append("1 unit per pick at the price on the board. Only 💰 tags have passed testing; the ✅ agree games are "
                 "a candidate rule being tracked forward; the Pick and Likely-winner columns are information.")
    return "\n".join(lines)


def window(league: str, end: str, days: int = 7, grade: Optional[Callable] = None) -> List[Dict]:
    """One row per day (newest first) plus a total row, for the Analyst Desk / Record tables."""
    g = grade or grade_day
    end_d = date.fromisoformat(end)
    tot = {k: {"w": 0, "l": 0, "p": 0, "units": 0.0} for k, _ in GROUPS}
    rows = []
    for i in range(days):
        d = (end_d - timedelta(days=i)).isoformat()
        gd = g(league, d)
        if not any(gd[k]["w"] or gd[k]["l"] or gd[k]["p"] for k, _ in GROUPS):
            continue
        rows.append({"Date": d, **{name: record_txt(gd[k]) for k, name in GROUPS}})
        for k, _ in GROUPS:
            for f in ("w", "l", "p", "units"):
                tot[k][f] += gd[k][f]
    if rows:
        rows.append({"Date": f"Last {days} days", **{name: record_txt(tot[k]) for k, name in GROUPS}})
    return rows
