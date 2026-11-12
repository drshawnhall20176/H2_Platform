"""
daily_review.py — the 3:30 AM ET morning review (Oct 31).

Every morning, after the last West Coast games are final, this does what the owners were doing by hand in the
Postgame Review: for every sport with a slate (or open bets) it

  1. grades yesterday's kickoff snapshots against ESPN's box scores (postgame.fetch_results / grade -- the same code
     the Postgame Review page uses), and summarises them: the model's side, each Use tag's hit rate, each market,
     the "line far from the projection" props, the star-out props, why the misses missed, and the biggest misses;
  2. lists the projection adjustments the last 30 days point to. These are SUGGESTIONS -- nothing changes the model
     until an owner approves one on the Postgame Review page;
  3. settles open Bet Log props by name against the final box (prop_settlement.build_plan) and then settles any
     parlay ticket whose legs now decide it. Anything uncertain -- a DNP, a name the box spells differently, a game
     that isn't final -- is left open and listed in the report.

The report is stored in the model store (daily_reviews) and shown on Postgame Review → 🌅 Morning report.

Scheduling: the workflow fires at 07:30 and 08:30 UTC; only the run where it is 3 AM in New York does the work, so
the review lands at 3:30 AM ET on both sides of daylight saving. `--force` (or DAILY_REVIEW_FORCE=1) runs it at any
hour; `--date YYYY-MM-DD` reviews that morning instead of today.

Like settle_results.py it REQUIRES DATABASE_URL (the store the app reads); without it it refuses to run.

    python daily_review.py [--force] [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

import betlog as B
import model_store as MS
import postgame as PG
import prop_settlement as PS
import props_engine as PE

ET = ZoneInfo("America/New_York")
RUN_HOUR_ET = 3
TREND_DAYS = 30            # the window suggestions look across (the Postgame Review page's default)
CATCH_UP_DAYS = 3          # also re-grade the last few slates if their report still had games pending
TOP_MISSES = 8
STAR_OUT_MARKS = ("usage bump", "teammate freshly out")


# --------------------------------------------------------------------------- timing
def due(now_utc: Optional[datetime] = None) -> bool:
    """Is it 3 AM or later in New York? GitHub's scheduler often starts runs hours late (Nov 1: the 3:30 AM runs never
    landed in the 3 AM hour, so nothing ran), so every scheduled run from 3 AM on does the work -- once per morning
    (main checks the done marker)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    return now_utc.astimezone(ET).hour >= RUN_HOUR_ET


DONE_KEY = "_ALL"          # a marker row in daily_reviews: this morning's review has run


def morning_of(now_utc: Optional[datetime] = None) -> str:
    return (now_utc or datetime.now(timezone.utc)).astimezone(ET).date().isoformat()


# --------------------------------------------------------------------------- summarising
def _flags(rec: Dict) -> List[str]:
    f = rec.get("flags")
    if isinstance(f, str):
        try:
            f = json.loads(f)
        except ValueError:
            f = [f]
    return [str(x) for x in (f or [])]


def star_out(rec: Dict) -> bool:
    return any(m in x for x in _flags(rec) for m in STAR_OUT_MARKS)


def _rate(rows: Sequence[Dict], key: str = "result") -> Optional[float]:
    if key == "model_hit":
        g = [r for r in rows if r.get("model_hit") is not None]
        return (sum(1 for r in g if r["model_hit"]) / len(g)) if g else None
    g = [r for r in rows if r.get("result") in ("hit", "miss")]
    return (sum(1 for r in g if r["result"] == "hit") / len(g)) if g else None


def _miss_size(r: Dict) -> float:
    line = float(r.get("line") or 0)
    return abs(float(r["actual"]) - line) / max(line, 1.0)


def _record(rows: Sequence[Dict]) -> Dict:
    hits = sum(1 for r in rows if r.get("result") == "hit")
    misses = sum(1 for r in rows if r.get("result") == "miss")
    return {"hits": hits, "misses": misses, "hit_rate": hits / (hits + misses) if hits + misses else None}


