"""Nov 12: ESPN box-score shapes for live props -- NHL, NFL, college football, college basketball."""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import intl_hoops as I     # noqa: E402
import live_games as LG    # noqa: E402

for lg, d in (("NHL", "20261111"), ("NFL", "20261109"), ("NCAAF", "20261108"), ("NCAAMB", "20261111")):
    params = {"dates": d, "limit": 5}
    if lg == "NCAAF":
        params["groups"] = 80
    if lg == "NCAAMB":
        params["groups"] = 50
    sb = I._http(LG.ESPN_URL[lg], params) or {}
    ev = (sb.get("events") or [{}])[0]
    s = I._http(f"https://site.api.espn.com/apis/site/v2/sports/{LG.ESPN_PATH[lg]}/summary", {"event": ev.get("id")}) or {}
    for team in ((s.get("boxscore") or {}).get("players") or [])[:1]:
        for blk in team.get("statistics") or []:
            a0 = (blk.get("athletes") or [{}])[0]
            print("BX", lg, "block", blk.get("name") or blk.get("type"), "labels", blk.get("labels"), "keys",
                  blk.get("keys"), "| athlete0", (a0.get("athlete") or {}).get("displayName"), a0.get("stats"))
