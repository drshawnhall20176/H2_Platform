"""Nov 12: automatic tennis calibration."""
import random

import tennis_calibration as TC


def _picks(n_days=12, per_day=20, truth_k=0.6, seed=1):
    rnd = random.Random(seed)
    out = []
    for d in range(n_days):
        for _ in range(per_day):
            p = rnd.uniform(0.2, 0.9)
            y = rnd.random() < TC.shrink(p, truth_k)
            out.append({"kickoff": f"2026-11-{d + 1:02d}T12:00:00+00:00", "model_p": p,
                        "result": "home" if y else "away"})
    out.append({"kickoff": "2026-11-05T12:00:00+00:00", "model_p": 0.7, "result": "retired"})   # left out
    return out


def test_overconfident_model_gets_pulled_in_and_saved():
    store = {}
    d = TC.auto(_picks(), write=True, get=store.get, save=store.__setitem__)
    assert d["applied"] and 0.4 <= d["new"] <= 0.8 and store[TC.KEY]["k"] == d["new"]
    assert TC.shrink(0.75, d["new"]) < 0.72
    assert TC.current_k(store.get) == d["new"]


def test_honest_model_is_left_alone_and_small_samples_wait():
    store = {}
    d = TC.auto(_picks(truth_k=1.0, seed=3), write=True, get=store.get, save=store.__setitem__)
    assert not d["applied"] or abs(d["new"] - 1.0) < 0.15
    few = TC.auto(_picks(n_days=3, per_day=10), write=True, get={}.get, save=lambda *a: None)
    assert not few["applied"] and "not enough yet" in few["why"]
