"""
test_odds.py — offline tests for odds math + edge join (no network).

    python test_odds.py     # or: pytest test_odds.py
"""

import projections as P
import odds_api as O
import mlb_engine as E


def test_implied_prob():
    assert round(O.implied_prob(-110), 4) == 0.5238
    assert round(O.implied_prob(100), 4) == 0.5
    assert round(O.implied_prob(120), 4) == 0.4545


def test_decimal():
    assert O.american_to_decimal(100) == 2.0
    assert O.american_to_decimal(-200) == 1.5
    assert O.american_to_decimal(150) == 2.5


def test_ev_percent():
    assert round(O.ev_percent(0.60, 120), 1) == 32.0
    assert round(O.ev_percent(0.50, -110), 2) == -4.55
    # break-even: fair price for 50% is +100 -> EV 0
    assert round(O.ev_percent(0.50, 100), 6) == 0.0


def test_devig():
    assert O.devig_two_way(-110, -110) == 0.5
    # favorite over: over -200 / under +160 -> fair over > 0.5
    fair = O.devig_two_way(-200, 160)
    assert 0.6 < fair < 0.72


def test_best_price_picks_highest_payout():
    # +120 pays more than -105; +120 should win
    book, price = O._best_price({"a": -105, "b": 120})
    assert price == 120


def test_parse_event_offers():
    event = {
        "bookmakers": [{
            "key": "fanduel",
            "markets": [{
                "key": "batter_hits",
                "outcomes": [
                    {"name": "Over", "description": "Aaron Judge", "point": 0.5, "price": -200},
                    {"name": "Under", "description": "Aaron Judge", "point": 0.5, "price": 160},
                ],
            }],
        }]
    }
    offers = O.parse_event_offers(event)
    assert len(offers) == 1
    o = offers[0]
    assert o["market"] == "batter_hits" and o["point"] == 0.5
    assert o["over"]["fanduel"] == -200 and o["under"]["fanduel"] == 160


def test_compute_edges_matches_and_ranks():
    slug = dict(plateAppearances=600, atBats=540, hits=165, doubles=34, triples=2,
                homeRuns=38, baseOnBalls=55, strikeOuts=140)
    row = {"Hitter": "José Ramírez", "Team": "CLE", "GameLabel": "CLE @ DET",
           "Opp Pitcher": "P", "Lineup": "Confirmed", "_stat": slug, "_exp_pa": 4.5, "_venue_id": None}
    meta = [{"label": "CLE @ DET", "game_date": "2026-07-28T23:10:00Z",
            "home_pm": E.PitcherMetrics(id=None), "home_name": "DET",
            "away_pm": E.PitcherMetrics(id=None), "away_name": "CLE"}]
    index = P.build_projection_index([row], meta, sims=15000, seed=3)

    offers = [
        # book sends de-accented name; should still match
        {"market": "batter_hits", "player": "Jose Ramirez", "point": 0.5,
         "over": {"fd": -200}, "under": {"fd": 160}},
        # unmatched player
        {"market": "batter_hits", "player": "Nobody Here", "point": 0.5,
         "over": {"fd": -150}, "under": {"fd": 120}},
    ]
    edges, stats = O.compute_edges(index, offers)
    assert stats["matched"] == 1 and stats["unmatched"] == 1
    assert all("EV%" in e for e in edges)
    # sorted by EV% descending
    evs = [e["EV%"] for e in edges]
    assert evs == sorted(evs, reverse=True)
    # model name (with accent) is preserved in output
    assert edges[0]["Player"] == "José Ramírez"
    # Regression guard: GameTime used to be silently dropped between build_projection_index's ctx
    # (which already carried it as "game_date") and compute_edges' own output row -- meaning
    # Edge Board's game-filter dropdown, which explicitly checks `if "GameTime" in edf.columns`,
    # could never take its already-written chronological-sort branch and always fell back to
    # alphabetical, regardless of how many games were on the slate.
    assert edges[0]["GameTime"] == "2026-07-28T23:10:00Z"
    print("✓ compute_edges carries GameTime through from the projection index, so Edge Board's "
         "existing chronological-sort branch actually has data to use")


# ----------------------------------------------------------------- market_lines_for_player
def test_market_lines_for_player_matches_by_normalized_name():
    offers = [
        # book sends de-accented name; should still match, same as compute_edges
        {"market": "batter_hits", "player": "Jose Ramirez", "point": 1.5,
         "over": {"fd": -150}, "under": {"fd": 120}},
        {"market": "batter_home_runs", "player": "Someone Else", "point": 0.5,
         "over": {"fd": -110}, "under": {"fd": -110}},
    ]
    lines = O.market_lines_for_player(offers, "José Ramírez")
    assert lines == {"batter_hits": 1.5}
    print("✓ market_lines_for_player matches names the same accent/spelling-insensitive way compute_edges does")


def test_market_lines_for_player_picks_the_most_booked_point():
    # Two books disagree on the point (1.5 vs 2.5) for the same market/player. The one backed by
    # MORE total book quotes should win -> 1.5 has 2 books total (1 over + 1 under from "fd" plus
    # 1 more from "dk" on the over side = 3), 2.5 only has 1.
    offers = [
        {"market": "batter_hits", "player": "Jose Ramirez", "point": 1.5,
         "over": {"fd": -150, "dk": -140}, "under": {"fd": 120}},
        {"market": "batter_hits", "player": "Jose Ramirez", "point": 2.5,
         "over": {"mgm": 250}, "under": {}},
    ]
    lines = O.market_lines_for_player(offers, "Jose Ramirez")
    assert lines == {"batter_hits": 1.5}
    print("✓ market_lines_for_player picks the point with the most total book quotes as consensus")


def test_market_lines_for_player_absent_when_no_match():
    offers = [{"market": "batter_hits", "player": "Nobody Here", "point": 1.5,
              "over": {"fd": -150}, "under": {"fd": 120}}]
    assert O.market_lines_for_player(offers, "Jose Ramirez") == {}
    print("✓ market_lines_for_player returns {} (not a guess) when nothing matches")


