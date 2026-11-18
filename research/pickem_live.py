"""Nov 18: the Pick'em board on today's real lines (no writes)."""
import os, sys
from collections import Counter
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import best_bets_data as BBD, model_store as MS, slate_store as SS, pickem as PK, sports
MS.save_reads = lambda *a, **k: 0
day = SS._today_et(); api = BBD.get_odds_api_key()
for sp in ("NBA", "NCAAMB", "NHL"):
    offers = BBD.fetch_generic_offers(sp, day, api)
    rows, meta = sports.get(sp).engine.build_slate(day)
    reads = BBD.slate_reads_for(sp, day, meta, offers, BBD.O.DEFAULT_BOOK) or {}
    pk = Counter(b for o in offers for b in (o.get("pickem") or {}))
    print("LV", sp, "offers", len(offers), "pickem lines by app", dict(pk), "reads", len(reads))
    for app in ("prizepicks", "underdog", "pick6"):
        lg = PK.legs(reads, offers, app, sp)
        if not lg: continue
        bk = [x for x in lg if x["basis"] == "books"]
        fl = PK.breakeven(PK.APPS[app]["power"][2], 2)
        print("LV", sp, app, "legs", len(lg), "books-checked", len(bk), "clear 2-pick break-even", sum(x["chance"] >= fl for x in bk),
              "| diff lines app vs books", sum(1 for x in bk if x["book_line"] != x["app_line"]))
        for x in bk[:6]:
            print("LVX", sp, app, x["player"], x["market"], x["side"], x["app_line"], "books", x["book_line"], round(x["book_over"] or 0, 3),
                  "->", round(x["chance"], 3), "model", round(x["model_over"], 3))
        e = PK.best_entry(lg, 3, PK.breakeven(PK.APPS[app]["power"][3], 3))
        if len(e) == 3:
            r = PK.entry_odds(e, app, sport=sp); print("LVE", sp, app, [(x["player"], x["side"], x["app_line"]) for x in e], round(r["all"], 3), round(r["ev"], 3))
