"""Nov 13: which DK soccer leagues ESPN + the Odds API cover (slugs verified on a recent date)."""
import json, os, urllib.request
from datetime import date, timedelta
def get(url):
    try:
        return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read())
    except Exception as e:
        return {"_err": str(e)}
k = os.environ.get("ODDS_API_KEY")
sp = get(f"https://api.the-odds-api.com/v4/sports?apiKey={k}&all=true")
print("ODDS:", [(s["key"], s["active"]) for s in sp if s["key"].startswith("soccer_")])
slugs = ["arg.1", "arg.copa", "aus.1", "aus.w.1", "aut.1", "bel.1", "bra.1", "bra.2", "chi.1", "col.1",
         "conmebol.libertadores", "conmebol.sudamericana", "cro.cup", "den.1", "den.2", "eng.2", "eng.3", "eng.4", "eng.fa",
         "eng.league_cup", "eng.w.1", "fra.2", "fra.coupe_de_france", "ger.2", "ger.3", "ger.dfb_pokal", "gre.1", "gua.1",
         "ita.2", "jpn.1", "jpn.2", "ned.1", "ned.2", "nir.1", "nor.1", "per.1", "por.1", "por.2", "sco.1", "sco.2",
         "esp.2", "esp.copa_del_rey", "sui.1", "tur.1", "uru.1", "usa.nwsl", "usa.usl.1", "uefa.europa.conf",
         "uefa.nations", "concacaf.nations.league", "caf.nations_qual", "fifa.worldq.uefa", "fifa.friendly",
         "uefa.wchampions", "mne.1", "pol.1", "swe.1", "rus.1", "ksa.1", "chn.1", "mex.2", "usa.open"]
days = [date(2026, 11, 13) - timedelta(days=i) for i in range(0, 60, 3)]
for s in slugs:
    n = 0; name = None; err = None
    for d in days[:8]:
        j = get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{s}/scoreboard?dates={d:%Y%m%d}")
        if "_err" in j:
            err = j["_err"]; break
        name = (j.get("leagues") or [{}])[0].get("name") or name
        n += len(j.get("events") or [])
    print("ESPN", s, "|", name, "| events(8 sample days):", n, "|", err or "")
