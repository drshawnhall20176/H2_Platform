import calibration as CAL
import parlay_check as PC


def test_parse_alt_lines_sides_and_prices():
    legs, bad = PC.parse("Rachaad White | Rush + Rec Yards | 50+ | -400\n"
                         "Collin Sexton | Assists | Over 1.5\n"
                         "Matisse Thybulle | Points | under | 7.5 | +110\n"
                         "Broken | Points\n")
    assert [(l["side"], l["line"], l["price"]) for l in legs] == [("Over", 49.5, -400.0), ("Over", 1.5, None),
                                                                  ("Under", 7.5, 110.0)]
    assert len(bad) == 1


def test_read_leg_uses_the_model_at_the_alt_line_and_flags_unknowns():
    reads = {(1, "x"): {"player": "Rachaad White", "market": "Rush + Rec Yards", "projection": 70.0, "values": [60, 80, 75, 65],
                        "dist": "normal", "line": 62.5, "p_final": 0.6, "slot": "RB1", "team_name": "WAS", "game": "PHI @ WAS"}}
    w = PC.read_leg({"player": "Rachaad White", "market": "Rush + Rec Yards", "side": "Over", "line": 49.5, "price": None},
                    reads, None)
    assert w["source"] == "model (alt line)" and w["p"] > 0.8 and w["cushion"] > 0.3
    at_line = PC.read_leg({"player": "R. White", "market": "Rush + Rec Yards", "side": "Over", "line": 62.5, "price": None},
                          reads, None)
    assert at_line["p"] == 0.6 and at_line["source"].startswith("model + books")
    unk = PC.read_leg({"player": "Nobody", "market": "Points", "side": "Over", "line": 7.5, "price": 110}, reads, None)
    assert unk["source"].startswith("your price") and 0.4 < unk["p"] < 0.5
    flip = PC.read_leg({"player": "Nobody", "market": "Points", "side": "Over", "line": 7.5, "price": None}, reads, None)
    assert flip["p"] == 0.5 and flip["flags"]


def test_check_prices_the_ticket_and_names_the_weak_leg():
    legs = [dict(player=f"P{i}", market="Receptions", side="Over", line=2.5, p=0.8, cushion=0.3, team=None, slot=None,
                 game=None, flags=[], source="model") for i in range(7)]
    legs.append(dict(player="Weak", market="Receiving Yards", side="Over", line=29.5, p=0.45, cushion=0.02, team=None,
                     slot=None, game=None, flags=[], source="model"))
    r = PC.check(legs, 500)
    assert abs(r["p_all"] - 0.8 ** 7 * 0.45) < 1e-9 and r["p_miss_one"] > r["p_all"]
    assert r["weakest"]["player"] == "Weak" and r["ev"] < 0
    assert any("below the bar" in w for w in r["warnings"]) and any("under 50%" in w for w in r["warnings"])


def test_script_conflicts():
    legs = [dict(player="RB", market="Rush Attempts", side="Over", slot="RB1", team="WAS"),
            dict(player="QB", market="Pass Attempts", side="Over", slot="QB", team="WAS"),
            dict(player="WR", market="Receptions", side="Over", slot="WR1", team="WAS")]
    out = PC.script_conflicts(legs)
    assert len(out) == 1 and "WAS" in out[0]


def test_calibration_fit_shrinks_an_optimistic_model():
    rows = []
    for i in range(400):                      # shown 65%, hit 55%
        rows.append({"result": "hit" if i % 20 < 11 else "miss", "chance": 0.65, "market": "Points"})
    rows += [{"result": "hit", "chance": 0.3, "market": "Anytime TD"}] * 50      # scorer props are left out
    f = CAL.fit(rows)
    assert f["enough"] and f["n"] == 400 and f["s"] == 0.5          # 65% shown, 55% hit: as far as it may go
    assert f["log_loss"][1] <= f["log_loss"][0]
    assert CAL.honest(0.65, 0.5) == 0.575 and CAL.chance("NFL", 0.3, "Anytime TD") == 0.3
    assert CAL.fit(rows[:20])["s"] == 1.0
