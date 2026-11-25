import injury_check as IC
import long_shots_scan as LSS


def test_classify_reads_status_and_report():
    assert IC.classify("Out", "") == "out"
    assert IC.classify("Day-To-Day", "Barrett (hamstring) is out for Wednesday's game against the Wizards") == "out"
    assert IC.classify("Day-To-Day", "Wade (hamstring) has been downgraded to questionable for Wednesday's game") == "questionable"
    assert IC.classify("Day-To-Day", "Maxey closed Monday's win with 24 points, nine assists") is None
    assert IC._norm("Michael Porter Jr.") == "michael porter"


def _row(player, chance, price=500):
    return {"Player": player, "Bet": "45+ PRA", "pick": f"{player} 45+ PRA", "Price": price, "EV per $1": 0.5,
            "Honest chance": chance, "Projection": 40, "Main line": 38, "Flags": []}


def test_saved_long_shots_drop_players_ruled_out_after_the_scan():
    """Nov 18: RJ Barrett topped the 4:13 PM scan; he was ruled out at 5:55 PM."""
    saved = {"at": "x", "rows": [_row("RJ Barrett", 0.31), _row("Dean Wade", 0.27), _row("Davion Mitchell", 0.30),
                                 _row("Isaiah Hartenstein", 0.26)]}
    saved["top"] = LSS.pick_top(saved["rows"])
    st = {"RJ Barrett": "out", "Dean Wade": "questionable"}.get
    got = LSS.recheck(saved, "NBA", status=st)
    assert [r["Player"] for r in got["top"]] == ["Davion Mitchell", "Isaiah Hartenstein"]
    assert "RJ Barrett" not in {r["Player"] for r in got["rows"]}
    wade = next(r for r in got["rows"] if r["Player"] == "Dean Wade")
    assert "(questionable)" in wade["pick"] and wade["Flags"]
    assert LSS.recheck(saved, "NBA", status=lambda n: None) is saved
    assert LSS.load("NBA", "d", get=lambda k: saved) is saved              # tests' store: no live check


def test_report_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(IC, "_fetch", lambda s: calls.append(s) or {"rj barrett": "out"})
    IC._cache.clear()
    assert IC.report("NBA", now=1000) == {"rj barrett": "out"} and IC.report("NBA", now=1300)
    assert calls == ["NBA"]
    IC.report("NBA", now=2000)
    assert calls == ["NBA", "NBA"]
    IC._cache.clear()


JS = {"injuries": [
    {"displayName": "Boston Bruins", "injuries": [
        {"status": "Injured Reserve", "shortComment": "Hagens (back) is wearing a non-contact sweater.",
         "athlete": {"displayName": "James Hagens", "team": {"abbreviation": "BOS", "displayName": "Boston Bruins"},
                     "position": {"abbreviation": "C"}}, "details": {"type": "Back", "returnDate": "2026-11-27"}},
        {"status": "Day-To-Day", "shortComment": "Zacha (lower body) is questionable for Wednesday.",
         "athlete": {"displayName": "Pavel Zacha", "team": {"abbreviation": "BOS", "displayName": "Boston Bruins"}}},
        {"status": "Day-To-Day", "shortComment": "day-to-day",
         "athlete": {"displayName": "Charlie McAvoy", "team": {"abbreviation": "BOS", "displayName": "Boston Bruins"}}}]},
    {"displayName": "Duke Blue Devils", "injuries": [
        {"status": "Out", "shortComment": "", "athlete": {"displayName": "Some Guard"}}]}]}


def test_parse_keeps_flagged_players_with_their_team():
    got = IC.parse(JS)
    assert [e["name"] for e in got] == ["James Hagens", "Pavel Zacha", "Some Guard"]      # plain day-to-day isn't news
    hag = got[0]
    assert hag["status"] == "out" and hag["abbr"] == "BOS" and hag["returns"] == "2026-11-27" and hag["pos"] == "C"
    assert got[2]["team"] == "Duke Blue Devils"
    assert IC.parse({}) == [] and IC.parse(None) == []


def test_for_team_matches_abbreviation_full_name_nickname_and_school():
    rep = IC.parse(JS)
    for t in ("BOS", "Boston Bruins", "Bruins"):
        assert [e["name"] for e in IC.for_team("NHL", t, rep)] == ["James Hagens", "Pavel Zacha"]
    assert [e["name"] for e in IC.for_team("NCAAMB", "Duke", rep)] == ["Some Guard"]
    assert IC.for_team("NHL", "Winnipeg Jets", rep) == [] and IC.for_team("NHL", "", rep) == []


def test_screen_drops_out_players_and_flags_questionable_ones():
    rows = [{"sport": "NBA", "player": "RJ Barrett", "pick": "a"}, {"sport": "NBA", "player": "Dean Wade", "pick": "b"},
            {"sport": "NBA", "player": "Davion Mitchell", "pick": "c"}, {"sport": "SOCCER", "player": "RJ Barrett"}]
    st = {"RJ Barrett": "out", "Dean Wade": "questionable"}
    got = IC.screen(rows, lambda r: r["sport"], lambda r: r.get("player"), status=lambda sp, n: st.get(n))
    assert [r["pick"] for r in got[:2]] == ["b", "c"] and got[0]["_inj"] == "questionable"
    assert got[2]["sport"] == "SOCCER"                                   # no report for that league: left alone
    assert IC.screen(rows, None, None) == rows                           # a failure leaves the rows as they were


def test_player_card_injury_note():
    import player_card as PC
    assert "Out tonight" in PC.injury_note({"Player": "X"}, "NBA", status=lambda s, n: "out")
    assert "Questionable" in PC.injury_note({"Player": "X", "_inj": "questionable"}, "NBA")
    assert PC.injury_note({"Player": "X"}, "NBA", status=lambda s, n: None) == ""


def test_game_card_injury_column():
    import game_card as GC
    html = GC.injuries_html("Boston Bruins", IC.for_team("NHL", "BOS", IC.parse(JS)))
    assert "James Hagens" in html and "back ~11/27" in html and "Pavel Zacha" in html
    assert "Nobody listed" in GC.injuries_html("Jets", [])