# ----------------------------------------------------------------- market_lines_for_slate
def test_market_lines_for_slate_builds_lookup_for_every_player_in_one_pass():
    offers = [
        {"market": "pitcher_strikeouts", "player": "Tomoyuki Sugano", "point": 3.5,
         "over": {"fd": -120}, "under": {"fd": 100}},
        {"market": "batter_hits", "player": "Jose Ramirez", "point": 1.5,
         "over": {"fd": -150}, "under": {"fd": 120}},
    ]
    lines = O.market_lines_for_slate(offers)
    assert lines[(P.normalize_name("Tomoyuki Sugano"), "pitcher_strikeouts")] == 3.5
    assert lines[(P.normalize_name("Jose Ramirez"), "batter_hits")] == 1.5
    print("✓ market_lines_for_slate correctly builds a real per-player, per-market line lookup for the whole slate in one pass")


def test_market_lines_for_slate_matches_the_exact_real_reported_case():
    # The real, specific discrepancy this whole feature was built from: DraftKings' real line on
    # Sugano's strikeouts was 3.5, while the platform's own hardcoded default was 5.5.
    offers = [{"market": "pitcher_strikeouts", "player": "Tomoyuki Sugano", "point": 3.5,
              "over": {"draftkings": -115}, "under": {"draftkings": -105}}]
    lines = O.market_lines_for_slate(offers)
    assert lines[(P.normalize_name("Tomoyuki Sugano"), "pitcher_strikeouts")] == 3.5
    assert lines[(P.normalize_name("Tomoyuki Sugano"), "pitcher_strikeouts")] != 5.5
    print("✓ market_lines_for_slate correctly resolves the exact real Sugano case that surfaced this whole gap")


def test_market_lines_for_slate_uses_minimum_line_when_books_disagree():
    # THE REAL PRODUCTION BUG THIS FIX EXISTS FOR: DraftKings posted 0.5 for Ezequiel Tovar's
    # H+R+RBI while other books posted 1.5. The old "most-booked wins" logic picked 1.5 --
    # the model then computed "Over 1.5" probability for a bet that was actually available at
    # "Over 0.5" on DraftKings. A bettor CAN get 0.5; that's the real line that matters.
    offers = [
        {"market": "batter_hits_runs_rbis", "player": "Ezequiel Tovar", "point": 1.5,
         "over": {"fanduel": -130, "betmgm": -140}, "under": {"fanduel": 110, "betmgm": 118}},
        {"market": "batter_hits_runs_rbis", "player": "Ezequiel Tovar", "point": 0.5,
         "over": {"draftkings": -115}, "under": {"draftkings": -115}},
    ]
    lines = O.market_lines_for_slate(offers)
    assert lines[(P.normalize_name("Ezequiel Tovar"), "batter_hits_runs_rbis")] == 0.5
    print("✓ market_lines_for_slate correctly resolves the exact real Tovar case: DK's 0.5 wins over other books' 1.5 because the minimum is the real available bet")


def test_market_lines_for_slate_minimum_line_independent_per_player():
    # Two players in the same market with different line situations -- each player's own
    # minimum is resolved independently, not cross-contaminated between players.
    offers = [
        {"market": "batter_hits", "player": "Player A", "point": 1.5,
         "over": {"fd": -150, "dk": -140}, "under": {"fd": 120}},
        {"market": "batter_hits", "player": "Player A", "point": 2.5,
         "over": {"mgm": 250}, "under": {}},
        {"market": "batter_hits", "player": "Player B", "point": 0.5,
         "over": {"fd": -200}, "under": {"fd": 150}},
    ]
    lines = O.market_lines_for_slate(offers)
    assert lines[(P.normalize_name("Player A"), "batter_hits")] == 1.5   # min of 1.5 and 2.5
    assert lines[(P.normalize_name("Player B"), "batter_hits")] == 0.5   # B unaffected
    print("✓ market_lines_for_slate resolves each player's own minimum line independently")


def test_market_lines_for_slate_preferred_book_overrides_minimum():
    # A user who selects FanDuel as their book should get FanDuel's line (1.5), not DK's
    # lower line (0.5) -- they're not betting at DraftKings.
    offers = [
        {"market": "batter_hits_runs_rbis", "player": "Ezequiel Tovar", "point": 1.5,
         "over": {"fanduel": -130}, "under": {"fanduel": 110}},
        {"market": "batter_hits_runs_rbis", "player": "Ezequiel Tovar", "point": 0.5,
         "over": {"draftkings": -115}, "under": {"draftkings": -115}},
    ]
    key = (P.normalize_name("Ezequiel Tovar"), "batter_hits_runs_rbis")
    assert O.market_lines_for_slate(offers, preferred_book="fanduel")[key] == 1.5
    assert O.market_lines_for_slate(offers, preferred_book="draftkings")[key] == 0.5
    print("✓ market_lines_for_slate uses the preferred book's specific line — a FanDuel user gets 1.5, a DK user gets 0.5, for the same player")


def test_market_lines_for_slate_falls_back_to_minimum_when_preferred_book_has_no_coverage():
    offers = [
        {"market": "batter_hits_runs_rbis", "player": "Rare Player", "point": 1.5,
         "over": {"fanduel": -130}, "under": {"fanduel": 110}},
    ]
    lines = O.market_lines_for_slate(offers, preferred_book="draftkings")
    assert lines[(P.normalize_name("Rare Player"), "batter_hits_runs_rbis")] == 1.5
    print("✓ market_lines_for_slate falls back to minimum-across-all-books when the preferred book has no coverage for a specific player")


def test_market_lines_for_slate_different_players_same_market_dont_collide():
    offers = [
        {"market": "pitcher_strikeouts", "player": "Pitcher One", "point": 8.5,
         "over": {"fd": -110}, "under": {"fd": -110}},
        {"market": "pitcher_strikeouts", "player": "Pitcher Two", "point": 4.5,
         "over": {"fd": -110}, "under": {"fd": -110}},
    ]
    lines = O.market_lines_for_slate(offers)
    assert lines[(P.normalize_name("Pitcher One"), "pitcher_strikeouts")] == 8.5
    assert lines[(P.normalize_name("Pitcher Two"), "pitcher_strikeouts")] == 4.5
    print("✓ market_lines_for_slate correctly keys by (player, market) together, so two real pitchers' own very different real strikeout lines don't collide")


