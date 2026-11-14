import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import soccer_data as D, model_store as MS
res = MS.load_results("SOCCER_EPL")
print("EPL results", len(res), "sample", {k: res[-1].get(k) for k in list(res[-1])[:12]})
eid = res[-1]["id"]
data = D._http(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{D.LEAGUES['SOCCER_EPL']['slug']}/summary", {"event": eid})
for t in ((data or {}).get("boxscore") or {}).get("teams") or []:
    print("TEAM", (t.get("team") or {}).get("displayName"), [(s.get("name"), s.get("displayValue")) for s in t.get("statistics") or []])
print("keys", list((data or {}).keys()))
