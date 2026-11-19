"""
money_review.py — which sports get 💰 Money picks, re-decided every week from the graded record (Nov 19).

Owner: "this should be updated on some recurring basis. Sports with short seasons should be accounted for some how."

Every Monday (money-review workflow, kept on schedule by clockwork) each props sport's graded pre-game reads in the
money band (props_engine.MONEY_BAND: the model 6-15% better than the sportsbook price; pick'em-only lines and markets
with no record of their own left out) are scored at the price they carried:

  * TURN ON when the sport's last MAX_READS band reads (at least MIN_READS, over at least MIN_DAYS[sport] slate
    days) returned at least ON_ROI per $1, the low end of the 90% range (resampling whole slate days) is above zero,
    and both halves of the window (by date) made money.
  * TURN OFF a sport that's on when that window lost money AND its later half lost money too -- one cold week
    doesn't flip it, a fading edge does.
  * Otherwise keep what it is.

Short seasons: the window is the last MAX_READS reads, not the last N days -- a nightly sport (NBA, ~80 band reads a
night) refreshes it within a month; a weekly one (NFL, college football) keeps building it week after week, and
across seasons, so a short season is judged on enough games instead of a few Sundays. MIN_DAYS counts game days, set
lower for the weekly sports (6 weeks) than the nightly ones (10 nights). A sport with no new graded reads since the
last decision (out of season) keeps its verdict untouched; when its next season starts, the window still holds the
end of last season until this season's reads replace it.
"""
from __future__ import annotations

import random
import sys
from datetime import date, datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence

SPORTS = ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB")
KEY = "money:rules"
MAX_READS = 2000
MIN_READS = 300
MIN_DAYS = {"NFL": 6, "NCAAF": 6}          # weekly sports: game days (weeks); everyone else: MIN_DAYS_NIGHTLY
MIN_DAYS_NIGHTLY = 10
ON_ROI = 0.02
EVERY_DAYS = 6                             # re-decided once a week (Monday), whatever day the job runs


def _roi(rows: Sequence[Dict]) -> float:
    return sum((r["dec"] - 1) if r["hit"] else -1.0 for r in rows) / len(rows)


def scored(sport: str, graded: Sequence[Dict]) -> List[Dict]:
    """Graded reads in the money band with a sportsbook price: [{date, dec, hit}], oldest first."""
    import postgame as PG
    import props_engine as PE
    out = []
    for r in graded:
        r = PG.as_tagged(r) if r.get("bet_use_tag") else r
        if r.get("result") not in ("hit", "miss"):
            continue
        d = PE.decimal(r.get("price"))
        if not d or not PE.in_money_band(sport, r.get("ev"), r.get("book"), market=r.get("market")):
            continue
        out.append({"date": str(r.get("slate_date")), "dec": d, "hit": r["result"] == "hit"})
    out.sort(key=lambda x: x["date"])
    return out


