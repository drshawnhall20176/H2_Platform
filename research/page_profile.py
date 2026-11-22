"""Sample a page's memory and the function it's in every 2 seconds (in-app guards on)."""
import os, sys, subprocess
sys.path.insert(0, ".")
CHILD = r'''
import sys, os, time, threading, traceback, resource
sys.path.insert(0, ".")
page, sp = sys.argv[1], sys.argv[2]
import slate_store as SS, best_bets_data as BBD
SS._in_app = lambda: True
BBD._in_app = lambda: True
import streamlit as st
st.page_link = lambda *a, **k: None
st.switch_page = lambda *a, **k: None
from streamlit.testing.v1 import AppTest
main_id = threading.get_ident()
def rss():
    with open("/proc/self/statm") as f: return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6
stop = []
def sampler():
    last = 0
    while not stop:
        frames = sys._current_frames()
        # the script thread: the deepest frame inside the repo
        best = None
        for tid, fr in frames.items():
            if tid == threading.get_ident(): continue
            st_ = traceback.extract_stack(fr)
            mine = [f for f in st_ if "/H2_Platform/" in f.filename and "site-packages" not in f.filename]
            if mine and (best is None or len(mine) > len(best)): best = mine
        r = rss()
        if r - last > 50 or True:
            where = " <- ".join(f"{os.path.basename(f.filename)}:{f.name}:{f.lineno}" for f in (best or [])[-3:][::-1])
            print(f"PP {sp} {os.path.basename(page)} {r:.0f}MB {where}", flush=True)
            last = r
        time.sleep(3)
threading.Thread(target=sampler, daemon=True).start()
t = time.time()
at = AppTest.from_file(page, default_timeout=200)
at.secrets["AUDIENCE"] = "owner"
for k in ("ODDS_API_KEY", "DATABASE_URL"):
    if os.environ.get(k): at.secrets[k] = os.environ[k]
at.session_state["sport"] = sp
at.run()
stop.append(1)
print(f"PP DONE {sp} {page} peak={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e3:.0f}MB {time.time()-t:.0f}s exc={[str(e.value)[:150] for e in at.exception]}", flush=True)
'''
for page, sp in (("views/39_Analyst_Desk.py", "NBA"), ("views/53_Long_Shots.py", "NCAAF"),
                 ("views/31_NCAAF_Player_Lines.py", "NCAAF"), ("views/16_#L01f50d_Retrospective.py", "NCAAF"),
                 ("views/10_Hot_Hand_Engine.py", "NCAAMB")):
    p = subprocess.run([sys.executable, "-c", CHILD, page, sp], capture_output=True, text=True, timeout=600)
    for l in p.stdout.splitlines():
        if l.startswith("PP"): print(l)
    if "PP DONE" not in p.stdout: print("PP FAIL", page, p.stderr[-300:])
