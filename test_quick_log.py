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
    assert fields["entry_odds_source"] == "model_fair"
    print("✓ bet_log_fields_from_play correctly uses the model's own Fair price as entry_odds "
         "when no real offers are provided, and labels it as such")


def test_bet_log_fields_from_play_prefers_the_plays_own_real_price_over_a_fresh_offers_lookup():
    # The actual architectural fix: when a play already carries RealPrice/PriceSource (set once,
    # correctly, by build_best_bets at board-build time), quick_log must use THAT value directly
    # rather than doing its own separate, redundant lookup via offers -- even when offers is ALSO
    # provided and would produce a genuinely different answer. This guarantees "what a person saw
    # on screen" and "what got logged" are always the exact same number, never two independently
    # computed prices that could disagree if the market moved between board-build and log time.
    play = dict(_play(player="Wade Meckler", market="Batter Total Hits", side="Over", fair=-282),
               RealPrice=-260, PriceSource="book", RealPriceBook="draftkings")
    # A DIFFERENT offers snapshot, deliberately, simulating the market having moved since the
    # play was built -- if quick_log did its own independent lookup, it would find THIS number
    # instead, which must NOT happen.
    stale_offers = [{"player": "Wade Meckler", "market": "batter_hits", "point": 0.5,
                     "over": {"draftkings": -305}, "under": {"draftkings": 250}}]
    fields = Q.bet_log_fields_from_play(play, "2026-07-20", "MLB", offers=stale_offers,
                                        preferred_book="draftkings")
    assert fields["entry_odds"] == -260   # the play's OWN real price, not the stale offers lookup
    assert fields["entry_odds_source"] == "book"
    print("✓ bet_log_fields_from_play prefers the play's own already-computed RealPrice over a "
         "fresh (and potentially inconsistent) offers-based lookup")


def test_bet_log_fields_from_play_falls_back_to_offers_lookup_when_play_has_no_real_price_yet():
    # Plays without RealPrice/PriceSource set (an older cached play, a sport that doesn't
    # populate these fields yet) must still correctly fall back to the offers-based lookup --
    # this is a genuine fallback, not a replacement of the existing mechanism.
    play = _play(player="Wade Meckler", market="Batter Total Hits", side="Over", fair=-282)
    assert "RealPrice" not in play   # confirms this play genuinely has no pre-computed real price
    offers = [{"player": "Wade Meckler", "market": "batter_hits", "point": 0.5,
              "over": {"draftkings": -260}, "under": {"draftkings": 210}}]

    class _FakeSport:
        market_map = {"Batter Total Hits": "batter_hits"}

    import unittest.mock as mock
    with mock.patch("sports.get", return_value=_FakeSport()):
        fields = Q.bet_log_fields_from_play(play, "2026-07-20", "MLB", offers=offers,
                                            preferred_book="draftkings")
    assert fields["entry_odds"] == -260.0 and fields["entry_odds_source"] == "book"
    print("✓ bet_log_fields_from_play correctly falls back to the offers-based lookup when the "
         "play itself has no pre-computed RealPrice")


def test_bet_log_fields_from_play_ignores_play_price_source_when_not_book():
    # A play with PriceSource="model_fair" (the normal, honest default when no real price exists
    # at all) must not be misread as having a real price -- only PriceSource == "book" counts.
    play = dict(_play(player="Wade Meckler", fair=-282), RealPrice=None, PriceSource="model_fair")
    fields = Q.bet_log_fields_from_play(play, "2026-07-20", "MLB")
    assert fields["entry_odds"] == -282 and fields["entry_odds_source"] == "model_fair"
    print("✓ bet_log_fields_from_play correctly ignores a play's PriceSource when it isn't "
         "\"book\", falling through to the normal Fair-odds behavior")



    # Regression guard for the actual fix: a real captured book price now replaces the model's
    # own Fair-derived price when a genuine match exists in already-fetched offers. Confirmed
    # against a real production finding: every previously-logged bet showed a "priced edge" of
    # well under 0.1 percentage points versus its own model_prob -- a tautology, not a real edge,
    # because entry_odds and model_prob were never independent numbers before this fix.
    import unittest.mock as mock
    play = _play(player="Wade Meckler", market="Batter Total Hits", side="Over", fair=-282)
    offers = [{"player": "Wade Meckler", "market": "batter_hits", "point": 0.5,
              "over": {"draftkings": -260}, "under": {"draftkings": 210}}]

    class _FakeSport:
        market_map = {"Batter Total Hits": "batter_hits"}

    with mock.patch("sports.get", return_value=_FakeSport()):
        fields = Q.bet_log_fields_from_play(play, "2026-07-20", "MLB", offers=offers,
                                            preferred_book="draftkings")
    assert fields["entry_odds"] == -260.0
    assert fields["entry_odds_source"] == "book"
    assert fields["line"] == 0.5   # the real posted point, from the real offer
    print("✓ bet_log_fields_from_play uses a real captured book price (and its real point) "
         "when offers are provided and a genuine match exists")


