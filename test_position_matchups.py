"""Pure-logic tests for position_matchups.py — slots, what a defense allowed, ranks, rows, head-to-head."""
import position_matchups as PM


def pg(game, order, team, opp, pid, name, pos, **stats):
    return {"game": game, "order": order, "team": team, "opp": opp, "pid": pid, "name": name, "pos": pos, "stats": stats}


# ------------------------------------------------------------------ slot assignment (football)
def test_football_slots_follow_usage_not_listing_order():
    players = [pg("g", 1, "A", "B", 1, "Qb1", "QB", pass_att=30, pass_yds=250),
               pg("g", 1, "A", "B", 2, "Qb2", "QB", pass_att=2, pass_yds=5),
               pg("g", 1, "A", "B", 3, "Back1", "RB", rush_att=5, rush_yds=20, rec=1),
               pg("g", 1, "A", "B", 4, "Back2", "RB", rush_att=15, rush_yds=70, rec=2),
               pg("g", 1, "A", "B", 5, "Wr_low", "WR", tgt=2, rec=1, rec_yds=8),
               pg("g", 1, "A", "B", 6, "Wr_top", "WR", tgt=11, rec=8, rec_yds=100),
               pg("g", 1, "A", "B", 7, "Wr_mid", "WR", tgt=6, rec=4, rec_yds=40),
               pg("g", 1, "A", "B", 8, "Wr_4th", "WR", tgt=1, rec=1, rec_yds=3),
               pg("g", 1, "A", "B", 9, "Te", "TE", tgt=5, rec=3, rec_yds=30)]
    s = PM.assign_football_slots(players)
    assert s["QB"][0]["name"] == "Qb1"
    assert [s["RB1"][0]["name"], s["RB2"][0]["name"]] == ["Back2", "Back1"]       # by carries
    assert [s[k][0]["name"] for k in ("WR1", "WR2", "WR3")] == ["Wr_top", "Wr_mid", "Wr_low"]   # by targets
    assert "Wr_4th" not in [x["name"] for v in s.values() for x in v] and s["TE1"][0]["name"] == "Te"


def test_players_with_no_usage_hold_no_slot_and_fullbacks_count_as_backs():
    s = PM.assign_football_slots([pg("g", 1, "A", "B", 1, "Idle", "WR"), pg("g", 1, "A", "B", 2, "Fb", "FB", rush_att=3, rush_yds=9),
                                  pg("g", 1, "A", "B", 3, "K", "K", pass_att=0)])
    assert list(s) == ["RB1"] and s["RB1"][0]["name"] == "Fb"


def test_receivers_without_targets_rank_by_receptions_then_yards():
    s = PM.assign_football_slots([pg("g", 1, "A", "B", 1, "Few", "WR", rec=2, rec_yds=90), pg("g", 1, "A", "B", 2, "Many", "WR", rec=7, rec_yds=60)])
    assert s["WR1"][0]["name"] == "Many"


# ------------------------------------------------------------------ headline metrics
def test_football_points_and_basketball_pra():
    assert abs(PM.football_points({"pass_yds": 250, "pass_td": 2, "pass_int": 1, "rush_yds": 20}) - (10 + 8 - 2 + 2)) < 1e-9
    assert abs(PM.football_points({"rec": 5, "rec_yds": 60, "rec_td": 1}) - (5 + 6 + 6)) < 1e-9
    assert PM.basketball_pra({"pts": 20, "reb": 5, "ast": 3, "fg3m": 9}) == 28
    assert PM.football_points({"pass_yds": float("nan")}) == 0.0


def test_position_group_reads_espn_abbreviations():
    assert [PM.position_group(a) for a in ("PG", "SG", "G", "SF", "PF", "F", "C", "G-F", "F-C", "C-F", "gf", None, "", "nan", "X")] == \
        ["G", "G", "G", "F", "F", "F", "C", "G", "F", "C", None, None, None, None, None]


def test_basketball_slots_group_everyone_and_skip_dnp():
    s = PM.assign_basketball_slots([pg("g", 1, "A", "B", 1, "P1", "PG", min=30, pts=20), pg("g", 1, "A", "B", 2, "P2", "SG", min=20, pts=8),
                                    pg("g", 1, "A", "B", 3, "Big", "C", min=25, pts=10, reb=9), pg("g", 1, "A", "B", 4, "Dnp", "PF", min=0),
                                    pg("g", 1, "A", "B", 5, "NoPos", None, min=10, pts=4)])
    assert {k: [p["name"] for p in v] for k, v in s.items()} == {"G": ["P1", "P2"], "C": ["Big"]}


# ------------------------------------------------------------------ what a defense allowed
def games_for_football():
    """Defense D faced offenses A (wk1) and B (wk2); defense E faced A (wk3)."""
    return [pg("1", 1, "A", "D", 1, "A_wr", "WR", tgt=10, rec=8, rec_yds=100, rec_td=1),
            pg("2", 2, "B", "D", 2, "B_wr", "WR", tgt=6, rec=3, rec_yds=30),
            pg("3", 3, "A", "E", 1, "A_wr", "WR", tgt=4, rec=2, rec_yds=10)]


def test_allowed_by_slot_credits_the_defense_and_orders_newest_first():
    al = PM.allowed_by_slot(games_for_football(), "NFL")
    assert set(al) == {"D", "E"} and [g["order"] for g in al["D"]] == [2, 1]
    assert al["D"][1]["slots"]["WR1"]["rec_yds"] == 100
    summ = PM.summarize(al, "NFL")
    wr1_d = summ["D"]["WR1"]
    assert wr1_d["games"] == 2 and abs(wr1_d["stats"]["rec_yds"] - 65) < 1e-9
    assert abs(wr1_d["pts"] - ((8 + 10 + 6) + (3 + 3)) / 2) < 1e-9
    assert summ["D"]["QB"]["pts"] == 0.0                         # a slot nobody used is a real zero


