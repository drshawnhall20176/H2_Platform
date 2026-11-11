"""Nov 11: which books does the Odds API carry college-basketball player props for? (DK/FD don't post them.)
Checks today's NCAAB events with every US, Hard Rock, and pick'em book (incl. Underdog), then a sample of what the
platform's own fetch + parse keeps."""
import os
import sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import odds_api as O        # noqa: E402

key = os.environ["ODDS_API_KEY"]
evs = O.fetch_events_all(key, sport="basketball_ncaab")
print("NB events listed", len(evs))
books = list(O.US_BOOKS) + list(O.PICKEM_BOOKS) + ["underdog", "betr_us_dfs", "espnbet", "ballybet", "betparx"]
seen, per_book_events = Counter(), Counter()
mk = ["player_points", "player_rebounds", "player_assists", "player_threes"]
checked = 0
for ev in evs[:40]:
    try:
        js, hdr = O._get(f"sports/basketball_ncaab/events/{ev['id']}/odds",
                         {"apiKey": key, "markets": ",".join(mk), "oddsFormat": "american",
                          "bookmakers": ",".join(books[:10])})
        js2, hdr = O._get(f"sports/basketball_ncaab/events/{ev['id']}/odds",
                          {"apiKey": key, "markets": ",".join(mk), "oddsFormat": "american",
                           "bookmakers": ",".join(books[10:])})
    except O.OddsAPIError as e:
        print("NB err", str(e)[:120])
        continue
    checked += 1
    got = set()
    for j in (js, js2):
        for b in (j or {}).get("bookmakers") or []:
            for m in b.get("markets") or []:
                n = len(m.get("outcomes") or [])
                seen[(b["key"], m["key"])] += n
                got.add(b["key"])
    for b in got:
        per_book_events[b] += 1
    if got:
        print("NB", ev.get("away_team"), "@", ev.get("home_team"), ev.get("commence_time"), "->", sorted(got))
print(f"NB checked {checked} events; credits left {hdr.get('remaining')}")
for b, n in per_book_events.most_common():
    print("NB book", b, "events with player props:", n)
for (b, m), n in sorted(seen.items()):
    print("NB", b, m, "outcomes", n)
# what the platform's parser keeps for one event with props
for ev in evs[:40]:
    js, _ = O.fetch_event_props(ev["id"], key, mk, sport="basketball_ncaab")
    offers = O.parse_event_offers(js) if hasattr(O, "parse_event_offers") else None
    if offers:
        o = offers[0]
        print("NB parsed sample", {k: o.get(k) for k in ("player", "market", "line", "over", "under", "pickem")})
        print("NB parsed offers", len(offers), "with sportsbook prices", sum(bool(x.get("over")) for x in offers),
              "pickem only", sum((not x.get("over")) and bool(x.get("pickem")) for x in offers))
        break
