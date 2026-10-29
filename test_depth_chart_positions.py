"""Tonight's depth chart decides which position group a team's own players are read in (Oct 29: Peyton Watson is
listed "G" on the roster but starts at SF; Evan Mobley is listed "C" but starts at PF next to Jarrett Allen)."""
import basketball_engine as BB
import player_props as PPR
import position_matchups as PM


def _ath(i, name):
    return {"id": str(i), "displayName": name}


CLE_FEED = {"depthchart": [{"positions": {
    "pg": {"position": {"abbreviation": "PG"}, "athletes": [_ath(1, "James Harden"), _ath(6, "Craig Porter Jr."),
                                                            _ath(7, "Tyrese Proctor")]},
    "sg": {"position": {"abbreviation": "SG"}, "athletes": [_ath(2, "Donovan Mitchell"), _ath(5, "Sam Merrill"),
                                                            _ath(7, "Tyrese Proctor")]},
    "sf": {"position": {"abbreviation": "SF"}, "athletes": [_ath(3, "Peyton Watson"), _ath(8, "Jaylon Tyson"),
                                                            _ath(5, "Sam Merrill")]},
    "pf": {"position": {"abbreviation": "PF"}, "athletes": [_ath(4, "Evan Mobley"), _ath(3, "Peyton Watson")]},
    "c": {"position": {"abbreviation": "C"}, "athletes": [_ath(9, "Jarrett Allen"), _ath(4, "Evan Mobley")]},
}}]}


def chart():
    return BB.get_team_depth_chart(5, "https://x", lambda url, params=None: CLE_FEED)


def test_feed_parses_to_each_players_highest_listing():
    c = chart()
    assert c[3] == {"pos": "SF", "rank": 0, "name": "Peyton Watson"}       # SF starter beats PF backup
    assert c[4]["pos"] == "PF" and c[4]["rank"] == 0                        # Mobley: PF starter, not C backup
    assert c[5]["pos"] == "SG" and c[5]["rank"] == 1                        # Merrill: SG 2nd beats SF 3rd
    assert c[7]["pos"] == "PG"                                              # tie on rank -> earlier position
    assert BB.get_team_depth_chart(5, "https://x", lambda url, params=None: None) == {}
    assert BB.get_team_depth_chart(None, "https://x", lambda url, params=None: CLE_FEED) == {}


def usage():
    # Roster labels: Watson G, Mobley + Allen C (Mobley carries the old double-big guess), Merrill G.
    def u(pid, name, mins, **kw):
        return dict({"pid": pid, "name": name, "games_in_slot": 4, "avg": 20.0, "avg_min": mins,
                     "start_rate": 1.0, "slot2": None}, **kw)
    return {"G": [u(2, "Donovan Mitchell", 35), u(1, "James Harden", 35), u(3, "Peyton Watson", 32),
                  u(5, "Sam Merrill", 24, start_rate=0.0)],
            "C": [u(9, "Jarrett Allen", 30), u(4, "Evan Mobley", 34, slot2="F")],
            "F": [u(20, "Unlisted Guy", 12, start_rate=0.0)]}


def test_chart_moves_players_to_the_group_they_play_tonight():
    out = PM.apply_depth_chart(usage(), chart())
    names = {g: [p["name"] for p in lst] for g, lst in out.items()}
    assert names["G"] == ["Donovan Mitchell", "James Harden", "Sam Merrill"]
    assert names["F"] == ["Evan Mobley", "Peyton Watson", "Unlisted Guy"]
    assert names["C"] == ["Jarrett Allen"]
    mobley = out["F"][0]
    assert mobley["pos"] == "PF" and mobley["slot2"] is None and mobley["chart_starter"] is True
    assert out["F"][2]["chart_starter"] is False and "pos" not in out["F"][2]     # unlisted keeps roster group


def test_no_chart_changes_nothing():
    u = usage()
    assert PM.apply_depth_chart(u, {}) is u and PM.apply_depth_chart(u, None) is u


def test_name_fallback_when_ids_differ():
    c = {"x": {"pos": "SF", "rank": 0, "name": "Peyton Watson"}}
    out = PM.apply_depth_chart({"G": [{"pid": 3, "name": "Peyton Watson", "games_in_slot": 1, "avg_min": 30}]}, c)
    assert out["F"][0]["pos"] == "SF"


def test_roles_follow_the_chart_and_pos_column_shows_position_and_group():
    out = PM.apply_depth_chart(usage(), chart())
    rows = [{"slot": g, "players": [dict(p) for p in lst]} for g, lst in out.items()]
    role = PM.roles(rows)
    assert role["Peyton Watson"] == "Starter" and role["Sam Merrill"] == "Rotation"
    assert role["Unlisted Guy"] == "Rotation"
    assert PM._pos_text("F", {"pos": "SF"}) == "SF (F)"
    assert PM._pos_text("C", {"pos": "C"}) == "C"
    assert PM._pos_text("C", {"slot2": "F"}) == "C/F"                       # no chart: old double-big label


def test_rotation_carries_the_chart_group_into_the_props_model():
    rot = PPR.rotation(PM.apply_depth_chart(usage(), chart()))
    by = {r["name"]: r for r in rot}
    assert by["Peyton Watson"]["slot"] == "F" and by["Peyton Watson"]["pos"] == "SF"
    assert by["Evan Mobley"]["slot"] == "F" and by["Evan Mobley"]["slot2"] is None
    assert len(rot) == len({r["pid"] for r in rot})


def _pg(game, team, opp, pid, pos, pts, order):
    return {"game": game, "order": order, "team": team, "opp": opp, "pid": pid, "name": str(pid), "pos": pos,
            "starter": True, "stats": {"min": 30, "pts": pts, "reb": 5, "ast": 3, "fg3m": 1}}


def test_position_factors_use_the_chart_group():
    # Defense D allows a lot to guards, little to forwards; player 3 is roster "G" but charted SF.
    cur = []
    for t in range(10):
        for i in range(3):
            d = f"2026-10-2{i}"
            cur += [_pg(f"{t}-{i}", f"O{t}", f"D{t}", f"g{t}", "PG", 30 if t == 0 else 20, d),
                    _pg(f"{t}-{i}", f"O{t}", f"D{t}", f"f{t}", "SF", 10 if t == 0 else 20, d)]
    cur.append(_pg("X1", "CLE", "Z", 3, "G", 15, "2026-10-28"))
    plain = PPR.position_factors({(3, "D0")}, cur, [], "NBA", mode="season")
    charted = PPR.position_factors({(3, "D0")}, cur, [], "NBA", mode="season", charts={3: {"pos": "SF", "rank": 0}})
    assert plain[(3, "pts")] > 1.0 > charted[(3, "pts")]