def test_market_lines_for_slate_empty_offers():
    assert O.market_lines_for_slate([]) == {}


def test_market_lines_for_slate_skips_offers_with_no_real_book_quotes():
    offers = [{"market": "batter_hits", "player": "Ghost Offer", "point": 1.5, "over": {}, "under": {}}]
    assert O.market_lines_for_slate(offers) == {}
    print("✓ market_lines_for_slate skips an offer with zero real book quotes rather than treating it as real coverage")


def test_kelly_fraction():
    # p=0.60 at even money (+100): f* = (0.6*2 - 1)/(2-1) = 0.20
    assert abs(O.kelly_fraction(0.60, 100) - 0.20) < 1e-9
    assert O.kelly_fraction(0.50, 100) == 0.0      # fair odds -> no edge
    assert O.kelly_fraction(0.40, 100) == 0.0      # -EV -> clamped to 0


def test_kelly_stake_caps_and_fractions():
    # full f=0.20, quarter -> 0.05; 5% cap is not binding -> 0.05 * 1000 = 50
    assert O.kelly_stake(0.60, 100, 1000, fraction=0.25, cap_pct=0.05) == 50.0
    # tighter 2% cap binds -> 20
    assert O.kelly_stake(0.60, 100, 1000, fraction=0.25, cap_pct=0.02) == 20.0
    # -EV bet -> no stake
    assert O.kelly_stake(0.45, 100, 1000) == 0.0
    # small bankroll, half-Kelly -> small bet
    assert O.kelly_stake(0.58, 120, 50, fraction=0.5, cap_pct=0.05) > 0


def test_fetch_slate_props_threads_sport_through():
    # Regression test: fetch_slate_props used to call fetch_events()/fetch_event_props() with no
    # sport arg, silently defaulting to MLB no matter what the caller asked for. Monkeypatch both
    # to record what sport they actually received.
    calls = {"events_sport": None, "props_sport": None}

    def fake_fetch_events(api_key, sport=O.SPORT):
        calls["events_sport"] = sport
        return [{"id": "evt1", "commence_time": "2026-07-13T23:00:00Z"}]

    def fake_fetch_event_props(event_id, api_key, markets, regions="us", sport=O.SPORT):
        calls["props_sport"] = sport
        return {"bookmakers": []}, {"remaining": "42"}

    orig_events, orig_props = O.fetch_events, O.fetch_event_props
    O.fetch_events, O.fetch_event_props = fake_fetch_events, fake_fetch_event_props
    try:
        offers, info = O.fetch_slate_props("2026-07-13", "fake_key", ["player_points"],
                                           sport="basketball_wnba")
    finally:
        O.fetch_events, O.fetch_event_props = orig_events, orig_props

    assert calls["events_sport"] == "basketball_wnba"
    assert calls["props_sport"] == "basketball_wnba"
    assert info["events_fetched"] == 1
    print("✓ fetch_slate_props actually forwards sport to both fetch_events and fetch_event_props")


def test_fetch_slate_props_defaults_to_mlb_for_backward_compat():
    # Existing MLB call sites that don't pass sport= must keep working unchanged.
    import inspect
    sig = inspect.signature(O.fetch_slate_props)
    assert sig.parameters["sport"].default == "baseball_mlb"
    print("✓ fetch_slate_props still defaults to MLB when sport isn't specified")


def test_fetch_slate_props_threads_markets_into_parsing():
    # Regression test for a real bug found in a live WNBA test: fetch_slate_props correctly
    # passed `markets` into fetch_event_props (the actual API call), but never passed it into
    # parse_event_offers (the parsing step) — which has its OWN independent default of MLB's
    # SUPPORTED_MARKETS. Result: every real WNBA offer the API returned got silently filtered out
    # during parsing, because none of player_points/player_rebounds/etc. are in MLB's list.
    # compute_edges then saw an empty offers list -> matched=0 AND unmatched=0, indistinguishable
    # from "no props posted yet" without reading the source.
    wnba_event_json = {
        "bookmakers": [{
            "key": "fanduel",
            "markets": [{
                "key": "player_points",
                "outcomes": [
                    {"description": "A. Player", "name": "Over", "point": 15.5, "price": -110},
                    {"description": "A. Player", "name": "Under", "point": 15.5, "price": -110},
                ],
            }],
        }],
    }

    def fake_fetch_events(api_key, sport=O.SPORT):
        return [{"id": "evt1", "commence_time": "2026-07-14T23:00:00Z"}]

    def fake_fetch_event_props(event_id, api_key, markets, regions="us", sport=O.SPORT):
        return wnba_event_json, {"remaining": "100"}

    orig_events, orig_props = O.fetch_events, O.fetch_event_props
    O.fetch_events, O.fetch_event_props = fake_fetch_events, fake_fetch_event_props
    try:
        offers, info = O.fetch_slate_props("2026-07-14", "fake_key", ["player_points"],
                                           sport="basketball_wnba")
    finally:
        O.fetch_events, O.fetch_event_props = orig_events, orig_props

    assert len(offers) == 1, "the WNBA player_points offer must survive parsing, not be silently dropped"
    assert offers[0]["market"] == "player_points"
    assert offers[0]["player"] == "A. Player"
    print("✓ fetch_slate_props threads the caller's markets list into parse_event_offers too, "
          "not just fetch_event_props")


# ----------------------------------------------------------------- parse_game_spread
def test_parse_game_spread_averages_across_books():
    event = {
        "bookmakers": [
            {"key": "fanduel", "markets": [{"key": "spreads", "outcomes": [
                {"name": "Atlanta Dream", "point": -8.5, "price": -110},
                {"name": "Chicago Sky", "point": 8.5, "price": -110},
            ]}]},
            {"key": "draftkings", "markets": [{"key": "spreads", "outcomes": [
                {"name": "Atlanta Dream", "point": -9.5, "price": -105},
                {"name": "Chicago Sky", "point": 9.5, "price": -115},
            ]}]},
        ]
    }
    spreads = O.parse_game_spread(event)
    assert spreads["Atlanta Dream"] == -9.0    # avg(-8.5, -9.5)
    assert spreads["Chicago Sky"] == 9.0       # avg(8.5, 9.5)
    print("✓ parse_game_spread averages the point across every book that posted a spreads market")