def test_summarize_recent_window_and_basketball_group_totals():
    al = PM.allowed_by_slot(games_for_football(), "NFL")
    assert PM.summarize(al, "NFL", n=1)["D"]["WR1"]["stats"]["rec_yds"] == 30   # newest game only
    bb = [pg("g1", "2026-10-01", 1, 2, 10, "G1", "PG", min=30, pts=20, reb=4, ast=6), pg("g1", "2026-10-01", 1, 2, 11, "G2", "SG", min=20, pts=10, reb=2, ast=2)]
    s = PM.summarize(PM.allowed_by_slot(bb, "NBA"), "NBA")
    assert s[2]["G"]["pts"] == 20 + 10 + 4 + 2 + 6 + 2 and s[2]["G"]["stats"]["pts"] == 30   # the group's totals


# ------------------------------------------------------------------ ranks / tiers / trend
def synthetic_summary(values):
    return {f"T{i}": {"WR1": {"games": 5, "pts": v, "stats": {"rec_yds": v * 8}}} for i, v in enumerate(values)}


def test_rank_one_is_the_softest_with_stable_ties():
    s = synthetic_summary([10, 30, 20, 30])
    assert PM.rank_slot(s, "WR1") == {"T1": 1, "T3": 2, "T2": 3, "T0": 4}
    assert PM.league_average(s, "WR1") == 22.5


def test_tier_thirds_and_edge_cases():
    assert [PM.tier(r, 30) for r in (1, 10, 11, 20, 21, 30)] == ["Soft", "Soft", "Neutral", "Neutral", "Tough", "Tough"]
    assert PM.tier(None, 30) == "—" and PM.tier(1, 2) == "—"


def test_trend_label_needs_a_real_swing():
    assert PM.trend_label(10, 12) == "▲ softer lately" and PM.trend_label(10, 8) == "▼ tougher lately"
    assert PM.trend_label(10, 11) == "steady" and PM.trend_label(None, 5) == "—" and PM.trend_label(0, 5) == "—"


# ------------------------------------------------------------------ the matchup rows
def table_inputs():
    pgames = []
    for i in range(10):                                           # ten defenses D0..D9, softer with i
        for wk in (1, 2, 3):
            pgames.append(pg(f"{i}-{wk}", wk, "O", f"D{i}", 100 + i, f"Opp wr {i}", "WR", tgt=5, rec=3 + i, rec_yds=30 + 10 * i))
    for wk in (1, 2, 3, 4):                                       # the offense we look at, with some form
        pgames.append(pg(f"o{wk}", wk, "HOME", "X", 7, "Star", "WR", tgt=9, rec=6, rec_yds=80, rec_td=1))
    pgames.append(pg("h", 2, "HOME", "D9", 7, "Star", "WR", tgt=9, rec=10, rec_yds=130))      # an earlier game vs D9
    return pgames


def test_matchup_rows_line_the_starter_up_against_the_defense_rank():
    pgames = table_inputs()
    al = PM.allowed_by_slot(pgames, "NFL")
    summ, rec = PM.summarize(al, "NFL"), PM.summarize(al, "NFL", n=PM.RECENT_N)
    depth = {"WR1": [{"pid": 7, "name": "Star", "status": "Questionable"}, {"pid": 8, "name": "Backup"}]}
    rows = {r["slot"]: r for r in PM.matchup_rows("NFL", depth, "D9", summ, rec, pgames)}
    wr1 = rows["WR1"]
    assert wr1["rank"] == 1 and wr1["tier"] == "Soft" and wr1["games"] == 4 and wr1["n_teams"] == 11 and wr1["vs_league_pct"] > 0
    assert wr1["players"][0]["name"] == "Star" and wr1["players"][0]["status"] == "Questionable"
    assert wr1["players"][0]["h2h"]["games"] == 1 and wr1["players"][0]["recent"]["games"] == 4
    assert [p["name"] for p in wr1["players"]] == ["Star", "Backup"] and wr1["players"][1]["recent"] is None
    assert rows["QB"]["rank"] is None and rows["QB"]["players"] == []               # no depth, no ranked defenses


def test_too_few_ranked_defenses_gives_no_rank_or_league_average():
    pgames = [pg(f"{i}", 1, "O", f"D{i}", 100 + i, "w", "WR", tgt=5, rec=3, rec_yds=30) for i in range(5)]
    al = PM.allowed_by_slot(pgames, "NFL")
    summ = PM.summarize(al, "NFL")
    row = [r for r in PM.matchup_rows("NFL", {}, "D1", summ, None) if r["slot"] == "WR1"][0]
    assert row["rank"] is None and row["league_avg"] is None and row["tier"] == "—" and row["allowed"] is not None


def test_only_defenses_with_enough_games_are_ranked():
    s = synthetic_summary([10, 20, 30, 40, 50, 60, 70, 80, 90])
    s["T0"]["WR1"]["games"] = 1                                   # one game -> out of the pool
    pool = PM.ranking_pool(s)
    assert "WR1" not in pool["T0"] and len(PM.rank_slot(pool, "WR1")) == 8


