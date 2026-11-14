"""Nov 14: the lean record splits by how big the model's disagreement with the line is."""
from datetime import date

import pick_records as PR


def _rec(mm, hs, fh, fa):
    return {"kickoff": date.today().isoformat(), "model_margin": mm, "home_spread": hs, "final_home": fh,
            "final_away": fa}


def test_records_split_by_gap_and_rows_get_their_own_band():
    # NCAAF sd 15.5: gap 2 pts -> small band; gap 10 pts -> big band
    recs = [_rec(5, -3, 30, 20)] * 3 + [_rec(5, -3, 20, 30)] + [_rec(13, -3, 20, 30)] * 4
    got = PR.lean_records("NCAAF", recs=recs)
    assert got["Spread"] == (3, 8)
    assert got[("Spread", 0)] == (3, 4) and got[("Spread", 2)] == (0, 4)
    rows = [{"sport": "NCAAF", "bet_market": "Spread", "_gaps": {"Spread": 2 / 15.5}},
            {"sport": "NCAAF", "bet_market": "Spread", "_gaps": {"Spread": 10 / 15.5}},
            {"sport": "NCAAF", "bet_market": "Spread", "_gaps": {"Spread": 5 / 15.5}}]
    PR.annotate_leans(rows, lambda lg: got)
    assert rows[0]["lean_record"].startswith("Spread, 0–4 pt gap: 3–1")
    assert rows[1]["lean_record"].startswith("Spread, 8+ pt gap: 0–4")
    assert rows[2]["lean_record"].startswith("Spread: 3–5")          # no record in its band yet: the overall one


def test_hockey_band_labels_use_goals():
    assert PR.band_label(1, "Spread", "NHL") == "0.6–1.2 goal gap"
    assert PR.band_label(2, "Total", "NHL") == "1.2+ goal gap"
