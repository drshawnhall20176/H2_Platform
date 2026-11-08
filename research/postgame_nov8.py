"""Nov 8 morning: last night's postgame -- the saved morning reviews, the bets, and the game-script calls."""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B           # noqa: E402
import model_store as MS     # noqa: E402

M = "2026-11-08"
for sp in ("NBA", "NHL", "NCAAF", "NCAAMB", "NFL", "UFC"):
    rep = MS.load_daily_review(sp, M)
    print(f"\n===== PG {sp}: review {'found' if rep else 'MISSING'}  (mornings: {MS.daily_review_mornings(sp)[:3]})")
    if not rep:
        continue
    for d, s in (rep.get("slates") or {}).items():
        print("PG slate", d, json.dumps(s, default=str)[:900])
    for n in rep.get("notes") or []:
        print("PG note", str(n)[:300])
    cal = rep.get("calibration") or {}
    print("PG cal", {k: cal.get(k) for k in ("n", "s", "active", "enough", "log_loss", "side_active")}, "| by_side", json.dumps(cal.get("by_side"), default=str)[:300])
    tr = rep.get("trend") or {}
    print("PG trend", tr.get("days"), "days", tr.get("slates"), "slates", tr.get("graded"), "graded")
    for u in tr.get("use") or []:
        print("PG use", json.dumps(u, default=str)[:250])
    for b in (tr.get("beat") or [])[:6]:
        print("PG beat", json.dumps(b, default=str)[:250])
    for g in rep.get("suggestions") or []:
        print("PG SUGG", json.dumps(g, default=str)[:420])
    gp = rep.get("game_picks")
    if gp:
        print("PG gamepicks", json.dumps(gp, default=str)[:600])
    st = rep.get("settlement") or {}
    print("PG settled", len(st.get("settled") or []), "tickets", len(st.get("tickets") or []), "unresolved", len(st.get("unresolved") or []), "pending", len(st.get("still_pending") or []))
# bets placed Nov 7
bets = [b for b in B.list_bets() if str(b.get("date") or b.get("game_date") or b.get("ts") or "")[:10] == "2026-11-07" or str(b.get("slate_date") or "")[:10] == "2026-11-07"]
print("\nPG BETS keys", sorted(bets[0].keys()) if bets else None)
tot = defaultdict(lambda: [0.0, 0.0, 0, 0])
for b in bets:
    real = b.get("is_real_bet")
    tag = b.get("tag") or b.get("category") or ""
    pl = b.get("profit") if b.get("profit") is not None else None
    print("PG BET", b.get("sport"), "|", b.get("player"), b.get("market"), b.get("side"), b.get("line"), "|", b.get("odds"), "| stake", b.get("stake"),
          "| result", b.get("result"), "| profit", pl, "| tag", tag, "| ticket", b.get("ticket") or b.get("parlay_id"), "| real", real)
# script calls graded
for sp in ("NBA", "NCAAMB", "NHL", "NCAAF"):
    f = MS.get_setting(f"script_learn:{sp}", {}) or {}
    tr = f.get("track") or {}
    print("PG SCRIPT", sp, "graded calls", tr.get("n"), "model", tr.get("model"), "table", tr.get("table"), "| source", (f.get("scenario") or {}).get("source"))
    for k, v in sorted((tr.get("bands") or {}).items()):
        print("PG SCRIPT   ", k, v)
