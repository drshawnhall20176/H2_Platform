"""Nov 16: the Live Games board leads with a summary and the closest game."""
from datetime import datetime, timedelta, timezone

import live_lead as LL

NOW = datetime(2026, 11, 16, 21, 0, tzinfo=timezone.utc)


def _it(label, wh, start=0.5):
    away, home = label.split(" @ ")
    return {"label": label, "home": home, "away": away, "win_home": wh, "start_home": start,
            "leader": None if wh is None else (home if wh >= 0.5 else away)}


def test_live_games_are_ordered_closest_first_and_unread_games_stay_last():
    items = [_it("A @ B", 0.95), _it("C @ D", None), _it("E @ F", 0.44), _it("G @ H", 0.70), _it("I @ J", 0.56)]
    assert [x["label"] for x in LL.order_live(items)] == ["E @ F", "I @ J", "G @ H", "A @ B", "C @ D"]
    assert LL.lead_chance(0.44) == 0.56 and LL.lead_chance(None) is None
    assert LL.order_live([]) == []


def test_summary_names_the_closest_game_and_the_biggest_swing():
    items = [_it("A @ B", 0.95, start=0.60), _it("E @ F", 0.44, start=0.75), _it("C @ D", None)]
    tiles = LL.summary(items, n_later=3, n_done=2)
    assert [t["value"] for t in tiles] == ["3", "56%", "+35%", "3", "2"]
    assert tiles[1]["label"] == "Closest: E @ F (E ahead)"
    assert tiles[2]["label"] == "Biggest swing: B (A @ B)"            # home went 60% -> 95%
    quiet = LL.summary([_it("A @ B", 0.62, start=0.60)], 0, 0)
    assert [t["label"] for t in quiet] == ["Live now", "Closest: A @ B (B ahead)", "Still to start today", "Final"]
    assert [t["value"] for t in LL.summary([], 4, 1)] == ["0", "4", "1"]


def test_starts_in_reads_like_a_person_would_say_it():
    assert LL.starts_in(NOW + timedelta(minutes=25), NOW) == "25 min"
    assert LL.starts_in(NOW + timedelta(minutes=135), NOW) == "2 h 15 min"
    assert LL.starts_in(NOW - timedelta(minutes=2), NOW) == "any minute" and LL.starts_in(None, NOW) == ""


def test_next_up_shows_the_pre_game_read_for_the_first_games_only():
    later = [{"home": f"H{i}", "away": f"A{i}", "detail": f"{7 + i}:00 PM", "kickoff": NOW + timedelta(hours=i + 1)}
             for i in range(4)]
    looked = []

    def pre_for(g):
        looked.append(g["home"])
        return None if g["home"] == "H1" else {"model_margin": 6.0, "model_total": 226.0}
    rows = LL.next_up(later, pre_for, lambda g, pre: 0.68 if g["home"] == "H0" else 0.31, lambda g: g["kickoff"], NOW, n=3)
    assert looked == ["H0", "H1", "H2"]                                # the fourth game costs no look-up
    assert rows[0] == {"Start": "7:00 PM", "Starts in": "1 h 00 min", "Game": "A0 @ H0",
                       "Pre-game favourite": "H0 68%", "Projected score": "110–116"}
    assert rows[1]["Pre-game favourite"] == "—" and rows[1]["Projected score"] == "—"
    assert rows[2]["Pre-game favourite"] == "A2 69%" and rows[3]["Projected score"] == "—"


def test_live_board_leads_with_the_closest_game(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import live_games as LG
    import model_store as MS
    import streamlit as st
    st.cache_data.clear()

    def game(i, hs, as_, state="in"):
        return {"league": "NBA", "event_id": f"e{i}", "home": f"Home{i}", "away": f"Away{i}", "home_score": hs,
                "away_score": as_, "state": state, "period": 4, "clock_left": 3.0, "halftime": False,
                "kickoff": f"2026-11-17T00:0{i}:00Z", "detail": "7:00 PM", "possession": None}
    games = [game(1, 110, 80), game(2, 98, 97), game(3, 0, 0, state="pre")]
    picks = [{"sport": "NBA", "home": f"Home{i}", "away": f"Away{i}", "kickoff": f"2026-11-17T00:0{i}:00Z",
              "model_margin": 2.0, "model_total": 224.0, "model_p": 0.56, "result": None} for i in (1, 2, 3)]
    monkeypatch.setattr(LG, "games", lambda lg, day: games)
    monkeypatch.setattr(MS, "load_game_picks", lambda sport, ungraded=False, db_path=None: picks)
    monkeypatch.setattr(LG, "pregame_for", lambda g, picks: {"model_margin": 2.0, "model_total": 224.0, "source": "lab"})
    at = AppTest.from_file("views/54_Live_Games.py", default_timeout=120)
    at.session_state["sport"] = "NBA"
    at.run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    cards = [m.value for m in at.markdown if "Away" in m.value and "@ Home" in m.value and "**" in m.value]
    assert cards[0].startswith("⚖️ Closest game · **Away2 97 @ Home2 98**") and "Away1 80 @ Home1 110" in cards[1]
    nxt = [d.value for d in at.dataframe if "Starts in" in d.value.columns][0]
    assert list(nxt["Game"]) == ["Away3 @ Home3"] and nxt["Projected score"][0] == "111–113"
