import os, sys, json
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, betlog as B, watch as W
b = MS.get_setting("brief:2026-11-18:morning")
print("BRIEF\n" + (b.get("text") if isinstance(b, dict) else str(b)))
for x in B.list_bets():
    if (x.get("id") or 0) >= 742:
        print("BET", x.get("id"), x.get("slate_date"), x.get("player") or x.get("game"), x.get("market"), x.get("side"),
              x.get("line"), x.get("entry_odds"), x.get("stake"), B._result(x), round(B.bet_pnl(x) or 0, 2), x.get("actual") if "actual" in x else "")
print("WATCH", json.dumps(MS.get_setting(W.STATUS_KEY, {}), default=str)[:800])
print("OVERS", json.dumps(MS.get_setting(W.OVERS_KEY, {}), default=str)[:800])