def _lock(done: Sequence[Dict]) -> Dict:
    """The 🔒 Most probable record (hits / misses / hit_rate, plus the chance shown and profit at the price)."""
    rec = _record([r for r in done if PE.most_probable(r.get("chance"), r.get("cushion"), r.get("gap"))])
    row = PG.lock_record(done) or {}
    rec.update(chance=row.get("Model said"), profit=row.get("Profit per $1"), priced=row.get("Priced", 0))
    return rec


def summarize_slate(graded: Sequence[Dict]) -> Dict:
    """One slate's grading, ready to store as JSON."""
    counts = {k: sum(1 for r in graded if r.get("result") == k) for k in ("hit", "miss", "push", "void", "pending")}
    done = [r for r in graded if r.get("result") in ("hit", "miss", "push")]
    mh, mn = PG.model_record(done)
    by_m: Dict[str, List[Dict]] = {}
    for r in done:
        by_m.setdefault(r["market"], []).append(r)
    markets = []
    for m, rs in sorted(by_m.items()):
        proj = sum(float(r["projection"]) for r in rs if r.get("projection") is not None and r.get("actual") is not None)
        act = sum(float(r["actual"]) for r in rs if r.get("projection") is not None and r.get("actual") is not None)
        markets.append({"market": m, "graded": len(rs), "hit_rate": _rate(rs), "model_side": _rate(rs, "model_hit"),
                        "vs_projection": (act / proj - 1) if proj > 0 else None})
    gaps = [r for r in done if str(r.get("gap") or "").startswith("big")]
    stars = [r for r in done if star_out(r)]
    picks = [r for r in done if r.get("use_tag") and r.get("use_tag") != PE.USE_PASS]
    misses = sorted((r for r in picks if r["result"] == "miss" and r.get("actual") is not None),
                    key=_miss_size, reverse=True)[:TOP_MISSES]
    return {
        "counts": counts,
        "model": {"right": mh, "graded": mn},
        "use": PG.use_record(done),
        "most_probable": _lock(done),
        "markets": markets,
        "big_gap": {"graded": len(gaps), "model_right": _rate(gaps, "model_hit"), "hit_rate": _rate(gaps)},
        "star_out": {"graded": len(stars), "hit_rate": _rate(stars),
                     "unders": _rate([r for r in stars if r.get("side") == "Under"]),
                     "overs": _rate([r for r in stars if r.get("side") == "Over"])},
        "causes": PG.cause_counts(done),
        "top_misses": [{"player": r.get("player"), "game": r.get("game"), "market": r.get("market"),
                        "side": r.get("side"), "line": r.get("line"), "projection": r.get("projection"),
                        "actual": r.get("actual"), "use": r.get("use_tag"), "cause": r.get("cause")} for r in misses],
    }


def game_pick_notes(rep: Optional[Dict]) -> List[str]:
    """College spreads v2 (game_picks.py) -- yesterday and the running record, while it's being tracked."""
    if not rep:
        return []
    out = []
    y, s = rep.get("yesterday") or {}, rep.get("season") or {}
    if y.get("graded"):
        out.append(f"College spreads v2 (tracking): {y['record']} yesterday.")
    if s.get("graded"):
        clv = "" if s.get("avg_clv") is None else f", lines moved {s['avg_clv']:+.1f} pts toward the picks on average"
        out.append(f"College spreads v2 season: {s['record']} ({s['hit']:.0%}; 52.4% breaks even at -110){clv}.")
    return out


