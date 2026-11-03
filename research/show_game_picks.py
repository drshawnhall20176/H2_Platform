"""research/show_game_picks.py — print today's / upcoming game-lines records for a few leagues (Nov 3). Read-only."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    import model_store as MS
    lo = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
    for lg in os.environ.get("SHOW_LEAGUES", "NCAAMB").split(","):
        for p in MS.load_game_picks(lg):
            if str(p.get("kickoff")) < lo:
                continue
            print(json.dumps({k: p.get(k) for k in ("sport", "kickoff", "away", "home", "home_spread", "line", "close_line",
                                                    "model_margin", "edge", "line_total", "model_total", "model_p",
                                                    "fair_home", "use", "pick")}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
