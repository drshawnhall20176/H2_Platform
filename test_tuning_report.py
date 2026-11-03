import random

import blend_weights as BW
import model_store as MS
import props_engine as PE
import tuning_report as T


def _graded(n, model_skill, seed=1, market="Points"):
    """Reads where the truth is the market's chance (model_skill=0) or the model's (model_skill=1)."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        q_mkt = rnd.uniform(0.35, 0.65)
        q_mod = min(0.95, max(0.05, q_mkt + rnd.uniform(-0.2, 0.2)))
        truth = model_skill * q_mod + (1 - model_skill) * q_mkt
        p_over = q_mod
        out.append({"result": "hit" if rnd.random() < truth else "miss", "slate_date": f"2026-10-{1 + i % 28:02d}",
                    "player": f"P{i}", "market": market, "side": "Over", "line": 10.5,
                    "chance": 0.4 * q_mod + 0.6 * q_mkt, "price": -110, "p_model": p_over, "p_market": q_mkt})
    return out


def test_fit_prefers_the_books_when_the_model_adds_nothing():
    rows = T.prepare(_graded(3000, 0.0), PE.MODEL_WEIGHT)
    assert T.fit_weight(rows)["best"] <= 0.10


def test_fit_prefers_the_model_when_it_is_right():
    rows = T.prepare(_graded(3000, 1.0), PE.MODEL_WEIGHT)
    assert T.fit_weight(rows)["best"] >= 0.50


def test_report_proposes_only_with_enough_reads(monkeypatch):
    monkeypatch.setattr(BW, "_load", lambda: {})
    rep = T.build("NBA", _graded(3000, 0.0), [])
    assert rep["proposals"] and rep["proposals"][0]["market"] == "Points" and rep["proposals"][0]["w"] <= 0.10
    assert "blend:Points" in rep["markdown"]
    small = T.build("NBA", _graded(60, 0.0), [])
    assert not small["proposals"]
    few = [dict(r, slate_date="2026-10-0" + str(1 + i % 3)) for i, r in enumerate(_graded(3000, 0.0))]
    rep3 = T.build("NBA", few, [])
    assert not rep3["proposals"] and "3 of 5 slates" in rep3["markdown"]


def test_backs_out_the_model_chance_for_old_reads():
    r = {"result": "hit", "chance": 0.4 * 0.7 + 0.6 * 0.5, "price": -110, "market": "Points", "side": "Over",
         "slate_date": "d", "player": "x", "line": 1}
    row = T.prepare([r], 0.4)[0]
    q_mkt = PE.implied(-110) / (1 + PE.ASSUMED_VIG)
    assert abs(row["q_mkt"] - q_mkt) < 1e-9
    assert abs(row["q_mod"] - (r["chance"] - 0.6 * q_mkt) / 0.4) < 1e-9


def test_under_side_flips_stored_chances():
    r = {"result": "miss", "chance": 0.55, "price": -110, "market": "Points", "side": "Under", "slate_date": "d",
         "player": "x", "line": 1, "p_model": 0.3, "p_market": 0.48}
    row = T.prepare([r], 0.4)[0]
    assert abs(row["q_mod"] - 0.7) < 1e-9 and abs(row["q_mkt"] - 0.52) < 1e-9


def test_weight_for_uses_approved_then_default(monkeypatch):
    monkeypatch.setattr(BW, "_load", lambda: {("NBA", "Points"): 0.15})
    assert PE.weight_for({}, "NBA", "Points") == 0.15
    assert PE.weight_for({}, "NBA", "Assists") == PE.MODEL_WEIGHT
    assert PE.weight_for({"model_weight": 0.3}, "NBA", "Points") == 0.3


def test_blend_store_round_trip_and_snapshot_columns(tmp_path):
    db = str(tmp_path / "m.db")
    import model_store
    model_store.save([], db_path=db)
    rec = MS.snapshot_record("NBA", "2026-11-02", "A @ B", {"player": "X", "projection": 12.0, "line": 10.5,
                                                             "p_final": 0.55, "p_model": 0.62, "p_market": 0.5,
                                                             "over_price": -110, "under_price": -110}, "Points")
    assert rec["p_model"] == 0.62 and rec["p_market"] == 0.5 and rec["over_price"] == -110
    assert MS.save([rec], db_path=db) == 1
    assert MS.approve_blend("NBA", "Points", 0.2, db_path=db)
    snaps = MS.load_snapshots("NBA", db_path=db)
    assert snaps[0]["p_model"] == 0.62
    act = MS.list_blend(db_path=db)
    assert act[0]["market"] == "Points" and act[0]["w"] == 0.2


def test_approve_tuning_blend_key(monkeypatch):
    import approve_tuning as A
    got = []
    monkeypatch.setattr(MS, "approve_blend", lambda s, m, w, d=None: got.append((s, m, w)) or True)
    monkeypatch.setattr(MS, "list_tuning", lambda: [])
    assert A.main(["--sport", "NBA", "--factors", '{"blend:Points": 0.2}', "--reason", "weekly"]) == 0
    assert got == [("NBA", "Points", 0.2)]
    assert A.main(["--sport", "NBA", "--factors", '{"blend:Points": 0.9}', "--reason", "weekly"]) == 1


def test_weekly_tab_shows_report_and_approves(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    import postgame as PG
    monkeypatch.setattr(BW, "_load", lambda: {})
    rep = T.build("NBA", _graded(3000, 0.0), [])
    got = []
    monkeypatch.setattr(MS, "snapshot_dates", lambda sport, db_path=None: ["2026-11-01"])
    monkeypatch.setattr(MS, "load_snapshots", lambda sport=None, dates=None, db_path=None: [])
    monkeypatch.setattr(MS, "list_tuning", lambda active_only=True, db_path=None: [])
    monkeypatch.setattr(MS, "list_blend", lambda active_only=True, db_path=None: [])
    monkeypatch.setattr(MS, "daily_review_mornings", lambda sport, db_path=None: ["2026-11-03"] if sport.endswith("-tuning") else [])
    monkeypatch.setattr(MS, "load_daily_review", lambda sport, morning, db_path=None: rep)
    monkeypatch.setattr(MS, "approve_blend", lambda s, m, w, d=None, db_path=None: got.append((s, m, w)) or True)
    monkeypatch.setattr(PG, "fetch_results", lambda sport, d, games, fetch=None: {})
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "41_Postgame_Review.py"), default_timeout=30)
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("weekly tuning report" in m.value for m in at.markdown)
    btn = next(b for b in at.button if b.key and b.key.startswith("pgr_blend_"))
    btn.click().run()
    assert got and got[0][:2] == ("NBA", "Points")


def test_page_survives_an_old_model_store_without_blend_functions(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    import postgame as PG
    for name in ("list_blend", "approve_blend", "retire_blend"):
        monkeypatch.delattr(MS, name)
    monkeypatch.setattr(MS, "snapshot_dates", lambda sport, db_path=None: ["2026-11-01"])
    monkeypatch.setattr(MS, "load_snapshots", lambda sport=None, dates=None, db_path=None: [])
    monkeypatch.setattr(MS, "list_tuning", lambda active_only=True, db_path=None: [])
    monkeypatch.setattr(MS, "daily_review_mornings", lambda sport, db_path=None: [])
    monkeypatch.setattr(PG, "fetch_results", lambda sport, d, games, fetch=None: {})
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "41_Postgame_Review.py"), default_timeout=30)
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_report_has_a_lock_section(monkeypatch):
    monkeypatch.setattr(BW, "_load", lambda: {})
    rows = [{"result": "hit" if i % 3 else "miss", "slate_date": "2026-11-01", "player": f"L{i}", "market": "Points",
             "side": "Under", "line": 20.5, "chance": 0.64, "cushion": 0.2, "gap": "agree", "price": -150}
            for i in range(12)]
    rep = T.build("NBA", rows, [])
    assert rep["locks"]["graded"] == 12 and rep["locks"]["hits"] == 8
    assert "Most probable" in rep["markdown"] and "| Points | Under | 8-4 |" in rep["markdown"]