def test_bet_log_fields_from_play_falls_back_to_fair_when_offers_have_no_match():
    import unittest.mock as mock
    play = _play(player="Wade Meckler", market="Batter Total Hits", side="Over", fair=-282)
    offers = [{"player": "A Totally Different Player", "market": "batter_hits", "point": 1.5,
              "over": {"draftkings": -150}, "under": {"draftkings": 130}}]

    class _FakeSport:
        market_map = {"Batter Total Hits": "batter_hits"}

    with mock.patch("sports.get", return_value=_FakeSport()):
        fields = Q.bet_log_fields_from_play(play, "2026-07-20", "MLB", offers=offers)
    assert fields["entry_odds"] == -282   # the Fair fallback, untouched
    assert fields["entry_odds_source"] == "model_fair"
    assert fields["line"] == 0.5   # the play's own original line, not the unrelated offer's point
    print("✓ bet_log_fields_from_play falls back to Fair odds when offers don't contain a real "
         "match for this specific player/market")


def test_bet_log_fields_from_play_offers_provided_but_market_not_in_sports_map():
    # A real, honest edge case: offers exist, but this sport's own market_map doesn't have an
    # entry for this specific display market name -- must degrade to the Fair fallback, not crash.
    import unittest.mock as mock
    play = _play(market="Some Unmapped Market")
    offers = [{"player": "Ohtani", "market": "whatever", "point": 0.5,
              "over": {"draftkings": -150}, "under": {"draftkings": 130}}]

    class _FakeSport:
        market_map = {}   # this market genuinely isn't mapped

    with mock.patch("sports.get", return_value=_FakeSport()):
        fields = Q.bet_log_fields_from_play(play, "2026-07-20", "MLB", offers=offers)
    assert fields["entry_odds_source"] == "model_fair"
    print("✓ bet_log_fields_from_play degrades honestly to Fair odds when the market isn't in "
         "this sport's own market_map, rather than crashing")


def _ml_play(side="New York Yankees", fair=-145, game="Red Sox @ Yankees", model_prob=0.59):
    return {"Player": None, "PlayerId": None, "Team": None, "Game": game, "Market": "Moneyline",
           "Side": side, "Line": None, "Fair": fair, "ModelProb": model_prob, "Why": "x"}


def test_bet_log_fields_from_play_uses_real_moneyline_price_when_matched():
    # Regression guard for the actual fix: a real captured moneyline price now replaces the
    # model's own Fair-derived price for team-level picks, same as the player-prop path already
    # does -- moneylines are a genuinely different data shape (team + price, no market_key/line/
    # over-under split), so this exercises the SEPARATE moneyline lookup path specifically.
    moneylines = {"New York Yankees": {"draftkings": -150, "fanduel": -145}}
    fields = Q.bet_log_fields_from_play(_ml_play(), "2026-07-29", "MLB", moneylines=moneylines,
                                        preferred_book="draftkings")
    assert fields["entry_odds"] == -150.0
    assert fields["entry_odds_source"] == "book"
    print("✓ bet_log_fields_from_play uses a real captured moneyline price when the team matches")


def test_bet_log_fields_from_play_falls_back_to_fair_when_moneylines_have_no_match():
    moneylines = {"Boston Red Sox": {"draftkings": 130}}   # the OTHER team, not the one we bet
    fields = Q.bet_log_fields_from_play(_ml_play(side="New York Yankees"), "2026-07-29", "MLB",
                                        moneylines=moneylines)
    assert fields["entry_odds"] == -145 and fields["entry_odds_source"] == "model_fair"
    print("✓ bet_log_fields_from_play falls back to Fair odds when moneylines don't contain a "
         "real match for this specific team")


def test_bet_log_fields_from_play_moneyline_path_ignored_for_player_props():
    # The two real-price paths must never cross-contaminate: a player-prop play should never
    # accidentally use the moneyline lookup, and vice versa (covered by the mirror test below).
    moneylines = {"New York Yankees": {"draftkings": -150}}
    player_play = _play(player="Ohtani", market="Batter HR", side="Over", fair=-150)
    fields = Q.bet_log_fields_from_play(player_play, "2026-07-20", "MLB", moneylines=moneylines)
    assert fields["entry_odds"] == -150 and fields["entry_odds_source"] == "model_fair"
    print("✓ a player-prop play is never affected by a moneylines dict being passed in")


def test_bet_log_fields_from_play_offers_path_ignored_for_moneyline_plays():
    offers = [{"player": "Someone", "market": "batter_hits", "point": 0.5,
              "over": {"draftkings": -200}, "under": {"draftkings": 165}}]
    fields = Q.bet_log_fields_from_play(_ml_play(), "2026-07-29", "MLB", offers=offers)
    assert fields["entry_odds"] == -145 and fields["entry_odds_source"] == "model_fair"
    print("✓ a moneyline play (no Player) is never affected by an offers list being passed in "
         "without a matching moneylines dict")


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
                          "side", "line", "entry_odds", "entry_odds_source", "model_prob",
                          "stake", "book", "close_odds", "result", "notes", "ticket", "sport",
                          "trader"}
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