def calibration_notes(cal: Dict) -> List[str]:
    """One line on how honest the chances have been (calibration.py), once there are enough graded reads."""
    if not cal.get("enough"):
        return []
    hi = [b for b in cal["buckets"] if b["shown"] >= 0.6]
    if not hi:
        return []
    n = sum(b["n"] for b in hi)
    shown = sum(b["shown"] * b["n"] for b in hi) / n
    hit = sum(b["hit"] * b["n"] for b in hi) / n
    line = f"Calibration: reads shown at 60%+ (avg {shown:.0%}) hit {hit:.0%} over the last {n}"
    if cal["s"] >= 0.99:
        return [line + f" (active: {cal.get('active', 1.0):.2f})."]
    # Nov 11: this fit covers the whole window, including days before the shown chances last changed, so it isn't a
    # to-do. Say what the automatic overall factor (calibration.auto_global) decided instead of a bare suggestion.
    auto = next((d for d in cal.get("auto") or [] if d.get("side") == "overall"), None)
    if auto and auto.get("applied"):
        return [line + "."]
    wait = f" Automatic: {auto['why']} — it applies itself if it holds up." if auto and auto.get("why") else ""
    return [line + f"; over all those days a factor of {cal['s']:.2f} would fit (active: "
            f"{cal.get('active', 1.0):.2f}), but part of that is from before the last automatic change.{wait} "
            "Nothing for you to do."]


def notes(slates: Dict[str, Dict]) -> List[str]:
    """Plain-English takeaways from the slates just graded (the headline bullets on the page)."""
    out = []
    for d, s in sorted(slates.items()):
        c = s["counts"]
        if not (c["hit"] + c["miss"]):
            if c["pending"]:
                out.append(f"{d}: {c['pending']} props still waiting on final box scores.")
            continue
        m = s["model"]
        if m["graded"]:
            out.append(f"{d}: the model's side was right on {m['right']} of {m['graded']} "
                       f"({m['right'] / m['graded']:.0%}).")
        for u in s["use"]:
            if u["Use"] == PE.USE_PASS:
                continue
            said = f", model said {u['Model said']:.0%}" if u.get("Model said") is not None else ""
            out.append(f"{d}: {u['Use']} {u['Hits']}-{u['Graded'] - u['Hits']} ({u['Hit rate']:.0%}{said}).")
        mp = s.get("most_probable") or {}
        if mp.get("hit_rate") is not None:
            out.append(f"{d}: {PE.MOST_PROBABLE} {mp['hits']}-{mp['misses']} ({mp['hit_rate']:.0%}).")
        g = s["big_gap"]
        if g["graded"] >= 3 and g["model_right"] is not None:
            who = "the model" if g["model_right"] >= 0.5 else "the market"
            out.append(f"{d}: on {g['graded']} props with the line far from the projection, {who} was right "
                       f"({g['model_right']:.0%} model).")
        so = s["star_out"]
        if so["graded"] >= 3 and so["hit_rate"] is not None:
            out.append(f"{d}: star-out props went {so['hit_rate']:.0%} over {so['graded']}.")
        for mk in s["markets"]:
            if mk["graded"] >= 8 and mk["vs_projection"] is not None and abs(mk["vs_projection"]) >= 0.15:
                out.append(f"{d}: {mk['market']} results ran {mk['vs_projection']:+.0%} vs the projections "
                           f"({mk['graded']} props) — one night, so watch for a pattern before acting.")
    return out


# --------------------------------------------------------------------------- grading
def grade_dates(sport: str, dates: Sequence[str], fetch: Callable = PG._http,
                db_path: Optional[str] = None) -> Dict[str, List[Dict]]:
    snaps = MS.load_snapshots(sport, list(dates), db_path=db_path) if dates else []
    out: Dict[str, List[Dict]] = {}
    for d in sorted({s["slate_date"] for s in snaps}):
        day = [s for s in snaps if s["slate_date"] == d]
        try:
            res = PG.fetch_results(sport, d, sorted({(s["team"], s["opp"]) for s in day}), fetch=fetch)
        except Exception as exc:                                    # noqa: BLE001 — one bad fetch never stops the run
            print(f"  [{sport}] {d}: couldn't reach the box scores ({type(exc).__name__}: {exc})")
            res = {}
        out[d] = PG.grade(day, res)
    return out


def slates_for(sport: str, morning: str, db_path: Optional[str] = None) -> List[str]:
    """Yesterday's slate, plus any of the few before it whose last morning report still had props pending."""
    m = date.fromisoformat(morning)
    yesterday = (m - timedelta(days=1)).isoformat()
    have = set(MS.snapshot_dates(sport, db_path=db_path))
    out = [yesterday] if yesterday in have else []
    for k in range(2, CATCH_UP_DAYS + 1):
        d = (m - timedelta(days=k)).isoformat()
        if d not in have:
            continue
        prev = MS.load_daily_review(sport, (date.fromisoformat(d) + timedelta(days=1)).isoformat(), db_path=db_path)
        if prev is None or ((prev.get("slates") or {}).get(d, {}).get("counts", {}).get("pending")):
            out.append(d)
    return sorted(out)


