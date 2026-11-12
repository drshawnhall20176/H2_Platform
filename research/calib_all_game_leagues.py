"""How honest each Game Lab / International Hoops league's win chance is (Nov 12), the check that exposed tennis:
favorite's win rate vs what the model said, by band, plus the best shrink factor k and its held-out result."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intl_hoops as I
import model_store as MS
import tennis_calibration as TC

for lg in list(I.LEAGUES) + ["TENNIS"]:
    try:
        ps = MS.load_game_picks(lg)
    except Exception as exc:
        print(lg, "load failed", exc); continue
    rs = TC.rows(ps)
    if not rs:
        print(f"{lg}: 0 graded"); continue
    n = len(rs); days = len({r['day'] for r in rs})
    fav = sum((r['y'] == 1) == (r['p'] >= .5) for r in rs) / n
    said = sum(max(r['p'], 1 - r['p']) for r in rs) / n
    bands = []
    for lo, hi in ((.5, .6), (.6, .7), (.7, .8), (.8, 1.01)):
        b = [r for r in rs if lo <= max(r['p'], 1 - r['p']) < hi]
        if len(b) >= 10:
            w = sum((r['y'] == 1) == (r['p'] >= .5) for r in b) / len(b)
            s = sum(max(r['p'], 1 - r['p']) for r in b) / len(b)
            bands.append(f"{int(lo*100)}-{int(min(hi,1)*100)}%: n={len(b)} won {w:.0%} said {s:.0%}")
    k = TC.fit(rs); h = TC.holdout(rs, 1.0)
    print(f"{lg}: n={n} days={days} fav won {fav:.0%} said {said:.0%} | best k={k:.2f} holdout {h}")
    for b in bands:
        print("    ", b)
