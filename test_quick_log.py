"""
test_quick_log.py — offline tests for quick_log.py's pure, testable field mapping. The
Streamlit-dependent render_quick_log itself isn't unit tested here (no Streamlit runtime in
this environment), but the actual logic that matters most -- correctly mapping a play dict to
real Bet Log fields, and correctly deduplicating -- is fully covered, since a wrong mapping here
would silently corrupt real trade-log data.

    python test_quick_log.py     # or: pytest test_quick_log.py
"""

import quick_log as Q


# ----------------------------------------------------------------- STAKE_QUICK_PICKS
def test_stake_quick_picks_covers_full_range():
    assert Q.STAKE_QUICK_PICKS[0] == 0.0
    assert Q.STAKE_QUICK_PICKS[-1] == 500.0
    print("✓ STAKE_QUICK_PICKS correctly spans the full requested $0-$500 range")


def test_stake_quick_picks_half_dollar_increments():
    diffs = [round(b - a, 4) for a, b in zip(Q.STAKE_QUICK_PICKS, Q.STAKE_QUICK_PICKS[1:])]
    assert all(d == 0.5 for d in diffs)
    print("✓ STAKE_QUICK_PICKS correctly steps by exactly 0.5 throughout the whole range")


def test_stake_quick_picks_exact_count():
    # 0.0 through 500.0 in 0.5 steps is exactly 1001 real, distinct values.
    assert len(Q.STAKE_QUICK_PICKS) == 1001
    print("✓ STAKE_QUICK_PICKS has exactly the right number of real, distinct values")


def test_stake_quick_picks_no_duplicates():
    assert len(Q.STAKE_QUICK_PICKS) == len(set(Q.STAKE_QUICK_PICKS))


def _play(player="Ohtani", market="Batter HR", side="Over", line=0.5, fair=-150,
         model_prob=0.60, game="LAD @ SF", player_id=None):
    return {"Player": player, "Team": "LAD", "Game": game, "Market": market, "Side": side,
           "Line": line, "ModelProb": model_prob, "Fair": fair, "Why": "x", "PlayerId": player_id}


# ----------------------------------------------------------------- bet_log_fields_from_play
def test_bet_log_fields_from_play_correct_mapping():
    play = _play()
    fields = Q.bet_log_fields_from_play(play, "2026-07-20", "MLB", stake=25.0)
    assert fields["slate_date"] == "2026-07-20"
    assert fields["game"] == "LAD @ SF"
    assert fields["player"] == "Ohtani"
    assert fields["market"] == "Batter HR"
    assert fields["side"] == "Over"
    assert fields["line"] == 0.5
    assert fields["entry_odds"] == -150
    assert fields["model_prob"] == 0.60
    assert fields["stake"] == 25.0
    assert fields["sport"] == "MLB"
    print("✓ bet_log_fields_from_play correctly maps every real field from a play dict")


def test_bet_log_fields_from_play_default_stake_zero():
    fields = Q.bet_log_fields_from_play(_play(), "2026-07-20", "MLB")
    assert fields["stake"] == 0.0
    print("✓ bet_log_fields_from_play defaults stake to 0.0 when not supplied")


def test_bet_log_fields_from_play_handles_missing_line_gracefully():
    play = _play()
    del play["Line"]
    fields = Q.bet_log_fields_from_play(play, "2026-07-20", "MLB")
    assert fields["line"] == 0.0   # doesn't crash, falls back to a real, sane default
    print("✓ bet_log_fields_from_play handles a play missing Line without crashing")


def test_bet_log_fields_from_play_handles_missing_model_prob_gracefully():
    play = _play()
    del play["ModelProb"]
    fields = Q.bet_log_fields_from_play(play, "2026-07-20", "MLB")
    assert fields["model_prob"] == 0.0
    print("✓ bet_log_fields_from_play handles a play missing ModelProb without crashing")


def test_bet_log_fields_from_play_entry_odds_is_the_model_fair_price():
    # A real, deliberate honesty check: entry_odds must come from the play's own "Fair" field
    # (the model's fair price), never fabricated or left as a real book price this page doesn't
    # actually have.
    play = _play(fair=+340)
    fields = Q.bet_log_fields_from_play(play, "2026-07-20", "MLB")
    assert fields["entry_odds"] == 340
    print("✓ bet_log_fields_from_play correctly uses the model's own Fair price as entry_odds")


def test_bet_log_fields_from_play_maps_player_id():
    # Added directly on request, for automated result settlement -- confirms the play's own
    # PlayerId (set on every play by build_best_bets) flows through correctly.
    play = _play(player_id=660271)
    fields = Q.bet_log_fields_from_play(play, "2026-07-20", "MLB")
    assert fields["player_id"] == 660271
    print("✓ bet_log_fields_from_play correctly maps the play's own PlayerId")


def test_bet_log_fields_from_play_player_id_none_when_absent():
    play = _play()   # player_id defaults to None in the _play fixture
    fields = Q.bet_log_fields_from_play(play, "2026-07-20", "MLB")
    assert fields["player_id"] is None
    print("✓ bet_log_fields_from_play correctly leaves player_id as None when the play has none, not fabricated")


