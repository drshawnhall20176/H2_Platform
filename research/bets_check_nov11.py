"""Nov 11 morning: yesterday's bets (results, P/L) and anything still open."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B           # noqa: E402

allb = B.list_bets()
for b in allb:
    if str(b.get("slate_date")) in ("2026-11-09", "2026-11-10") or not b.get("settled_at") and b.get("result") in (None, "", "pending"):
        print("BC", b["id"], b.get("slate_date"), b.get("sport"), "|", b.get("player"), b.get("market"), b.get("side"),
              b.get("line"), "| odds", b.get("entry_odds"), "stake", b.get("stake"), "real", b.get("is_real_bet"),
              "| result", b.get("result"), "pl", b.get("profit"), "| ticket", b.get("ticket"), "| pid", b.get("player_id"),
              "| tag", b.get("strategy_tag"), "| notes", (b.get("notes") or "")[:80])
