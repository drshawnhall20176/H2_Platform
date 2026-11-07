"""The Game Script feedback loop (Nov 7): learn from cached games, choose the scenario source, log and grade calls."""
import random
from datetime import date, timedelta

import scenario_model as M
import script_learn as L


def _cache(n=700, seed=3):
    random.seed(seed)
    teams = [str(i) for i in range(16)]
    st = {t: random.gauss(0, 6) for t in teams}
    games = {}
    d0 = date(2025, 10, 22)
    for k in range(n):
        d = (d0 + timedelta(days=k // 6)).isoformat()
        a, b = random.sample(teams, 2)
        sp = st[a] - st[b] + 2.5 + random.gauss(0, 1.5)
        m = st[a] - st[b] + 2.5 + random.gauss(0, 12)
        fav = a if sp > 0 else b
        players = {f"{a}p{i}": {"team": a, "minutes": 30 - i * 4, "points": max(0, 14 - i * 2 + m / 6 + random.gauss(0, 5)),
                                "rebounds": 5.0, "assists": 3.0, "threes": 1.0} for i in range(5)}
        players.update({f"{b}p{i}": {"team": b, "minutes": 30 - i * 4, "points": max(0, 14 - i * 2 - m / 6 + random.gauss(0, 5)),
                                     "rebounds": 5.0, "assists": 3.0, "threes": 1.0} for i in range(5)})
        games[f"g{k}"] = [d, {"teams": {a: {"home": True, "score": 110 + m / 2}, b: {"home": False, "score": 110 - m / 2}},
                              "fav": fav, "strength": abs(sp), "players": players}]
    return {"days": set(), "games": games}


def test_choose_needs_a_held_out_win():
    ev = {"alternate": {"n": 500, "table": 1.25, "line": 1.24, "matchup": 1.26},
          "season": {"n": 500, "table": 1.28, "line": 1.25, "matchup": 1.27}}
    assert L.choose(ev) == "line"
    ev["alternate"]["matchup"] = 1.23
    ev["season"]["matchup"] = 1.24
    assert L.choose(ev) == "matchup"
    ev["season"]["matchup"] = 1.30                              # loses on the other season -> not promoted
    assert L.choose(ev) == "line"
    assert L.choose({}) == "table"
    assert L.choose({"alternate": {"n": 500, "table": 1.2, "line": 1.21, "matchup": 1.22}}) == "table"


def test_learn_refits_everything_from_the_cache():
    fit = L.learn("NBA", _cache())
    assert fit["games"] == 700 and fit["shares"] and fit["effects"]
    sc = fit["scenario"]
    assert sc["rows"] > 300 and set(sc["eval"]["alternate"]) >= {"table", "line", "matchup", "n"}
    assert sc["source"] in ("table", "line", "matchup")
    if sc["source"] != "table":
        p = M.predict(sc["model"], {f: 1.0 for f in sc["model"]["feats"]})
        assert abs(sum(p.values()) - 1) < 1e-9


def test_grade_and_track_calls():
    cache = _cache(50)
    gid, (d, p) = next(iter(cache["games"].items()))
    fav = p["fav"]
    dog = next(t for t in p["teams"] if t != fav)
    probs = {"fav_blowout": 0.4, "middle": 0.3, "close": 0.2, "dog_blowout": 0.1}
    calls = {"pending": [{"gid": gid, "d": d, "fav_id": fav, "dog_id": dog, "p": probs, "table": probs},
                         {"gid": "nope", "d": "2020-01-01", "fav_id": "x", "dog_id": "y", "p": probs, "table": probs}]}
    assert L.grade(calls, cache, "NBA") == 1
    assert calls["pending"] == [] and calls["graded"][0]["y"] in M.CLASSES
    tr = L.track(calls)
    assert tr["n"] == 1 and tr["bands"]


def test_page_uses_logged_call(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    import best_bets_data as BBD
    import model_store as MS
    import script_effects as SE
    g = "San Antonio Spurs @ Sacramento Kings"
    plays = [{"Player": "A One", "Team": "San Antonio Spurs", "Game": g, "Market": "Points", "Side": "Over", "Line": 9.5,
              "ModelProb": 0.55, "RealPrice": -110, "Projection": 10.6, "_game_log": [{"min": 20.0}] * 5}]
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, [], []))
    monkeypatch.setattr(MS, "load_snapshots", lambda *a, **k: [])
    monkeypatch.setattr(SE, "fetch_lines", lambda sp, days: [])
    call = {"gid": "1", "d": __import__("datetime").datetime.now(__import__("pytz").timezone("US/Eastern")).strftime("%Y-%m-%d"),
            "fav": "San Antonio Spurs", "dog": "Sacramento Kings", "fav_id": "24", "dog_id": "23", "strength": 13.5,
            "p": {"fav_blowout": 0.61, "middle": 0.2, "close": 0.15, "dog_blowout": 0.04}, "table": {}, "source": "line",
            "why": [], "context": {"fav": {"n": 8, "won_big": 4, "lost_big": 0, "close": 2, "avg_margin": 11.2,
                                           "last5": [20, 5, 18, -3, 16], "b2b": False}, "dog": None}}
    monkeypatch.setattr(SE, "calls", lambda sport: {"pending": [call]})
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "50_Game_Script.py"), default_timeout=30)
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.metric[1].value == "61%"
    assert any("line curve" in c.value for c in at.caption)
