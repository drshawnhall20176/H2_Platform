import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B, intl_picks as IP, model_store as MS
recs = MS.load_game_picks("NCAAMB")
for b in B.list_bets():
    if int(b["id"]) not in range(866, 880):
        continue
    lm = None
    try:
        lm = IP.link_manual(b, "NCAAMB", recs)
    except Exception as e:
        lm = f"ERR {type(e).__name__}"
    print("DIAG", b["id"], "sport_ok", b.get("sport") == "NCAAMB", "player_none", b.get("player") in (None, ""),
          "ticket_blank", not b.get("ticket"), "has_at", " @ " in str(b.get("game") or ""),
          "market", b.get("market"), "has_link", "gl:NCAAMB:" in str(b.get("notes") or ""), "result_set", bool(b.get("result")),
          "slate", str(b.get("slate_date"))[:10], "player_type", type(b.get("player")).__name__,
          "ticket_type", type(b.get("ticket")).__name__, "link_manual", (lm if isinstance(lm, str) else bool(lm)))
