import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB, college_lines as CL
day = "2026-11-24"
win = TB.winner_rows(day, leagues=["NCAAMB"])
rows = CL.today_rows("NCAAMB", day, win)
tr = [r for r in rows if r["Bet?"] != "Info only"]
print("tracking rows", len(tr), "games", len({r['Game'] for r in tr}))
for r in tr:
    print("|".join(str(x) for x in (r["Time"], r["Game"], r["Bet?"], r["Use"], r["Pick type"], r["Market"], r["Pick"], r["Price"],
          r["Blowout risk"], r.get("_move", ""), r["Last meetings"][:40])))
byg = {}
for w in win:
    byg[w["game"]] = w
print("--- line pick vs close-gap check + money pick")
for r in tr:
    w = byg.get(r["Game"], {})
    print(r["Game"], "| best:", w.get("best"), w.get("bet_market"), "| money:", w.get("money_pick"), w.get("money_score"), "| move:", w.get("spread_move"))
