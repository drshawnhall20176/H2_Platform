import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB
rows = TB.ufc_rows("2026-11-07", os.environ.get("ODDS_API_KEY"))
print("CARD", len(rows))
for r in rows:
    print("CARD", r["time"], "|", r["game"], "|", r["fav"], None if r["chance"] is None else f"{r['chance']:.0%}", r["fav_price"], "| books", r["books"])
