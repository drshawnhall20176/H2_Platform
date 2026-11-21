"""Nov 21 morning: 💰 live-test results + why the NHL warm build found 0 games."""
import sys, traceback
sys.path.insert(0, ".")
import money_scoreboard as MSB, model_store as MS, props_engine as PE, sports, todays_best as TB
b = MSB.scoreboard()
for r in b["sports"]:
    print(f"MC money {r['sport']}: {r['hits']}-{r['misses']} units={r['units']:+.2f} clv={r.get('clv')} n={r.get('clv_n')}")
t = b["total"]; print(f"MC money TOTAL {t['hits']}-{t['misses']} units={t['units']:+.2f} needed={t['needed']}")
for sp in ("NBA", "NHL", "NCAAMB", "NCAAF"):
    rev = MS.load_daily_review(sp, "2026-11-21") or {}
    s = (rev.get("slates") or {}).get("2026-11-20") or {}
    print(f"MC review {sp}: money={s.get('money')} lock={s.get('most_probable')}")
rows = [r for r in TB.collect("2026-11-20", ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"), past=True)["rows"] if r.get("kind") == "Prop"]
top = sorted(rows, key=lambda r: -(r.get("chance") or 0))[:15]
print("MC strongest15:", sum(r.get("result") == "win" for r in top), "-", sum(r.get("result") == "loss" for r in top))
g = TB.winner_rows("2026-11-20", leagues=["NCAAMB"], past=True)
gm = [x for x in g if x.get("money")]
print("MC game money NCAAMB:", sum(x.get("money_result") == "win" for x in gm), "-", sum(x.get("money_result") == "loss" for x in gm), "of", len(gm))
nhl = sports.get("NHL")
for d in ("2026-11-20", "2026-11-21"):
    try:
        fn = getattr(nhl.engine.build_slate, "uncached", nhl.engine.build_slate)
        rows_, meta = fn(d)
        print(f"MC NHL build {d}: {len(rows_)} players {len(meta)} games")
    except Exception:
        print("MC NHL build", d, "ERR", traceback.format_exc()[-600:].replace("\n", " | "))
