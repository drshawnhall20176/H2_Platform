"""Nov 6: candidate 🎯 single rules, checked slate by slate (a rule must help on most slates, not just in total).
R1 NHL: no singles.  R2 NFL: no Over singles.  R3 NFL: singles capped at +8% value.  R4 NBA: no Over singles (after the
side correction, are any Over singles still losing?)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from single_bar_study import _dec   # noqa: E402


def prof(rows):
    return sum((_dec(r["price"]) - 1) if r["y"] else -1 for r in rows)


def main():
    import daily_review as D, model_store as MS, props_engine as PE
    rules = {"NHL": [("R1 all singles (would be removed)", lambda r: True)],
             "NFL": [("R2 Over singles (would be removed)", lambda r: r["side"] == "Over"),
                     ("R3 singles value>=8% (would be removed)", lambda r: r["ev"] >= 0.08)],
             "NBA": [("R4 Over singles (would be removed)", lambda r: r["side"] == "Over"),
                     ("NBA singles value 5-12% (check)", lambda r: 0.05 <= r["ev"] < 0.12)],
             "NCAAF": [("Over singles", lambda r: r["side"] == "Over")]}
    for sp, rs in rules.items():
        graded = D.grade_dates(sp, MS.snapshot_dates(sp))
        rows, seen = [], set()
        for d, recs in graded.items():
            for r in recs:
                if r.get("result") not in ("hit", "miss") or r.get("use_tag") != PE.USE_SINGLE or r.get("price") is None:
                    continue
                k = (d, r.get("player"), r.get("market"), r.get("side"), r.get("line"))
                if k in seen:
                    continue
                seen.add(k)
                ev = r.get("ev")
                if ev is None and r.get("chance") is not None:
                    ev = r["chance"] * _dec(r["price"]) - 1
                if ev is None:
                    continue
                rows.append({"date": d, "side": r.get("side"), "ev": ev, "price": r["price"], "y": r["result"] == "hit"})
        print(f"\n## {sp}: {len(rows)} 🎯 singles")
        for name, f in rs:
            sel = [r for r in rows if f(r)]
            print(f"{name}: n={len(sel)} profit {prof(sel):+.1f}u ({(prof(sel) / len(sel)) if sel else 0:+.0%}/bet)")
            for d in sorted({r['date'] for r in rows}):
                s = [r for r in sel if r["date"] == d]
                if s:
                    print(f"    {d}: n={len(s):3d} hit {sum(r['y'] for r in s) / len(s):4.0%} profit {prof(s):+.1f}u")


if __name__ == "__main__":
    main()
