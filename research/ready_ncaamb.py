import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, pick_ledger as PL, sports
from collections import Counter
from datetime import datetime, timezone
D = "2026-11-23"
res = MS.load_results("NCAAMB", since="2026-11-15")
print("results latest", max(str(g.get("date"))[:10] for g in res), "n since 11/15", len(res),
      "on 11/22", sum(str(g.get("date"))[:10] == "2026-11-22" for g in res))
picks = [p for p in MS.load_game_picks("NCAAMB") if sports.game_dt(p.get("kickoff")) and sports.game_dt(p["kickoff"]).strftime("%Y-%m-%d") == D]
print("today picks", len(picks))
c = Counter(sports.game_dt(p["kickoff"]).strftime("%H:%M") for p in picks); print("tip times", sorted(c.items()))
print("neutral", sum(bool(p.get("neutral")) for p in picks), "with spread", sum(p.get("home_spread") is not None for p in picks),
      "with total", sum(p.get("line_total") is not None for p in picks), "with model", sum(p.get("model_margin") is not None for p in picks))
le = [(p["model_margin"] + p["home_spread"]) > 0 for p in picks if p.get("home_spread") is not None and p.get("model_margin") is not None and p["model_margin"] + p["home_spread"] != 0]
print("home-lean share", f"{sum(le)}/{len(le)}")
print("uses", Counter(str(p.get("use")) for p in picks))
print("captured at", max(str(p.get("captured_at") or p.get("updated_at") or "") for p in picks) if picks else None)
for p in sorted(picks, key=lambda p: p["kickoff"])[:40]:
    print(sports.game_dt(p["kickoff"]).strftime("%H:%M"), p["away"], "@", p["home"], "N" if p.get("neutral") else "", "spr", p.get("home_spread"), "mm", round(p["model_margin"],1) if p.get("model_margin") is not None else None)
pr = MS.get_setting(f"PROPS_BOARD:NCAAMB:{D}") 
import todays_best as TB
try:
    rows = (TB.load_props("NCAAMB", D) or {}).get("rows") or []
except Exception as e:
    rows = []; print("props err", e)
print("props saved today", len(rows))
print("hot today", len((PL.load("hot", "ALL", D) or {}).get("rows", {})))
