"""Nov 26: the cards' news -- ESPN headlines matched to the game's teams or the player, plus injury notes."""
from datetime import datetime, timedelta, timezone

import news as NW

NOW = datetime(2026, 11, 26, 15, 0, tzinfo=timezone.utc)


def _art(head, hours_ago, teams=(), athletes=(), desc="A short summary."):
    cats = [{"type": "team", "description": t} for t in teams] + \
           [{"type": "athlete", "description": a} for a in athletes] + [{"type": "league", "description": "NBA"}]
    return {"headline": head, "description": desc, "published": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "links": {"web": {"href": "https://www.espn.com/x"}}, "categories": cats}


JS = {"articles": [
    _art("76ers survive in clutch again", 5, teams=["Philadelphia 76ers"]),
    _art("Heat's Adebayo questionable with back tightness", 2, teams=["Miami Heat"], athletes=["Bam Adebayo"]),
    _art("Old Heat story", 200, teams=["Miami Heat"]),
    _art("Celtics roll", 3, teams=["Boston Celtics"]),
    _art("Knicks guard Jalen Brunson back at practice", 1, teams=[]),
]}


def test_parse_orders_newest_first_and_trims():
    long = {"articles": [_art("X", 1, desc="word " * 100)]}
    it = NW.parse(long)[0]
    assert len(it["summary"]) <= NW.SUMMARY_MAX + 1 and it["summary"].endswith("…")
    got = NW.parse(JS)
    assert got[0]["headline"].startswith("Knicks") and got[0]["url"]


def test_game_news_matches_either_team_recent_only():
    got = NW.for_game(NW.parse(JS), "Miami Heat", "Philadelphia 76ers", now=NOW)
    heads = [g["headline"] for g in got]
    assert heads == ["Heat's Adebayo questionable with back tightness", "76ers survive in clutch again"]


def test_player_news_his_first_then_team():
    got = NW.for_player(NW.parse(JS), "Bam Adebayo", "Miami Heat", now=NOW)
    assert got[0]["about"] == "him" and all(g["headline"] != "Old Heat story" for g in got)
    by_name = NW.for_player(NW.parse(JS), "Jalen Brunson", None, now=NOW)
    assert by_name and by_name[0]["headline"].startswith("Knicks")


def test_injury_notes_and_markdown():
    rep = [{"name": "Bam Adebayo", "team": "Miami Heat", "abbr": "MIA", "status": "questionable",
            "label": "Questionable", "comment": "Back tightness; game-time decision."},
           {"name": "No Note", "team": "Miami Heat", "abbr": "MIA", "status": "out", "label": "Out", "comment": ""}]
    notes = NW.injury_notes("NBA", ("Miami Heat",), report=rep)
    assert [n["name"] for n in notes] == ["Bam Adebayo"]
    md = NW.markdown(NW.for_game(NW.parse(JS), "Miami Heat", "Philadelphia 76ers", now=NOW), notes)
    assert "⚠️ **Bam Adebayo** (Questionable): Back tightness" in md and "[ESPN](https://www.espn.com/x)" in md


def test_feed_failure_is_quiet():
    NW._cache.clear()
    def boom(sport, limit=100):
        raise OSError("down")
    assert NW.items("NBA", get=boom) == []


def test_college_needs_the_team_tag():
    js = {"articles": [_art("Bulldogs roll past rivals", 2, teams=[]),
                       _art("Georgia upsets No. 5", 3, teams=["Georgia Bulldogs"])]}
    got = NW.for_game(NW.parse(js), "Georgia Bulldogs", "Cincinnati Bearcats", now=NOW, sport="NCAAMB")
    assert [g["headline"] for g in got] == ["Georgia upsets No. 5"]


def test_league_wide_roundups_are_left_out_unless_the_headline_names_the_team():
    every = ["Chicago Bears", "Detroit Lions", "Dallas Cowboys", "Kansas City Chiefs", "Buffalo Bills", "Miami Dolphins"]
    js = {"articles": [_art("NFL Week 12 betting odds: lines for every game", 1, teams=every),
                       _art("2027 NFL draft order projections", 2, teams=every),
                       _art("Can Caleb Williams steer Bears past Lions?", 3, teams=every),
                       _art("How Jeffery Simmons changed the Bears' defense", 4, teams=["Chicago Bears"])]}
    got = [it["headline"] for it in NW.for_game(NW.parse(js), "Chicago Bears", "Detroit Lions", sport="NFL", now=NOW)]
    assert got == ["Can Caleb Williams steer Bears past Lions?", "How Jeffery Simmons changed the Bears' defense"]
