"""
Oct 29 fixes after the Oct 28 tickets: the Depth tab names its stat, every props row shows its cushion and the
model's chance at the "N+" milestones, legs carry warnings, and the parlay pages keep thin / flagged legs out.
"""

import grading
import position_matchups as PM
import props_engine as PE


def _row(**kw):
    base = {"pid": 1, "player": "Kevin Durant", "projection": 35.8, "values": [33, 38, 30, 36, 41], "dist": "normal",
            "line": 39.5, "side": "Under", "lean": "No lean", "flags": [], "out": False}
    base.update(kw)
    return base


def test_cushion_is_side_aware_and_milestones_use_n_minus_a_half():
    assert round(PE.cushion(35.8, 39.5, "Over"), 3) == round((35.8 - 39.5) / 39.5, 3)        # negative: wrong side
    assert round(PE.cushion(19.5, 15, "Over"), 3) == round((19.5 - 14.5) / 14.5, 3)           # "15+" clears at 14.5
    assert PE.cushion(28.3, 29.5, "Under") > 0
    r = _row()
    p40 = PE.milestone_chance(r, 40)
    assert abs(p40 - PE.prob_over(35.8, r["values"], 39.5, "normal")) < 1e-9 and p40 < 0.5
    rungs = PE.ladder(r, "PRA")
    assert [n for n, _ in rungs] == [30, 35, 40] and rungs[0][1] > rungs[1][1] > rungs[2][1]
    assert PE.ladder_text(r, "PRA").startswith("30+ ")
    assert [n for n, _ in PE.ladder(dict(r, projection=7.4, values=[6, 8, 7]), "Rebounds")] == [4, 6, 8]


def test_leg_warnings_catch_what_lost_the_tickets():
    assert "missed his team's last game" in PE.leg_warnings(_row(returning=True, projection=25.4), "Over", 21)
    assert any("other side" in w for w in PE.leg_warnings(_row(), "Over", 40))                 # Durant 40+
    assert any("thin cushion" in w for w in PE.leg_warnings(_row(projection=30.9), "Over", 30))   # LeBron 30+
    assert "blowout risk" in PE.leg_warnings(_row(flags=["Blowout risk (+12.5)"], projection=50), "Over", 40)
    assert PE.leg_warnings(_row(projection=22.1), "Over", 15) == []                            # Walter 15+


def test_depth_tab_names_pra_and_splits_it():
    pg = [dict(game=f"g{i}", order=f"2026-10-2{i}", team="HOU", opp="X", pid=6, name="Tari Eason", pos="PF",
               stats=dict(min=24, pts=8, reb=6, ast=2)) for i in range(4)]
    form = PM.player_form(pg, 6, "NBA")
    assert form["avg"] == 16 and form["split"] == {"pts": 8, "reb": 6, "ast": 2}
    rows = [{"slot": "F", "rank": 6, "n_teams": 30, "tier": "Soft", "allowed": 80.8, "league_avg": 69.7,
             "vs_league_pct": 16.0, "thin": False, "trend": "steady", "line": "", "role_change": None, "model_factor": 1.05,
             "players": [{"name": "Tari Eason", "avg_min": 24, "recent": form, "h2h": None}]}]
    d = PM.display_rows_by_player(rows)[0]
    assert d["Last 4 (PRA)"] == "16.0 (4 g)" and d["Last 4 split"] == "8.0 pts · 6.0 reb · 2.0 ast"
    assert "Allowed / g (PRA)" in d and "Last 4" not in d
    text = PM.callouts({"rows": rows}, "HOU", "MIL", family="basketball")["targets"][0]
    assert "averaging 16.0 PRA lately (8.0 pts · 6.0 reb · 2.0 ast)" in text and "allowing 80.8 PRA" in text


def test_parlay_pool_keeps_thin_and_flagged_legs_out():
    def play(name, cushion=None, warnings=None):
        return {"Player": name, "Team": name, "Game": name, "Market": "PRA", "Conviction": 1.6, "_ceiling": 2.0,
                "Cushion": cushion, "Warnings": warnings or []}
    pool = grading.build_parlay_leg_pool([play("Walter", 0.52), play("LeBron", 0.05), play("Edge", 0.3, ["missed his team's last game"]),
                                          play("MLB-style")], max_per_market=10)
    assert {p["Player"] for p in pool} == {"Walter", "MLB-style"}


def test_teammate_bump_is_the_gentler_one():
    assert PE.USAGE_RATE_CAP == 0.10 and PE.REDISTRIBUTE_SHARE == 0.75 and PE.BUMP_MAX_ABS == 8.0
