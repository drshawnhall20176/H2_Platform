import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, model_store as MS, todays_best as TB
from datetime import datetime
import pytz
d = datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
print("available:", MS.available(), "date", d)
for sp in ("NBA",):
    try:
        plays, meta, _ = BBD.load_generic_best_bets_board(sp, d, BBD.O.DEFAULT_BOOK)
        print(sp, "plays", len(plays), "props-model rows", sum(1 for p in plays if p.get("Model") == "player-props"),
              "tagged", sum(1 for p in plays if p.get("Use")))
        rows = TB.props_rows(sp, plays)
        print("props_rows", len(rows))
        ok = MS.save_setting(TB.KEY.format(sport=sp, date=d), {"at": "x", "rows": rows})
        print("direct save ok:", ok)
        print("saved now:", (TB.load_props(sp, d) or {}).get("at"), len((TB.load_props(sp, d) or {}).get("rows") or []))
        print("diag:", BBD.st.session_state.get(f"_bb_diag_{sp}_{d}") if hasattr(BBD, "st") else None)
    except Exception:
        traceback.print_exc()
