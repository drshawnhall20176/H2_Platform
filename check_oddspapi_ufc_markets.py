"""
check_oddspapi_ufc_markets.py — lists every market OddsPapi has for UFC/MMA (sportId=20),
and flags which ones are player/fighter props vs. plain fight-winner/totals.

Answers the real question before any integration work: does OddsPapi actually have UFC props,
or just fight winner like The Odds API? Run locally, key never leaves your machine:

    ODDSPAPI_KEY=your_real_key python3 check_oddspapi_ufc_markets.py

Or pass it as the first argument:

    python3 check_oddspapi_ufc_markets.py your_real_key
"""
import os
import sys

import requests

UFC_SPORT_ID = 20
BASE_URL = "https://api.oddspapi.io/v4"


def main():
    api_key = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ODDSPAPI_KEY")
    if not api_key:
        print("No key found. Set ODDSPAPI_KEY or pass it as the first argument.")
        sys.exit(1)

    print(f"Fetching markets for sportId={UFC_SPORT_ID} (UFC/MMA)...")
    try:
        r = requests.get(f"{BASE_URL}/markets",
                         params={"apiKey": api_key, "sportId": UFC_SPORT_ID}, timeout=20)
    except requests.RequestException as e:
        print(f"Network error: {e}")
        sys.exit(1)

    if r.status_code != 200:
        print(f"FAILED: HTTP {r.status_code}: {r.text[:300]}")
        sys.exit(1)

    markets = r.json() or []
    ufc_markets = [m for m in markets if m.get("sportId") == UFC_SPORT_ID]

    if not ufc_markets:
        print("No markets returned for UFC/MMA at all -- the key works, but this sport isn't "
             "covered by /v4/markets the way you'd expect. Worth a look at their coverage page "
             "or a message to their support before building anything.")
        return

    props = [m for m in ufc_markets if m.get("playerProp")]
    non_props = [m for m in ufc_markets if not m.get("playerProp")]

    print(f"\n{len(ufc_markets)} total UFC/MMA market(s) found.\n")

    print(f"Non-prop markets ({len(non_props)}):")
    for m in non_props:
        print(f"  {m.get('marketId')}: {m.get('marketName')}")

    print(f"\nPlayer/fighter prop markets ({len(props)}):")
    if not props:
        print("  (none -- same fight-winner-only limitation as The Odds API)")
    else:
        for m in props:
            print(f"  {m.get('marketId')}: {m.get('marketName')}")

    print("\n" + ("✅ Real prop coverage exists — worth building the integration."
                  if props else
                  "⚠️  No prop markets for UFC — this source won't get you past fight winner "
                  "either, same as The Odds API."))


if __name__ == "__main__":
    main()
