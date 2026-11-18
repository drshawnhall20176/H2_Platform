"""Nov 18: whole games whose posted props the model never read (window-based, so early-posted lines aren't miscounted).
Lines captured Nov 10-16 (UTC) vs every saved read Nov 10-18; a game counts as unread when none of its players with
lines was read on any of those days."""
import os, sys
from collections import defaultdict
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, line_history as LH, model_view as MV
DAYS = [f"2026-11-{d:02d}" for d in range(10, 19)]
SKIP = ("player_1st_td", "player_last_td")
for sp in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    idx = LH.sport_index(sp, "2026-11-10")
    games = defaultdict(lambda: {"players": set(), "first": "9999", "last": ""})
    for (pl, mk), rows in idx.items():
        if mk in SKIP: continue
        for r in rows:
            c = str(r["captured_at"])
            if c[:10] > "2026-11-16": continue
            g = games[r.get("game")]
            g["players"].add(MV.norm_name(pl)); g["first"] = min(g["first"], c[:16]); g["last"] = max(g["last"], c[:16])
    read = set()
    for s in MS.load_snapshots(sp, DAYS): read.add(MV.norm_name(s["player"]))
    miss = [(lab, g) for lab, g in games.items() if not (g["players"] & read)]
    part = [(lab, len(g["players"] - read), len(g["players"])) for lab, g in games.items() if g["players"] & read and len(g["players"] - read) >= 6]
    print(f"GG {sp}: games with posted props {len(games)}, NEVER read {len(miss)}, read but 6+ players with lines unread {len(part)}")
    for lab, g in sorted(miss, key=lambda x: x[1]["first"])[:25]:
        print(f"GGX {sp} unread game: {lab} | lines {len(g['players'])} players | captured {g['first']} .. {g['last']}")
    for lab, u, n in part[:10]:
        print(f"GGP {sp} partly read: {lab} | {u} of {n} players unread")
