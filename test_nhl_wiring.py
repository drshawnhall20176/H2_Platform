"""
test_nhl_wiring.py — NHL's hook-ups into the shared platform (offline).

The engine and projection logic have their own files (test_nhl_engine.py / test_nhl_projections.py);
this covers everything that connects NHL to the pages that were written before it existed: the
sport registry, the schedule board, the grading map, the team-trend tag, the podcast copy, and the
scoreboard score fields the trend tag reads.
"""

import pytest

import basketball_engine as BB
import best_bets_data as BBD
import league_structure as LS
import nhl_engine as NE
import podcast as PC
import retro
import schedule_board as SB
import sports

_ALL_NHL_NAMES = [
    "Boston Bruins", "Buffalo Sabres", "Detroit Red Wings", "Florida Panthers", "Montréal Canadiens",
    "Ottawa Senators", "Tampa Bay Lightning", "Toronto Maple Leafs", "Carolina Hurricanes",
    "Columbus Blue Jackets", "New Jersey Devils", "New York Islanders", "New York Rangers",
    "Philadelphia Flyers", "Pittsburgh Penguins", "Washington Capitals", "Chicago Blackhawks",
    "Colorado Avalanche", "Dallas Stars", "Minnesota Wild", "Nashville Predators", "St. Louis Blues",
    "Utah Mammoth", "Winnipeg Jets", "Anaheim Ducks", "Calgary Flames", "Edmonton Oilers",
    "Los Angeles Kings", "San Jose Sharks", "Seattle Kraken", "Vancouver Canucks", "Vegas Golden Knights",
]


# ------------------------------------------------------------------- registry
def test_nhl_registry_entry_is_live_and_resolves_its_modules():
    nhl = sports.get("NHL")
    assert nhl.enabled and nhl.has_projections and nhl.odds_sport_key == "icehockey_nhl"
    assert nhl.engine is NE
    import nhl_projections
    assert nhl.projections is nhl_projections
    import config_nhl
    import importlib
    assert importlib.import_module(nhl.config_module) is config_nhl


def test_hot_hand_and_matchup_lab_stay_basketball_only():
    # NHL deliberately has neither page (they are basketball-shaped) — it must not be routed to them
    src = open("streamlit_app.py").read()
    assert '"10": ("WNBA", "NBA", "NCAAMB")' in src and '"11": ("WNBA", "NBA", "NCAAMB")' in src


# ------------------------------------------------------------------- league structure / schedule board
def test_nhl_table_covers_all_32_teams_in_four_divisions():
    assert set(_ALL_NHL_NAMES) <= set(LS.NHL_TEAM_CONFERENCE)
    for name in _ALL_NHL_NAMES:
        conf, div = LS.NHL_TEAM_CONFERENCE[name]
        assert conf in ("Eastern", "Western") and div in ("Atlantic", "Metropolitan", "Central", "Pacific")
    by_div = {}
    for name in _ALL_NHL_NAMES:
        by_div.setdefault(LS.NHL_TEAM_CONFERENCE[name][1], []).append(name)
    assert {k: len(v) for k, v in by_div.items()} == {"Atlantic": 8, "Metropolitan": 8, "Central": 8, "Pacific": 8}
    for name in _ALL_NHL_NAMES:      # divisions never straddle conferences
        conf, div = LS.NHL_TEAM_CONFERENCE[name]
        assert (conf == "Eastern") == (div in ("Atlantic", "Metropolitan"))


def test_nhl_spelling_variants_resolve():
    for alias in ("Montreal Canadiens", "Montréal Canadiens", "Utah Hockey Club", "Utah Mammoth"):
        assert alias in LS.NHL_TEAM_CONFERENCE


def test_schedule_board_groups_nhl_games_by_conference_and_division(monkeypatch):
    assert "NHL" in SB.SUPPORTED_SPORTS
    raw = [{"gameId": "1", "game_date": "2026-10-21T23:00:00Z", "status_state": "pre",
            "status_detail": "Scheduled", "home_name": "Colorado Avalanche", "away_name": "Vancouver Canucks",
            "home_logo": "h.png", "away_logo": "a.png"},
           {"gameId": "2", "game_date": "2026-10-21T23:30:00Z", "status_state": "pre",
            "status_detail": "Scheduled", "home_name": "Boston Bruins", "away_name": "Toronto Maple Leafs",
            "home_logo": None, "away_logo": None},
           {"gameId": "3", "game_date": "2026-10-21T23:45:00Z", "status_state": "pre",
            "status_detail": "Scheduled", "home_name": "Brand New Franchise", "away_name": "Boston Bruins",
            "home_logo": None, "away_logo": None}]
    monkeypatch.setattr(NE, "get_schedule", lambda d: raw)
    SB.todays_schedule.clear()
    out = SB.todays_schedule("NHL", "2026-10-21")
    assert out["has_divisions"] is True
    assert set(out["grouped"]) == {"Western", "Eastern"}
    assert [g["home"] for g in out["grouped"]["Western"]["Central"]] == ["Colorado Avalanche"]
    assert [g["home"] for g in out["grouped"]["Eastern"]["Atlantic"]] == ["Boston Bruins"]
    assert [g["home"] for g in out["other"]] == ["Brand New Franchise"]   # unknown team fails safe, not dropped
    SB.todays_schedule.clear()