def test_parse_game_spread_ignores_non_spread_markets():
    event = {"bookmakers": [{"key": "fanduel", "markets": [
        {"key": "h2h", "outcomes": [{"name": "Atlanta Dream", "price": -400}]},
        {"key": "totals", "outcomes": [{"name": "Over", "point": 165.5, "price": -110}]},
    ]}]}
    assert O.parse_game_spread(event) == {}
    print("✓ parse_game_spread ignores h2h/totals markets, only reads 'spreads'")


def test_parse_game_spread_empty_when_no_bookmakers():
    assert O.parse_game_spread({"bookmakers": []}) == {}


# ----------------------------------------------------------------- fetch_slate_spreads
def test_fetch_slate_spreads_only_requests_the_spreads_market():
    calls = {"markets_requested": None}

    def fake_fetch_events(api_key, sport=O.SPORT):
        return [{"id": "evt1", "commence_time": "2026-07-14T23:00:00Z"}]

    def fake_fetch_event_props(event_id, api_key, markets, regions="us", sport=O.SPORT):
        calls["markets_requested"] = markets
        return {"bookmakers": [{"key": "fd", "markets": [{"key": "spreads", "outcomes": [
            {"name": "Atlanta Dream", "point": -6.5}, {"name": "Chicago Sky", "point": 6.5},
        ]}]}]}, {"remaining": "500"}

    orig_events, orig_props = O.fetch_events, O.fetch_event_props
    O.fetch_events, O.fetch_event_props = fake_fetch_events, fake_fetch_event_props
    try:
        spreads, info = O.fetch_slate_spreads("2026-07-14", "fake_key", sport="basketball_wnba")
    finally:
        O.fetch_events, O.fetch_event_props = orig_events, orig_props

    assert calls["markets_requested"] == ["spreads"]   # not the 4-market player-prop list — cheap fetch
    assert spreads == {"Atlanta Dream": -6.5, "Chicago Sky": 6.5}
    assert info["events_fetched"] == 1 and info["remaining"] == "500"
    print("✓ fetch_slate_spreads requests only the 'spreads' market (cheap) and returns {team: spread}")


# ----------------------------------------------------------------- _eastern_date_str
def test_eastern_date_str_uses_real_us_eastern_calendar_date():
    # Regression guard for a real bug: fetch_slate_props/fetch_slate_spreads used to compare a
    # game's raw UTC commence_time date-prefix directly against the Eastern-context slate date
    # (from st.date_input) as plain strings. Any game starting from ~8pm ET onward rolls to the
    # NEXT calendar day in UTC, so that string comparison silently excluded it from "today's"
    # slate entirely -- reported live as "Edge Board does not contain all games" (missing night
    # games, especially West Coast).
    assert O._eastern_date_str("2026-07-29T01:40:00Z") == "2026-07-28"   # 9:40 PM ET on the 28th
    assert O._eastern_date_str("2026-07-28T17:40:00Z") == "2026-07-28"   # 1:40 PM ET -- same day either way
    assert O._eastern_date_str(None) is None
    assert O._eastern_date_str("not a real timestamp") is None
    print("✓ _eastern_date_str resolves a game's real US/Eastern calendar date, not the UTC "
         "date its commence_time happens to be stamped in")


def test_fetch_slate_props_includes_late_night_games_that_roll_to_next_utc_day():
    # The exact live scenario this bug caused: a 9:40 PM ET game (common for West Coast teams)
    # has a UTC commence_time on the FOLLOWING calendar date. The old raw-string comparison
    # dropped it from "today"; the fix correctly keeps it.
    def fake_fetch_events(api_key, sport=O.SPORT):
        return [
            {"id": "evt_early", "commence_time": "2026-07-28T17:40:00Z"},   # 1:40 PM ET same day
            {"id": "evt_late", "commence_time": "2026-07-29T01:40:00Z"},    # 9:40 PM ET same Eastern day
            {"id": "evt_other_day", "commence_time": "2026-07-29T17:40:00Z"},  # genuinely the next day
        ]

    def fake_fetch_event_props(event_id, api_key, markets, regions="us", sport=O.SPORT):
        return {"bookmakers": []}, {"remaining": "999"}

    orig_events, orig_props = O.fetch_events, O.fetch_event_props
    O.fetch_events, O.fetch_event_props = fake_fetch_events, fake_fetch_event_props
    try:
        offers, info = O.fetch_slate_props("2026-07-28", "fake_key", ["batter_hits"])
    finally:
        O.fetch_events, O.fetch_event_props = orig_events, orig_props

    assert info["events_total"] == 2   # early + late, NOT evt_other_day
    assert info["events_fetched"] == 2
    print("✓ fetch_slate_props includes a 9:40 PM ET game (next-day in UTC) in the correct "
         "Eastern slate date, and still correctly excludes a genuinely different day's game")


