"""Nov 26: Today says why it has no player picks."""
import customer_today as CT


def test_empty_reason_names_the_dark_sports_and_the_reads():
    t = CT.empty_reason(["NBA", "NHL"], {"NFL": 235, "NCAAMB": 330, "NCAAF": 20})
    assert t.startswith("No pick clears the bar today: NBA and NHL have no games today; the model read 585 NCAAF, "
                        "NCAAMB and NFL props, and none earned a bet")
    assert "Test list" in t


def test_empty_reason_before_any_build():
    assert "haven't been built yet" in CT.empty_reason([], {})
    assert CT.empty_reason(["NHL"], {}).startswith("No pick clears the bar today: NHL has no games today.")


def test_has_games_many_runs_side_by_side(monkeypatch):
    import time
    calls = []

    def slow(k, day):
        calls.append(k)
        time.sleep(0.2)
        if k == "BAD":
            raise RuntimeError("feed down")
        return k != "NHL"
    monkeypatch.setattr(CT, "has_games", slow)
    t0 = time.time()
    got = CT.has_games_many(["NBA", "NHL", "NFL", "BAD"], "2026-11-26")
    assert time.time() - t0 < 0.6                                # four 0.2 s checks, not 0.8 s in a row
    assert got == {"NBA": True, "NHL": False, "NFL": True, "BAD": None} and CT.has_games_many([], "x") == {}


def test_saved_counts_answer_first(monkeypatch):
    asked = []
    monkeypatch.setattr(CT, "has_games", lambda k, d: asked.append(k) or True)
    got = CT.has_games_many(["NBA", "NHL", "NFL", "SOCCER"], "2026-11-26", saved={"NBA": 0, "NHL": 0, "NFL": 16})
    assert got == {"NBA": False, "NHL": False, "NFL": True, "SOCCER": True} and asked == ["SOCCER"]


def test_warm_slates_merges_the_days_counts():
    import warm_slates as WS
    store = {"games_on:2026-11-26": {"n": {"NBA": 0, "NCAAMB": 21}}}
    WS.save_games_on("2026-11-26", {"NFL": 16, "NBA": 0}, save=store.__setitem__,
                     get=lambda k, d=None: store.get(k, d))
    assert store["games_on:2026-11-26"]["n"] == {"NBA": 0, "NCAAMB": 21, "NFL": 16}
    WS.save_games_on("2026-11-26", {}, save=lambda *a: (_ for _ in ()).throw(AssertionError("no write")))


def test_members_are_not_sent_to_the_office():
    t = CT.empty_reason(["NBA"], {"NFL": 10}, owner=False)
    assert "Test list" not in t and "under Games" in t
    assert "Test list" in CT.empty_reason(["NBA"], {"NFL": 10})
