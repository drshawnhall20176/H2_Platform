"""Nov 21: rules are frozen to their versions (rules.py) -- this fails when a rule's parameters change unregistered."""
import pick_ledger as PL
import rules as RU


def test_no_rule_has_drifted_from_its_registered_version():
    assert RU.drift() == [], RU.drift()


def test_versions_by_date():
    assert RU.version("strong", "2026-11-20") == 1 and RU.version("strong", "2026-11-21") == 2
    assert RU.version("strong", "2026-11-01") is None


def test_ledger_stamps_the_rule_version_and_sums_a_version_record():
    from datetime import datetime, timezone
    s = {}
    get, save = (lambda k, d=None: s.get(k, d)), (lambda k, v: s.__setitem__(k, v))
    now = datetime(2026, 11, 21, 15, 0, tzinfo=timezone.utc)
    PL.add("strong", "ALL", "2026-11-21", [{"sport": "NBA", "pid": 1, "market": "Points", "side": "Under",
                                            "line": 9.5, "price": -110}], now, get, save)
    k = PL.KEY.format(kind="strong", sport="ALL", day="2026-11-21")
    row = next(iter(s[k]["rows"].values()))
    assert row["rule_v"] == 2
    row["result"] = "win"
    s[k]["graded_at"] = "x"
    r = PL.since_record("strong", "ALL", "2026-11-21", "2026-11-22", get)
    assert (r["hits"], r["misses"], r["slates"]) == (1, 0, 1)
