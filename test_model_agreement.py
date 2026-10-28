"""
test_model_agreement.py — one model, one answer: the shared form / matchup / fatigue numbers across Position
Matchups, Hot Hand Engine and Matchup Lab, and the market-disagreement policy.

    python -m pytest test_model_agreement.py
"""

import nba_projections as NP
import player_props as PPR
import position_matchups as PM
import props_engine as PE
import quick_log


def mitchell_row():
    log = ([dict(pts=p, reb=r, ast=a, fg3m=t, min=34, src="current") for p, r, a, t in
            ((21, 0, 2, 2), (22, 1, 10, 3), (18, 2, 5, 3), (11, 0, 11, 1))] +
           [dict(pts=p, reb=r, ast=a, fg3m=t, min=30, src="prior") for p, r, a, t in
            ((12, 2, 1, 2), (15, 3, 11, 0), (9, 1, 6, 1), (12, 4, 6, 2))])
    return {"Player": "Davion Mitchell", "Team": "Miami Heat", "Opp": "Atlanta Hawks", "GameLabel": "MIA @ ATL",
            "AvgMin": 33, "PTS": 15.0, "REB": 1.6, "AST": 6.5, "FG3M": 1.8, "_pid": 7, "_team_id": 1,
            "_opp_id": 2, "_game_log": log}


# --------------------------------------------------------------------------- one form number
def test_hot_hand_and_matchup_lab_show_the_same_form_as_player_props():
    row = mitchell_row()
    board = NP.build_hot_hand_board([row], {2: {"pts": 110, "reb": 44, "ast": 26, "fg3m": 12, "poss": 100}})
    hh = next(b for b in board if b["Market"] == "Points")["Recent Avg"]
    lab = next(p for p in NP.build_matchup_profile(row, [], {}, {}) if p["Market"] == "Points")["Recent Avg"]
    cur = [dict(game=f"c{i}", order=f"2026-10-2{i}", team=1, opp=9, pid=7, name="DM", pos="PG",
                stats=dict(min=34, pts=p)) for i, p in enumerate((11, 18, 22, 21))]
    prior = [dict(game=f"p{i}", order=f"2026-04-0{i + 1}", team=1, opp=9, pid=7, name="DM", pos="PG",
                  stats=dict(min=30, pts=p)) for i, p in enumerate((12, 9, 15, 12))]
    props = PE.wmean(PPR.form(cur, prior, 7, "Points")["values"],
                     PPR.form_games(cur, prior, 7)["weights"])
    assert hh == lab and abs(hh - props) < 0.06 and 17.5 < hh < 19.0


# --------------------------------------------------------------------------- one matchup number + fatigue
def test_hot_hand_uses_the_position_matchup_and_both_teams_rest():
    row = mitchell_row()
    allowed = {2: {"pts": 110, "reb": 44, "ast": 26, "fg3m": 12, "poss": 100}}
    plain = {b["Market"]: b for b in NP.build_hot_hand_board([row], allowed)}
    pos = {b["Market"]: b for b in NP.build_hot_hand_board([row], allowed, team_rest={2: {"rest_days": 1,
                                                                                         "is_back_to_back": True}},
                                                           position_factors={(7, "pts"): 0.87})}
    p = pos["Points"]
    assert p["Matchup Factor"] == 0.87 and p["Position Matchup"] == 0.87 and p["Team D Factor"] == plain["Points"]["Matchup Factor"]
    assert p["Opp B2B"] and "Opp on B2B" in p["Fatigue"]
    assert abs(p["Matchup Score"] - p["Recent Avg"] * 0.87 * 1.015) < 0.11


def test_position_factors_match_the_player_props_tab():
    def g(game, d, team, opp, pid, pos, pts):
        return dict(game=game, order=d, team=team, opp=opp, pid=pid, name=pid, pos=pos, stats=dict(min=30, pts=pts))
    cur = []
    for t in range(10):
        for i in range(3):
            cur.append(g(f"{t}-{i}", f"2026-10-2{i}", f"O{t}", f"D{t}", f"g{t}", "PG", 30 if t == 0 else 20))
    f = PPR.position_factors({("g5", "D0")}, cur, [], "NBA", mode="season")
    table = PPR.defense_allowed(PM.allowed_by_slot(cur, "NBA"), "Points")
    expected = PPR.blended_factor(PPR.raw_factor(table, "D0", "G"), None, "season")["factor"]
    assert abs(f[("g5", "pts")] - expected) < 1e-12 and f[("g5", "pts")] > 1.0


