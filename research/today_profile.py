import os, sys, time, cProfile, pstats, io
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import todays_best as TB, model_store as MS
day = "2026-11-17"
a = time.time(); MS.get_setting("x"); print("T one get_setting", round(time.time()-a, 2))
a = time.time(); MS.get_setting("x"); print("T second get_setting", round(time.time()-a, 2))
for label, f in (("collect", lambda: TB.collect(day, ['NFL', 'NBA', 'NHL', 'NCAAF', 'NCAAMB'])), ("winner_rows", lambda: TB.winner_rows(day))):
    pr = cProfile.Profile(); a = time.time(); pr.enable(); f(); pr.disable(); print("T", label, round(time.time()-a, 1))
    s = io.StringIO(); pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(25); print(s.getvalue()[:5000])