# --------------------------------------------------------------------------- settling
def settle(sport: str, open_bets: Sequence[Dict], fetch: Callable = PG._http, write: bool = True,
           bet_db: Optional[str] = None) -> Dict:
    """Settle this sport's open props from the box scores, then any parlay ticket its legs now decide."""
    kw = {"db_path": bet_db} if bet_db else {}
    mine = [b for b in open_bets if (b.get("sport") or "") == sport and not b.get("result")]
    plan = PS.build_plan(mine, sport, fetch=fetch)
    settled = []
    for p in plan["proposed"]:
        try:
            if write:
                B.update_bet(p["bet_id"], result=p["new_result"], **kw)
            settled.append({"bet_id": p["bet_id"], "description": p["description"], "actual": p["actual"],
                            "result": p["new_result"]})
        except Exception as exc:                                    # noqa: BLE001
            plan["unresolved"].append({"bet_id": p["bet_id"], "description": p["description"],
                                       "why": f"couldn't save the result ({type(exc).__name__})"})
    tickets = []
    if write:                                                   # Nov 6: also tickets whose legs settled elsewhere
        try:
            for t in B.ticket_settlements(B.list_bets(**kw)):
                B.update_bet(t["id"], result=t["result"], **kw)
                tickets.append(t)
        except Exception as exc:                                    # noqa: BLE001
            print(f"  [{sport}] ticket settlement failed: {type(exc).__name__}: {exc}")
    return {"settled": settled, "tickets": tickets, "unresolved": plan["unresolved"],
            "still_pending": plan["still_pending"]}