def test_depth_tab_shows_the_model_matchup_and_says_so_in_callouts():
    rows = [{"slot": "G", "rank": 29, "n_teams": 29, "tier": "Tough", "allowed": 58.8, "league_avg": 88.5,
             "vs_league_pct": -34.0, "thin": False, "trend": "steady", "line": "", "role_change": None,
             "model_factor": 0.87,
             "players": [{"name": "Davion Mitchell", "avg_min": 34, "recent": {"avg": 25.8, "games": 4}, "h2h": None}]}]
    assert PM.display_rows_by_player(rows)[0]["Model matchup"] == "-13%"
    fade = PM.callouts({"rows": rows}, "MIA", "ATL", family="basketball")["fades"][0]
    assert "model -13% after adjusting for the small sample" in fade


# --------------------------------------------------------------------------- when the books disagree
def test_a_big_gap_with_the_books_asks_for_a_news_check_and_trusts_the_market_more():
    vals = [21, 22, 18, 11, 12]
    g = PE.market_gap(18.2, vals, 11.5)
    assert g["level"] == "big" and g["pct"] > 0.5
    held = PE.read_line(18.2, vals, 11.5, "normal", over_price=-114, under_price=-104)
    assert held["gap"] == "big" and held["lean"] == "Check news"
    freed = PE.read_line(18.2, vals, 11.5, "normal", over_price=-114, under_price=-104, news_checked=True)
    assert freed["lean"] in ("Over", "No lean")
    # the model only gets 20% of the vote on a big gap
    p_m, p_k = freed["p_model"], freed["p_market"]
    assert abs(freed["p_final"] - (0.2 * p_m + 0.8 * p_k)) < 1e-9
    small = PE.read_line(23.0, vals, 21.5, "normal", over_price=-110, under_price=-110)
    assert small["gap"] in ("agree", "lean") and abs(small["p_final"] - (0.4 * small["p_model"] + 0.6 * small["p_market"])) < 1e-9


def test_gap_plays_are_listed_tagged_and_logged_with_the_tag():
    row = {"pid": 7, "player": "Davion Mitchell", "slot": "G", "out": False, "line": 11.5, "projection": 18.2,
           "side": "Over", "p_final": 0.56, "lean": "Check news", "gap": "big", "gap_pct": 0.58, "ev": 0.05,
           "over_price": -114, "under_price": -104, "price_src": "book", "flags": []}
    gaps = PE.market_gaps([row], {7: "Miami Heat"})
    assert gaps[0]["Gap"] == "+58%" and "check news" in gaps[0]["Status"]
    view = PE.display_compact([row])[0]
    assert view["Lean"] == "⚠️ Check news" and view["Notes"].startswith("⚠️ Market disagrees")
    play = PE.plays_for_log([row], "Points", "MIA @ ATL")[0]
    assert play["Notes"] == PE.GAP_TAG
    assert quick_log.bet_log_fields_from_play(play, "2026-10-28", "NBA")["notes"] == PE.GAP_TAG
    assert PE.best_reads([row], {}) == []                       # never in "best reads" until the news is checked


# --------------------------------------------------------------------------- parlay correlation
def test_same_player_correlation_follows_shared_stats_and_sides():
    a = {"player": "DM", "game": "g", "side": "Over", "market": "Points"}
    assert abs(PE.leg_correlation(a, dict(a, market="PRA")) - (0.25 + 0.65 / 3 ** 0.5)) < 1e-9
    assert abs(PE.leg_correlation(a, dict(a, market="Rebounds", side="Under")) + 0.25) < 1e-9
    assert PE.leg_correlation(a, dict(a, player="X")) == PE.SAME_GAME
    assert PE.leg_correlation(a, dict(a, game="other")) == 0.0
    assert PE.leg_correlation(a, dict(a, market="Points")) == 0.9


def test_threes_made_is_a_props_market():
    assert PPR.MARKETS["Threes Made"] == ("fg3m",) and PPR.DIST["Threes Made"] == "count"
    assert PPR.ODDS_MARKETS["Threes Made"] == "player_threes"