def test_thin_sample_flag_and_trend_in_rows():
    pgames = table_inputs()
    al = PM.allowed_by_slot(pgames, "NFL")
    summ = PM.summarize(al, "NFL")
    rows = PM.matchup_rows("NFL", {}, "D0", summ, PM.summarize(al, "NFL", n=1), pgames)
    assert all(not r["thin"] for r in rows if r["games"])
    summ["D0"]["WR1"]["games"] = 2
    assert [r for r in PM.matchup_rows("NFL", {}, "D0", summ, None)][3]["thin"] is True


# ------------------------------------------------------------------ usage depth
def test_usage_depth_ranks_by_slots_held_for_football_and_minutes_for_basketball():
    pgames = [pg(f"g{k}", k, "A", "B", 1, "Regular", "WR", tgt=9, rec=5, rec_yds=60) for k in (1, 2, 3)] + \
             [pg("g3", 3, "A", "B", 2, "Newcomer", "WR", tgt=3, rec=2, rec_yds=20)] + \
             [pg("g4", 4, "A", "B", 2, "Newcomer", "WR", tgt=12, rec=9, rec_yds=130)]
    d = PM.usage_depth(pgames, "A", "NFL", last_n=4)
    assert [p["name"] for p in d["WR1"]][0] == "Newcomer" or d["WR1"][0]["games_in_slot"] >= d["WR1"][-1]["games_in_slot"]
    bb = [pg("g1", "2026-10-01", "A", "B", 1, "Starter", "PG", min=34, pts=18), pg("g1", "2026-10-01", "A", "B", 2, "Sub", "SG", min=12, pts=9)]
    assert [p["name"] for p in PM.usage_depth(bb, "A", "NBA")["G"]] == ["Starter", "Sub"]
    assert PM.usage_depth(bb, "Z", "NBA") == {}


# ------------------------------------------------------------------ head-to-head
def game(date, home, away, hs, as_):
    return {"date": date, "home": home, "away": away, "home_score": hs, "away_score": as_}


def test_h2h_meetings_filter_orient_and_skip_unplayed():
    games = [game("2025-10-01", "KC", "DEN", 27, 20), game("2024-11-10", "DEN", "KC", 17, 30), game("2026-10-12", "DEN", "KC", None, None),
             game("2025-01-01", "KC", "LV", 10, 9), game("2023-12-31", "DEN", "KC", float("nan"), float("nan")), game("2022-01-01", "KC", "KC", 1, 0)]
    m = PM.h2h_meetings(games, "KC", "DEN")
    assert [x["date"] for x in m] == ["2025-10-01", "2024-11-10"]
    assert (m[0]["a_score"], m[0]["b_score"], m[0]["margin"], m[0]["total"], m[0]["winner"]) == (27, 20, 7, 47, "KC")
    assert (m[1]["a_score"], m[1]["b_score"], m[1]["margin"]) == (30, 17, 13)       # KC was the away team


def test_h2h_summary_and_sentence():
    m = PM.h2h_meetings([game("2025-10-01", "KC", "DEN", 27, 20), game("2024-11-10", "DEN", "KC", 17, 30), game("2023-09-01", "KC", "DEN", 10, 10),
                         game("2022-09-01", "DEN", "KC", 24, 20)], "KC", "DEN")
    s = PM.h2h_summary(m, "KC", "DEN")
    assert (s["games"], s["a_wins"], s["b_wins"], s["ties"]) == (4, 2, 1, 1) and abs(s["avg_margin"] - (7 + 13 + 0 - 4) / 4) < 1e-9
    assert "KC lead the series 2–1–1 over 4 meeting(s)" in PM.h2h_sentence(s, "KC", "DEN")
    empty = PM.h2h_summary([], "KC", "DEN")
    assert empty["avg_margin"] is None and "No completed KC–DEN meetings" in PM.h2h_sentence(empty, "KC", "DEN")
    tied = PM.h2h_summary(PM.h2h_meetings([game("2025-01-01", "KC", "DEN", 10, 7), game("2024-01-01", "KC", "DEN", 7, 10)], "KC", "DEN"), "KC", "DEN")
    assert PM.h2h_sentence(tied, "KC", "DEN").startswith("Series tied 1–1")
    den = PM.h2h_summary(PM.h2h_meetings([game("2025-01-01", "KC", "DEN", 7, 10)], "KC", "DEN"), "KC", "DEN")
    assert PM.h2h_sentence(den, "KC", "DEN").startswith("DEN lead the series 1–0")


# ------------------------------------------------------------------ display
def test_display_rows_and_callouts():
    pgames = table_inputs()
    al = PM.allowed_by_slot(pgames, "NFL")
    summ = PM.summarize(al, "NFL")
    depth = {"WR1": [{"pid": 7, "name": "Star", "status": "Out"}, {"pid": 8, "name": "Backup"}]}
    rows = PM.matchup_rows("NFL", depth, "D9", summ, PM.summarize(al, "NFL", n=2), pgames)
    disp = {r["Slot"]: r for r in PM.display_rows(rows)}
    assert disp["WR1"]["Starter"] == "Star 🚫 Out" and disp["WR1"]["Verdict"] == "🟢 Soft" and disp["WR1"]["D rank (1 = softest)"] == "1/11"
    assert disp["WR1"]["Last 4"].endswith("(4 g)") and disp["WR1"]["vs this D"].endswith("(1 g)") and disp["WR1"]["Next up"].startswith("Backup")
    assert disp["QB"]["Starter"] == "—" and disp["QB"]["Allowed / g"] != "—"
    side = {"rows": rows}
    co = PM.callouts(side, "HOME", "D9")
    assert co["targets"] and "Star (WR1)" in co["targets"][0] and "rank 1/11" in co["targets"][0] and "[Out]" in co["targets"][0]
    assert co["fades"] == []
    assert PM.callouts({"rows": PM.matchup_rows("NFL", depth, "D9", summ, None, pgames)[:0]}, "H", "D") == {"targets": [], "fades": []}


