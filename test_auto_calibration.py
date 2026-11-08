"""Nov 8: the loop calibrates itself each morning -- applied only when it holds up out of sample."""
import random

import calibration as CAL


def _rows(n_days, per_day, true_shrink, side="Under", seed=1):
    random.seed(seed)
    out = {}
    for d in range(n_days):
        day = f"2026-10-{d + 10:02d}"
        rs = []
        for _ in range(per_day):
            p = random.uniform(0.52, 0.72)
            truth = 0.5 + true_shrink * (p - 0.5)
            rs.append({"result": "hit" if random.random() < truth else "miss", "chance": p, "side": side, "market": "Points"})
        out[day] = rs
    return out


def test_overconfident_side_is_learned_and_applied(monkeypatch):
    import model_store as MS
    applied = {}
    monkeypatch.setattr(CAL, "side_factors", lambda sport: (1.0, 1.0))
    monkeypatch.setattr(MS, "list_calibration", lambda *a, **k: [])
    monkeypatch.setattr(MS, "approve_calibration", lambda key, s, details=None, **k: applied.update({key: (s, details)}) or True)
    dec = CAL.auto_side("NHL", _rows(8, 200, 0.4), "2026-11-08")
    under = next(d for d in dec if d["side"] == "Under")
    assert under["applied"] and under["new"] < 0.8 and "NHL:Under" in applied and applied["NHL:Under"][1]["auto"]
    assert any("Learned overnight" in n for n in CAL.auto_notes(dec))
    over = next(d for d in dec if d["side"] == "Over")
    assert not over["applied"] and "not enough" in over["why"]


def test_honest_chances_are_left_alone(monkeypatch):
    import model_store as MS
    monkeypatch.setattr(CAL, "side_factors", lambda sport: (1.0, 1.0))
    monkeypatch.setattr(MS, "list_calibration", lambda *a, **k: [])
    monkeypatch.setattr(MS, "approve_calibration", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no write")))
    dec = CAL.auto_side("NBA", _rows(8, 200, 1.0, seed=3), "2026-11-08")
    assert not any(d["applied"] for d in dec)


def test_only_days_since_the_current_factor_count(monkeypatch):
    """A factor approved this morning: the older days (graded before it) mustn't stack it again."""
    import model_store as MS
    monkeypatch.setattr(CAL, "side_factors", lambda sport: (1.0, 0.88))
    monkeypatch.setattr(MS, "list_calibration", lambda *a, **k: [{"sport": "NHL:Under", "s": 0.88,
                                                                   "approved_ts": "2026-10-16T11:00:00"}])
    monkeypatch.setattr(MS, "approve_calibration", lambda *a, **k: True)
    dec = CAL.auto_side("NHL", _rows(8, 200, 0.4), "2026-11-08")
    under = next(d for d in dec if d["side"] == "Under")
    assert under["since"] == "2026-10-16" and under["n"] == 400 and not under["applied"]   # two days since: not enough
