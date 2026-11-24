import sys, os, collections; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB, model_store as MS, daily_review as DR, props_money as PM, candidate_rules as CR
LG = ["NBA", "NHL", "NFL", "NCAAF", "NCAAMB"]
print("== Nov 23 game lines (graded) ==")
for lg in LG:
    rows = TB.winner_rows("2026-11-23", leagues=[lg], past=True)
    c = {k: collections.Counter(str(r.get(k) or "") [:6] for r in rows) for k in ("money_result", "best_result", "winner_result")}
    print(lg, len(rows), {k: dict(v) for k, v in c.items()})
print("== props: earned chance vs hit, Nov 17-23 ==")
for sp in LG:
    days = [d for d in MS.snapshot_dates(sp) if "2026-11-17" <= d <= "2026-11-23"]
    g = DR.grade_dates(sp, days)
    rows = [r for rs in g.values() for r in rs if r.get("result") in ("hit", "miss") and r.get("chance") is not None]
    by = collections.defaultdict(lambda: [0, 0.0, 0, 0.0])
    for r in rows:
        side = r.get("side"); pm = r.get("p_market")
        pm_side = None if pm is None else (float(pm) if side == "Over" else 1 - float(pm))
        try: e = PM.earned(sp, r.get("market"), side, float(r["chance"]), pm_side)
        except Exception: e = None
        if e is None: continue
        k = (side, "priced" if pm_side is not None else "pickem")
        by[k][0] += 1; by[k][1] += e; by[k][2] += r["result"] == "hit"; by[k][3] += float(r["chance"])
    print(sp, {f"{s}/{t}": f"model {v[3]/v[0]:.0%} earned {v[1]/v[0]:.1%} hit {v[2]/v[0]:.1%} n={v[0]}" for (s, t), v in by.items() if v[0] >= 20})
print("== candidate rules ==")
for lg in LG:
    try: print(lg, CR.status_line(lg, "2026-11-23"))
    except Exception as e: print(lg, "err", e)
for sp in LG:
    try: print(sp, CR.prop_status_line(sp))
    except Exception as e: print(sp, "err", e)
print("== today's data freshness ==")
for lg in LG:
    sv = TB.load_props(lg, "2026-11-24") or {}
    gp = [p for p in MS.load_game_picks(lg, ungraded=True) if str(p.get("kickoff") or p.get("date") or "")[:10] in ("2026-11-24", "2026-11-25")]
    print(lg, "props saved", len(sv.get("rows") or []), "at", sv.get("at"), "| game picks today", len(gp))
