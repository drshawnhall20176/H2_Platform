import os, sys
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, settle_results as S
try:
    print("SETTLE main ->", S.main())
except SystemExit as e:
    print("settle exit", e)
except Exception as exc:
    print("settle error", type(exc).__name__, exc)
bets = [b for b in B.list_bets() if str(b.get("slate_date")) == "2026-11-15"]
for b in sorted(bets, key=lambda b: b["id"]):
    print("BET", b["id"], b.get("sport"), b.get("game"), "|", b.get("player"), b.get("market"), b.get("side"), b.get("line"), "|", b.get("entry_odds"), b.get("stake"), "|", b.get("result"), b.get("actual_value") or b.get("actual"), "| real" if b.get("is_real_bet") else "| track", "| parlay leg" if b.get("parlay_id") or b.get("parent_id") else "")
