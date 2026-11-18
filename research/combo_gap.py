"""Nov 18: why are NBA combo lines (PR / PA / RA / PRA) unread for players the model DID read in Points?"""
import os, sys
from collections import Counter, defaultdict
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, line_history as LH, model_view as MV
COMBO = {"player_points_rebounds": "PR", "player_points_assists": "PA", "player_rebounds_assists": "RA",
         "player_points_rebounds_assists": "PRA", "player_points": "Points"}
for d in ("2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17"):
    idx = LH.sport_index("NBA", d)
    snaps = MS.load_snapshots("NBA", [d])
    have = defaultdict(set)
    for s in snaps: have[MV.norm_name(s["player"])].add(s["market"])
    books = Counter(); times = Counter(); n = 0; ex = []
    for (pl, mk), rows in idx.items():
        if mk not in COMBO or mk == "player_points": continue
        rows = [r for r in rows if str(r["captured_at"])[:10] in (d,)]
        if not rows: continue
        p = MV.norm_name(pl)
        if "Points" in have[p] and COMBO[mk] not in have[p]:
            n += 1
            for r in rows: books[r.get("book")] += 1; times[str(r["captured_at"])[11:13]] += 1
            if len(ex) < 4: ex.append((pl, COMBO[mk], sorted(have[p]), sorted({r.get('book') for r in rows}), sorted({str(r['captured_at'])[11:16] for r in rows})))
    print("CG", d, "unread combos for players read in Points:", n, "books", dict(books.most_common(8)), "hours UTC", dict(sorted(times.items())))
    for e in ex: print("CGX", e)
