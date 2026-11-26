"""Nov 26: each Test-list pick against a chosen book's current price -- Go / Thin / No go, different lines flagged."""
import book_check as BC

OFFERS = [
    {"market": "player_points", "player": "LeBron James", "point": 18.5,
     "over": {"draftkings": -105, "fanduel": -110}, "under": {"draftkings": -125, "fanduel": -108},
     "pickem": {"pick6": {"under": {"price": None}}}},
    {"market": "player_points", "player": "LeBron James", "point": 19.5,
     "over": {"betmgm": 110}, "under": {"betmgm": -140}},
]
BOOKS = ["draftkings", "fanduel", "betmgm"]


def test_go_thin_no_go_at_the_same_line():
    q = BC.prop_quotes(OFFERS, "Lebron James", "player_points", "Under")
    row = {"kind": "🃏 Bet", "line": 18.5, "side": "Under", "chance": 0.524}
    dk = BC.judge(row, q, "draftkings", BOOKS)
    assert dk["book_verdict"] == BC.NOGO and abs(dk["book_need"] - 125 / 225) < 1e-9
    fd = BC.judge(row, q, "fanduel", BOOKS)
    assert fd["book_verdict"] == BC.THIN                       # needs 51.9%, has 52.4%
    assert dk["best_book"] == "fanduel" and dk["best_price"] == -108
    assert BC.judge(dict(row, chance=0.56), q, "fanduel", BOOKS)["book_verdict"] == BC.GO


def test_a_different_line_is_flagged_not_called_a_go():
    q = BC.prop_quotes(OFFERS, "LeBron James", "player_points", "Under")
    v = BC.judge({"kind": "🃏 Bet", "line": 18.5, "side": "Under", "chance": 0.6}, q, "betmgm", BOOKS)
    assert v["book_verdict"].startswith(BC.OTHER) and "19.5 (better)" in v["book_verdict"]
    v = BC.judge({"kind": "🃏 Bet", "line": 18.5, "side": "Over", "chance": 0.6},
                 BC.prop_quotes(OFFERS, "LeBron James", "player_points", "Over"), "betmgm", BOOKS)
    assert v["book_verdict"].startswith(BC.NOGO)              # Over 19.5 is a worse number


def test_not_posted_and_paper():
    q = BC.prop_quotes(OFFERS, "LeBron James", "player_points", "Under")
    assert BC.judge({"kind": "🃏 Bet", "line": 18.5, "side": "Under", "chance": 0.6}, q, "bovada", BOOKS)[
        "book_verdict"] == BC.NONE
    assert BC.judge({"kind": "🧪 Close gap (paper)", "line": 18.5, "side": "Under", "chance": None}, q,
                    "draftkings", BOOKS)["book_verdict"] == BC.PAPER


def test_pickem_app_column():
    q = BC.prop_quotes(OFFERS, "LeBron James", "player_points", "Under")
    assert BC.judge_app({"line": 18.5, "side": "Under", "chance": 0.6}, q, "pick6", 0.585).startswith(BC.GO)
    assert BC.judge_app({"line": 18.5, "side": "Under", "chance": 0.55}, q, "pick6", 0.585).startswith(BC.NOGO)
    assert BC.judge_app({"line": 18.5, "side": "Under", "chance": 0.55}, q, "prizepicks", 0.585) == BC.NONE
    assert BC.judge_app({"open_as": "game"}, q, "pick6", 0.585) == "— Props only"


EVENT = {"home_team": "North Carolina Tar Heels", "away_team": "Duke Blue Devils", "bookmakers": [
    {"key": "draftkings", "markets": [
        {"key": "spreads", "outcomes": [{"name": "North Carolina Tar Heels", "point": -3.0, "price": -110},
                                        {"name": "Duke Blue Devils", "point": 3.0, "price": -110}]},
        {"key": "totals", "outcomes": [{"name": "Over", "point": 150.5, "price": -112},
                                       {"name": "Under", "point": 150.5, "price": -108}]},
        {"key": "h2h", "outcomes": [{"name": "North Carolina Tar Heels", "price": -150},
                                    {"name": "Duke Blue Devils", "price": 130}]}]},
    {"key": "fanduel", "markets": [
        {"key": "spreads", "outcomes": [{"name": "North Carolina Tar Heels", "point": -2.5, "price": -115}]}]}]}


def test_game_lines():
    ev = BC.find_event([EVENT], "North Carolina", "Duke")
    assert ev is EVENT
    q = BC.game_quotes(ev, "Spread", "home", "North Carolina", "Duke")
    dk = BC.judge({"kind": "💰 Money pick", "line": -3.0, "side": "home", "chance": 0.55}, q, "draftkings",
                  ["draftkings", "fanduel"])
    assert dk["book_verdict"] == BC.GO
    fd = BC.judge({"kind": "💰 Money pick", "line": -3.0, "side": "home", "chance": 0.55}, q, "fanduel",
                  ["draftkings", "fanduel"])
    assert "-2.5 (better)" in fd["book_verdict"]                 # laying 2.5 beats laying 3
    t = BC.game_quotes(ev, "Total", "under", "North Carolina", "Duke")
    assert t[150.5]["books"]["draftkings"] == -108
    ml = BC.game_quotes(ev, "Moneyline", "away", "North Carolina", "Duke")
    assert BC.judge({"kind": "🃏 Bet", "line": None, "side": "away", "chance": 0.45}, ml, "draftkings",
                    ["draftkings"])["book_verdict"] == BC.GO


def test_compare_price_and_line():
    assert BC.compare(-105, 18.5, -110, 18.5, "Under") == "▲ -105 vs -110"
    assert BC.compare(-120, 18.5, -110, 18.5, "Under") == "▼ -120 vs -110"
    assert BC.compare(-110, 18.5, -110, 18.5, "Under") == "= same"
    assert BC.compare(-130, 19.5, -110, 18.5, "Under").startswith("▲ line 19.5 vs 18.5")
    assert BC.compare(100, 1.5, -110, 2.5, "home").startswith("▼ line 1.5 vs 2.5")
    assert BC.compare(None, None, -110, 2.5, "home") == "—"
