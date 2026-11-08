"""Nov 7: Amen Thompson / Kevin Durant Overs -- the model's read, live prices, and how they did without Capela."""
import os
import sys
from datetime import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analyst as A                  # noqa: E402
import analyst_publisher as AP       # noqa: E402
import best_bets_data as BBD         # noqa: E402
import nba_engine as N               # noqa: E402
import props_engine as PE            # noqa: E402
import sports                        # noqa: E402

D = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
plays, meta, _ = BBD.load_generic_best_bets_board("NBA", D, BBD.O.DEFAULT_BOOK)
deps = AP.default_deps()
offers = deps["fetch_offers"]("NBA", D, deps["api_key"]()) or []
idx = A.index_offers(offers)
omap = sports.get("NBA").market_map
for who in ("Amen Thompson", "Kevin Durant", "Alperen Sengun", "Jabari Smith Jr."):
    for p in plays:
        if p.get("Player") == who and p.get("Model") == "player-props" and p.get("Market") in ("Points", "Rebounds", "PRA", "Pts+Reb"):
            o = idx.get((A._norm(who), omap.get(p["Market"]))) or []
            live = {(x["point"], s): x[s].get("draftkings") for x in o for s in ("over", "under") if "draftkings" in (x.get(s) or {})}
            print("HO READ", who, p["Market"], p["Side"], p["Line"], f"model {p['ModelProb']:.0%}", "proj", p.get("Projection"),
                  "| Use", p.get("Use"), "| DK", {k: v for k, v in sorted(live.items()) if abs(k[0] - p["Line"]) <= 2})
# with / without Capela (Rockets, this season + last)
roster = {pl["name"]: pl["id"] for pl in N.get_team_roster(10)}
print("HO roster sample", list(roster)[:20])
def log(name, n=40):
    pid = roster.get(name)
    return N.get_player_recent_games(pid, n, team_id=10, before_date=D) if pid else []
cap = {g.get("date") for g in log("Clint Capela")}
adams = {g.get("date") for g in log("Steven Adams")}
for who, stat in (("Amen Thompson", "reb"), ("Kevin Durant", "pts"), ("Alperen Sengun", "reb"), ("Jabari Smith Jr.", "reb")):
    lg = [g for g in log(who) if g.get("src") != "prior"]
    lg_all = log(who)
    for label, games in (("this season", lg), ("incl. last season", lg_all)):
        w = [g[stat] for g in games if g.get("date") in cap and g.get(stat) is not None]
        wo = [g[stat] for g in games if g.get("date") not in cap and g.get(stat) is not None]
        both_out = [g[stat] for g in games if g.get("date") not in cap and g.get("date") not in adams and g.get(stat) is not None]
        avg = lambda v: round(sum(v) / len(v), 1) if v else None   # noqa: E731
        print("HO SPLIT", who, stat, label, "| with Capela", avg(w), f"(n={len(w)})", "| without", avg(wo), f"(n={len(wo)})",
              "| without both bigs", avg(both_out), f"(n={len(both_out)})", "| last 5", [g.get(stat) for g in games[-5:]])
