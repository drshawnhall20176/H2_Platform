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
        clear = [x for x in chk if x["chance"] >= (x["needed"] if x.get("needed") is not None else PK.breakeven(6, 3))]
        print("PK", app, "legs", len(lg), "checked", len(chk), "clear", len(clear))
        for x in sorted(chk, key=lambda x: -(x["chance"] - (x.get("needed") or PK.breakeven(6, 3))))[:3]:
            print("   ", x["player"], x["market"], x["side"], x["app_line"], "price", x.get("price"), "needs",
                  None if x.get("needed") is None else round(x["needed"], 3), "chance", round(x["chance"], 3),
                  "books", x.get("book_line"))
        e = PK.best_entry(lg, 3, PK.breakeven(6, 3))
        if len(e) == 3:
            r = PK.entry_odds(e, app, sport=sp)
            print("   ENTRY", [x["player"] for x in e], r and {k: r[k] for k in ("all", "ev", "mult")})
