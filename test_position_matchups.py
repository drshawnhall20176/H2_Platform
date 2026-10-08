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
