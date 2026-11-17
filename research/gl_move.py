"""Nov 17: game lines -- when the spread moves toward the model's side (open -> close), does the pick cover more?"""
import os, sys, json
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
for lg in ("NCAAMB", "NBA", "NCAAF"):
    recs = MS.load_game_picks(lg)
    done = [r for r in recs if r.get("final_home") is not None and r.get("open_line") is not None and r.get("close_line") is not None]
    print(f"\n{lg}: {len(recs)} records, {len(done)} with finals+open+close")
    for r in done[:2]:
        print("  SAMPLE", json.dumps({k: r.get(k) for k in ("home","away","pick","line","open_line","close_line","home_spread","model_margin","edge","result","use","lock","final_home","final_away")}, default=str))
    st = {}
    for r in done:
        try:
            mm = float(r["model_margin"]); o = float(r["open_line"]); c = float(r["close_line"])
            fh, fa = float(r["final_home"]), float(r["final_away"])
        except (TypeError, ValueError, KeyError):
            continue
        # convention check: line = home spread (home -5 means home favored by 5); model_margin = home - away
        home_side = mm + o > 0                       # model thinks home covers the opening spread
        move = (o - c) if home_side else (c - o)     # home spread getting more negative = market toward home
        margin = fh - fa
        cover = (margin + o > 0) if home_side else (margin + o < 0)
        if margin + o == 0: continue
        edge = abs(mm + o)
        b = "toward" if move >= 1.0 else ("away" if move <= -1.0 else "flat")
        for key in (("all", b),) + ((("edge3+", b),) if edge >= 3 else ()):
            n, h = st.get(key, (0, 0)); st[key] = (n + 1, h + cover)
    for k in sorted(st):
        n, h = st[k]; print(f"  {k[0]:6} {k[1]:6} n {n:4} covered (at OPEN line) {h/n:.1%}")