def test_a_slot_every_defense_allowed_the_same_amount_is_not_ranked():
    pgames = [pg(f"{i}", 1, "O", f"D{i}", 100 + i, "w", "WR", tgt=5, rec=3, rec_yds=30) for i in range(10)]
    summ = PM.summarize(PM.allowed_by_slot(pgames, "NFL"), "NFL")
    for s in summ.values():
        for slot in s:
            s[slot]["games"] = 5
    rows = {r["slot"]: r for r in PM.matchup_rows("NFL", {}, "D1", summ, None)}
    assert rows["WR1"]["rank"] is None and rows["WR1"]["tier"] == "—"          # ten identical lines


def test_backs_rank_by_carries_not_receptions():
    s = PM.assign_football_slots([pg("g", 1, "A", "B", 1, "Receiver back", "RB", rush_att=4, rec=7, rush_yds=15),
                                  pg("g", 1, "A", "B", 2, "Runner", "RB", rush_att=11, rec=1, rush_yds=50)])
    assert s["RB1"][0]["name"] == "Runner" and s["RB2"][0]["name"] == "Receiver back"


def test_h2h_of_a_team_with_itself_is_empty():
    assert PM.h2h_meetings([game("2025-01-01", "KC", "KC", 10, 7)], "KC", "KC") == []


def test_callouts_put_the_biggest_gaps_first():
    def row(slot, name, pct, tier_):
        return dict(slot=slot, rank=1, n_teams=32, tier=tier_, vs_league_pct=pct, allowed=20.0, league_avg=15.0, trend="steady",
                    players=[dict(name=name, status=None, recent=None, h2h=None)])
    side = {"rows": [row("WR1", "Small soft", 10, "Soft"), row("WR2", "Big soft", 60, "Soft"), row("TE1", "Mild tough", -10, "Tough"),
                     row("RB1", "Awful tough", -45, "Tough"), row("QB", "Neutral", 1, "Neutral")]}
    co = PM.callouts(side, "O", "D")
    assert [t.split(" (")[0] for t in co["targets"]] == ["Big soft", "Small soft"]
    assert [t.split(" (")[0] for t in co["fades"]] == ["Awful tough", "Mild tough"]
    assert len(PM.callouts(side, "O", "D", limit=1)["targets"]) == 1


def test_basketball_rotation_is_ordered_by_minutes_not_by_production():
    bb = [pg("g1", "2026-10-01", "A", "B", 1, "Starter", "PG", min=34, pts=8), pg("g1", "2026-10-01", "A", "B", 2, "Hot sub", "SG", min=12, pts=30)]
    assert [p["name"] for p in PM.usage_depth(bb, "A", "NBA")["G"]] == ["Starter", "Hot sub"]


# ------------------------------------------------------------------ slot game log (one position vs one defense)
def log_fixture():
    """Defense DAL over five weeks; each week a different offense's WR1 (by targets) plus a lesser WR2. Week 4 has no WR2 at all."""
    pgs = []
    for wk in range(1, 6):
        pgs.append(pg(f"g{wk}", wk, f"O{wk}", "DAL", f"a{wk}", f"Star{wk}", "WR", tgt=10, rec=wk, rec_yds=10 * wk, rec_td=1 if wk == 5 else 0))
        if wk != 4:
            pgs.append(pg(f"g{wk}", wk, f"O{wk}", "DAL", f"b{wk}", f"Sub{wk}", "WR", tgt=3, rec=1, rec_yds=5))
    pgs.append(pg("x", 3, "DAL", "O3", "d1", "DalWr", "WR", tgt=5, rec=2, rec_yds=20))             # DAL's own offense must not appear in DAL's log
    games = [dict(order=1, date="2026-09-06", home="DAL", away="O1", home_score=30, away_score=20),
             dict(order=2, date="2026-09-13", home="O2", away="DAL", home_score=17, away_score=17),
             dict(order=3, date="2026-09-20", home="O3", away="DAL", home_score=10, away_score=24),
             dict(order=4, date="2026-09-27", home="DAL", away="O4", home_score=None, away_score=None),
             dict(order=5, date="2026-10-04", home="DAL", away="O5", home_score=21, away_score=27)]
    return PM.allowed_by_slot(pgs, "NFL"), PM.build_game_meta(games)


def test_allowed_by_slot_remembers_who_held_each_slot_best_first():
    allowed, _ = log_fixture()
    wk1 = [g for g in allowed["DAL"] if g["order"] == 1][0]
    assert wk1["who"] == {"WR1": ["Star1"], "WR2": ["Sub1"]}
    bb = PM.allowed_by_slot([pg("g", 1, "A", "B", 1, "Low", "G", min=20, pts=2), pg("g", 1, "A", "B", 2, "High", "PG", min=30, pts=30),
                             pg("g", 1, "A", "B", 3, "Unnamed", "G", min=10, pts=9)], "NBA")
    assert bb["B"][0]["who"]["G"] == ["High", "Unnamed", "Low"]                      # the group's top producers first


