"""Nov 18: dry run of the Pick'em Board with the new apps (Dabble, ParlayPlay) and exchange prices (Novig, ProphetX)."""
import os, sys
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import odds_api as O, best_bets_data as BBD, pickem as PK
api = BBD.get_odds_api_key()
date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
for sp in ("NBA",):
    main = BBD.fetch_generic_offers(sp, date, api)
    extra = BBD.fetch_pickem_extra_offers(sp, date, api)
    merged = BBD.merge_offers(main, extra)
    reads = BBD.load_slate_reads(sp, date, O.DEFAULT_BOOK)
    c = Counter()
    for o in merged:
        for b in list(o.get("over") or {}) + list(o.get("pickem") or {}):
            c[b] += 1
    print("PK", sp, "offers main", len(main), "extra", len(extra), "merged", len(merged), "reads", len(reads or {}))
    print("PK books", dict(c))
    ex_lines = sum(1 for o in merged if any(b in (o.get("over") or {}) for b in O.EXCHANGE_BOOKS))
    print("PK lines with an exchange price", ex_lines)
    for app in PK.APPS:
        lg = PK.legs(reads or {}, merged, app, sp)
        chk = [x for x in lg if x["basis"] == "books"]
        fl = PK.breakeven(PK.APPS[app]["power"][3], 3)
        bar = lambda x: max(fl, x["needed"]) if x.get("needed") is not None else fl
        clear = [x for x in chk if x["chance"] >= bar(x)]
        same = [x for x in chk if x.get("book_line") == x["app_line"] and x.get("needed") is not None]
        if same:
            import statistics as stt
            print("   same-line picks", len(same), "median chance-needed", round(stt.median(x["chance"] - x["needed"] for x in same), 3),
                  "share where app price beats books by >5pts", round(sum(1 for x in same if x["chance"] - x["needed"] > 0.05) / len(same), 3))
        print("PK", app, "legs", len(lg), "checked", len(chk), "clear", len(clear))
        for x in sorted(chk, key=lambda x: -(x["chance"] - bar(x)))[:3]:
            print("   ", x["player"], x["market"], x["side"], x["app_line"], "price", x.get("price"), "needs",
                  None if x.get("needed") is None else round(x["needed"], 3), "chance", round(x["chance"], 3),
                  "books", x.get("book_line"))
        e = PK.best_entry(lg, 3, fl)
        if len(e) == 3:
            r = PK.entry_odds(e, app, sport=sp)
            print("   ENTRY", [x["player"] for x in e], r and {k: r[k] for k in ("all", "ev", "mult")})
