"""Nov 11: the platform's own daily check-in."""
import morning_brief as MB

REPORTS = {
    "NHL": {"calibration": {"auto": [{"side": "Under", "applied": True, "active": 0.88, "new": 1.0,
                                      "why": "held up on 4 of 4 splits"},
                                     {"side": "Over", "applied": False, "active": 1.0, "why": "not enough yet"}]},
            "auto_tuning": [], "notes": ["2026-11-10: the model's side was right on 405 of 635 (64%).",
                                         "2026-11-10: 🎯 Most probable 37-17 (69%)."]},
    "NBA": {"calibration": {"auto": [{"side": "overall", "applied": False, "active": 1.0, "why": "not enough yet"}]},
            "auto_tuning": [{"market": "RA", "applied": False, "why": "waiting"}], "notes": []},
}
BETS = [
    {"id": 1, "slate_date": "2026-11-10", "stake": 4, "entry_odds": 106, "result": "win", "player": "Maxey"},
    {"id": 2, "slate_date": "2026-11-10", "stake": 4, "entry_odds": -110, "result": "loss", "player": "Rollins"},
    {"id": 3, "slate_date": "2026-11-10", "stake": 6, "entry_odds": 529, "result": "win", "market": "Parlay",
     "ticket": "T1"},
    {"id": 4, "slate_date": "2026-11-10", "stake": 0, "entry_odds": -120, "result": "win", "ticket": "T1",
     "player": "Booker"},
]


def test_morning_note_says_what_ran_learned_and_won():
    health = ["✅ Settling bets", "🔴 Morning review: didn't run"]
    text = MB.morning("2026-11-11", REPORTS, BETS, health)
    assert "🔴 Morning review: didn't run" in text and "✅ Settling bets" not in text
    assert "NHL Unders: 0.88 → 1.00" in text and "waited for more data — nothing for you to do" in text
    assert "Singles: 1–1" in text and "Parlays: 1–0, +$31.74" in text and "missed: Rollins" in text
    assert "Total: +$31.98" in text
    assert "**NHL**: right on 405 of 635 (64%)" in text


def test_health_lines_from_runs():
    runs = {"settle-results.yml": [{"status": "completed", "conclusion": "success"}],
            "capture-closing-lines.yml": [{"status": "completed", "conclusion": "failure"}],
            "script-learn.yml": [], "daily-review.yml": [{"status": "completed", "conclusion": "success"},
                                                         {"status": "completed", "conclusion": "failure"}]}
    got = MB.job_health(None, fetch=lambda wf: runs[wf])
    assert got == ["✅ Settling bets", "🔴 Closing lines: failed", "🔴 Game-script learning: didn't run",
                   "🟠 Morning review: ran, but 1 of 2 runs failed"]


def test_picks_note_lists_good_bets_sized_to_the_budget():
    rows = [{"sport": "NBA", "kind": "Prop", "pick": "A Points Over 20.5", "price": 100, "chance": 0.66,
             "use": "🔒 Lock", "market": "Points", "game": "X @ Y", "time": "7:00 PM"},
            {"sport": "NBA", "kind": "Prop", "pick": "B Points Over 9.5", "price": -300, "chance": 0.70,
             "use": "🔒 Lock", "market": "Points"}]
    recs = lambda sp: {"Lock": (700, 1000)}
    text = MB.picks("2026-11-11", rows, [], recs, {"daily_budget": 40, "stop_loss": 25})
    assert "A Points Over 20.5 (+100)" in text and "B Points" not in text and "$5 each" in text
    none = MB.picks("2026-11-11", rows[1:], [], recs, {"daily_budget": 40})
    assert "no Good bets" in none


def test_long_notes_split_for_discord():
    text = "\n".join("line %d %s" % (i, "x" * 80) for i in range(60))
    parts = MB.chunks(text)
    assert len(parts) > 1 and all(len(p) <= MB.DISCORD_LIMIT + 1 for p in parts)
    sent = []
    assert MB.deliver(text, "https://example/webhook", post=sent.append) and len(sent) == len(parts)
    assert not MB.deliver(text, None)


def test_auto_sends_whatever_is_due(monkeypatch):
    calls = []
    monkeypatch.setattr(MB, "run", lambda kind, day, force=False: calls.append(kind) or 0)
    assert MB.main(["auto", "2026-11-11"]) == 0 and calls == ["morning", "picks"]
    calls.clear()
    MB.main([])
    assert calls == ["morning", "picks"]


def test_picks_fill_a_table_for_home():
    rows = [{"sport": "NBA", "kind": "Prop", "pick": "A Points Over 20.5", "price": 100, "chance": 0.66,
             "use": "🔒 Lock", "market": "Points", "game": "X @ Y", "time": "7:00 PM"}]
    table = []
    MB.picks("2026-11-11", rows, [], lambda sp: {"Lock": (700, 1000)}, {"daily_budget": 40}, table=table)
    assert table and table[0]["Pick"] == "A Points Over 20.5" and table[0]["Price"] == "+100" and table[0]["Time"] == "7:00 PM"


def test_picks_note_includes_intl_hoops_and_tennis_reads():
    lines = [{"sport": "TENNIS", "pick": "A to win", "game": "B vs A", "time": "11:00 AM", "chance": 0.64,
              "use": "🎯 Single only", "need": -150, "untested": True},
             {"sport": "INTL", "pick": "Real Madrid -4.5", "game": "X @ Real Madrid", "time": "2:45 PM", "chance": 0.58,
              "use": "🎟️ Parlay + Single"}]
    table = []
    text = MB.picks("2026-11-12", [], [], lambda sp: {}, {"daily_budget": 40}, table=table, lines=lines)
    assert "no Good bets" in text and "TENNIS · A to win (needs -150 or better)" in text and "not yet proven" in text
    assert "INTL · Real Madrid -4.5" in text and text.index("TENNIS ·") < text.index("INTL ·")   # earliest first
    assert len(table) == 2 and table[0]["Sport"] == "TENNIS" and table[0]["Stake"] == "$1"


def test_morning_scorecard_grades_yesterdays_line_reads():
    past = [{"sport": "TENNIS", "result": "win"}, {"sport": "TENNIS", "result": "loss"},
            {"sport": "INTL", "result": "win"}, {"sport": "INTL", "result": None}]
    assert MB.lines_yesterday(past) == ["**INTL** playable reads: 1-0", "**TENNIS** playable reads: 1-1"]
    text = MB.morning("2026-11-12", {}, [], [], past)
    assert "How the model did" in text and "TENNIS** playable reads: 1-1" in text


def test_learned_names_a_league_calibration_change():
    rep = {"GAME_LINES": {"calibration": {"auto": [{"side": "overall", "label": "NBL win chances", "active": 1.0,
                                                    "new": 0.8, "applied": True, "why": "held up"}]}}}
    out = MB.learned(rep)
    assert out[0] == "🔧 NBL win chances: 1.00 → 0.80 (held up)"
