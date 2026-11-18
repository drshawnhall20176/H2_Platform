"""Nov 18: NHL / NCAAF / NFL lines on players the model never read at all -- per slate, recent days only."""
import os, sys
from collections import Counter, defaultdict
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, line_history as LH, model_view as MV
for sp, days in (("NHL", ("2026-11-15", "2026-11-16", "2026-11-17")), ("NBA", ("2026-11-16", "2026-11-17")),
                 ("NCAAF", ("2026-11-14",)), ("NFL", ("2026-11-15", "2026-11-16"))):
    for d in days:
        idx = LH.sport_index(sp, (date.fromisoformat(d) - timedelta(days=3 if sp in ("NFL", "NCAAF") else 0)).isoformat())
        snaps = MS.load_snapshots(sp, [d])
        read = {MV.norm_name(s["player"]) for s in snaps}
        games_read = {s["game"] for s in snaps}
        lines = defaultdict(set)
        for (pl, mk), rows in idx.items():
            rows = [r for r in rows if str(r["captured_at"])[:10] <= d and str(r["captured_at"])[:10] >= (date.fromisoformat(d) - timedelta(days=3 if sp in ("NFL","NCAAF") else 0)).isoformat()]
            if rows: lines[MV.norm_name(pl)].add((mk, rows[-1].get("game")))
        unread = {p: v for p, v in lines.items() if p not in read}
        mk = Counter(m for v in unread.values() for m, _ in v)
        gm = Counter(g for v in unread.values() for _, g in v)
        print(f"NG {sp} {d}: players with lines {len(lines)}, read by the model {len(read)}, never read {len(unread)}; "
              f"their markets {dict(mk.most_common(6))}")
        print(f"NG {sp} {d}: games of the unread lines {dict(gm.most_common(6))} | games the model saved: {len(games_read)}")
        print(f"NG {sp} {d}: examples {list(unread)[:15]}")
