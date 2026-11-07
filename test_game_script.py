"""Game Script (Nov 7): props under each kind of game, and tickets that count the script."""
import script_effects as SE


def test_shares_by_spread():
    sh = SE.shares(-13.5)
    assert abs(sum(sh.values()) - 1) < 1e-9 and sh["fav_blowout"] == 0.546 and sh["dog_blowout"] == 0.021
    assert SE.shares(None)["close"] == 0.323


def test_script_shifts_are_centered_and_point_the_right_way():
    sh = SE.shares(-13.5)
    by = SE.over_by_script(0.50, "starter", False, "Points", sh)      # underdog starter
    assert by["fav_blowout"] < 0.45 < by["close"]                    # his team gets blown out: Under
    assert abs(sum(sh[s] * by[s] for s in SE.SCRIPTS) - 0.50) < 1e-9  # the mix is the model's own read
    bench = SE.over_by_script(0.50, "bench", True, "Points", sh)       # favorite's bench
    assert bench["fav_blowout"] > bench["close"]
    assert SE.over_by_script(0.5, None, True, "Points", sh)["close"] == 0.5
    half = SE.over_by_script(0.5, "starter", False, "Rebounds", sh)
    assert abs(half["fav_blowout"] - 0.5) < abs(by["fav_blowout"] - 0.5)


def test_ticket_counts_shared_script():
    sh = SE.shares(-13.5)
    a = SE.side_chance(SE.over_by_script(0.5, "starter", False, "Points", sh), "Under")
    b = SE.side_chance(SE.over_by_script(0.5, "bench", True, "Points", sh), "Over")
    scripted, plain, per = SE.ticket([a, b], sh)
    assert scripted > plain                                          # both win when the favorite runs away
    assert per["fav_blowout"] > per["close"]


def test_page_renders(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    import best_bets_data as BBD
    import model_store as MS
    g = "San Antonio Spurs @ Sacramento Kings"
    log = [{"min": 30.0}] * 10
    plays = [{"Model": "player-props", "Player": "Zach LaVine", "Team": "Sacramento Kings", "Game": g, "Market": "Points",
              "Side": "Under", "Line": 20.5, "ModelProb": 0.54, "RealPrice": -112, "Use": "", "_game_log": log},
             {"Model": "player-props", "Player": "Dylan Harper", "Team": "San Antonio Spurs", "Game": g, "Market": "Points",
              "Side": "Over", "Line": 17.5, "ModelProb": 0.56, "RealPrice": -104, "Use": "", "_game_log": [{"min": 22.0}] * 10}]
    monkeypatch.setattr(BBD, "load_generic_best_bets_board", lambda *a, **k: (plays, [], []))
    monkeypatch.setattr(MS, "load_game_picks", lambda lg, ungraded=False, db_path=None: [
        {"kickoff": "2026-11-07T03:00:00Z", "home": "Sacramento Kings", "away": "San Antonio Spurs", "home_spread": 13.5}])
    import todays_best as TB
    monkeypatch.setattr(TB, "_et_date", lambda iso: __import__("datetime").datetime.now(
        __import__("pytz").timezone("US/Eastern")).strftime("%Y-%m-%d"))
    at = AppTest.from_file(str(Path(__file__).parent / "views" / "50_Game_Script.py"), default_timeout=30)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.metric[1].value == "55%"                               # Spurs by 15+ at -13.5
    at.radio(key="gs_script").set_value("fav_blowout").run()
    assert not at.exception
    assert any("Zach LaVine Points Under" in k for k in at.multiselect[0].options)
