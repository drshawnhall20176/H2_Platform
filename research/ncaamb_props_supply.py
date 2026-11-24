import sys, os, collections; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS
days = [d for d in MS.snapshot_dates("NCAAMB") if d >= "2026-11-03"]
snaps = MS.load_snapshots("NCAAMB", days)
print("snapshot cols", sorted(snaps[0].keys()) if snaps else None)
by = collections.defaultdict(collections.Counter)
games = collections.defaultdict(set); allgames = collections.defaultdict(set)
for s in snaps:
    d = s["slate_date"]
    src = s.get("book") or s.get("source") or "?"
    priced = s.get("p_market") is not None
    by[d][("priced" if priced else "pickem") + ":" + str(src)] += 1
    allgames[d].add(s.get("game"))
    if priced: games[d].add(s.get("game"))
for d in sorted(by):
    print(d, "games w/ props", len(allgames[d]), "games w/ sportsbook-priced props", len(games[d]), dict(by[d].most_common(8)))
gp = MS.load_game_picks("NCAAMB")
cnt = collections.Counter(str(p.get("kickoff"))[:10] for p in gp)
print("game picks per day", sorted(cnt.items())[-20:])
