"""position_pbp.py — play-by-play stat lines by period, and defenders who sat out (snap counts)."""
import pandas as pd

import position_pbp as PP


def play(week, team, qtr, **kw):
    base = dict(season=2026, week=week, posteam=team, qtr=qtr, yards_gained=0.0, complete_pass=0.0, pass_attempt=0.0,
                rush_attempt=0.0, sack=0.0, two_point_attempt=0.0, passer_player_id=None, rusher_player_id=None,
                receiver_player_id=None, pass_touchdown=0.0, rush_touchdown=0.0, interception=0.0)
    base.update(kw)
    return base


def pbp():
    rows = [
        play(1, "A", 1, pass_attempt=1, complete_pass=1, yards_gained=12, passer_player_id="qb", receiver_player_id="wr1"),
        play(1, "A", 2, pass_attempt=1, complete_pass=1, yards_gained=40, passer_player_id="qb", receiver_player_id="wr1", pass_touchdown=1),
        play(1, "A", 3, pass_attempt=1, complete_pass=0, yards_gained=0, passer_player_id="qb", receiver_player_id="wr2"),
        play(1, "A", 3, pass_attempt=1, complete_pass=0, yards_gained=-7, passer_player_id="qb", sack=1),            # a sack: no attempt
        play(1, "A", 4, pass_attempt=1, complete_pass=0, interception=1, passer_player_id="qb", receiver_player_id="wr2"),
        play(1, "A", 5, rush_attempt=1, yards_gained=9, rusher_player_id="rb"),                                       # overtime
        play(1, "A", 1, rush_attempt=1, yards_gained=4, rusher_player_id="rb"),
        play(1, "A", 2, rush_attempt=1, yards_gained=1, rusher_player_id="rb", rush_touchdown=1),
        play(1, "A", 2, rush_attempt=1, yards_gained=2, rusher_player_id="rb", two_point_attempt=1),                  # excluded
        play(2, "A", 1, rush_attempt=1, yards_gained=30, rusher_player_id="rb"),
        play(1, "B", 1, rush_attempt=1, yards_gained=3, rusher_player_id="rb_b"),
        play(1, None, 1, rush_attempt=1, yards_gained=3, rusher_player_id="x"),                                       # no possession team
    ]
    return pd.DataFrame(rows)


def test_full_game_totals_exclude_sacks_and_two_point_tries():
    L = PP.period_lines(pbp())
    qb = L[(202601, "A", "qb")]["Full Game"]
    assert (qb["pass_att"], qb["pass_cmp"], qb["pass_yds"], qb["pass_td"], qb["pass_int"], qb["pass_long"]) == (4, 2, 52, 1, 1, 40)
    rb = L[(202601, "A", "rb")]["Full Game"]
    assert (rb["rush_att"], rb["rush_yds"], rb["rush_td"], rb["rush_long"], rb["td"], rb["atd"]) == (3, 14, 1, 9, 1, 1)
    wr1, wr2 = L[(202601, "A", "wr1")]["Full Game"], L[(202601, "A", "wr2")]["Full Game"]
    assert (wr1["tgt"], wr1["rec"], wr1["rec_yds"], wr1["rec_long"], wr1["rec_td"], wr1["td"]) == (2, 2, 52, 40, 1, 1)
    assert (wr2["tgt"], wr2["rec"], wr2["rec_yds"], wr2["atd"]) == (2, 0, 0, 0)
    assert (202601, "A", "x") not in L and (202601, None, "x") not in L


def test_a_passing_td_is_the_receivers_td_and_flags_anytime_scorer():
    f = pbp()
    f.loc[1, "receiver_player_id"] = "wr1"
    L = PP.period_lines(f)
    assert L[(202601, "A", "wr1")]["Full Game"]["rec_td"] == 1 and L[(202601, "A", "wr1")]["Full Game"]["atd"] == 1


def test_shares_are_of_the_teams_own_carries_and_targets():
    L = PP.period_lines(pbp())
    assert abs(L[(202601, "A", "rb")]["Full Game"]["rush_share"] - 100.0) < 1e-9
    assert abs(L[(202601, "A", "wr1")]["Full Game"]["tgt_share"] - 50.0) < 1e-9
    assert abs(L[(202601, "A", "wr2")]["Full Game"]["tgt_share"] - 50.0) < 1e-9
    assert L[(202601, "A", "qb")]["Full Game"]["rush_share"] == 0.0


def test_halves_and_quarters_split_the_game_and_overtime_is_second_half():
    L = PP.period_lines(pbp())
    rb = L[(202601, "A", "rb")]
    assert rb["1st Half"]["rush_yds"] == 5 and rb["2nd Half"]["rush_yds"] == 9 and rb["Q1"]["rush_yds"] == 4 and rb["Q2"]["rush_yds"] == 1
    assert "Q3" not in rb and "Q4" not in rb
    for who in ("qb", "wr1", "wr2", "rb"):
        per = L[(202601, "A", who)]
        for k in ("pass_att", "rush_yds", "rec_yds", "tgt"):
            assert per.get("1st Half", {}).get(k, 0) + per.get("2nd Half", {}).get(k, 0) == per["Full Game"][k]
    assert sum(L[(202601, "A", "qb")][q]["pass_att"] for q in ("Q1", "Q2", "Q3", "Q4")) == 4


