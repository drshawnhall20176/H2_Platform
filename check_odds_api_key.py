"""
check_odds_api_key.py — standalone diagnostic for an Odds API key against UFC/MMA coverage.

Run locally, outside Streamlit, with your key as an environment variable so it never has to be
pasted anywhere else:

    ODDS_API_KEY=your_real_key python3 check_odds_api_key.py

Or pass it as the first argument:

    python3 check_odds_api_key.py your_real_key

Does two checks, in order, matching the two things that can independently fail:
  1. Events list  -- confirms the key itself is valid and MMA events are visible at all
     (this endpoint is typically free / doesn't count against quota).
  2. Event odds    -- confirms the actual odds/markets fetch works for a real upcoming event
     (this is the one that consumes quota and can hit INVALID_MARKET or coverage gaps).
"""
import os
import sys

import ufc_engine as E


def main():
    api_key = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("No key found. Set ODDS_API_KEY or pass it as the first argument.")
        sys.exit(1)

    print("1) Checking events list (mma_mixed_martial_arts)...")
    try:
        events = E.get_ufc_events(api_key)
    except E.OddsAPIError as err:
        print(f"   FAILED: {err}")
        print("   Key or account problem -- fix this before checking odds coverage.")
        sys.exit(1)

    if not events:
        print("   OK — key works, but no upcoming UFC events are in the feed right now.")
        print("   (Normal between events; try again closer to a real fight week.)")
        return

    print(f"   OK — {len(events)} upcoming event(s) found:")
    for e in events[:5]:
        print(f"     - {e.get('home_team', '?')} vs. {e.get('away_team', '?')} "
             f"({e.get('commence_time', '?')})")

    print("\n2) Checking event odds for the first upcoming event...")
    first = events[0]
    try:
        odds_data = E.get_event_odds(first.get("id", ""), api_key)
    except E.OddsAPIError as err:
        print(f"   FAILED: {err}")
        print("   Events list works, but the odds/markets fetch itself failed — check the "
             "message above against The Odds API's own error code reference.")
        sys.exit(1)

    parsed = E.parse_bout_odds(odds_data)
    if not parsed:
        print("   Odds fetch succeeded, but no bookmaker has posted lines for this event yet.")
        print("   (Common well before a card, especially early in the week.)")
    else:
        print(f"   OK — real odds found for markets: {list(parsed.keys())}")
        print("\nYour key is working for UFC. ✅")


if __name__ == "__main__":
    main()
