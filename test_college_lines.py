import college_lines as CL


def test_prop_supply_counts_only_sportsbook_priced_games():
    plays = [{"Game": "A @ B", "PriceSource": "book", "RealPriceBook": "fanduel"},
             {"Game": "A @ B", "PriceSource": "book", "RealPriceBook": "fanduel"},
             {"Game": "C @ D", "PriceSource": "book", "Pickem": True},
             {"Game": "E @ F", "PriceSource": "model"}]
    t = CL.prop_supply(plays, 44)
    assert "**1 of 44**" in t and "FanDuel" in t


def test_plays_lists_money_picks_and_close_gap_games_by_time(monkeypatch):
    import game_previews as GP
    monkeypatch.setattr(GP, "_last", lambda lg, p: "—")
    monkeypatch.setattr(GP, "blowout", lambda lg, p: "🟩 20%")
    rows = [{"game": "A @ B", "time": "9:00 PM", "money": True, "money_pick": "B -3.5", "money_price": -110,
             "_full": {"home": "B"}},
            {"game": "C @ D", "time": "7:00 PM", "money": False}]
    recs = [{"home": "D", "away": "C", "kickoff": "2026-11-25T00:00:00Z", "home_spread": -4.0, "model_margin": 5.0,
             "game_id": "g"}]
    out = CL.plays("NCAAMB", "2026-11-24", rows, recs=recs)
    assert [o["Game"] for o in out] == ["C @ D", "A @ B"]
    assert out[0]["Play"] == "D -4" and out[0]["Why"].startswith("✅") and out[1]["Why"].startswith("💰")
