"""Morning check-in (Nov 24, owner): how yesterday's 🃏 Bet / 🧪 Tracking picks did, each group's running record
against the +5% profitable pace, and what qualifies today. Model picks only -- nothing from the Bet Log (public log)."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, datetime, timedelta, timezone
import pytz
import picks_performance as PP
import pick_ledger as PL

et = pytz.timezone("US/Eastern")
today = datetime.now(et).date()
yday = (today - timedelta(days=1)).isoformat()
print("=== CHECKIN START ===")
print(f"Morning check-in · {today:%a %b %-d}")
for g in PP.GROUPS:
    allp = PP.ledger_picks(g["kind"], g["sports"], g["from"], yday)
    yp = [p for p in allp if p["day"] == yday]
    s, y = PP.summary(allp), PP.summary(yp)
    yl = (f"yesterday {y['wins']}-{y['losses']}" + (f"-{y['pushes']}" if y["pushes"] else "") + f" ({y['units']:+.2f}u)"
          if (y["n"] or y["pushes"]) else "yesterday: none graded")
    run = (f"running {s['wins']}-{s['losses']} ({s['hit_rate']:.0%}, needed {s['needed']:.0%}), {s['units']:+.2f}u vs "
           f"pace {s['pace_units']:+.2f}u, {s['roi']:+.1%} per $1 — {PP.verdict(s)}" if s["n"] else "no graded picks yet")
    print(f"- {g['label']}: {yl}; {run}")
    if yp:
        print("    " + "; ".join(f"{'✅' if p['result']=='win' else '❌' if p['result']=='loss' else '➖'} {p['pick']}"
                               for p in yp[:30]))
# today
try:
    import candidate_rules as CR, model_store as MS
    start = datetime(today.year, today.month, today.day, 5, tzinfo=timezone.utc)
    cg = CR.picks(MS.load_game_picks("NCAAMB"), today.isoformat(), now=start)
    print(f"Today's 🧪 close-gap games ({len(cg)}):")
    for c in sorted(cg, key=lambda c: c.get("kickoff") or ""):
        print(f"    {c['time']} · {c['pick']} ({c['game']})")
except Exception as e:
    print("close-gap today: unavailable", type(e).__name__)
for sp in PP.SPORTS:
    try:
        n = len(PL.rows("money", sp, today.isoformat()))
        if n:
            print(f"💰 props on today's {sp} board so far: {n}")
    except Exception:
        pass
print("=== CHECKIN END ===")