def test_build_game_meta_indexes_both_directions_and_drops_bad_rows():
    m = PM.build_game_meta([dict(order=1, date="2026-09-06T17:00Z", home="A", away="B", home_score="30", away_score=20),
                            dict(order=2, date="d", home="A", away="A", home_score=1, away_score=2),
                            dict(order=None, home="A", away="B"), dict(order=3, home=None, away="B"),
                            dict(order=4, date=None, home="A", away="B", home_score=float("nan"), away_score="x")])
    none = {"primetime": None, "setting": None, "role": None, "total": None}
    assert m[(1, "A", "B")] == {"date": "2026-09-06", "venue": "Home", "def_score": 30.0, "off_score": 20.0, **none}
    assert m[(1, "B", "A")] == {"date": "2026-09-06", "venue": "Away", "def_score": 20.0, "off_score": 30.0, **none}
    assert m[(4, "A", "B")] == {"date": "", "venue": "Home", "def_score": None, "off_score": None, **none}
    assert set(k[0] for k in m) == {1, 4} and PM.build_game_meta(None) == {}


def test_slot_game_log_rows_are_newest_first_with_venue_result_player_and_stats():
    allowed, meta = log_fixture()
    log = PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, n=10)
    assert [r["order"] for r in log["rows"]] == [5, 4, 3, 2, 1] and log["games"] == 5
    wk5, wk4, wk3, wk2, wk1 = log["rows"]
    assert (wk5["opp"], wk5["venue"], wk5["result"], wk5["score"], wk5["who"], wk5["date"]) == ("O5", "Home", "L", "21-27", "Star5", "2026-10-04")
    assert (wk3["venue"], wk3["result"], wk3["score"]) == ("Away", "W", "24-10") and (wk2["result"], wk2["score"]) == ("T", "17-17")
    assert (wk4["result"], wk4["score"]) == (None, "") and wk4["venue"] == "Home"                    # a game with no final score
    assert wk5["stats"] == {"rec": 5.0, "rec_yds": 50.0, "rec_td": 1.0} and abs(wk5["pts"] - (5 + 5 + 6)) < 1e-9
    assert [k for k, _ in log["stat_cols"]] == ["rec", "rec_yds", "rec_td"]
    assert abs(log["avg"]["stats"]["rec_yds"] - 30.0) < 1e-9 and abs(log["avg"]["pts"] - (2 + 4 + 6 + 8 + 16) / 5) < 1e-9


def test_slot_game_log_average_is_over_the_rows_shown():
    allowed, meta = log_fixture()
    five = PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, n=None)
    three = PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, n=3)
    assert five["games"] == 5 and three["games"] == 3
    assert abs(five["avg"]["pts"] - sum(1 * k + 1 * k + (6 if k == 5 else 0) for k in range(1, 6)) / 5) < 1e-9
    assert abs(three["avg"]["stats"]["rec"] - (5 + 4 + 3) / 3) < 1e-9 and [r["order"] for r in three["rows"]] == [5, 4, 3]


def test_slot_game_log_venue_filters_before_the_window_and_unknown_venues_drop_out():
    allowed, meta = log_fixture()
    home = PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, n=2, venue="Home")
    assert [r["order"] for r in home["rows"]] == [5, 4]                           # the two NEWEST home games, not "home games among the last two"
    away = PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, n=10, venue="Away")
    assert [r["order"] for r in away["rows"]] == [3, 2]
    nometa = PM.slot_game_log(allowed, "DAL", "WR1", "NFL", {}, n=10, venue="Home")
    assert nometa["rows"] == [] and nometa["avg"] is None and nometa["games"] == 0
    assert PM.slot_game_log(allowed, "DAL", "WR1", "NFL", {}, n=10)["games"] == 5            # no schedule at all still lists the games


def test_a_game_where_the_opponent_had_nobody_at_the_slot_is_a_row_of_zeros():
    allowed, meta = log_fixture()
    log = PM.slot_game_log(allowed, "DAL", "WR2", "NFL", meta, n=10)
    wk4 = [r for r in log["rows"] if r["order"] == 4][0]
    assert wk4["who"] == "" and wk4["pts"] == 0.0 and set(wk4["stats"].values()) == {0.0}
    assert abs(log["avg"]["stats"]["rec"] - 4 / 5) < 1e-9                             # the zero week is in the average


def test_slot_game_log_for_an_unknown_defense_is_empty():
    allowed, meta = log_fixture()
    log = PM.slot_game_log(allowed, "NOPE", "QB", "NFL", meta)
    assert log["rows"] == [] and log["avg"] is None and [k for k, _ in log["stat_cols"]] == ["pass_yds", "pass_td", "rush_yds"]


def test_basketball_log_lists_a_group_with_its_top_three_names():
    pgs = [pg("g", "2026-10-01T00:00Z", "A", "B", i, f"P{i}", "G", min=30 - i, pts=10 + i, reb=1, ast=1, fg3m=i) for i in range(1, 5)]
    allowed = PM.allowed_by_slot(pgs, "NBA")
    meta = PM.build_game_meta([dict(order="2026-10-01T00:00Z", date="2026-10-01T00:00Z", home="A", away="B", home_score=100, away_score=90)])
    log = PM.slot_game_log(allowed, "B", "G", "NBA", meta)
    r = log["rows"][0]
    assert r["who"] == "P4, P3, P2" and (r["venue"], r["result"]) == ("Away", "L") and abs(r["pts"] - (11 + 12 + 13 + 14 + 4 + 4)) < 1e-9
    assert [lbl for _, lbl in log["stat_cols"]] == ["pts", "reb", "ast", "3PM"]


