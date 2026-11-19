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


def rescore(sport: str, r: Dict) -> Optional[Dict]:
    """Nov 19 (owner's re-test): one graded read as TODAY's model reads it -- the current blend weight, side factors
    and trust toward the books' price, from the saved model and market chances -- the side it would play, its edge
    at the price that side carried, and whether it won. None without both prices or a final stat.

    Why: on Nov 17 the model began leaning harder on the books (calibration trust 0.54, Points 0.30). Edges the old
    model called 6-15% mostly shrink under it, so a record scored with the edges saved at the time judges a flag the
    live board no longer produces (research/money_retest.py)."""
    import calibration as CAL
    import props_engine as PE
    if r.get("actual") is None or r.get("p_model") is None or r.get("p_market") is None:
        return None
    op, up = r.get("over_price"), r.get("under_price")
    if op is None or up is None:
        return None
    w = PE.weight_for({}, sport, r.get("market"))
    if str(r.get("gap") or "").startswith("big"):
        w = min(w, PE.GAP_MODEL_WEIGHT)
    pm = float(r["p_market"])
    p = PE.blend(float(r["p_model"]), pm, w)
    p = CAL.apply_side(p, CAL.side_factors(sport))
    p = CAL.apply_trust(p, pm, CAL.trust(sport, r.get("market")))
    thr = PE.threshold(float(r["line"]))
    if r["actual"] == thr:
        return None
    best = None
    for side, pr, ps in (("Over", op, p), ("Under", up, 1 - p)):
        dec = PE.decimal(pr)
        if dec and (best is None or ps * dec - 1 > best["ev"]):
            best = {"side": side, "ev": ps * dec - 1, "dec": dec, "hit": (r["actual"] > thr) == (side == "Over")}
    return best


def scored(sport: str, graded: Sequence[Dict]) -> List[Dict]:
    """Graded reads the CURRENT model puts in the money band, with a sportsbook price: [{date, dec, hit}], oldest
    first (rescore: the edges as today's model would show them, not as they were saved)."""
    import props_engine as PE
    out = []
    for r in graded:
        if (r.get("book") or "") in PE.PICKEM_BOOKS:
            continue
        x = rescore(sport, r)
        if x is None or not PE.in_money_band(sport, x["ev"], r.get("book"), market=r.get("market")):
            continue
        out.append({"date": str(r.get("slate_date")), "dec": x["dec"], "hit": x["hit"]})
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
        # Nov 19: on needs evidence -- too few reads under the current model turns a sport off, not keeps it on
        why = f"{len(rows)} reads over {len(days)} game days — needs {MIN_READS} over {need_days} to decide"
        if rows:
            why += f" (so far {_roi(rows):+.1%} per $1)"
        return {**base, "on": False, "changed": was_on, "why": why}
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