# --------------------------------------------------------------------------- the run
def review_sport(sport: str, morning: str, open_bets: Sequence[Dict], fetch: Callable = PG._http,
                 db_path: Optional[str] = None, write: bool = True, bet_db: Optional[str] = None) -> Optional[Dict]:
    """One sport's morning report, or None when the sport had nothing to review (out of season)."""
    if sport == "UFC":
        import ufc_review as UR
        rep = UR.review(morning, open_bets, fetch=fetch, db_path=db_path, write=write, bet_db=bet_db)
        if rep and rep["settlement"]["settled"] and write:
            kw = {"db_path": bet_db} if bet_db else {}
            try:
                for t in B.ticket_settlements(B.list_bets(**kw)):
                    B.update_bet(t["id"], result=t["result"], **kw)
                    rep["settlement"]["tickets"].append(t)
            except Exception as exc:                                # noqa: BLE001
                print(f"  [UFC] ticket settlement failed: {type(exc).__name__}: {exc}")
        return rep
    dates = slates_for(sport, morning, db_path=db_path)
    has_bets = any((b.get("sport") or "") == sport and not b.get("result") for b in open_bets)
    has_game_picks = sport == "NCAAF" and bool(MS.load_game_picks("NCAAF", ungraded=True, db_path=db_path))
    if not dates and not has_bets and not has_game_picks:
        return None
    graded = grade_dates(sport, dates, fetch=fetch, db_path=db_path)
    slates = {d: summarize_slate(rows) for d, rows in graded.items()}

    # Suggestions look across the whole window (already-graded slates are re-fetched; ESPN is free).
    cutoff = (date.fromisoformat(morning) - timedelta(days=TREND_DAYS)).isoformat()
    window = [d for d in MS.snapshot_dates(sport, db_path=db_path) if cutoff <= d < morning]
    trend = dict(graded)
    trend.update(grade_dates(sport, [d for d in window if d not in graded], fetch=fetch, db_path=db_path))
    trend_rows = [r for rows in trend.values() for r in rows if r.get("result") in ("hit", "miss", "push")]
    active = {(t["sport"], t["market"], t.get("slot") or ""): float(t["factor"])
              for t in MS.list_tuning(db_path=db_path)}
    sugg = PG.suggestions(trend_rows, active)
    # Nov 10: projection tunings apply themselves when they hold up on the props graded since their last change
    try:
        auto_tune = PG.auto_tunings(trend_rows, MS.list_tuning(db_path=db_path), morning, write=write)
    except Exception as exc:                                    # noqa: BLE001
        print(f"  [{sport}] auto tuning failed: {type(exc).__name__}: {exc}")
        auto_tune = []
    if any(d.get("applied") for d in auto_tune):
        active = {(t["sport"], t["market"], t.get("slot") or ""): float(t["factor"])
                  for t in MS.list_tuning(db_path=db_path)}
        sugg = PG.suggestions(trend_rows, active)

    settlement = settle(sport, open_bets, fetch=fetch, write=write, bet_db=bet_db) if has_bets else \
        {"settled": [], "tickets": [], "unresolved": [], "still_pending": []}
    games_rep = None
    if sport == "NCAAF":
        try:
            import game_picks as GP
            games_rep = GP.review(morning, fetch=fetch, db_path=db_path)
        except Exception as exc:                                    # noqa: BLE001
            print(f"  [NCAAF] game picks review failed: {type(exc).__name__}: {exc}")
    import calibration as CAL
    cal = CAL.fit(trend_rows)
    cal["active"] = CAL.factor(sport)
    cal["by_side"] = CAL.fit_by_side(trend_rows)               # Nov 5: Over and Under fitted separately
    cal["side_active"] = list(CAL.side_factors(sport))
    # Nov 8: the loop learns on its own -- each side's factor refit on the window and applied when it holds up out of
    # sample (calibration.auto_side); the decisions ride in the report, applied ones in the morning notes
    try:
        cal["auto"] = CAL.auto_side(sport, trend, morning, write=write)
        # Nov 10: the overall factor (ticket math) learns the same way
        cal["auto"].append(CAL.auto_global(sport, trend, morning, write=write))
    except Exception as exc:                                    # noqa: BLE001
        cal["auto"] = []
        print(f"  [{sport}] auto-calibration failed: {type(exc).__name__}: {exc}")
    return {"sport": sport, "morning": morning, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "slates": slates, "notes": notes(slates) + CAL.auto_notes(cal.get("auto") or [])
            + PG.auto_tuning_notes(auto_tune) + calibration_notes(cal)
            + game_pick_notes(games_rep),
            "calibration": cal, "game_picks": games_rep,
            "trend": {"days": TREND_DAYS, "slates": len(trend), "graded": len(trend_rows),
                      "use": PG.use_record(trend_rows), "beat": PG.beat_model(trend_rows)},
            "suggestions": sugg, "settlement": settlement, "auto_tuning": auto_tune}


