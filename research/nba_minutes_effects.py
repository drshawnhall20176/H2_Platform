import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, script_effects as SE, todays_best as TB
got = MS.get_setting("script_learn:NBA"); d = json.loads(got) if isinstance(got, str) else (got or {})
print("NM learned keys", list(d.keys()))
print("NM minutes", json.dumps(d.get("minutes"), default=str)[:900])
SE.refresh("NBA") if hasattr(SE, "refresh") else None
print("NM SE minutes after refresh", json.dumps((SE.DATA.get("NBA") or {}).get("minutes"), default=str)[:600])
rows = TB.blowout_rows("2026-11-10", sports_=("NBA",))
for r in rows: print("NM blow", r["time"], r["game"], r["team"], r["who"], round(r["chance"], 3), "fav_big", round(r["fav_big"], 3), "dog_big", round(r["dog_big"], 3), r["line"])
