"""
test_backfill_closing_lines.py — offline tests for backfill_closing_lines.py.

No network, no real API key, no database. resolve_events_for_date is the only function that
actually calls the network (odds_api.fetch_historical_events + mlb_engine.get_schedule) — it's
exercised indirectly here by feeding its OUTPUT SHAPE straight into the pure functions downstream
(group_missing_bets_by_event, estimate_cost, backfill_event), which is where the real cost-control
and matching logic lives and is fully testable without hitting the real provider.
"""

from unittest.mock import patch

import backfill_closing_lines as BF
import odds_api as O


def test_game_label_matches_real_logged_format():
    # Regression guard: a real user's exported bet log showed every single `game` field with
    # a " (Game N)" suffix -- even gameNumber=1, non-doubleheader games -- matching
    # mlb_engine.py's own build_slate label construction exactly. A conditional
    # ("only add the suffix when gameNumber > 1") would silently fail to match every non-DH game.
    assert BF.game_label({"away_name": "Atlanta Braves", "home_name": "New York Mets",
                          "gameNumber": 1}) == "Atlanta Braves @ New York Mets (Game 1)"
    assert BF.game_label({"away_name": "Baltimore Orioles", "home_name": "Detroit Tigers",
                          "gameNumber": 2}) == "Baltimore Orioles @ Detroit Tigers (Game 2)"
    print("✓ game_label always includes the (Game N) suffix, matching real logged bet.game values")


def test_group_missing_bets_by_event_minimizes_markets_per_event():
    # This is the whole cost-control mechanism: historical event-odds costs 10 credits PER
    # MARKET requested, per event. An event should only ever carry the union of markets its OWN
    # missing bets need, never the sport's full 17-market list.
    missing_bets = [
        {"id": 1, "game": "Atlanta Braves @ New York Mets (Game 1)", "market": "Batter Total Hits"},
        {"id": 2, "game": "Atlanta Braves @ New York Mets (Game 1)", "market": "Batter HR"},
        {"id": 3, "game": "Baltimore Orioles @ Detroit Tigers (Game 1)", "market": "Batter HR"},
        {"id": 4, "game": "Unresolvable Team @ Nowhere (Game 1)", "market": "Batter HR"},
    ]
    resolved = {
        "Atlanta Braves @ New York Mets (Game 1)": {
            "event_id": "evt_abc", "commence_iso": "2026-07-27T23:10:00Z",
            "away_name": "Atlanta Braves", "home_name": "New York Mets"},
        "Baltimore Orioles @ Detroit Tigers (Game 1)": {
            "event_id": "evt_xyz", "commence_iso": "2026-07-27T23:05:00Z",
            "away_name": "Baltimore Orioles", "home_name": "Detroit Tigers"},
    }
    groups, unresolved = BF.group_missing_bets_by_event(missing_bets, resolved)

    assert groups["evt_abc"]["markets"] == {"batter_hits", "batter_home_runs"}
    assert len(groups["evt_abc"]["bets"]) == 2
    assert groups["evt_xyz"]["markets"] == {"batter_home_runs"}
    assert len(groups["evt_xyz"]["bets"]) == 1
    assert len(unresolved) == 1 and unresolved[0]["id"] == 4   # unmatched game -> reported, not dropped
    print("✓ each event only carries the union of markets its own missing bets need, and an "
         "unmatched game's bets land in 'unresolved', not silently discarded")


def test_estimate_cost_matches_documented_formula():
    # 10 credits x markets x regions, per event -- the exact rate confirmed against the
    # provider's own historical-odds-data docs, not a guess.
    groups = {
        "evt_abc": {"markets": {"batter_hits", "batter_home_runs"}, "bets": [], "event": {}},
        "evt_xyz": {"markets": {"batter_home_runs"}, "bets": [], "event": {}},
    }
    assert BF.estimate_cost(groups, "us") == 10 * 2 * 1 + 10 * 1 * 1   # 30
    assert BF.estimate_cost(groups, "us,uk") == 10 * 2 * 2 + 10 * 1 * 2   # 60
    print("✓ estimate_cost matches the documented 10 x markets x regions rate exactly")


def test_backfill_event_matches_real_offers_to_bets():
    # End-to-end (odds_api call mocked, everything downstream real): a realistic historical
    # response, parsed by the real parse_event_offers, matched by the real clv_capture engine
    # (the same one the live capture path uses) -- confirms the whole chain wires together, not
    # just each piece in isolation.
    fake_response = {
        "timestamp": "2026-07-27T23:09:00Z",
        "data": {
            "id": "evt_abc",
            "bookmakers": [{"key": "draftkings", "markets": [
                {"key": "batter_hits", "outcomes": [
                    {"description": "Ozzie Albies", "point": 0.5, "name": "Over", "price": -199},
                    {"description": "Ozzie Albies", "point": 0.5, "name": "Under", "price": 160}]},
                {"key": "batter_home_runs", "outcomes": [
                    {"description": "Ben Rice", "point": 0.5, "name": "Over", "price": 240},
                    {"description": "Ben Rice", "point": 0.5, "name": "Under", "price": -320}]},
            ]}],
        },
    }
    group = {
        "event": {"event_id": "evt_abc", "commence_iso": "2026-07-27T23:10:00Z",
                  "away_name": "Atlanta Braves", "home_name": "New York Mets"},
        "bets": [
            {"id": 1, "game": "Atlanta Braves @ New York Mets (Game 1)", "market": "Batter Total Hits",
             "book": "draftkings", "side": "Over", "line": 0.5, "player": "Ozzie Albies"},
            {"id": 2, "game": "Atlanta Braves @ New York Mets (Game 1)", "market": "Batter HR",
             "book": "draftkings", "side": "Over", "line": 0.5, "player": "Ben Rice"},
            {"id": 3, "game": "Atlanta Braves @ New York Mets (Game 1)", "market": "Batter HR",
             "book": "fanduel", "side": "Over", "line": 0.5, "player": "Ben Rice"},   # wrong book
        ],
        "markets": {"batter_hits", "batter_home_runs"},
    }
    with patch.object(O, "fetch_historical_event_props", return_value=(fake_response, {"used": "120"})):
        report = BF.backfill_event("evt_abc", group, "FAKE_KEY", "us")

    assert report["updates"] == {1: -199, 2: 240}
    assert report["no_match"] == [3]         # fanduel bet correctly NOT matched to a draftkings price
    assert report["snapshot_ts"] == "2026-07-27T23:09:00Z"
    print("✓ backfill_event correctly matches each bet to its own book's price and leaves a "
         "different-book bet unmatched (apples-to-apples, same rule as the live capture path)")