def test_before_cutoff_is_exclusive_and_orders_are_composite():
    assert set(k[0] for k in PP.period_lines(pbp())) == {202601, 202602}
    assert set(k[0] for k in PP.period_lines(pbp(), before=202602)) == {202601}
    assert PP.period_lines(pbp(), before=202601) == {} and PP.period_lines(None) == {} and PP.period_lines(pbp().iloc[0:0]) == {}
    assert PP.season_order(2026, 4) == 202604


def test_missing_optional_columns_read_as_zero():
    f = pbp().drop(columns=["two_point_attempt", "sack", "interception"])
    qb = PP.period_lines(f)[(202601, "A", "qb")]["Full Game"]
    assert qb["pass_int"] == 0 and qb["pass_att"] == 5                                                           # no sack column → every attempt counts


def snaps():
    rows = []
    for wk in range(1, 7):
        rows.append(dict(season=2026, week=wk, team="DAL", player="Star", defense_snaps=0.0 if wk in (3, 4) else 60.0, defense_pct=0.0 if wk in (3, 4) else 0.9))
        rows.append(dict(season=2026, week=wk, team="DAL", player="Rookie", defense_snaps=50.0 if wk >= 4 else 0.0, defense_pct=0.8 if wk >= 4 else 0.0))
        rows.append(dict(season=2026, week=wk, team="DAL", player="Cut", defense_snaps=40.0 if wk <= 2 else 0.0, defense_pct=0.7 if wk <= 2 else 0.0))
        rows.append(dict(season=2026, week=wk, team="DAL", player="Scrub", defense_snaps=5.0, defense_pct=0.05))
        rows.append(dict(season=2026, week=wk, team="DAL", player="Once", defense_snaps=60.0 if wk == 5 else 0.0, defense_pct=0.9 if wk == 5 else 0.0))
    rows += [dict(season=2026, week=wk, team="NYG", player="Giant", defense_snaps=55.0, defense_pct=0.8) for wk in (1, 2, 4)]     # bye in week 3
    return pd.DataFrame(rows)


def test_absences_only_count_between_a_players_first_and_last_game():
    ab, reg = PP.defense_absences(snaps())
    assert ab[(202603, "DAL")] == ["Star"] and ab[(202604, "DAL")] == ["Star"]
    assert (202601, "DAL") not in ab and (202605, "DAL") not in ab
    assert all("Rookie" not in v and "Cut" not in v and "Scrub" not in v and "Once" not in v for v in ab.values())
    assert (202603, "NYG") not in ab                                                                               # a bye is not an absence


def test_regulars_are_the_newest_seasons_heavy_users_most_used_first():
    _, reg = PP.defense_absences(snaps())
    assert [r["name"] for r in reg["DAL"]] == ["Star", "Rookie", "Cut"]
    assert reg["DAL"][0]["games"] == 4 and abs(reg["DAL"][0]["avg_pct"] - 0.9) < 1e-9
    _, strict = PP.defense_absences(snaps(), min_games=5)
    assert [r["name"] for r in strict.get("DAL", [])] == []
    _, heavy = PP.defense_absences(snaps(), min_avg_pct=0.85)
    assert [r["name"] for r in heavy["DAL"]] == ["Star"]
    assert PP.defense_absences(None) == ({}, {}) and PP.defense_absences(snaps().iloc[0:0]) == ({}, {})


def test_previous_season_absences_are_kept_but_not_offered_as_regulars():
    old = snaps().assign(season=2025)
    new = pd.DataFrame([dict(season=2026, week=w, team="DAL", player="Newbie", defense_snaps=50.0, defense_pct=0.8) for w in (1, 2)])
    ab, reg = PP.defense_absences(pd.concat([old, new], ignore_index=True))
    assert (202503, "DAL") in ab and [r["name"] for r in reg["DAL"]] == ["Newbie"]


def test_two_touchdowns_still_flag_one_anytime_scorer_and_rush_rec_yards_add_up():
    f = pd.DataFrame([play(1, "A", 1, rush_attempt=1, yards_gained=5, rusher_player_id="rb", rush_touchdown=1),
                      play(1, "A", 2, rush_attempt=1, yards_gained=7, rusher_player_id="rb", rush_touchdown=1),
                      play(1, "A", 2, pass_attempt=1, complete_pass=1, yards_gained=11, passer_player_id="qb", receiver_player_id="rb")])
    rb = PP.period_lines(f)[(202601, "A", "rb")]["Full Game"]
    assert rb["td"] == 2 and rb["atd"] == 1 and rb["rush_rec_yds"] == 23 and rb["rush_yds"] == 12 and rb["rec_yds"] == 11


def test_a_player_exactly_at_the_snap_threshold_counts_as_a_regular():
    rows = [dict(season=2026, week=w, team="DAL", player="Edge", defense_snaps=30.0, defense_pct=0.35) for w in (1, 2)]
    _, reg = PP.defense_absences(pd.DataFrame(rows))
    assert [r["name"] for r in reg["DAL"]] == ["Edge"]
    _, none = PP.defense_absences(pd.DataFrame(rows), min_avg_pct=0.36)
    assert none.get("DAL", []) == []
