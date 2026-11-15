"""Nov 15: what would the new weekly-sport rules decide today (dry run, nothing written)?"""
import os, sys, json
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, daily_review as D, calibration as CAL, tuning_report as TR, postgame as PG
morning = date.today().isoformat()
for sp in ("NFL", "NCAAF"):
    cutoff = (date.today() - timedelta(days=D.WEEKLY_TREND_DAYS)).isoformat()
    ds = [d for d in MS.snapshot_dates(sp) if cutoff <= d < morning]
    trend = D.grade_dates(sp, ds)
    n = sum(len(v) for v in trend.values())
    print(f"\n=== {sp}: {len(ds)} slates, {n} graded reads, dates {ds[:3]}..{ds[-3:]}")
    print("history", {sd: CAL.factor_history(f'{sp}:{sd}') for sd in ('Over', 'Under')})
    for d in CAL.auto_side(sp, trend, morning, write=False) + [CAL.auto_global(sp, trend, morning, write=False)]:
        print(f"DEC {sp} {d['side']:8} active {d['active']} -> {d['new']}  n={d['n']} dates={d['dates']} splits={d['splits']} passed={d['passed']} gain={d['gain']:+.4f} | {d['why']}")
    rows = [r for v in trend.values() for r in v if r.get("result") in ("hit", "miss", "push")]
    for t in PG.auto_tunings(rows, MS.list_tuning(), morning, write=False):
        print(f"TUNE {sp} {t.get('market')} {t.get('slot') or ''} n={t.get('n_since')} | {t.get('why')} -> {t.get('factor')}")
    try:
        rep = TR.build(sp, [r for v in trend.values() for r in v], MS.list_bets() if hasattr(MS, "list_bets") else [], days=63)
        for pr in rep.get("proposals") or []:
            print(f"BLEND {sp} {pr['market']} {pr['now']} -> {pr['w']} n={pr['n']} | {pr['why']}")
    except Exception as exc:
        print("tuning build", type(exc).__name__, exc)
