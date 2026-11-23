import sys, os, json; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB, pick_ledger as PL, model_store as MS
from datetime import datetime, timezone
D = "2026-11-23"; now = datetime.now(timezone.utc).isoformat()
for sp in ("NBA", "NFL", "NCAAMB"):
    b = TB.load_props(sp, D) or {}
    rows = b.get("rows") or []
    print("PROPS", sp, "saved", b.get("saved_at") or b.get("at"), "rows", len(rows))
    keep = []
    for r in rows:
        keep.append({k: r.get(k) for k in ("time","game","player","team","market","side","line","price","book","earned","chance","need","use","money","lock","pickem_only","kickoff")})
    keep.sort(key=lambda r: -((r.get("earned") or r.get("chance") or 0) - (r.get("need") or 0.52)))
    for r in keep[:25]: print("P", sp, json.dumps(r, default=str))
rows = TB.winner_rows(D, leagues=["NCAAMB"], past=True)
for r in rows:
    f = r.get("_full") or {}
    if f.get("final_home") is not None or str(f.get("kickoff")) <= now: continue
    hs, mm = f.get("home_spread"), f.get("model_margin")
    print("G", json.dumps({"time": r.get("time"), "game": r.get("game"), "spread": hs, "model": mm, "gap": None if hs is None or mm is None else round(abs(mm+hs),1),
        "line_pick": r.get("best"), "money": r.get("money_pick"), "money_price": r.get("money_price"), "money_score": r.get("money_score"), "money_flag": r.get("money"),
        "winner": r.get("winner"), "chance": r.get("chance"), "price": r.get("price"), "total": f.get("line_total"), "model_total": f.get("model_total"), "neutral": f.get("neutral")}, default=str))
cand = (PL.load("cand", "NCAAMB", D) or {}).get("rows") or {}
print("CAND", json.dumps([r["pick"] + " " + str(r.get("time")) for r in cand.values()]))
st = PL.strongest(D) if hasattr(PL, "strongest") else None
print("STRONG", json.dumps([(x.get("sport"), x.get("pick"), x.get("price"), x.get("earned") or x.get("chance"), x.get("time")) for x in (st or [])][:20], default=str))