def test_unwrap_events_response_handles_both_documented_shapes():
    # Regression guard for the actual bug this session hit: a live run showed "Success" in
    # GitHub Actions but changed zero rows. The most likely cause traced back to this exact
    # unwrap step -- fetch_historical_events' wrapper shape was the least-verified assumption in
    # the whole module (flagged as such in its own docstring), and if the real response turned
    # out to be a bare list (like the LIVE /events endpoint already is, see fetch_events above)
    # rather than {"data": [...]}, the old code's `data.get("data") if isinstance(data, dict)
    # else data` would have handled a bare list fine -- but ANY other shape silently became [],
    # with no way to tell why from a run's log. This is now a pure, independently testable
    # function instead of dead-ended inline logic, specifically so both shapes (and the failure
    # case) are locked in by a test, not just re-assumed correct next time this is touched.
    assert BF._unwrap_events_response([{"id": "evt_1"}]) == [{"id": "evt_1"}]                # bare list
    assert BF._unwrap_events_response({"data": [{"id": "evt_1"}]}) == [{"id": "evt_1"}]      # wrapped
    assert BF._unwrap_events_response({"data": "not a list"}) == []          # malformed wrapper
    assert BF._unwrap_events_response({"no_data_key": []}) == []             # different key name
    assert BF._unwrap_events_response(None) == []
    assert BF._unwrap_events_response("unexpected string") == []
    print("✓ _unwrap_events_response handles both documented response shapes and fails soft "
         "(empty list, not a crash) on anything else")


def test_resolve_events_for_date_warns_when_schedule_has_games_but_events_come_back_empty():
    # The exact failure signature from this session's real run: MLB's own schedule (a separate,
    # already-proven data source) says games existed, but the historical events call came back
    # empty -- this MUST print a diagnostic with the raw response shape, not just silently
    # report "0 game(s) resolved" with no further clue in the log.
    fake_schedule = [
        {"away_name": "Baltimore Orioles", "home_name": "Detroit Tigers", "gameNumber": 1,
         "game_date": "2026-07-27T23:05:00Z"},
    ]
    with patch.object(BF.E, "get_schedule", return_value=fake_schedule), \
        patch.object(O, "fetch_historical_events", return_value=({"unexpected_key": []}, {})), \
        patch("builtins.print") as mock_print:
        matched, unmatched, headers = BF.resolve_events_for_date("2026-07-27", "FAKE_KEY")

    assert matched == {}
    assert "Baltimore Orioles @ Detroit Tigers (Game 1)" in unmatched
    printed = " ".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
    assert "0 events returned" in printed and "1 real game" in printed
    print("✓ resolve_events_for_date prints a real diagnostic (not a silent empty result) when "
         "the schedule proves games existed but the historical events call returned none")


def test_backfill_event_handles_unexpected_response_shape_without_crashing():
    # Regression guard: this module's own docstring is explicit that the historical response
    # shape is UNVERIFIED against a live call from this sandbox. If the real API's wrapper key
    # ever turns out to be named something other than "data", this must warn loudly and return
    # zero matches, not raise and abort the whole run.
    bad_response = {"bookmakers": []}   # already-unwrapped, or a different key name than expected
    group = {
        "event": {"event_id": "evt_zzz", "commence_iso": "2026-07-27T23:10:00Z",
                  "away_name": "A", "home_name": "B"},
        "bets": [{"id": 9, "game": "A @ B (Game 1)", "market": "Batter HR",
                 "book": "draftkings", "side": "Over", "line": 0.5, "player": "X"}],
        "markets": {"batter_home_runs"},
    }
    with patch.object(O, "fetch_historical_event_props", return_value=(bad_response, {})):
        report = BF.backfill_event("evt_zzz", group, "FAKE_KEY", "us")   # must not raise
    assert report["updates"] == {}
    assert report["no_match"] == [9]
    print("✓ an unexpected historical response shape fails soft (warns, zero matches) rather "
         "than crashing the run")


if __name__ == "__main__":
    test_game_label_matches_real_logged_format()
    test_unwrap_events_response_handles_both_documented_shapes()
    test_resolve_events_for_date_warns_when_schedule_has_games_but_events_come_back_empty()
    test_group_missing_bets_by_event_minimizes_markets_per_event()
    test_estimate_cost_matches_documented_formula()
    test_backfill_event_matches_real_offers_to_bets()
    test_backfill_event_handles_unexpected_response_shape_without_crashing()
    print("\nAll backfill_closing_lines tests passed.")