def test_targets_and_fades_need_the_model_to_agree():
    def row(tier, vs, mf):
        return {"slot": "F", "rank": 4 if tier == "Soft" else 26, "n_teams": 29, "tier": tier, "allowed": 81.2,
                "league_avg": 69.8, "vs_league_pct": vs, "thin": False, "trend": "steady", "line": "",
                "role_change": None, "model_factor": mf,
                "players": [{"name": "Giannis", "avg_min": 32, "recent": {"avg": 43.0, "games": 4}, "h2h": None}]}
    assert PM.callouts({"rows": [row("Soft", 16.0, 0.96)]}, "MIA", "ATL", family="basketball")["targets"] == []
    assert len(PM.callouts({"rows": [row("Soft", 16.0, 1.06)]}, "MIA", "ATL", family="basketball")["targets"]) == 1
    assert PM.callouts({"rows": [row("Tough", -20.0, 1.01)]}, "MIA", "ATL", family="basketball")["fades"] == []
    assert len(PM.callouts({"rows": [row("Soft", 16.0, None)]}, "MIA", "ATL", family="basketball")["targets"]) == 1


# --------------------------------------------------------------------------- Oct 28 Edgecombe retest
def test_pricing_at_draftkings_uses_its_line_and_prices_but_the_consensus_probability():
    offers = [{"market": "player_rebounds", "player": "VJ Edgecombe", "point": 5.5,
               "over": {"draftkings": -125, "betrivers": 102}, "under": {"draftkings": -105, "betrivers": -130}},
              {"market": "player_rebounds", "player": "VJ Edgecombe", "point": 6.5,
               "over": {"fanduel": 120}, "under": {"fanduel": -150}}]
    dk = PE.shop(offers, book="draftkings")
    assert dk["line"] == 5.5 and dk["best_over"] == ("draftkings", -125) and dk["best_under"] == ("draftkings", -105)
    best = PE.shop(offers)
    assert best["best_over"] == ("betrivers", 102)
    assert abs(dk["p_market"] - best["p_market"]) < 1e-12                     # consensus either way
    gone = PE.shop(offers[1:], book="draftkings")
    assert gone["missing_book"] and gone["best_over"] is None and gone["line"] == 6.5


def test_a_combo_a_quarter_off_the_line_is_flagged_even_with_a_wide_spread():
    vals = [24, 24, 14, 27, 30, 12, 35]                                         # PRA: wide game-to-game swings
    assert PE.market_gap(27.3, vals, 20.5)["level"] == "big"                  # +33%: outright rule
    assert PE.market_gap(23.7, [23, 32, 23, 22, 13, 26], 19.5)["level"] != "big"   # +22%, inside his swing


def test_no_lean_when_his_own_hit_rate_contradicts_it():
    threes = [5, 1, 0, 1, 0]                                                    # one big night, misses 1.5 otherwise
    r = PE.read_line(2.1, threes, 1.5, "count", over_price=108, under_price=-140)
    assert r["lean"] == "No lean"
    ok = PE.read_line(2.1, [2, 3, 1, 2, 3], 1.5, "count", over_price=108, under_price=-140)
    assert ok["lean"] in ("Over", "No lean")


def test_a_player_who_missed_the_teams_last_game_gets_a_news_check_on_overs():
    def g(game, d, pid, name, pts, reb):
        return dict(game=game, order=d, team="PHI", opp="X", pid=pid, name=name, pos="SG",
                    stats=dict(min=34, pts=pts, reb=reb, ast=3))
    cur = [g("a", "2026-10-20", 5, "VJ Edgecombe", 9, 4), g("b", "2026-10-22", 5, "VJ Edgecombe", 11, 7),
           g("c", "2026-10-24", 5, "VJ Edgecombe", 17, 13)]
    cur += [g(x, d, 6, "Maxey", 30, 4) for x, d in (("a", "2026-10-20"), ("b", "2026-10-22"), ("c", "2026-10-24"),
                                                     ("d", "2026-10-25"))]                 # PHI played the 25th without him
    rot = [{"pid": 5, "name": "VJ Edgecombe", "slot": "G", "avg_min": 33, "status": None}]
    row = PPR.player_rows(rot, "D", "Rebounds", {}, None, cur, [], lines={5: 5.5}, mode="season",
                          context={"team": "PHI", "prices": {5: {"over": 102, "under": -130}}})[0]
    assert row["returning"] and row["flags"][0].startswith("⚠️ Missed the team's last game")
    assert row["lean"] == "Check news"
    listed = PE.market_gaps([row], {5: "76ers"})
    assert listed and "missed team's last game" in listed[0]["Why flagged"]
    freed = PPR.player_rows(rot, "D", "Rebounds", {}, None, cur, [], lines={5: 5.5}, mode="season",
                            context={"team": "PHI", "news_checked": True, "prices": {5: {"over": 102, "under": -130}}})[0]
    assert freed["lean"] != "Check news" or freed["gap"] == "big"