def test_defense_options_puts_the_game_first_and_ncaamb_stays_to_the_two_teams():
    allowed = {k: [] for k in ("Zed", "Home", "Alpha", "Away", "Beta")}
    names = {"Zed": "Zed FC", "Alpha": "alpha FC", "Beta": "Beta FC", "Home": "Home", "Away": "Away"}
    assert PM.defense_options(allowed, "Home", "Away", names, "NFL") == ["Home", "Away", "Alpha", "Beta", "Zed"]      # A-Z by display name, case-blind
    assert PM.defense_options(allowed, "Home", "Away", names, "NCAAMB") == ["Home", "Away"]
    assert PM.defense_options({"Away": []}, "Home", "Away", names, "NFL") == ["Away"]          # a team with no games is not offered
    assert PM.defense_options({}, "Home", "Away", names, "NBA") == []


def test_hit_rate_counts_overs_and_treats_the_line_as_a_push():
    allowed, meta = log_fixture()
    rows = PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, n=10)["rows"]              # rec yds 50, 40, 30, 20, 10
    assert PM.hit_rate(rows, "rec_yds", 30) == {"hits": 2, "games": 5, "pct": 40.0}
    assert PM.hit_rate(rows, "rec_yds", 29.5)["hits"] == 3 and PM.hit_rate(rows, "rec_yds", 0)["pct"] == 100.0
    assert PM.hit_rate(rows, "pts", 100)["hits"] == 0 and PM.hit_rate(rows, "pts", 6)["hits"] == 2        # points 2, 4, 6, 8, 16 — the 6 is a push
    assert PM.hit_rate(rows, "nope", 0.5)["hits"] == 0 and PM.hit_rate([], "rec", 1) is None


def test_heat_css_is_green_above_average_red_below_deeper_further_out():
    css = PM.heat_css([10, 20, 30, 40, 50])
    assert css[2] == "" and css[4].startswith("background-color: rgba(34, 170, 85") and css[0].startswith("background-color: rgba(214, 68, 68")
    alpha = lambda c: float(c.rsplit(",", 1)[1].strip(" )"))
    assert alpha(css[4]) > alpha(css[3]) > 0.12 and alpha(css[0]) > alpha(css[1]) > 0.12 and abs(alpha(css[4]) - 0.55) < 1e-9
    assert PM.heat_css([5, 5, 5]) == ["", "", ""] and PM.heat_css([]) == [] and PM.heat_css([None, None]) == ["", ""]
    mixed = PM.heat_css([None, 0, 10])
    assert mixed[0] == "" and mixed[1].startswith("background-color: rgba(214") and mixed[2].startswith("background-color: rgba(34")


def test_when_label_handles_football_weeks_and_basketball_dates():
    assert PM.when_label(5, "2026-10-04") == "Wk 5 · 10/04/26" and PM.when_label(5, "") == "Wk 5"
    assert PM.when_label("2026-10-04T23:00Z", "2026-10-04") == "10/04/26"
    assert PM.when_label(5, "2026/10/04") == "Wk 5" and PM.when_label(5, "10-04-2026!") == "Wk 5"            # only a YYYY-MM-DD date is reformatted
    assert dict(PM.LOG_SIZES) == {"Last 5": 5, "Last 10": 10, "Last 16": 16, "All sampled": None} and PM.LOG_VENUES == ("All", "Home", "Away")
    assert PM.when_label("2026-10-04T23:00Z", "") == "10/04/26" and PM.when_label(None, "") == "" and PM.when_label("x", "junk") == ""


def test_log_table_flattens_the_log_for_display():
    allowed, meta = log_fixture()
    log = PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, n=3)
    names = {"O5": "Five FC", "O3": "Three FC"}
    rows = PM.log_table(log, names, PM.METRIC_SHORT["football"])
    assert list(rows[0]) == ["Date", "Opponent", "W/L", "Score", "Player", "rec", "rec yds", "rec TD", "Fantasy pts"]
    assert rows[0]["Opponent"] == "vs Five FC" and rows[2]["Opponent"] == "at Three FC" and rows[1]["Opponent"] == "vs O4"
    assert rows[0]["W/L"] == "L" and rows[1]["W/L"] == "—" and rows[1]["Score"] == "—" and rows[0]["Date"] == "Wk 5 · 10/04/26"
    assert rows[0]["rec yds"] == 50.0 and rows[0]["Player"] == "Star5" and abs(rows[0]["Fantasy pts"] - 16.0) < 1e-9
    bare = PM.log_table(PM.slot_game_log(allowed, "DAL", "WR1", "NFL", {}, n=1), {}, "Fantasy pts")
    assert bare[0]["Opponent"] == "O5" and bare[0]["Date"] == "Wk 5"


# ------------------------------------------------------------------ build 225: NFL log filters, periods, charts
def test_build_game_meta_derives_primetime_stadium_role_and_total():
    m = PM.build_game_meta([dict(order=1, date="2026-09-06", home="A", away="B", time="20:20", roof="dome", spread=3.5, total=47),
                            dict(order=2, date="2026-09-13", home="A", away="B", time="13:00", roof="outdoors", spread=-2.5)])
    assert m[(1, "A", "B")]["primetime"] is True and m[(1, "A", "B")]["setting"] == "Indoors"
    assert (m[(1, "A", "B")]["role"], m[(1, "B", "A")]["role"], m[(1, "A", "B")]["total"]) == ("Favorite", "Underdog", 47.0)
    assert m[(2, "A", "B")]["primetime"] is False and m[(2, "A", "B")]["setting"] == "Outdoors"
    assert (m[(2, "A", "B")]["role"], m[(2, "B", "A")]["role"]) == ("Underdog", "Favorite")      # spread is the HOME margin


