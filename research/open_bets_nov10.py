import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B
for b in sorted(B.list_bets(), key=lambda b: (str(b.get("slate_date")), b["id"])):
    if B._result(b) in ("win", "loss", "push", "void"):
        continue
    print("OB", b["id"], b.get("slate_date"), b.get("sport"), "real" if b.get("is_real_bet") else "track", B._ticket(b) or "single",
          "|", b.get("player") or "", b.get("market"), b.get("side"), b.get("line"), "|", b.get("game"), "|", b.get("entry_odds"), "$", b.get("stake"), "|", b.get("notes"))
