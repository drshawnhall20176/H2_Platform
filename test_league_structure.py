"""
test_league_structure.py — offline unit tests for league_structure.py.

    python test_league_structure.py     # or: pytest test_league_structure.py
"""

import league_structure as LS
import config_wnba


def test_mlb_has_all_thirty_teams():
    assert len(LS.MLB_TEAM_LEAGUE) == 30
    print("✓ MLB_TEAM_LEAGUE has all 30 teams")


def test_mlb_keys_match_mlb_engine_abbr_table_exactly():
    # Regression guard for the real drift risk this table's own docstring flags: these must be
    # the EXACT same 30 team-name strings mlb_engine.MLB_TEAM_ABBR uses, or a real schedule row
    # (which uses those same names) would silently land in the "Other" bucket.
    import mlb_engine as E
    assert set(LS.MLB_TEAM_LEAGUE.keys()) == set(E.MLB_TEAM_ABBR.keys())
    print("✓ MLB_TEAM_LEAGUE's keys match mlb_engine.MLB_TEAM_ABBR's exactly, no drift")


def test_mlb_leagues_and_divisions_are_balanced():
    from collections import Counter
    leagues = Counter(lg for lg, _div in LS.MLB_TEAM_LEAGUE.values())
    assert leagues == {"AL": 15, "NL": 15}
    divisions = Counter((lg, div) for lg, div in LS.MLB_TEAM_LEAGUE.values())
    assert all(n == 5 for n in divisions.values()) and len(divisions) == 6
    print("✓ MLB is balanced: 15/15 AL/NL, 6 divisions of 5 teams each")


def test_mlb_athletics_still_in_al_west():
    # Regression guard for the specific real-world fact this table's own docstring calls out --
    # the Athletics kept their AL West slot through the Sacramento/Las Vegas relocation.
    assert LS.MLB_TEAM_LEAGUE["Athletics"] == ("AL", "West")
    print("✓ Athletics correctly still mapped to AL West through the relocation")


def test_nba_has_all_thirty_teams():
    assert len(LS.NBA_TEAM_CONFERENCE) == 30
    print("✓ NBA_TEAM_CONFERENCE has all 30 teams")


def test_nba_conferences_and_divisions_are_balanced():
    from collections import Counter
    confs = Counter(c for c, _d in LS.NBA_TEAM_CONFERENCE.values())
    assert confs == {"Eastern": 15, "Western": 15}
    divisions = Counter((c, d) for c, d in LS.NBA_TEAM_CONFERENCE.values())
    assert all(n == 5 for n in divisions.values()) and len(divisions) == 6
    print("✓ NBA is balanced: 15/15 Eastern/Western, 6 divisions of 5 teams each")


def test_nfl_has_all_thirty_two_teams():
    assert len(LS.NFL_TEAM_CONFERENCE) == 32
    print("✓ NFL_TEAM_CONFERENCE has all 32 teams")


def test_nfl_conferences_and_divisions_are_balanced():
    from collections import Counter
    confs = Counter(c for c, _d in LS.NFL_TEAM_CONFERENCE.values())
    assert confs == {"AFC": 16, "NFC": 16}
    divisions = Counter((c, d) for c, d in LS.NFL_TEAM_CONFERENCE.values())
    assert all(n == 4 for n in divisions.values()) and len(divisions) == 8
    print("✓ NFL is balanced: 16/16 AFC/NFC, 8 divisions of 4 teams each")


def test_nfl_abbreviations_have_no_accidental_duplicates():
    # A copy-paste typo (e.g. two teams both mapped under "LA") would silently merge two real
    # franchises into one bucket -- catch that here, not live.
    assert len(LS.NFL_TEAM_CONFERENCE) == len(set(LS.NFL_TEAM_CONFERENCE.keys()))
    print("✓ No duplicate NFL abbreviations in the table")


def test_wnba_team_conference_matches_config_wnba_exactly():
    # Derived from config_wnba.TEAMS on purpose, not duplicated -- this confirms that
    # relationship actually holds, so the two can never silently drift apart.
    derived = LS.wnba_team_conference()
    expected = {name: conf for _tid, (name, _abbr, conf) in config_wnba.TEAMS.items()}
    assert derived == expected
    print(f"✓ wnba_team_conference() matches config_wnba.TEAMS exactly ({len(derived)} teams)")


def test_wnba_conferences_are_east_west_only():
    confs = set(LS.wnba_team_conference().values())
    assert confs == {"East", "West"}
    print("✓ WNBA conferences are East/West only, as expected (no division level)")


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
