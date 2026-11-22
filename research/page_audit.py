"""Nov 21 (owner: "check every page every sport"): open every page for every sport the way the Cloud app would --
in-app guards on, live data, owner build -- each in its own process, and report its peak memory, time and errors.
AUDIT_SPORTS env picks the sports (comma list; "GENERAL" = the sport-free pages)."""
import ast, os, re, subprocess, sys, json, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, ".")
from pathlib import Path
import sports

src = Path("streamlit_app.py").read_text()
def lit(name):
    m = re.search(rf"{name} = (\{{.*?\n    \}})", src, re.S)
    return ast.literal_eval(m.group(1))
LEADS = lit("sport_only_leads")
PROJ_ONLY = ast.literal_eval(re.search(r"projections_only_titles = (\{.*?\})", src, re.S).group(1))
META = {}
for m in re.finditer(r'"(\d+)": \("([^"]+)",', src):
    META.setdefault(m.group(1), m.group(2))

CHILD = r'''
import sys, os, time, resource, json
sys.path.insert(0, ".")
page, sp = sys.argv[1], sys.argv[2]
import slate_store as SS, best_bets_data as BBD
SS._in_app = lambda: True
BBD._in_app = lambda: True
import streamlit as st
st.page_link = lambda *a, **k: None                 # page links need the site's menu; not what's being measured
st.switch_page = lambda *a, **k: None
from streamlit.testing.v1 import AppTest
t = time.time()
res = {"page": page, "sport": sp}
try:
    at = AppTest.from_file(page, default_timeout=150)
    at.secrets["AUDIENCE"] = "owner"
    for k in ("ODDS_API_KEY", "DATABASE_URL"):
        if os.environ.get(k):
            at.secrets[k] = os.environ[k]
    if sp != "-":
        at.session_state["sport"] = sp
    at.run()
    res["exc"] = [str(e.value)[:300] for e in at.exception]
    res["errors"] = [str(e.value)[:200] for e in at.error]
except Exception as e:
    res["exc"] = [f"{type(e).__name__}: {str(e)[:300]}"]
res["secs"] = round(time.time() - t)
res["peak_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e3)
print("PAJSON " + json.dumps(res))
'''

def pages_for(sp):
    out = []
    for f in sorted(Path("views").glob("*.py"), key=lambda p: int(re.match(r"\d+", p.name).group(0))):
        key = re.match(r"\d+", f.name).group(0)
        if sp in sports.LAB_SPORTS:
            if key not in (sports.LAB_PAGES[sp],) + sports.LAB_COMMON_PAGES:
                continue
        req = LEADS.get(key)
        if req and sp not in req:
            continue
        title = META.get(key, "")
        if title in PROJ_ONLY and not sports.get(sp).has_projections:
            continue
        out.append(str(f))
    return out + ["Home.py"]

def run(job):
    page, sp = job
    try:
        p = subprocess.run([sys.executable, "-c", CHILD, page, sp], capture_output=True, text=True, timeout=400)
        line = next((l for l in p.stdout.splitlines() if l.startswith("PAJSON ")), None)
        if line:
            return json.loads(line[7:])
        return {"page": page, "sport": sp, "exc": ["no result: " + (p.stderr[-300:] or "killed (memory?)")],
                "secs": None, "peak_mb": None, "rc": p.returncode}
    except subprocess.TimeoutExpired:
        return {"page": page, "sport": sp, "exc": ["TIMEOUT >400s"], "secs": 400, "peak_mb": None}

want = os.environ.get("AUDIT_SPORTS", "NFL").split(",")
only = [x for x in os.environ.get("AUDIT_PAGES", "").split(",") if x]
jobs = []
for sp in want:
    if sp == "GENERAL":
        jobs += [(p, "-") for p in ("Today.py", "Owner_Office.py", "Maintenance.py")]
    else:
        jobs += [(p, sp) for p in pages_for(sp) if not only or any(o in p for o in only)]
print(f"PA {len(jobs)} page loads for {want}")
with ThreadPoolExecutor(3) as ex:
    for r in ex.map(run, jobs):
        flag = ("CRASH " if r.get("exc") else "") + ("BIG " if (r.get("peak_mb") or 0) > 1200 else "") + \
               ("SLOW " if (r.get("secs") or 0) > 90 else "")
        print(f"PA {flag or 'ok '}{r['sport']:7} {r['page']:45} {r.get('peak_mb')}MB {r.get('secs')}s "
              f"{(r.get('exc') or [''])[0][:160]} {'ERR: ' + r['errors'][0][:100] if r.get('errors') else ''}")