def test_fetch_slate_props_flags_events_with_no_returned_offers():
    # The real, live-reported gap this closes: "Games priced: N" counts every event
    # successfully QUERIED, regardless of whether it returned any usable data -- so a game that
    # already started (books pulled pre-game props) still counts toward N, but produces zero
    # edge rows and silently disappears from the "Filter by game" list built from those rows.
    # That looked like a missing-game bug from the UI alone. no_offer_events makes the
    # already-queried-but-empty case directly visible instead of a guess.
    def fake_fetch_events(api_key, sport=O.SPORT):
        return [
            {"id": "evt_has_odds", "commence_time": "2026-07-28T22:40:00Z",
             "away_team": "Boston Red Sox", "home_team": "New York Yankees"},
            {"id": "evt_already_started", "commence_time": "2026-07-28T17:40:00Z",
             "away_team": "Cleveland Guardians", "home_team": "Cincinnati Reds"},
        ]

    def fake_fetch_event_props(event_id, api_key, markets, regions="us", sport=O.SPORT):
        if event_id == "evt_has_odds":
            return {"bookmakers": [{"key": "draftkings", "markets": [{"key": "batter_hits", "outcomes": [
                {"description": "Aaron Judge", "point": 0.5, "name": "Over", "price": -300},
                {"description": "Aaron Judge", "point": 0.5, "name": "Under", "price": 220},
            ]}]}]}, {"remaining": "999"}
        return {"bookmakers": []}, {"remaining": "999"}   # already started -- props pulled

    orig_events, orig_props = O.fetch_events, O.fetch_event_props
    O.fetch_events, O.fetch_event_props = fake_fetch_events, fake_fetch_event_props
    try:
        offers, info = O.fetch_slate_props("2026-07-28", "fake_key", ["batter_hits"])
    finally:
        O.fetch_events, O.fetch_event_props = orig_events, orig_props

    assert info["events_fetched"] == 2   # both were successfully queried
    assert len(offers) == 1              # but only one actually has usable offers
    assert info["no_offer_events"] == ["Cleveland Guardians @ Cincinnati Reds"]
    print("✓ fetch_slate_props flags exactly the queried-but-empty event, distinguishing it from "
         "one that genuinely has live offers, even though both count toward events_fetched")


def test_fetch_slate_props_exposes_raw_todays_events():
    # The direct, verifiable answer to "why isn't game X showing up at all" -- a real list of
    # exactly which events the provider's own feed returned for today, viewable in the UI
    # instead of inferred from downstream symptoms (a doubleheader leg the provider's own event
    # feed never listed looks identical, from every other diagnostic, to one that was queried and
    # came back empty -- this is the one place that actually tells them apart).
    def fake_fetch_events(api_key, sport=O.SPORT):
        return [{"id": "evt_1", "commence_time": "2026-07-28T21:10:00Z",
                 "away_team": "Cleveland Guardians", "home_team": "Cincinnati Reds"}]

    def fake_fetch_event_props(event_id, api_key, markets, regions="us", sport=O.SPORT):
        return {"bookmakers": []}, {"remaining": "999"}

    orig_events, orig_props = O.fetch_events, O.fetch_event_props
    O.fetch_events, O.fetch_event_props = fake_fetch_events, fake_fetch_event_props
    try:
        offers, info = O.fetch_slate_props("2026-07-28", "fake_key", ["batter_hits"])
    finally:
        O.fetch_events, O.fetch_event_props = orig_events, orig_props

    assert info["todays_events"] == [{"id": "evt_1", "away": "Cleveland Guardians",
                                      "home": "Cincinnati Reds", "commence_time": "2026-07-28T21:10:00Z"}]
    print("✓ fetch_slate_props exposes the raw list of events the provider actually returned for "
         "today, viewable directly instead of inferred")


# ----------------------------------------------------------------- real_entry_price
def test_real_entry_price_uses_preferred_book_when_available():
    import projections as P
    offers = [
        {"player": "Wade Meckler", "market": "batter_hits", "point": 0.5,
         "over": {"draftkings": -280, "fanduel": -260}, "under": {"draftkings": 220, "fanduel": 210}},
    ]
    result = O.real_entry_price(offers, "Wade Meckler", "batter_hits", "Over",
                                preferred_book="draftkings", projections_module=P)
    assert result == (-280.0, 0.5, "draftkings")
    print("✓ real_entry_price uses the exact preferred book's price when that book posted the market")


def test_real_entry_price_falls_back_to_best_price_when_preferred_book_missing():
    import projections as P
    offers = [
        {"player": "Wade Meckler", "market": "batter_hits", "point": 0.5,
         "over": {"draftkings": -280, "fanduel": -260}, "under": {"draftkings": 220, "fanduel": 210}},
    ]
    result = O.real_entry_price(offers, "Wade Meckler", "batter_hits", "Over",
                                preferred_book="betmgm", projections_module=P)
    assert result == (-260.0, 0.5, "fanduel")   # -260 pays more than -280 -- the real best price
    print("✓ real_entry_price falls back to the single best (highest-payout) price across books "
         "when the preferred book didn't post this market")


def test_real_entry_price_handles_under_and_yes_sides():
    import projections as P
    offers = [{"player": "X", "market": "batter_hits", "point": 0.5,
              "over": {"draftkings": -280}, "under": {"draftkings": 220}}]
    under = O.real_entry_price(offers, "X", "batter_hits", "Under", projections_module=P)
    assert under == (220.0, 0.5, "draftkings")
    yes = O.real_entry_price(offers, "X", "batter_hits", "Yes", projections_module=P)
    assert yes == (-280.0, 0.5, "draftkings")   # "Yes" treated as the Over side
    print("✓ real_entry_price correctly handles Under and treats Yes as the Over side")


def test_real_entry_price_none_when_no_real_offer_exists():
    import projections as P
    offers = [{"player": "Someone Else", "market": "batter_hits", "point": 0.5,
              "over": {"draftkings": -200}, "under": {"draftkings": 165}}]
    # Wrong player
    assert O.real_entry_price(offers, "Wade Meckler", "batter_hits", "Over", projections_module=P) is None
    # Wrong market
    assert O.real_entry_price(offers, "Someone Else", "batter_hr", "Over", projections_module=P) is None
    # Empty offers entirely
    assert O.real_entry_price([], "Someone Else", "batter_hits", "Over", projections_module=P) is None
    print("✓ real_entry_price returns None (never a guess) when no real offer matches at all")


# ----------------------------------------------------------------- moneyline (team-level) price capture
def test_parse_event_moneyline_keeps_per_book_prices():
    # A real, deliberate difference from parse_game_spread just above it: that one AVERAGES
    # across books into a single display number; a real price lookup needs each book's own
    # actual price, not an average nobody can bet at.
    event = {"bookmakers": [
        {"key": "draftkings", "markets": [{"key": "h2h", "outcomes": [
            {"name": "New York Yankees", "price": -150}, {"name": "Boston Red Sox", "price": 130}]}]},
        {"key": "fanduel", "markets": [{"key": "h2h", "outcomes": [
            {"name": "New York Yankees", "price": -145}, {"name": "Boston Red Sox", "price": 125}]}]},
    ]}
    parsed = O.parse_event_moneyline(event)
    assert parsed == {"New York Yankees": {"draftkings": -150, "fanduel": -145},
                      "Boston Red Sox": {"draftkings": 130, "fanduel": 125}}
    print("✓ parse_event_moneyline keeps each book's own real price, not an averaged number")


