"""Nov 15: one model -- every player page shows the model's read, its own numbers only explain it."""
import model_view as MV

SNAPS = [
    {"player": "Ja'Marr Chase", "market": "Receiving Yards", "line": 80.5, "projection": 74.0, "side": "Under",
     "chance": 0.58, "use_tag": "🎯 Single", "ts": "2026-11-15T12:00"},
    {"player": "Ja'Marr Chase", "market": "Receiving Yards", "line": 81.5, "projection": 75.0, "side": "Under",
     "chance": 0.6, "use_tag": "🎯 Single", "ts": "2026-11-15T15:00"},
    {"player": "Chase Brown", "market": "Anytime TD", "line": 0.5, "projection": 0.5, "side": "Over",
     "chance": 0.44, "p_market": 0.38, "use_tag": "", "ts": "2026-11-15T15:00"},
    {"player": "Kenneth Walker III", "market": "Rush Yards", "line": 70.5, "projection": None},
]


def test_latest_read_wins_and_names_normalize():
    reads = MV.latest_reads("NFL", "2026-11-15", snaps=SNAPS)
    assert reads[("jamarr chase", "Receiving Yards")]["line"] == 81.5
    assert ("kenneth walker", "Rush Yards") not in reads          # no projection -> not a read
    assert MV.norm_name("Kenneth Walker III") == "kenneth walker"
    assert MV.market_of("Rec Yds") == "Receiving Yards" and MV.market_of("Odd One") == "Odd One"


def test_attach_flags_disagreement():
    reads = MV.latest_reads("NFL", "2026-11-15", snaps=SNAPS)
    rows = [{"Player": "Ja'Marr Chase", "Market": "Receiving Yards", "Hot": 95.0},
            {"Player": "JaMarr Chase", "Market": "Rec Yds", "Hot": 70.0},
            {"Player": "Nobody", "Market": "Receptions", "Hot": 3.0}]
    out = MV.attach(rows, reads, own_key="Hot")
    assert out[0]["Model call"] == "Under 81.5" and out[0]["Use"] == "🎯 Single"
    assert out[0]["Agrees"] == "⚠️ model says Under" and out[1]["Agrees"] == "✅"
    assert out[2]["Model call"] == "no line posted" and out[2]["Agrees"] == ""
    assert MV.agreement(out) == (1, 2)


def test_player_calls_and_td():
    reads = MV.latest_reads("NFL", "2026-11-15", snaps=SNAPS)
    calls = MV.player_calls(reads, "Ja'Marr Chase")
    assert [c["Market"] for c in calls] == ["Receiving Yards"] and calls[0]["Chance"] == 0.6
    td = MV.attach_td([{"Player": "Chase Brown", "Rate": 0.30}, {"Player": "X", "Rate": 0.5}], reads,
                      own_key="Rate")
    assert td[0]["Model TD %"] == 0.44 and td[0]["Book TD %"] == 0.38 and td[0]["Model call"].startswith("Yes")
    assert td[0]["Agrees"] == "⚠️ model says Yes"                # 30% own rate sits under the book's 38%
    assert td[1]["Model TD %"] is None and td[1]["Agrees"] == ""
    assert MV.td_yes({"side": "Under", "chance": 0.7}) == 0.30000000000000004 or \
        abs(MV.td_yes({"side": "Under", "chance": 0.7}) - 0.3) < 1e-9


def test_call_shows_the_likelier_side_and_toss_ups():
    over43 = {"line": 2.5, "projection": 2.0, "side": "Over", "chance": 0.43, "use_tag": "⛔ Pass"}
    c = MV.call(over43)
    assert c["Model call"] == "Under 2.5" and abs(c["Chance"] - 0.57) < 1e-9 and c["Use"] == "⛔ Pass"
    flip = MV.call({"line": 5.5, "projection": 5.8, "side": "Over", "chance": 0.49})
    assert flip["Model call"] == "Toss-up at 5.5" and flip["_side"] is None
    rows = MV.attach([{"Player": "A", "Market": "Receptions", "own": 9}],
                     {("a", "Receptions"): {"line": 5.5, "projection": 5.8, "side": "Over", "chance": 0.51}},
                     own_key="own")
    assert rows[0]["Agrees"] == ""
