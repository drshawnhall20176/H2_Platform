import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
for lg in ("NBA", "NHL", "NFL", "NCAAF"):
    recs = [p for p in MS.load_game_picks(lg) if p.get("final_home") is not None and p.get("home_spread") is not None and p.get("model_margin") is not None and str(p.get("kickoff"))[:10] >= "2026-10-15"]
    b = {}
    for p in recs:
        hs, mm = float(p["home_spread"]), float(p["model_margin"]); act = float(p["final_home"]) - float(p["final_away"])
        d = mm + hs
        if d == 0 or act + hs == 0: continue
        win = (d > 0) == (act + hs > 0)
        if lg == "NHL":
            mp, fh = p.get("model_p"), p.get("fair_home")
            if mp is None or fh is None: continue
            g = abs(mp - fh); key = "<4%" if g < .04 else "4-8%" if g < .08 else "8%+"
            fav_win = (mp > 0.5) == (act > 0)          # model's winner correct
            b.setdefault(("ml-winner", key), []).append(fav_win)
            # moneyline on the model's side at the market's fair price: units
            side_p = mp if mp > fh else 1 - mp; mkt_p = fh if mp > fh else 1 - fh
            won = (act > 0) if mp > fh else (act < 0)
            b.setdefault(("ml-value-side", key), []).append(won)
        else:
            g = abs(d); key = "<2" if g < 2 else "2-5" if g < 5 else "5+"
            b.setdefault(("spread", key), []).append(win)
    for k, v in sorted(b.items()):
        print("H", lg, k, f"{sum(v)}-{len(v)-sum(v)} ({sum(v)/len(v):.0%})")
