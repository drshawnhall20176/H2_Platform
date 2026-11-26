"""Nov 26: NFL zones -- where a receiver's targets go and what the defense allows there."""
import nfl_zones as Z


def test_names_match_nflverse_short_form():
    assert Z.short_name("Amon-Ra St. Brown") == Z.pbp_short("A.St. Brown") == "a st brown"
    assert Z.short_name("Trey McBride") == Z.pbp_short("T.McBride")
    assert Z.short_name("Marvin Harrison Jr.") == "m harrison"


def _rows():
    rows = []
    for i in range(40):                                  # him: 20 left, 10 middle, 10 right
        side = "left" if i < 20 else "middle" if i < 30 else "right"
        rows.append({"week": 1, "off": "DET", "def": "GB", "rec": "a st brown", "side": side, "yds": 8.0, "comp": 1})
    for t in [f"T{i}" for i in range(10)] + ["CHI"]:     # every defense: 40 throws a side
        for side in Z.SIDES:
            for k in range(40):
                y = 14.0 if (t == "CHI" and side == "middle") else 7.0
                rows.append({"week": 2, "off": "X", "def": t, "rec": "x y", "side": side, "yds": y, "comp": 1})
    return rows


def test_player_split_and_soft_side():
    rows = _rows()
    me = Z.player(rows, "Amon-Ra St. Brown", "DET")
    assert me["targets"] == 40 and me["sides"]["left"]["share"] == 0.5
    de = Z.defense(rows, "CHI")
    assert de["middle"]["tier"] == "soft" and de["middle"]["rank"] == 1
    assert de["left"]["tier"] == "average"
    s = Z.sentences(me, de, "CHI")
    assert s[0].startswith("He's targeted to the **left** most: 50%")
    assert "CHI's soft side is the **middle**" in s[1]
    assert [r["Read"] for r in Z.table(me, de)] == ["⚪ About average", "🟢 Soft", "⚪ About average"]


def test_thin_sample_is_quiet():
    assert Z.player(_rows()[:5], "Amon-Ra St. Brown", "DET") is None
    assert Z.team_abbr("Detroit Lions") == "DET" and Z.team_abbr("DET") == "DET"
