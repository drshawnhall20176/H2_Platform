"""Per-side honest chance (Nov 5): Overs and Unders each pulled toward 50% by their own factor."""
import calibration as CAL
import props_engine as PE


def test_apply_side_uses_the_favored_sides_factor():
    f = (0.3, 0.9)
    assert abs(CAL.apply_side(0.70, f) - 0.56) < 1e-9          # an Over lean at 70% -> 56%
    assert abs(CAL.apply_side(0.30, f) - 0.32) < 1e-9          # an Under lean (30% over = 70% under) -> 68% under
    assert CAL.apply_side(0.6, None) == 0.6
    assert abs(CAL.honest(CAL.honest(0.7, 0.5), 0.6) - CAL.honest(0.7, 0.3)) < 1e-9   # factors stack by multiplying


def test_read_line_applies_side_factors_before_the_lean():
    vals = [24, 26, 22, 25, 27, 23, 26, 24]
    plain = PE.read_line(25.0, vals, 21.5, "normal", -110, -110)
    shrunk = PE.read_line(25.0, vals, 21.5, "normal", -110, -110, side_factors=(0.3, 1.0))
    assert plain["p_final"] > 0.5 and shrunk["p_final"] < plain["p_final"]
    assert shrunk["ev"] < plain["ev"]
    under = PE.read_line(18.0, vals, 21.5, "normal", -110, -110)
    under_s = PE.read_line(18.0, vals, 21.5, "normal", -110, -110, side_factors=(0.3, 1.0))
    assert abs(under["p_final"] - under_s["p_final"]) < 1e-9   # Unders untouched when their factor is 1.0


def test_fit_by_side_finds_the_overconfident_side():
    rows = []
    for i in range(400):                                       # Overs said 60%, hit 45%; Unders said 60%, hit 60%
        rows.append({"result": "hit" if i % 20 < 9 else "miss", "chance": 0.60, "side": "Over", "market": "Points"})
        rows.append({"result": "hit" if i % 5 < 3 else "miss", "chance": 0.60, "side": "Under", "market": "Points"})
    f = CAL.fit_by_side(rows)
    assert f["Over"]["enough"] and f["Over"]["s"] == 0.3 and f["Under"]["s"] >= 0.95


def test_beat_model_summary():
    import postgame as PG
    rows = [{"market": "Points", "result": "miss", "actual": 30, "projection": 20, "side": "Under", "chance": 0.6}] * 10 + \
           [{"market": "Points", "result": "hit", "actual": 15, "projection": 20, "side": "Under", "chance": 0.6}] * 30
    b = PG.beat_model(rows)[0]
    assert b["n"] == 40 and abs(b["beat_proj"] - 0.25) < 1e-9 and abs(b["under_beaten"] - 0.25) < 1e-9
    assert abs(b["under_said"] - 0.6) < 1e-9 and b["over_n"] == 0