def run(morning: str, fetch: Callable = PG._http, db_path: Optional[str] = None, write: bool = True,
        sports: Sequence[str] = tuple(PG.ESPN) + ("UFC", "TENNIS"), bet_db: Optional[str] = None) -> Dict[str, Dict]:
    """db_path: the model store (snapshots, tuning, reports); bet_db: the Bet Log. Both default to production."""
    kw = {"db_path": bet_db} if bet_db else {}
    try:
        open_bets = B.list_bets(settled=False, **kw)
    except Exception as exc:                                        # noqa: BLE001
        print(f"Couldn't read the Bet Log ({type(exc).__name__}: {exc}); reviewing without settling.")
        open_bets = []
    out = {}
    for sport in [x for x in sports if x != "TENNIS"]:
        try:
            rep = review_sport(sport, morning, open_bets, fetch=fetch, db_path=db_path, write=write, bet_db=bet_db)
        except Exception as exc:                                    # noqa: BLE001 — one sport never stops the rest
            print(f"[{sport}] review failed: {type(exc).__name__}: {exc}")
            continue
        if rep is None:
            print(f"[{sport}] nothing to review (no slate yesterday, no open bets).")
            continue
        out[sport] = rep
        if write:
            MS.save_daily_review(sport, morning, rep, db_path=db_path)
        s = rep["settlement"]
        print(f"[{sport}] slates {', '.join(rep['slates']) or (rep.get('card') or {}).get('date') or '—'} · {len(rep['suggestions'])} suggestion(s) · "
              f"settled {len(s['settled'])} prop(s) + {len(s['tickets'])} ticket(s) · "
              f"{len(s['unresolved'])} left for a person · {len(s['still_pending'])} not final")
        for n in rep["notes"]:
            print("   ", n)
    if write:
        settle_game_lines(bet_db)
    # Nov 12: tennis -- refit how far the Tennis Lab's chances are pulled toward 50% (tennis_calibration.py) and apply
    # it when it holds up on held-out days; saved as a TENNIS report so the morning brief lists it with the rest
    try:
        if "TENNIS" not in sports:
            raise LookupError("tennis not in this run")
        import tennis_calibration as TC
        d = TC.auto(write=write)
        rep = {"calibration": {"auto": [d]}, "notes": [f"{morning}: tennis calibration -- "
                                                        f"{'changed' if d['applied'] else 'kept'} "
                                                        f"{d['active']:.2f}" + (f" → {d['new']:.2f}" if d["applied"] else "")
                                                        + f" ({d['why']})"]}
        out["TENNIS"] = rep
        if write:
            MS.save_daily_review("TENNIS", morning, rep, db_path=db_path)
        print("[TENNIS]", rep["notes"][0])
    except LookupError:
        pass
    except Exception as exc:                                        # noqa: BLE001
        print(f"[TENNIS] calibration failed: {type(exc).__name__}: {exc}")
    return out


GAME_LINE_LEAGUES = ("NCAAF", "NCAAMB", "NBA", "NHL", "WNBA", "TENNIS")


def settle_game_lines(bet_db: Optional[str] = None) -> int:
    """Nov 8: game-line bets logged from Today's best / a Game Lab ("gl:<league>:<game_id>") settle once their game is
    graded. Only the international and tennis captures called this before, so a college football total logged on Saturday
    stayed open for good. Then parlay tickets whose legs are all settled roll up."""
    import intl_picks as IP
    n = 0
    for lg in GAME_LINE_LEAGUES:
        try:
            k = IP.settle_logged(lg)
            n += k
            if k:
                print(f"[{lg}] settled {k} game-line bet(s)")
        except Exception as exc:                                    # noqa: BLE001
            print(f"[{lg}] game-line settlement failed: {type(exc).__name__}: {exc}")
    kw = {"db_path": bet_db} if bet_db else {}
    try:
        for t in B.ticket_settlements(B.list_bets(**kw)):
            B.update_bet(t["id"], result=t["result"], **kw)
            n += 1
            print(f"ticket {t.get('ticket') or t['id']} -> {t['result']}")
    except Exception as exc:                                        # noqa: BLE001
        print(f"ticket roll-up failed: {type(exc).__name__}: {exc}")
    return n


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--force", action="store_true", help="run whatever the hour in New York")
    ap.add_argument("--date", help="the morning to review (YYYY-MM-DD); default today in New York")
    a = ap.parse_args(argv)
    force = a.force or os.environ.get("DAILY_REVIEW_FORCE", "").strip().lower() in ("1", "true", "yes")
    if not os.environ.get("DATABASE_URL") and not getattr(B, "USING_POSTGRES", False):
        print("DATABASE_URL not set — the review and settlements would go to a throwaway SQLite file and be lost.\n"
              "Set the DATABASE_URL secret (the same one settle-results uses).")
        return 1
    if not force and not a.date and not due():
        print(f"Not 3 AM in New York yet ({datetime.now(timezone.utc).astimezone(ET):%H:%M} ET) — this is the other "
              "daylight-saving slot; nothing to do.")
        return 0
    morning = a.date or morning_of()
    if not force and not a.date and MS.load_daily_review(DONE_KEY, morning):
        print(f"The {morning} review already ran — nothing to do.")
        return 0
    print(f"Morning review for {morning} (America/New_York).")
    run(morning)
    MS.save_daily_review(DONE_KEY, morning, {"ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
