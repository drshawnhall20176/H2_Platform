"""capture_game_picks.py — save college spread projections + the books' lines before kickoff and grade finished
games (game_picks.capture). Run by .github/workflows/capture-game-picks.yml. One odds request (2 credits) a run."""
import os
import sys

import game_picks as GP


def main() -> int:
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("ODDS_API_KEY isn't set.")
        return 1
    r = GP.capture(key)
    print(f"{r['games']} upcoming game(s) with a line; {r['picks']} pick(s) at {GP.PICK_EDGE:g}+ points "
          f"(+{r['held']} held for news); saved "
          f"{r['saved']}; graded {r['graded']} finished game(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
