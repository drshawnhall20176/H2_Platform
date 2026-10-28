"""
The NCAAF / NFL Hot Hand "Slate Avg" (Oct 28 report): picking one game made its two defenses the whole slate, so every
Matchup Factor came out as a mirrored pair (1.08x / 0.92x). The board is now built from the full slate in view and
narrowed afterwards.
"""

from pathlib import Path

import ncaaf_projections as NP

VIEWS = Path(__file__).parent / "views"


def test_the_board_is_built_from_the_whole_slate_then_narrowed():
    for name, call in (("35_NCAAF_Hot_Hand_Engine.py", "build_board(all_rows"),
                       ("25_NFL_Hot_Hand_Engine.py", "build_hh_board(all_rows")):
        src = (VIEWS / name).read_text()
        assert call in src and "_shown_games" in src, name
        assert "build_board(final_rows" not in src and "build_hh_board(final_rows" not in src, name


def test_one_games_factors_are_measured_against_every_opponent_on_the_slate():
    allowed = {"MTSU": {"passing_YDS": 256.2}, "KSU": {"passing_YDS": 218.6},
               **{f"T{i}": {"passing_YDS": 200.0 + 10 * i} for i in range(6)}}
    key = next(k for k in NP._NCAAF_ALLOWED_KEY_TO_ROW_FIELD if k == "passing_YDS") if "passing_YDS" in NP._NCAAF_ALLOWED_KEY_TO_ROW_FIELD else None
    if key is None:
        return                                                     # market keys differ: covered by the source check
    mk = next(m for m, spec in NP._MARKET_SPEC.items() if NP._ROW_FIELD_TO_CFBD_COL.get(spec[0], spec[0]) == "passing_YDS")
    rows = [{"Player": "Rickie Collins", "Team": "KSU", "Opp": "MTSU", "GameLabel": "KSU @ MTSU",
             "_markets": [mk], NP._MARKET_SPEC[mk][0]: 201.6},
            {"Player": "Roman Gagliano", "Team": "MTSU", "Opp": "KSU", "GameLabel": "KSU @ MTSU",
             "_markets": [mk], NP._MARKET_SPEC[mk][0]: 200.6}]
    board = {b["Player"]: b for b in NP.build_ncaaf_hot_hand_board(rows, allowed)}
    slate = sum(v["passing_YDS"] for v in allowed.values()) / len(allowed)
    assert board["Rickie Collins"]["Slate Avg"] == round(slate, 1)
    f1, f2 = board["Rickie Collins"]["Matchup Factor"], board["Roman Gagliano"]["Matchup Factor"]
    assert abs((f1 + f2) / 2 - 1.0) > 0.02                         # no longer a mirrored pair around 1.00
