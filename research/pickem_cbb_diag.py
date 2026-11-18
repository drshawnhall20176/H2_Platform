"""Nov 18: why the Pick'em Board shows no NCAAMB lines when DK Pick6 has them posted."""
import os, sys
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import odds_api as O, best_bets_data as BBD, pickem as PK, props_engine as PE
api = BBD.get_odds_api_key()
date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
sp = "NCAAMB"
main = BBD.fetch_generic_offers(sp, date, api)
info = BBD.generic_fetch_info(sp, date) or {}
print("CD info", {k: (v if not isinstance(v, list) else len(v)) for k, v in info.items()})
c = Counter()
for o in main:
    for b in list(o.get("over") or {}) + list(o.get("pickem") or {}):
        c[b] += 1
print("CD main offers", len(main), dict(c))
print("CD markets", Counter(o["market"] for o in main).most_common())
print("CD games with offers", len({o.get("event_id") for o in main}))
ids = tuple(sorted({o["event_id"] for o in main if o.get("event_id")}))
extra = BBD.fetch_pickem_extra_offers(sp, date, api, ids)
print("CD extra", len(extra))
rows, meta = BBD._big_slate_props_games(BBD.sports.get(sp), sp, date, api)
print("CD big-slate meta", len(meta), [m.get("label") for m in meta][:10])
reads = BBD.load_slate_reads(sp, date, O.DEFAULT_BOOK) or {}
print("CD reads", len(reads), Counter(r.get("market_key") for r in reads.values()).most_common())
rk = {(PE.norm_name(r.get("player")), r.get("market_key")) for r in reads.values() if r.get("projection") is not None}
pk6 = [o for o in main if "pick6" in (o.get("pickem") or {})]
ok = sum(1 for o in pk6 if (PE.norm_name(o["player"]), o["market"]) in rk)
print("CD pick6 offers", len(pk6), "matching a read", ok)
print("CD pick6 sample", [(o["player"], o["market"], o["point"], o.get("home_team")) for o in pk6[:8]])
print("CD read sample", list(rk)[:8])
merged = BBD.merge_offers(main, extra)
for app in PK.APPS:
    print("CD legs", app, len(PK.legs(reads, merged, app, sp)))