# ------------------------------------------------------------------- grading map
def test_retro_market_stat_covers_every_nhl_market():
    for market in sports.get("NHL").market_map:
        assert market in retro.MARKET_STAT, f"{market} has no results key — its bets could never settle"
    assert retro.MARKET_STAT["Shots on Goal"] == "sog" and retro.MARKET_STAT["Saves"] == "saves"


def test_settle_bet_settles_an_nhl_prop_with_the_shared_settler():
    import settle_results
    results = {10: {"pts": 3.0, "ast": 1.0, "goals": 2.0, "sog": 4.0, "blk": 0.0}}
    bet = {"player_id": 10, "market": "Shots on Goal", "side": "Over", "line": 3.5}
    assert settle_results.settle_bet(bet, results) == "win"
    assert settle_results.settle_bet(dict(bet, side="Under"), results) == "loss"
    assert settle_results.settle_bet(dict(bet, player_id=99), results) is None   # didn't play -> never guessed


# ------------------------------------------------------------------- team trend tag
def test_attach_team_trend_nhl_uses_scoreboard_goals_for(monkeypatch):
    calls = []

    def fake_scoring(team_id, date_str, n=10, days_back=45):
        calls.append((team_id, n))
        return {"goals_for": 4.0 if n == 10 else 3.0, "goals_against": 2.5, "games": n}
    monkeypatch.setattr(NE, "get_team_recent_scoring", fake_scoring)
    plays = [{"Team": "Colorado Avalanche", "Player": "A"}, {"Team": "Colorado Avalanche", "Player": "B"}]
    rows = [{"Team": "Colorado Avalanche", "_team_id": 17}]
    BBD.attach_team_trend("NHL", plays, rows, "2026-10-21")
    assert calls == [(17, 10), (17, 40)]                       # once per team, not once per play
    assert all("Hot" in p["TeamTrend"] and p["TeamTrendRatio"] == 1.33 for p in plays)


def test_attach_team_trend_nhl_stays_steady_without_games(monkeypatch):
    monkeypatch.setattr(NE, "get_team_recent_scoring",
                        lambda *a, **k: {"goals_for": 0.0, "goals_against": 0.0, "games": 0})
    plays = [{"Team": "Colorado Avalanche", "Player": "A"}]
    BBD.attach_team_trend("NHL", plays, [{"Team": "Colorado Avalanche", "_team_id": 17}], "2026-10-21")
    assert "Steady" in plays[0]["TeamTrend"] and plays[0]["TeamTrendRatio"] is None


# ------------------------------------------------------------------- scoreboard score fields (basketball_engine)
def test_recent_game_ids_now_carry_the_final_scores():
    ev = {"events": [{
        "id": "g1", "date": "2026-10-10T00:00Z", "status": {"type": {"completed": True}},
        "competitions": [{"competitors": [
            {"team": {"id": "17"}, "score": "5"},
            {"team": {"id": "22", "displayName": "Vancouver Canucks"}, "score": "3"}]}]}]}
    games = BB.get_team_recent_game_ids(17, "2026-10-21", NE.SITE_API, lambda u, params=None: ev, n=5)
    assert games[0]["score"] == "5" and games[0]["opp_score"] == "3"
    # existing fields are untouched
    assert games[0]["gameId"] == "g1" and games[0]["opp_id"] == "22"


# ------------------------------------------------------------------- podcast copy
def test_podcast_uses_hockey_teaching_segments_and_market_banter():
    seg_topics = {PC.rotating_teaching(f"2026-10-{d:02d}", "NHL")["topic"] for d in range(1, 15)}
    assert len(seg_topics) >= 4
    text = " ".join(b["text"] for d in range(1, 15)
                    for b in PC.rotating_teaching(f"2026-10-{d:02d}", "NHL")["beats"] if "text" in b)
    for basketball_word in ("tip-off", "the shot didn't fall", "blowout", "she's"):
        assert basketball_word not in text
    for market in ("Goals", "Shots on Goal", "Blocked Shots", "Saves"):
        assert market in PC._DEEZY_PUSH


def test_podcast_script_assembles_for_nhl():
    sections = PC.assemble_script("2026-10-21", [], [], None, None, sport="NHL")
    assert len(sections) == 7
    flat = PC.script_to_text("2026-10-21", sections)
    assert "overtime winner" in flat and "buzzer-beater" not in flat
    assert "ice time" in flat.lower()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
