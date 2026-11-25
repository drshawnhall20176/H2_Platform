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
    assert list(out[0])[:5] == ["League", "Time", "Game", "Bet?", "Model & market agree?"]
    assert out[0]["Pick type"] == CL.LINE and out[1]["Pick type"] == CL.MONEY
    full = CL.board_rows("NCAAMB", "2026-11-24", rows, recs=recs)
    assert {o["Market"] for o in full} == {"Spread", "Moneyline"} and len(full) == 4


def test_same_game_matches_full_names_to_short_labels():
    assert CL.same_game("Boston Celtics @ New York Knicks", "BOS Celtics @ NY Knicks")
    assert not CL.same_game("Boston Celtics @ New York Knicks", "Lakers @ Suns")


def test_today_cards_put_bets_then_tracking_then_moves_then_line_picks(monkeypatch):
    rows = [
        {"Game": "G1", "Bet?": "Info only", "Pick type": CL.WINNER, "Pick": "A ML", "Chance": 0.9, "Use": "", "Price": -900},
        {"Game": "G1", "Bet?": "Info only", "Pick type": CL.LINE, "Pick": "A -12", "Chance": 0.55, "Use": "", "Price": -110},
        {"Game": "G2", "Bet?": "🧪 Tracking", "Pick type": CL.CLOSE, "Pick": "B -3", "Chance": None, "Use": "✅", "Price": -110},
        {"Game": "G3", "Bet?": "🃏 Bet", "Pick type": CL.MONEY, "Pick": "C ML", "Chance": 0.45, "Use": "💰", "Price": 130},
        {"Game": "G4", "Bet?": "Info only", "Pick type": CL.LINE, "Pick": "D +4", "Chance": 0.5, "Use": "📈", "Price": -110,
         "_move": "D +2.5 → +4"},
    ]
    cards = CL.today_cards(rows)
    assert [c["game"] for c in cards] == ["G3", "G2", "G4", "G1"]
    assert cards[0]["bet"] == "🃏 Bet" and cards[0]["money"] and cards[0]["price"] == "+130"
    assert cards[3]["pick"] == "A -12"                         # the line pick, not the -900 favorite


def test_soccer_today_rows_flag_tracking_and_label_reads():
    rows = CL._soccer("2026-11-24", rows=[{"time": "3:00 PM", "game": "X vs Y", "winner": "Y", "chance": 0.5,
                                            "price": 120, "league": "EPL"}],
                      flags=[{"time": "3:00 PM", "game": "X vs Y", "pick": "Over 2.5 goals", "market": "Total",
                              "price": 105, "chance": 0.52, "ev": 0.03, "league": "EPL"}])
    assert [r["Bet?"] for r in rows] == ["🧪 Tracking", "Info only"]


def test_close_gap_line_picks_log_as_test_legs_and_the_coach_grades_a_test_ticket():
    import coach as CO
    import game_lines_table as GLT
    r = {"league": "NCAAMB", "bet_market": "Spread", "best": "Belmont +2.5", "bet_price": -110,
         "_full": {"home": "Akron", "away": "Belmont", "home_spread": -2.5, "model_margin": 0.8}}
    assert GLT.is_tracking(r) and not GLT.is_tracking(dict(r, _full=dict(r["_full"], model_margin=8.0)))
    (it,) = GLT.line_items([r], [(0, "✓ Pick")])
    assert it["tracking"] and it["grade"].startswith("🧪 Tracking")
    chk = CO.ticket_check([dict(it, sport="NCAAMB", price=-110)], "Singles", 2.7, 0, None, [], "2026-11-24",
                          lim={"max_legs": 4, "max_parlay_stake": 10, "stop_loss": 50, "daily_budget": 100,
                               "max_parlays": 2})
    assert chk["grade"] == "T" and chk["headline"].startswith("🧪 Test ticket")
    assert any(lv == "test" for lv, _ in chk["flags"]) and not any(lv == "red" for lv, _ in chk["flags"])