def evaluate(sport: str, rows: Sequence[Dict], was_on: bool, seed: int = 1) -> Dict:
    """The verdict for one sport from its band reads (oldest first)."""
    rows = list(rows)[-MAX_READS:]
    days = sorted({r["date"] for r in rows})
    need_days = MIN_DAYS.get(sport, MIN_DAYS_NIGHTLY)
    base = {"sport": sport, "was_on": was_on, "n": len(rows), "days": len(days), "first": days[0] if days else None,
            "last": days[-1] if days else None}
    if len(rows) < MIN_READS or len(days) < need_days:
        return {**base, "on": was_on, "changed": False,
                "why": f"{len(rows)} reads over {len(days)} game days — needs {MIN_READS} over {need_days} to decide"}
    roi = _roi(rows)
    half = len(rows) // 2
    h1, h2 = _roi(rows[:half]), _roi(rows[half:])
    byd = {d: [r for r in rows if r["date"] == d] for d in days}
    rng = random.Random(seed)
    boots = sorted(_roi([r for d in rng.choices(days, k=len(days)) for r in byd[d]]) for _ in range(1000))
    lo, hi = boots[50], boots[949]
    stats = {**base, "roi": roi, "halves": [h1, h2], "range90": [lo, hi],
             "hit": sum(r["hit"] for r in rows) / len(rows), "needed": sum(1 / r["dec"] for r in rows) / len(rows)}
    if not was_on and roi >= ON_ROI and lo > 0 and h1 > 0 and h2 > 0:
        return {**stats, "on": True, "changed": True,
                "why": f"{roi:+.1%} per $1 over {len(rows)} reads, both halves up, 90% range {lo:+.1%}..{hi:+.1%}"}
    if was_on and roi < 0 and h2 < 0:
        return {**stats, "on": False, "changed": True,
                "why": f"{roi:+.1%} per $1 over {len(rows)} reads and the later half {h2:+.1%} — the edge has faded"}
    return {**stats, "on": was_on, "changed": False,
            "why": f"{roi:+.1%} per $1 over {len(rows)} reads (halves {h1:+.1%} / {h2:+.1%}, 90% range "
                   f"{lo:+.1%}..{hi:+.1%})"}


def due(saved: Optional[Dict], today: date) -> bool:
    if not saved or not saved.get("at"):
        return True
    try:
        last = date.fromisoformat(str(saved["at"])[:10])
    except ValueError:
        return True
    return (today - last).days >= EVERY_DAYS and today.weekday() == 0 or (today - last).days >= 8


def run(today: Optional[date] = None, force: bool = False, grade: Optional[Callable] = None, get=None, save=None,
        write: bool = True) -> Optional[Dict]:
    import model_store as MS
    import props_engine as PE
    today = today or datetime.now(timezone.utc).date()
    get = get or MS.get_setting
    save = save or MS.save_setting
    saved = get(KEY, None)
    if not force and not due(saved, today):
        print(f"money review: last run {saved.get('at', '')[:10]} — not due")
        return None
    if grade is None:
        import daily_review as DR

        def grade(sp):
            g = DR.grade_dates(sp, MS.snapshot_dates(sp))
            return [r for rows in g.values() for r in rows]
    prev = (saved or {}).get("sports") or {}
    out = {}
    for sp in SPORTS:
        was_on = bool((prev.get(sp) or {}).get("on", sp in PE.MONEY_DEFAULT))
        try:
            rows = scored(sp, grade(sp))
        except Exception as exc:                                # noqa: BLE001 -- one sport never stops the rest
            print(f"[{sp}] money review failed: {type(exc).__name__}: {exc}")
            if sp in prev:
                out[sp] = prev[sp]
            continue
        last = (prev.get(sp) or {}).get("last")
        if prev.get(sp) and rows and last and rows[-1]["date"] <= last:
            out[sp] = {**prev[sp], "changed": False, "why": "no new games since the last review (out of season) — "
                                                             "verdict kept"}
        else:
            out[sp] = evaluate(sp, rows, was_on)
        v = out[sp]
        print(f"[{sp}] 💰 {'ON' if v['on'] else 'off'}{' (changed)' if v.get('changed') else ''}: {v['why']}")
    rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sports": out}
    if write:
        save(KEY, rec)
        try:
            notes = [f"{today.isoformat()}: 💰 Money picks {'turned ON' if v['on'] else 'turned off'} for {sp} — "
                     f"{v['why']}." for sp, v in out.items() if v.get("changed")]
            MS.save_daily_review("MONEY", today.isoformat(), {
                "notes": notes, "money_auto": [{"sport": sp, "changed": bool(v.get("changed")), "text":
                                                f"💰 Money picks {'ON' if v['on'] else 'off'} for {sp} ({v['why']})"}
                                               for sp, v in out.items()]})
        except Exception as exc:                                # noqa: BLE001
            print(f"money review note failed: {type(exc).__name__}: {exc}")
    return rec


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    run(force="--force" in argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
