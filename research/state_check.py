"""Nov 14: open bets (stuck?), calibration settings in force, slates."""
import os, sys, json
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B
import model_store as MS
today = date(2026, 11, 14)
bets = B.list_bets()
open_ = [b for b in bets if not b.get("result")]
print("bets total", len(bets), "open", len(open_))
for b in sorted(open_, key=lambda x: str(x.get("slate_date"))):
    print("OPEN", b.get("id"), b.get("slate_date"), b.get("sport"), "|", b.get("player"), b.get("market"), b.get("side"), b.get("line"),
          "|", b.get("entry_odds"), "$", b.get("stake"), "| parlay" if b.get("parlay_id") or b.get("ticket_id") else "", "| notes", str(b.get("notes"))[:60], "| game", b.get("game"))
keys = ["tennis_calibration", "intl_slate", "soccer_slate", "intl_last_run"] + [f"game_calibration:{k}" for k in ("NCAAMB", "NBA", "NHL", "EUROLEAGUE")]
for k in keys:
    v = MS.get_setting(k)
    if isinstance(v, dict) and "history" in v:
        v = {**v, "history": v["history"][-1:]}
    print("SET", k, json.dumps(v, default=str)[:300])
# prop calibration settings
for k in ("calibration", "prop_calibration", "calibration:NBA", "calibration_NBA", "NBA_calibration"):
    v = MS.get_setting(k)
    if v is not None:
        print("SET", k, json.dumps(v, default=str)[:600])
