"""
players_hub.py — one Players page for the customer (Nov 16).

The owner app has a separate sidebar page per player tool (Position Matchups, Matchup Lab, Hot Hand Engine, QB Lab,
Anytime TD Engine ...). Since the one-model rule they all lead with the same model read and differ in the explanation,
so to a customer they are one page with views. This lists a sport's views under plain names; views/58_Players.py shows
a switcher and runs only the chosen tool's own script, unchanged (so nothing about the tools themselves is duplicated).
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

BY_POSITION, HOT, HEAD = "By position", "Hot players", "Head to head"
QBS, TDS, PITCHERS, HOMERS = "Quarterbacks", "Touchdown scorers", "Pitchers", "Home runs"

# sport -> [(view name, views/ page number)]
TOOLS = {
    "NBA": [(BY_POSITION, "38"), (HOT, "10"), (HEAD, "11")],
    "NCAAMB": [(BY_POSITION, "38"), (HOT, "10"), (HEAD, "11")],
    "WNBA": [(HOT, "10"), (HEAD, "11")],
    "NFL": [(BY_POSITION, "38"), (HOT, "25"), (HEAD, "12"), (QBS, "14"), (TDS, "13")],
    "NCAAF": [(BY_POSITION, "38"), (HOT, "35"), (HEAD, "30"), (QBS, "29"), (TDS, "36")],
    "NHL": [(BY_POSITION, "38")],
    "MLB": [(PITCHERS, "7"), (HOMERS, "8"), (HEAD, "9")],
}
SPORTS = tuple(TOOLS)
ABOUT = {BY_POSITION: "Each position against the defense it faces tonight.",
         HOT: "Who is running hot, adjusted for the opponent.",
         HEAD: "One player against one opponent, in detail.",
         QBS: "Quarterback reads for the slate.",
         TDS: "Who is most likely to score a touchdown.",
         PITCHERS: "Starting pitcher reads for the slate.",
         HOMERS: "Who is most likely to hit a home run."}


def tools_for(sport: str) -> List[Tuple[str, str]]:
    return list(TOOLS.get(str(sport), []))


def script_for(number: str, views_dir: Path) -> Optional[Path]:
    """The views/ file whose leading page number is `number` ("38" -> views/38_Position_Matchups.py)."""
    import re
    for f in sorted(Path(views_dir).glob("*.py")):
        m = re.match(r"(\d+)", f.name)
        if m and m.group(1) == str(number):
            return f
    return None
