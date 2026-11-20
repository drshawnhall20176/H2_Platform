"""Nov 20: peak memory of building each sport's board (the Command Center build)."""
import gc, resource, sys, time
sys.path.insert(0, ".")
import best_bets_data as BBD, props_engine as PE

def rss():
    with open("/proc/self/statm") as fh:
        return int(fh.read().split()[1]) * 4096 / 1e6

day = PE._et_today()
print(f"MEM start rss={rss():.0f}MB peak={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e3:.0f}MB")
for sp in ("NCAAF", "NCAAMB", "NBA", "NHL", "NFL"):
    t = time.time(); before = rss()
    try:
        plays, meta, _ = BBD.load_generic_best_bets_board(sp, day, BBD.O.DEFAULT_BOOK)
        n = (len(plays), len(meta))
    except Exception as e:
        n = f"failed {type(e).__name__}: {e}"
    print(f"MEM {sp}: {n} rss {before:.0f}->{rss():.0f}MB peak={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e3:.0f}MB "
          f"{time.time()-t:.0f}s")
    gc.collect()
