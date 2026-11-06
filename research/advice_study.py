"""Nov 6: test two Postgame Review suggestions before applying them.
1. "Single only plays hit 42% -- raise the single edge +3% -> +5%": split 🎯 rows by value bucket, side, sport.
2. "Big gap: the MODEL was right 62% -- give the model more vote": split big-gap rows by sport/side/market kind,
   and check what a bet on the model's side would have earned at the posted price."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from single_bar_study import _dec, summarize   # noqa: E402


def main():
    import daily_review as D, model_store as MS, props_engine as PE
    for sp in ("NBA", "NHL", "NFL", "NCAAF", "WNBA"):
        try:
            graded = D.grade_dates(sp, MS.snapshot_dates(sp))
        except Exception as e:                                  # noqa: BLE001
            print(sp, "error", e); continue
        rows, seen = [], set()
        for d, recs in graded.items():
            for r in recs:
                if r.get("result") not in ("hit", "miss"):
                    continue
                k = (d, r.get("player"), r.get("market"), r.get("side"), r.get("line"))
                if k in seen:
                    continue
                seen.add(k)
                rows.append(dict(r, date=d, y=1 if r["result"] == "hit" else 0))
        print(f"\n## {sp}: {len(rows)} graded reads, {len(graded)} slates")
        singles = [r for r in rows if r.get("use_tag") == PE.USE_SINGLE and r.get("price") is not None]
        for r in singles:
            if r.get("ev") is None and r.get("chance") is not None:
                r["ev"] = r["chance"] * _dec(r["price"]) - 1
        singles = [r for r in singles if r.get("ev") is not None]
        print(summarize(singles, "🎯 single only (all)"))
        for lo, hi in [(-9, .03), (.03, .05), (.05, .08), (.08, .12), (.12, 9)]:
            print(summarize([r for r in singles if lo <= r["ev"] < hi], f"  🎯 value {lo:+.0%}..{hi:+.0%}"))
        for s in ("Over", "Under"):
            print(summarize([r for r in singles if r.get("side") == s], f"  🎯 {s}"))
            print(summarize([r for r in singles if r.get("side") == s and r["ev"] >= .05], f"  🎯 {s} value>=5%"))
        for tag in (PE.USE_BOTH, PE.USE_PARLAY, PE.USE_PASS):
            g = [r for r in rows if r.get("use_tag") == tag and r.get("price") is not None]
            print(summarize(g, f"{tag}"))
        gaps = [r for r in rows if str(r.get("gap") or "").startswith("big") and r.get("model_hit") is not None]
        if gaps:
            mr = sum(1 for r in gaps if r["model_hit"]) / len(gaps)
            print(f"big gap: n={len(gaps)} model right {mr:.0%}")
            for s in ("Over", "Under"):
                g = [r for r in gaps if (r.get("model_side") or r.get("lean_side") or r.get("proj_side")) == s]
                if not g:
                    g = [r for r in gaps if ((r.get("projection") or 0) > (r.get("line") or 0)) == (s == "Over")]
                if g:
                    print(f"   model says {s}: n={len(g)} model right {sum(1 for r in g if r['model_hit']) / len(g):.0%}")
            for kind in ("big", "big-low-count"):
                g = [r for r in gaps if r.get("gap") == kind]
                if g:
                    print(f"   {kind}: n={len(g)} model right {sum(1 for r in g if r['model_hit']) / len(g):.0%}")
            # money: bet the model's side at the posted price, where that side is the row's priced side
            priced = [r for r in gaps if r.get("price") is not None and
                      (((r.get("projection") or 0) > (r.get("line") or 0)) == (r.get("side") == "Over"))]
            if priced:
                print(summarize([dict(r, y=1 if r["model_hit"] else 0) for r in priced], "   model side at posted price"))
            dates = sorted({r["date"] for r in gaps})
            half = dates[len(dates) // 2] if dates else None
            for lab, g in (("early", [r for r in gaps if r["date"] < half]), ("late", [r for r in gaps if r["date"] >= half])):
                if g:
                    print(f"   {lab} half: n={len(g)} model right {sum(1 for r in g if r['model_hit']) / len(g):.0%}")


if __name__ == "__main__":
    main()