def test_primetime_roof_and_pickem_edges():
    assert PM.is_primetime("19:00") is True and PM.is_primetime("18:59") is False and PM.is_primetime("12:30") is False
    assert PM.is_primetime(None) is None and PM.is_primetime("") is None and PM.is_primetime("xx:yy") is None and PM.is_primetime("n/a") is None
    assert [PM.roof_setting(x) for x in ("dome", "CLOSED", "outdoors", "open", "", None, "retractable")] == \
        ["Indoors", "Indoors", "Outdoors", "Outdoors", None, None, None]
    m = PM.build_game_meta([dict(order=1, home="A", away="B", spread=0)])
    assert m[(1, "A", "B")]["role"] is None and m[(1, "B", "A")]["role"] is None                   # a pick'em has no favourite


def per_fixture():
    """DAL's defense over four games; WR1 = Star{n}. Weekly totals plus play-by-play halves for each."""
    pgs, look = [], {}
    for wk in range(1, 5):
        pgs.append(pg(f"g{wk}", wk, f"O{wk}", "DAL", f"a{wk}", f"Star{wk}", "WR", tgt=10, rec=wk, rec_yds=10 * wk))
        full = {"tgt": 10.0, "rec": float(wk), "rec_yds": 10.0 * wk, "rec_td": 0.0, "rec_long": 5.0 * wk, "tgt_share": 25.0, "td": 0.0}
        h1 = dict(full, rec=1.0, rec_yds=4.0 * wk)
        h2 = dict(full, rec=float(wk - 1), rec_yds=6.0 * wk)
        look[(wk, f"O{wk}", f"a{wk}")] = {"Full Game": full, "1st Half": h1, "2nd Half": h2}
    games = [dict(order=1, date="2026-09-06", home="DAL", away="O1", home_score=30, away_score=20, time="20:15", roof="dome", spread=3),
             dict(order=2, date="2026-09-13", home="O2", away="DAL", home_score=17, away_score=20, time="13:00", roof="outdoors", spread=-3),
             dict(order=3, date="2026-09-20", home="DAL", away="O3", home_score=10, away_score=24, time="13:00", roof="outdoors", spread=-4),
             dict(order=4, date="2026-09-27", home="O4", away="DAL", home_score=7, away_score=3, time="20:15", roof="dome", spread=1)]
    allowed = PM.allowed_by_slot(pgs, "NFL")
    return allowed, PM.build_game_meta(games), look


def test_attach_periods_counts_matches_and_gives_empty_for_missing_players():
    allowed, _, look = per_fixture()
    del look[(2, "O2", "a2")]
    assert PM.attach_periods(allowed, look) == 3
    by = {g["order"]: g for g in allowed["DAL"]}
    assert by[1]["periods"]["WR1"]["1st Half"]["rec"] == 1.0 and by[2]["periods"]["WR1"] == {}


def test_period_selects_the_part_of_the_game_and_unavailable_falls_back_with_flag():
    allowed, meta, look = per_fixture()
    PM.attach_periods(allowed, look)
    cols = PM.log_columns("NFL", "WR1")
    h1 = PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, period="1st Half", columns=cols)
    assert h1["period_ok"] and [r["stats"]["rec_yds"] for r in h1["rows"]] == [16.0, 12.0, 8.0, 4.0]
    h2 = PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, period="2nd Half", columns=cols)
    assert [r["stats"]["rec"] for r in h2["rows"]] == [3.0, 2.0, 1.0, 0.0]
    q3 = PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, period="Q3", columns=cols)
    assert all(r["stats"]["rec_yds"] == 0 for r in q3["rows"])                                  # no Q3 entry = all zeros
    plain, _m, _l = per_fixture()                                                                 # no periods attached
    p = PM.slot_game_log(plain, "DAL", "WR1", "NFL", meta, period="1st Half")
    assert p["period_ok"] is False and [r["stats"]["rec_yds"] for r in p["rows"]] == [40.0, 30.0, 20.0, 10.0]
    assert PM.slot_game_log(plain, "DAL", "WR1", "NFL", meta)["period_ok"] is True


def test_columns_follow_the_data_and_keep_the_order_of_the_slot_set():
    allowed, meta, look = per_fixture()
    PM.attach_periods(allowed, look)
    log = PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, columns=PM.log_columns("NFL", "WR1"))
    keys = [k for k, _ in log["stat_cols"]]
    assert "rec_yds" in keys and "pass_att" not in keys and "tgt_share" in keys
    assert keys == [k for k, _ in PM.log_columns("NFL", "WR1") if k in keys]
    assert {k for k, _ in PM.log_columns("NFL", "QB")} >= {"atd", "pass_att", "pass_cmp", "pass_yds", "pass_long", "pass_td", "pass_int"}
    assert {k for k, _ in PM.log_columns("NFL", "RB1")} >= {"rush_att", "rush_yds", "rush_long", "rush_share", "rush_rec_yds", "td"}
    assert "rec_long" in {k for k, _ in PM.log_columns("NFL", "TE1")} and PM.log_columns("NBA", "G")