def test_parse_event_moneyline_ignores_non_h2h_markets():
    event = {"bookmakers": [{"key": "draftkings", "markets": [
        {"key": "spreads", "outcomes": [{"name": "New York Yankees", "point": -1.5, "price": -110}]},
        {"key": "h2h", "outcomes": [{"name": "New York Yankees", "price": -150}]},
    ]}]}
    parsed = O.parse_event_moneyline(event)
    assert parsed == {"New York Yankees": {"draftkings": -150}}   # only the h2h outcome counted
    print("✓ parse_event_moneyline only reads the h2h market, ignoring spreads/other markets "
         "in the same response")


def test_real_moneyline_price_uses_preferred_book_when_available():
    moneylines = {"New York Yankees": {"draftkings": -150, "fanduel": -145}}
    result = O.real_moneyline_price(moneylines, "New York Yankees", preferred_book="draftkings")
    assert result == (-150.0, "draftkings")
    print("✓ real_moneyline_price uses the exact preferred book's price when available")


def test_real_moneyline_price_falls_back_to_best_price():
    moneylines = {"New York Yankees": {"draftkings": -150, "fanduel": -145}}
    result = O.real_moneyline_price(moneylines, "New York Yankees", preferred_book="betmgm")
    assert result == (-145.0, "fanduel")   # -145 pays more than -150 -- the real best price
    print("✓ real_moneyline_price falls back to the best available price across books")


def test_real_moneyline_price_case_and_whitespace_insensitive_team_match():
    moneylines = {"New York Yankees": {"draftkings": -150}}
    assert O.real_moneyline_price(moneylines, "new york yankees") == (-150.0, "draftkings")
    assert O.real_moneyline_price(moneylines, "  New York Yankees  ") == (-150.0, "draftkings")
    print("✓ real_moneyline_price matches team names regardless of case or surrounding whitespace")


def test_real_moneyline_price_none_when_team_not_found():
    moneylines = {"New York Yankees": {"draftkings": -150}}
    assert O.real_moneyline_price(moneylines, "Boston Red Sox") is None
    assert O.real_moneyline_price({}, "New York Yankees") is None
    assert O.real_moneyline_price(moneylines, "") is None
    print("✓ real_moneyline_price returns None (never a guess) when the team has no real offer")


def test_real_moneyline_price_survives_malformed_price_values():
    # Regression guard for a real, confirmed production crash: a live Game Watch deploy hit a
    # TypeError inside this exact code path, past where the original, unguarded version had no
    # protection at all. A malformed price value (a non-numeric string, a None that slipped
    # through, a nested structure instead of a plain number) must degrade to None, never crash
    # the page a pick is being logged from.
    moneylines = {"New York Yankees": {"draftkings": "not-a-real-price"}}
    assert O.real_moneyline_price(moneylines, "New York Yankees") is None
    print("✓ real_moneyline_price survives a malformed (non-numeric) price value instead of "
         "raising a TypeError")


def test_real_moneyline_price_survives_non_dict_price_entry():
    # A shape surprise one level up: the per-team value isn't even a dict of book->price at all.
    moneylines = {"New York Yankees": "not-a-dict-at-all", "Boston Red Sox": {"draftkings": 130}}
    # The malformed Yankees entry is skipped; the still-valid Red Sox entry keeps working.
    assert O.real_moneyline_price(moneylines, "New York Yankees") is None
    assert O.real_moneyline_price(moneylines, "Boston Red Sox") == (130.0, "draftkings")
    print("✓ real_moneyline_price skips a non-dict per-team entry instead of crashing, and "
         "still correctly serves every other real entry in the same dict")


def test_parse_event_moneyline_skips_a_malformed_outcome():
    # Same real production risk, one layer earlier: a malformed individual outcome in a live
    # response must be skipped (with the real raw entry logged for diagnosis), not crash the
    # whole parse and lose every other real price in the same event.
    event = {"bookmakers": [{"key": "draftkings", "markets": [{"key": "h2h", "outcomes": [
        {"name": "New York Yankees", "price": -150},
        {"name": "Boston Red Sox", "price": "garbage-value"},   # can't convert to float
    ]}]}]}
    parsed = O.parse_event_moneyline(event)
    assert parsed == {"New York Yankees": {"draftkings": -150.0}}   # bad entry skipped, good one kept
    print("✓ parse_event_moneyline skips a malformed individual outcome, keeping every other "
         "real price from the same event")


def test_compute_edges_tracks_real_unmatched_names_not_just_a_count():
    # Regression guard for the actual fix behind a long-open item ("player name mismatches"): a
    # bare unmatched COUNT gives no way to know which real player/market failed to match, so a
    # genuine book-vs-model spelling mismatch stayed invisible and unfixable. This confirms the
    # real name (not a placeholder) is recorded for each unmatched offer.
    import projections as P
    index = {}   # empty -- every offer below will fail to match, by construction
    offers = [
        {"player": "José Ramírez", "market": "batter_home_runs", "point": 0.5,
        "over": {"draftkings": 350}, "under": {"draftkings": -450}},
        {"player": "Some Totally Different Guy", "market": "batter_hits", "point": 1.5,
        "over": {"draftkings": 200}, "under": {"draftkings": -250}},
    ]
    rows, stats = O.compute_edges(index, offers, projections_module=P)
    assert rows == []
    assert stats["unmatched"] == 2
    # A REAL, CONFIRMED FIX added a "reason" field to each entry (see compute_edges' own
    # docstring) -- "unknown" here because this test doesn't pass known_names, the same real,
    # backward-compatible default every existing caller gets until it opts in.
    assert stats["unmatched_names"] == [
        {"player": "José Ramírez", "market": "batter_home_runs", "reason": "unknown"},
        {"player": "Some Totally Different Guy", "market": "batter_hits", "reason": "unknown"},
    ]
    print("✓ compute_edges tracks the real unmatched player names and markets, not just a count")


