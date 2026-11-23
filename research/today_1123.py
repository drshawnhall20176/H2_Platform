import sys, os, json; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB, pick_ledger as PL, model_store as MS
D = "2026-11-23"
rows = TB.winner_rows(D, leagues=["NCAAMB"], past=True)
out = []
for r in rows:
    f = r.get("_full") or {}
    if f.get("final_home") is None: continue
    out.append({k: r.get(k) for k in ("time","game","money_pick","money_price","money_score","money","money_result","best","best_result","winner","chance","price","winner_result")} | {k: f.get(k) for k in ("home_spread","model_margin","final_home","final_away","line_total","neutral","kickoff")})
print("FINAL", len(out), "of", len(rows))
for i in range(0, len(out), 20): print("JSON" + json.dumps(out[i:i+20], default=str))
recs = {p["game_id"]: p for p in MS.load_game_picks("NCAAMB")}
cand = (PL.load("cand", "NCAAMB", D) or {}).get("rows") or {}
cr = []
for k, r in cand.items():
    p = recs.get(r.get("game_id")) or {}
    if p.get("final_home") is None: cr.append((r["pick"], "open")); continue
    fh, fa = p["final_home"], p["final_away"]
    d = (fh - fa if r["money_side"] == "home" else fa - fh) + float(r["money_line"])
    cr.append((r["pick"], "push" if d == 0 else "win" if d > 0 else "loss"))
print("CAND", json.dumps(cr))
for kind, sp in (("strong","ALL"),("hot","ALL"),("money","NCAAMB")):
    rs = [x for x in ((PL.load(kind, sp, D) or {}).get("rows") or {}).values() if (x.get("sport") or sp) == "NCAAMB"]
    print("LEDGER", kind, len(rs), json.dumps([(x.get("pick"), x.get("price"), x.get("result")) for x in rs][:20]))