def test_every_filter_applies_before_the_window():
    allowed, meta, look = per_fixture()
    PM.attach_periods(allowed, look)
    def rows(**kw):
        return [r["order"] for r in PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, **kw)["rows"]]
    assert rows(primetime=True) == [4, 1] and rows(primetime=True, n=1) == [4]
    assert PM.build_game_meta([dict(order=9, home="DAL", away="O9")])[(9, "DAL", "O9")]["primetime"] is None       # unknown kickoff: neither
    assert rows(setting="Indoors") == [4, 1] and rows(setting="Outdoors") == [3, 2]
    assert rows(role="Favorite") == [2, 1] and rows(role="Underdog") == [4, 3]                   # spread is the HOME margin
    assert rows(venue="Home") == [3, 1] and rows(venue="Home", n=1) == [3]
    assert rows(only_opp="O2") == [2] and rows(only_opp="NOPE") == []
    assert rows(ranges=[("rec_yds", 25, None)]) == [4, 3] and rows(ranges=[("rec_yds", None, 20)]) == [2, 1]
    assert rows(ranges=[("rec_yds", 20, 30)]) == [3, 2] and rows(ranges=[("nope", 999, None)]) == [4, 3, 2, 1]
    assert rows(primetime=True, setting="Indoors", venue="Away") == [4]


def test_without_filter_needs_every_named_defender_out():
    allowed, meta, look = per_fixture()
    ab = {(1, "DAL"): ["Parsons", "Diggs"], (3, "DAL"): ["Parsons"], (4, "DAL"): []}
    f = lambda w: [r["order"] for r in PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, without=w, absences=ab)["rows"]]
    assert f(["Parsons"]) == [3, 1] and f(["Parsons", "Diggs"]) == [1] and f(["Nobody"]) == [] and f([]) == [4, 3, 2, 1]


def test_hit_rates_over_posted_lines():
    allowed, meta, look = per_fixture()
    log = PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta)
    hr = PM.hit_rates(log["rows"], {"rec_yds": 25.0, "rec": 2.0, "tgt_share": 40.0})
    assert hr["rec_yds"] == {"hits": 2, "games": 4, "pct": 50.0} and hr["rec"]["hits"] == 2 and hr["tgt_share"]["hits"] == 0
    assert PM.hit_rates(log["rows"], {}) == {} and PM.hit_rate([], "rec", 1.0) is None
    assert PM.hit_rate(log["rows"], "rec", 2.0)["hits"] == 2                                      # exactly on the line is a push, not a hit


def test_chart_allowed_uses_the_charted_player_and_falls_back_sensibly():
    pgs = [pg("g1", 1, "O1", "DAL", "w1", "UsageWr", "WR", tgt=9, rec=5, rec_yds=60),
           pg("g1", 1, "O1", "DAL", "w2", "ChartWr", "WR", tgt=4, rec=2, rec_yds=20),
           pg("g1", 1, "O1", "DAL", "q1", "BackupQb", "QB", pass_att=30, pass_yds=250),
           pg("g2", 2, "O2", "DAL", "w3", "OtherWr", "WR", tgt=7, rec=4, rec_yds=44)]
    allowed = PM.allowed_by_slot(pgs, "NFL")
    look = {(1, "O1", "w1"): {"Full Game": {"rec": 5.0, "rec_yds": 60.0}}, (1, "O1", "w2"): {"Full Game": {"rec": 2.0, "rec_yds": 20.0}},
            (1, "O1", "q1"): {"Full Game": {"pass_yds": 250.0}}, (2, "O2", "w3"): {"Full Game": {"rec": 4.0, "rec_yds": 44.0}}}
    charts = {(1, "O1"): {"WR1": ("w2", "ChartWr"), "WR2": ("w9", "Inactive"), "QB": ("q0", "InactiveQb")}}
    out = PM.chart_allowed(allowed, charts, look)
    g1 = [g for g in out["DAL"] if g["order"] == 1][0]
    assert g1["slot_source"] == "chart" and g1["who"]["WR1"] == ["ChartWr"] and g1["slots"]["WR1"]["rec_yds"] == 20.0
    assert g1["pids"]["WR1"] == ["w2"] and g1["periods"]["WR1"]["Full Game"]["rec"] == 2.0
    assert g1["who"]["WR2"] == ["Inactive"] and g1["slots"]["WR2"] == {} and g1["periods"]["WR2"] == {}      # listed, did nothing
    assert g1["who"]["QB"] == ["BackupQb"] and g1["slots"]["QB"]["pass_yds"] == 250.0                          # listed QB never played
    g2 = [g for g in out["DAL"] if g["order"] == 2][0]
    assert g2["slot_source"] == "usage" and g2["who"]["WR1"] == ["OtherWr"]                                    # no chart on file
    assert [g["who"]["WR1"] for g in allowed["DAL"] if g["order"] == 1] == [["UsageWr"]]                      # input untouched


def test_primetime_filter_drops_games_with_an_unknown_kickoff():
    allowed, meta, look = per_fixture()
    meta[(2, "DAL", "O2")]["primetime"] = None
    meta[(3, "DAL", "O3")]["primetime"] = None
    assert [r["order"] for r in PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, primetime=True)["rows"]] == [4, 1]
    assert [r["order"] for r in PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta)["rows"]] == [4, 3, 2, 1]


def test_requested_columns_the_data_cannot_fill_are_dropped_with_periods_and_without():
    allowed, meta, look = per_fixture()
    asked = (("rec", "REC"), ("pass_att", "PASS ATT"))
    assert [k for k, _ in PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, columns=asked)["stat_cols"]] == ["rec"]
    PM.attach_periods(allowed, look)
    assert [k for k, _ in PM.slot_game_log(allowed, "DAL", "WR1", "NFL", meta, columns=asked)["stat_cols"]] == ["rec"]