def test_compute_edges_dedupes_unmatched_names_across_alternate_lines():
    # The same player/market can appear multiple times in offers when a book posts alternate
    # lines -- the diagnostic list should show each real mismatch once, not once per line.
    import projections as P
    index = {}
    offers = [
        {"player": "José Ramírez", "market": "batter_home_runs", "point": 0.5,
        "over": {"draftkings": 350}, "under": {"draftkings": -450}},
        {"player": "José Ramírez", "market": "batter_home_runs", "point": 1.5,   # same player/market, alt line
        "over": {"draftkings": 800}, "under": {"draftkings": -1200}},
    ]
    rows, stats = O.compute_edges(index, offers, projections_module=P)
    assert stats["unmatched"] == 2   # the real count still reflects both offers
    assert stats["unmatched_names"] == [{"player": "José Ramírez", "market": "batter_home_runs", "reason": "unknown"}]
    print("✓ compute_edges dedupes the unmatched-names diagnostic list by (player, market), "
         "even though the raw unmatched count still reflects every offer")


def test_compute_edges_categorizes_a_real_on_roster_no_data_case():
    # ADDED DIRECTLY ON REQUEST, a real, confirmed fix for a real, reported case: Kevin Gausman
    # (just traded, hasn't debuted for his new team), Sean Murphy (just off a 60-day IL), and
    # Ronel Blanco (just back from Tommy John surgery) all showed up as "unmatched" alongside
    # genuine name mismatches -- but each was individually confirmed to be a real player
    # genuinely on tonight's roster, just without enough real data for the model to honestly
    # price. Confirms compute_edges correctly tags this case "on_roster_no_data", not the same
    # bucket as a real, fixable name-spelling mismatch.
    import projections as P
    index = {}
    known_names = {P.normalize_name("Kevin Gausman")}
    offers = [{"player": "Kevin Gausman", "market": "pitcher_outs", "point": 15.5,
              "over": {"draftkings": -110}, "under": {"draftkings": -110}}]
    rows, stats = O.compute_edges(index, offers, projections_module=P, known_names=known_names)
    assert stats["unmatched_names"] == [
        {"player": "Kevin Gausman", "market": "pitcher_outs", "reason": "on_roster_no_data"}]
    print("✓ compute_edges correctly tags a real, known roster player with no index entry as 'on_roster_no_data', not a name mismatch")


def test_compute_edges_categorizes_a_real_genuine_name_mismatch():
    import projections as P
    index = {}
    known_names = {P.normalize_name("Kevin Gausman")}   # a genuinely different real player
    offers = [{"player": "Some Totally Different Guy", "market": "batter_hits", "point": 1.5,
              "over": {"draftkings": 200}, "under": {"draftkings": -250}}]
    rows, stats = O.compute_edges(index, offers, projections_module=P, known_names=known_names)
    assert stats["unmatched_names"] == [
        {"player": "Some Totally Different Guy", "market": "batter_hits", "reason": "name_mismatch"}]
    print("✓ compute_edges correctly tags a real name genuinely absent from the roster as 'name_mismatch', the one real category actually worth chasing down")


def test_compute_edges_reason_defaults_to_unknown_without_known_names():
    # Confirms every real, existing caller that doesn't pass known_names (e.g. any sport that
    # hasn't wired this in yet) gets the exact same real, undifferentiated behavior as before
    # this fix -- not a crash, not a silently wrong default judgment call.
    import projections as P
    index = {}
    offers = [{"player": "Kevin Gausman", "market": "pitcher_outs", "point": 15.5,
              "over": {"draftkings": -110}, "under": {"draftkings": -110}}]
    rows, stats = O.compute_edges(index, offers, projections_module=P)
    assert stats["unmatched_names"][0]["reason"] == "unknown"
    print("✓ compute_edges defaults every unmatched reason to 'unknown' when known_names isn't passed, fully backward compatible")


def test_known_roster_names_and_compute_edges_work_together_end_to_end():
    # A REAL, END-TO-END TEST, not just each piece checked in isolation: simulates the actual
    # real scenario this whole fix was built for -- a real player (Kevin Gausman) genuinely on
    # tonight's roster (his name is in rows/meta) but with no real index entry (build_projection_
    # index skipped him for real, honest reasons), alongside a genuinely different name that
    # never appears on the roster at all.
    import projections as P
    rows = [{"Hitter": "Kevin Gausman"}]
    known_names = P.known_roster_names(rows, [])
    index = {}   # empty -- Gausman genuinely has no real index entry, by construction
    offers = [
        {"player": "Kevin Gausman", "market": "pitcher_outs", "point": 15.5,
        "over": {"draftkings": -110}, "under": {"draftkings": -110}},
        {"player": "Some Totally Different Guy", "market": "batter_hits", "point": 1.5,
        "over": {"draftkings": 200}, "under": {"draftkings": -250}},
    ]
    rows_out, stats = O.compute_edges(index, offers, projections_module=P, known_names=known_names)
    by_player = {u["player"]: u["reason"] for u in stats["unmatched_names"]}
    assert by_player["Kevin Gausman"] == "on_roster_no_data"
    assert by_player["Some Totally Different Guy"] == "name_mismatch"
    print("✓ known_roster_names and compute_edges work together end to end, correctly separating a real on-roster player from a real genuine mismatch")


