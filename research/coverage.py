"""Nov 18: lines the books posted that the model never read; your bets missing a closing price."""
import os, sys
from collections import Counter, defaultdict
from datetime import date, timedelta
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_store as MS, line_history as LH, model_view as MV, betlog as B, props_engine as PE
since = (date.today() - timedelta(days=14)).isoformat()
import slate_props as SP, nfl_projections as NP, ncaaf_projections as CP, nhl_projections as HP
KEYMAP = dict(SP.CORE_MARKETS)
for mod in (NP, CP, HP):
    for name in dir(mod):
        v = getattr(mod, name)
        if isinstance(v, dict) and v and all(isinstance(k, str) and k.startswith("player_") for k in v):
            for k, t in v.items():
                if isinstance(t, tuple) and len(t) > 1 and isinstance(t[1], str):
                    KEYMAP.setdefault(k, t[1])
KEYMAP.update({"player_anytime_td": "Anytime TD", "player_total_saves": "Saves", "player_blocked_shots": "Blocked Shots",
               "player_goals": "Goals", "player_points_nhl": "Points"})
print("KEYMAP", KEYMAP)
def mkname(sp, k):
    if sp == "NHL" and k == "player_points": return "Points"
    if sp == "NHL" and k == "player_assists": return "Assists"
    return KEYMAP.get(k, k)
for sp in ("NBA", "NHL", "NFL", "NCAAF", "NCAAMB"):
    idx = LH.sport_index(sp, since)
    lines = defaultdict(set)            # date -> {(player, market)}
    for (pl, mk), rows in idx.items():
        for r in rows:
            d = str(r.get("captured_at"))[:10]
            lines[d].add((MV.norm_name(pl), mkname(sp, mk)))
    ds_all = sorted({(date.fromisoformat(d) + timedelta(days=k)).isoformat() for d in lines for k in range(-1, 8)})
    snaps = MS.load_snapshots(sp, ds_all) if lines else []
    reads = defaultdict(set)
    for s in snaps:
        reads[s["slate_date"]].add((MV.norm_name(s.get("player")), MV.market_of(s.get("market")) or s.get("market")))
    tot = miss = 0; mk_miss = Counter(); mk_tot = Counter(); ex = []; known = Counter()
    for d in sorted(lines):
        if d >= date.today().isoformat(): continue
        span = range(-1, 8) if sp in ("NFL", "NCAAF") else range(-1, 1)
        have = set().union(*[reads.get((date.fromisoformat(d) + timedelta(days=k)).isoformat(), set()) for k in span])
        players_read = {p for p, _ in have}
        for k in lines[d]:
            tot += 1; mk_tot[k[1]] += 1
            if k not in have:
                miss += 1; mk_miss[k[1]] += 1
                known[(k[1], k[0] in players_read)] += 1
                if len(ex) < 12: ex.append((d,) + k)
    if tot:
        print(f"COV {sp}: book lines captured {tot}, never read by the model {miss} ({miss/tot:.1%})")
        print(f"COV {sp} unread by market: " + ", ".join(f"{m} {mk_miss[m]}/{mk_tot[m]}" for m in sorted(mk_tot, key=lambda m: -mk_miss[m])[:14]))
        print(f"COV {sp} examples: {ex}")
        print(f"COV {sp} unread lines where the model DID read that player in another market: " + ", ".join(
            f"{m} {known[(m, True)]}/{known[(m, True)] + known[(m, False)]}" for m in sorted(mk_miss, key=lambda m: -mk_miss[m])[:12]))
    else:
        print(f"COV {sp}: no book lines captured in the last 14 days")
bets = B.list_bets()
settled = [b for b in bets if b.get("result") in ("win", "loss", "push")]
print(f"BETS settled {len(settled)}, with a closing price {sum(1 for b in settled if b.get('close_odds') is not None)}")
miss = Counter((b.get("sport"), b.get("market")) for b in settled if b.get("close_odds") is None)
print("BETS missing close by sport/market:", dict(miss.most_common(12)))
