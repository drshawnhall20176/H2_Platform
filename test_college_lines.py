import college_lines as CL


def test_prop_supply_counts_only_sportsbook_priced_games():
    plays = [{"Game": "A @ B", "PriceSource": "book", "RealPriceBook": "fanduel"},
             {"Game": "A @ B", "PriceSource": "book", "RealPriceBook": "fanduel"},
             {"Game": "C @ D", "PriceSource": "book", "Pickem": True},
             {"Game": "E @ F", "PriceSource": "model"}]
    t = CL.prop_supply(plays, 44)
    assert "**1 of 44**" in t and "FanDuel" in t


def test_plays_lists_money_picks_and_close_gap_games_by_time_with_icons_left(monkeypatch):
    import game_previews as GP
    monkeypatch.setattr(GP, "_last", lambda lg, p: "—")
    monkeypatch.setattr(GP, "blowout", lambda lg, p: "🟩 20%")
    monkeypatch.setattr(GP, "agreement", lambda p, lg="": "✅ Agree" if p.get("home") == "D" else "🟨 Same winner")
    rows = [{"game": "A @ B", "time": "9:00 PM", "money": True, "money_pick": "B -3.5", "money_price": -110,
             "money_market": "Spread", "best": "B -3.5", "bet_market": "Spread", "use": "🎯 Single only",
             "winner": "B", "chance": 0.7, "price": -200, "_full": {"home": "B"}},
            {"game": "C @ D", "time": "7:00 PM", "money": False, "best": "D -4", "bet_market": "Spread",
             "use": "⚪ No edge", "winner": "D", "chance": 0.6, "price": -150, "_full": {"home": "D"}}]
    recs = [{"home": "D", "away": "C", "kickoff": "2026-11-25T00:00:00Z", "home_spread": -4.0, "model_margin": 5.0,
             "game_id": "g"}]
    out = CL.plays("NCAAMB", "2026-11-24", rows, recs=recs)
    assert [(o["Game"], o["Use"], o["Pick"]) for o in out] == [("C @ D", "✅", "D -4"), ("A @ B", "💰 🎯", "B -3.5")]
    assert list(out[0])[:5] == ["Time", "Game", "Use", "Pick type", "Market"]
    assert out[0]["Pick type"] == CL.LINE and out[1]["Pick type"] == CL.MONEY
    full = CL.board_rows("NCAAMB", "2026-11-24", rows, recs=recs)
    assert {o["Market"] for o in full} == {"Spread", "Moneyline"} and len(full) == 4


def test_same_game_matches_full_names_to_short_labels():
    assert CL.same_game("Boston Celtics @ New York Knicks", "BOS Celtics @ NY Knicks")
    assert not CL.same_game("Boston Celtics @ New York Knicks", "Lakers @ Suns")