def test_compute_edges_categorizes_a_real_active_player_not_playing_tonight():
    # A REAL, CONFIRMED SECOND FIX, layered on the first: a live Edge Board run showed real,
    # established, active players (Kevin Gausman -- just traded, no Cubs debut yet; Alí Sánchez
    # -- active Yankees catcher; Edgar Quero -- active White Sox catcher with real 2026 stats;
    # Zach Thornton -- active Mets rookie) STILL landing in the same "genuinely doesn't appear
    # anywhere" bucket as a true spelling bug, even though none of them had a real name problem
    # -- they simply weren't part of tonight's specific slate. Confirms compute_edges correctly
    # tags this real case "not_playing_tonight" when all_active_names is passed, instead of the
    # misleading "name_mismatch".
    import projections as P
    index = {}
    known_names = set()   # empty -- none of these players is on TONIGHT's specific slate
    all_active_names = {"Kevin Gausman", "Alí Sánchez", "Edgar Quero", "Zach Thornton"}
    offers = [{"player": "Kevin Gausman", "market": "pitcher_outs", "point": 15.5,
              "over": {"draftkings": -110}, "under": {"draftkings": -110}}]
    rows, stats = O.compute_edges(index, offers, projections_module=P,
                                  known_names=known_names, all_active_names=all_active_names)
    assert stats["unmatched_names"] == [
        {"player": "Kevin Gausman", "market": "pitcher_outs", "reason": "not_playing_tonight"}]
    print("✓ compute_edges correctly tags a real, active player not on tonight's slate as 'not_playing_tonight', not a misleading name mismatch")


def test_compute_edges_still_categorizes_a_real_genuine_mismatch_with_all_active_names_passed():
    # The real, actually-worth-fixing category must still work correctly once a third real
    # category exists -- a genuinely unknown name must not accidentally fall into
    # "not_playing_tonight" just because all_active_names was passed.
    import projections as P
    index = {}
    known_names = set()
    all_active_names = {"Kevin Gausman"}   # a real, but genuinely different, active player
    offers = [{"player": "Some Totally Different Guy", "market": "batter_hits", "point": 1.5,
              "over": {"draftkings": 200}, "under": {"draftkings": -250}}]
    rows, stats = O.compute_edges(index, offers, projections_module=P,
                                  known_names=known_names, all_active_names=all_active_names)
    assert stats["unmatched_names"] == [
        {"player": "Some Totally Different Guy", "market": "batter_hits", "reason": "name_mismatch"}]
    print("✓ compute_edges still correctly tags a real, genuine mismatch as 'name_mismatch' even when all_active_names is also passed")


def test_compute_edges_normalizes_all_active_names_for_a_real_accented_match():
    # A real, direct check that normalization is genuinely applied to all_active_names too, not
    # just the book's own offer -- the real Alí Sánchez case depends on this: MLB's own API
    # returns the real accented spelling, a book might post either spelling, and both must
    # normalize to the same real string for this real match to work at all.
    import projections as P
    index = {}
    known_names = set()
    all_active_names = {"Alí Sánchez"}   # the real, accented spelling from MLB's own API
    offers = [{"player": "Ali Sanchez", "market": "batter_hits", "point": 0.5,   # book's own unaccented spelling
              "over": {"draftkings": -110}, "under": {"draftkings": -110}}]
    rows, stats = O.compute_edges(index, offers, projections_module=P,
                                  known_names=known_names, all_active_names=all_active_names)
    assert stats["unmatched_names"][0]["reason"] == "not_playing_tonight"
    print("✓ compute_edges correctly normalizes all_active_names too, so a real accent difference between the book and MLB's own API doesn't cause a false name_mismatch")


# ----------------------------------------------------------------- real_market_prob
def test_real_market_prob_over_and_under_sum_to_one():
    import projections as P
    offers = [{"player": "Wade Meckler", "market": "batter_total_bases", "point": 1.5,
              "over": {"draftkings": -140, "fanduel": -135},
              "under": {"draftkings": 115, "fanduel": 110}}]
    over_p = O.real_market_prob(offers, "Wade Meckler", "batter_total_bases", "Over",
                                preferred_book="draftkings", projections_module=P)
    under_p = O.real_market_prob(offers, "Wade Meckler", "batter_total_bases", "Under",
                                 preferred_book="draftkings", projections_module=P)
    assert abs(over_p + under_p - 1.0) < 1e-9
    assert 0.5 < over_p < 0.6   # a real, sanity-checkable range for -140/+115
    print("✓ real_market_prob's Over and Under probabilities sum to exactly 1.0, a proper devig "
         "of the same book's own two-sided prices")


def test_real_market_prob_uses_one_books_own_both_sides_not_mixed_books():
    # Regression guard for a real, deliberate design choice: mixing one book's Over price with
    # a DIFFERENT book's Under price would blend two independent vig structures into a number
    # that isn't really either book's true market view. Must return None, never guess.
    import projections as P
    offers = [{"player": "X", "market": "batter_total_bases", "point": 1.5,
              "over": {"draftkings": -140}, "under": {"fanduel": 110}}]
    result = O.real_market_prob(offers, "X", "batter_total_bases", "Over", projections_module=P)
    assert result is None
    print("✓ real_market_prob returns None rather than devigging across two different books' "
         "own independent prices")


def test_real_market_prob_prefers_preferred_book_when_it_has_both_sides():
    import projections as P
    offers = [{"player": "X", "market": "batter_total_bases", "point": 1.5,
              "over": {"draftkings": -140, "fanduel": -200},
              "under": {"draftkings": 115, "fanduel": 165}}]
    dk_prob = O.real_market_prob(offers, "X", "batter_total_bases", "Over",
                                 preferred_book="draftkings", projections_module=P)
    fd_prob = O.real_market_prob(offers, "X", "batter_total_bases", "Over",
                                 preferred_book="fanduel", projections_module=P)
    assert dk_prob != fd_prob   # genuinely different books' own vig -- confirms the right one was used
    print("✓ real_market_prob uses the preferred book's own two-sided prices specifically, not "
         "an arbitrary book, when the preferred book posted both sides")


def test_real_market_prob_none_when_no_real_match_at_all():
    import projections as P
    assert O.real_market_prob([], "X", "batter_total_bases", "Over", projections_module=P) is None
    offers = [{"player": "Someone Else", "market": "batter_total_bases", "point": 1.5,
              "over": {"draftkings": -140}, "under": {"draftkings": 115}}]
    assert O.real_market_prob(offers, "X", "batter_total_bases", "Over", projections_module=P) is None
    print("✓ real_market_prob returns None (never a guess) with no real match at all")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
