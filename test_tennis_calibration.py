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


def test_every_league_has_its_own_calibration_key():
    import tennis_calibration as TC
    assert TC.key_for("TENNIS") == "tennis_calibration" and TC.key_for("NBL") == "game_calibration:NBL"
    store = {"game_calibration:NBL": {"k": 0.8}}
    assert TC.current_k(store.get, sport="NBL") == 0.8 and TC.current_k(store.get, sport="EUROLEAGUE") == 1.0
    d = TC.auto(picks=[], write=False, get=store.get, save=store.__setitem__, sport="NBL")
    assert not d["applied"] and "not enough" in d["why"] and d["label"] == "NBL win chances"


def test_hoops_build_applies_the_league_calibration():
    from datetime import datetime, timezone
    import intl_picks as IP
    import intl_hoops as I
    from test_intl_models import _ev, NOW
    games = [{"home_team": h, "away_team": a, "home_points": hp, "away_points": ap, "neutral_site": False}
             for h, a, hp, ap in [("Real Madrid", "Monaco", 95, 75), ("Monaco", "Fenerbahce", 80, 82),
                                  ("Fenerbahce", "Real Madrid", 70, 90)] * 6]
    r = I.ratings(games, 3.0)
    evs = [_ev("g1", "Real Madrid", "Monaco", -150, 130, spread=-2.5, total=160)]
    raw = IP.hoops_build("EUROLEAGUE", r, evs, NOW)[0]
    cal = IP.hoops_build("EUROLEAGUE", r, evs, NOW, k=0.5)[0]
    assert raw["model_p"] == raw["model_p_raw"]
    assert abs((cal["model_p"] - 0.5) - 0.5 * (raw["model_p_raw"] - 0.5)) < 0.002 and cal["model_p_raw"] == raw["model_p_raw"]
