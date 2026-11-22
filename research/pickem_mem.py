import sys, time, resource, os
sys.path.insert(0, ".")
def rss():
    with open("/proc/self/statm") as f: return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6
import slate_store as SS, best_bets_data as BBD, pickem as PK
SS._in_app = lambda: True
BBD._in_app = lambda: True
from datetime import datetime
import pytz
d = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
api = BBD.get_odds_api_key()
for sp in ("NCAAF",):
    t = time.time(); print(f"PM start rss={rss():.0f}MB")
    main = BBD.fetch_generic_offers(sp, d, api); print(f"PM offers {len(main)} rss={rss():.0f}MB t={time.time()-t:.0f}s")
    ids = tuple(sorted({o["event_id"] for o in main if o.get("event_id")})); print("PM events", len(ids))
    extra = BBD.fetch_pickem_extra_offers(sp, d, api, ids); print(f"PM extra {len(extra)} rss={rss():.0f}MB t={time.time()-t:.0f}s")
    offers = BBD.merge_offers(main, extra); print(f"PM merged {len(offers)} rss={rss():.0f}MB")
    sb = BBD.saved_board(sp, d, BBD.O.DEFAULT_BOOK); print(f"PM saved_board {'yes' if sb else 'NO'} meta={len(sb[1]) if sb else 0} rss={rss():.0f}MB")
    reads = BBD.load_slate_reads(sp, d, BBD.O.DEFAULT_BOOK); print(f"PM reads {len(reads or {})} rss={rss():.0f}MB t={time.time()-t:.0f}s")
    legs = PK.legs(reads or {}, offers, "prizepicks", sp); print(f"PM legs {len(legs)} rss={rss():.0f}MB peak={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e3:.0f}MB t={time.time()-t:.0f}s")