def test_bet_log_fields_from_play_only_real_betlog_fields():
    # Confirms every key returned is a real, valid betlog.py field, not a typo or extra key that
    # would silently be dropped (or worse, rejected) by add_bet.
    real_betlog_fields = {"ts_placed", "slate_date", "game", "player", "player_id", "market",
                          "side", "line", "entry_odds", "model_prob", "stake", "book",
                          "close_odds", "result", "notes", "ticket", "sport", "trader"}
    fields = Q.bet_log_fields_from_play(_play(), "2026-07-20", "MLB")
    assert set(fields.keys()) <= real_betlog_fields
    print("✓ bet_log_fields_from_play returns only real, valid betlog.py field names")


def test_bet_log_fields_from_play_handles_moneyline_shape_end_to_end():
    # A team-level moneyline play (Player=None, no PlayerId, no real Line) -- added directly on
    # request for Game Watch's own moneyline logging. Confirms the full mapping (not just the
    # label) handles this shape cleanly: player/player_id come through as None (already-nullable
    # columns), line falls back to the same "missing -> 0.0" behavior every other play already
    # gets, not a crash or a special case.
    ml_play = {"Player": None, "PlayerId": None, "Team": None, "Game": "Red Sox @ Yankees",
              "Market": "Moneyline", "Side": "New York Yankees", "Line": None, "Fair": -145,
              "ModelProb": 0.59, "Why": "x"}
    fields = Q.bet_log_fields_from_play(ml_play, "2026-07-23", "MLB", stake=10.0)
    assert fields["player"] is None and fields["player_id"] is None
    assert fields["market"] == "Moneyline" and fields["side"] == "New York Yankees"
    assert fields["line"] == 0.0   # same honest "missing -> 0.0" fallback every other play gets
    assert fields["entry_odds"] == -145
    assert abs(fields["model_prob"] - 0.59) < 1e-9
    print("✓ bet_log_fields_from_play correctly handles a full moneyline-shaped play end to end")


# ----------------------------------------------------------------- bet_log_signature
def test_bet_log_signature_distinguishes_different_plays():
    sig_a = Q.bet_log_signature(_play(player="Ohtani"), "2026-07-20")
    sig_b = Q.bet_log_signature(_play(player="Judge"), "2026-07-20")
    assert sig_a != sig_b


def test_bet_log_signature_same_play_same_date_matches():
    play = _play()
    sig1 = Q.bet_log_signature(play, "2026-07-20")
    sig2 = Q.bet_log_signature(dict(play), "2026-07-20")   # a fresh, equal copy of the same play
    assert sig1 == sig2
    print("✓ bet_log_signature produces a matching signature for the same real play, enabling correct dedup")


def test_bet_log_signature_different_date_differs():
    play = _play()
    sig1 = Q.bet_log_signature(play, "2026-07-20")
    sig2 = Q.bet_log_signature(play, "2026-07-21")
    assert sig1 != sig2
    print("✓ bet_log_signature correctly distinguishes the same play logged on a different date")


def test_bet_log_signature_different_side_differs():
    sig_over = Q.bet_log_signature(_play(side="Over"), "2026-07-20")
    sig_under = Q.bet_log_signature(_play(side="Under"), "2026-07-20")
    assert sig_over != sig_under
    print("✓ bet_log_signature correctly distinguishes Over vs Under on the same market/line")


# ----------------------------------------------------------------- format_play_label
def test_format_play_label_normal_player_prop():
    label = Q.format_play_label(_play(player="Aaron Judge", market="Batter HR", side="Over",
                                      line=0.5, fair=+250))
    assert label == "Aaron Judge · Batter HR Over 0.5 @ +250"
    print("✓ format_play_label correctly formats a normal player-prop play")


def test_format_play_label_missing_fair_shows_dash():
    label = Q.format_play_label(_play(player="Aaron Judge", fair=None))
    assert "—" in label
    print("✓ format_play_label shows a dash (not a crash or 'None') when Fair is missing")


def test_format_play_label_team_level_play_has_no_player_or_line():
    # A moneyline play (Player=None) -- added directly on request for Game Watch's own
    # moneyline logging. Must skip the player/line pieces entirely, not show a confusing
    # "? · ... —" placeholder for a play that was never meant to have either.
    ml_play = {"Player": None, "Market": "Moneyline", "Side": "New York Yankees",
              "Line": None, "Fair": -145, "ModelProb": 0.59, "Game": "Red Sox @ Yankees"}
    label = Q.format_play_label(ml_play)
    assert label == "Moneyline New York Yankees @ -145"
    assert "?" not in label
    assert "None" not in label
    print("✓ format_play_label correctly formats a team-level moneyline play with no player/line, no '?' placeholder")


def test_format_play_label_team_level_play_missing_fair():
    ml_play = {"Player": None, "Market": "Moneyline", "Side": "Boston Red Sox", "Fair": None}
    label = Q.format_play_label(ml_play)
    assert label == "Moneyline Boston Red Sox @ —"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
