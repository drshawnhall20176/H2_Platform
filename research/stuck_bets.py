"""Nov 8: why are 11 real bets still open? Dry-run settlement (nothing written)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import betlog as B           # noqa: E402
import daily_review as D     # noqa: E402

open_ = [b for b in B.list_bets(settled=False) if b.get("is_real_bet")]
for b in open_:
    print("SB OPEN", b["id"], b.get("sport"), b.get("slate_date"), "|", b.get("player"), b.get("market"), b.get("side"), b.get("line"),
          "| game", b.get("game"), "| notes", b.get("notes"), "| ticket", b.get("ticket"), "| pid", b.get("player_id"))
for sp in sorted({b.get("sport") for b in open_}):
    try:
        st = D.settle(sp, [b for b in open_ if b.get("sport") == sp], write=False)
        print("SB SETTLE", sp, "settled", [(x.get("id"), x.get("result")) for x in st.get("settled") or []],
              "| unresolved", [(x.get("id"), x.get("why") or x.get("reason")) for x in st.get("unresolved") or []],
              "| pending", [x.get("id") for x in st.get("still_pending") or []])
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("SB ERR", sp, e)
