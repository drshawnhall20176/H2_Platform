"""research/injury_news_test.py — do reads hit worse when there's injury news AND the model is far from the market?
(Nov 5) For every graded read with both chances stored (p_model, p_market = P(over)): the side's model/market ratio
(what the boards call Conviction) and whether the read carried an injury flag. Hit rate by flag x ratio band."""
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NEWS = ("out)", "teammates out", "freshly out", "role change", "moves up", "backup", "Backup QB", "Missed the team",
        "more ice time", "usage bump")


def num(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def main() -> int:
    import daily_review as D
    import model_store as MS
    for sport in (os.environ.get("AUDIT_SPORTS") or "NBA,NHL,NFL").split(","):
        graded = D.grade_dates(sport, MS.snapshot_dates(sport))
        cell = defaultdict(lambda: [0, 0])
        for d, rs in graded.items():
            for r in rs:
                if r.get("result") not in ("hit", "miss"):
                    continue
                pm, pk = num(r.get("p_model")), num(r.get("p_market"))
                if pm is None or pk is None or not 0 < pk < 1:
                    continue
                side = r.get("side") or "Over"
                ratio = (pm / pk) if side == "Over" else ((1 - pm) / (1 - pk))
                try:
                    flags = " ".join(json.loads(r.get("flags") or "[]"))
                except Exception:                                   # noqa: BLE001
                    flags = str(r.get("flags") or "")
                news = any(k.lower() in flags.lower() for k in NEWS)
                band = "<1.10" if ratio < 1.10 else ("1.10-1.30" if ratio < 1.30 else ("1.30-1.50" if ratio < 1.50 else "1.50+"))
                c = cell[(news, band)]
                c[0] += 1 if r["result"] == "hit" else 0
                c[1] += 1
        print(f"\n{sport}: hit rate by injury news x model/market ratio (Conviction)")
        for news in (False, True):
            print("  " + ("injury news" if news else "no news    ") + "  " + "  ".join(
                f"{b}: {cell[(news, b)][0]}/{cell[(news, b)][1]} ({cell[(news, b)][0] / cell[(news, b)][1]:.0%})"
                if cell[(news, b)][1] else f"{b}: —" for b in ("<1.10", "1.10-1.30", "1.30-1.50", "1.50+")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
