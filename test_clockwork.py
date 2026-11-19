from datetime import datetime, timedelta, timezone

import clockwork as CW


def _t(h, m, d=19):
    return datetime(2026, 11, d, h, m, tzinfo=timezone.utc)


def test_cron_matching_covers_the_repos_forms():
    assert CW.matches("41 14-23 * * *", _t(15, 41)) and not CW.matches("41 14-23 * * *", _t(13, 41))
    assert CW.matches("*/30 0-8 * * *", _t(6, 30)) and not CW.matches("*/30 0-8 * * *", _t(6, 15))
    assert CW.matches("0 15,21 * * *", _t(21, 0)) and CW.matches("23 */3 * * *", _t(9, 23))
    assert CW.matches("0 9 * * 0", _t(9, 0, d=22)) and not CW.matches("0 9 * * 0", _t(9, 0, d=21))   # Sun Nov 22
    assert CW.matches("37 1-23/2 * * *", _t(3, 37)) and not CW.matches("37 1-23/2 * * *", _t(4, 37))


def test_due_steps_in_only_for_a_skipped_run_inside_the_window():
    crons = {"warm-slates": ["41 14-23 * * *"]}
    now = _t(15, 52)                                             # due 15:41, 11 minutes ago
    assert CW.due(now, {}, crons) == ["warm-slates"]
    assert CW.due(now, {"warm-slates": _t(15, 45)}, crons) == []          # GitHub ran it (late) -- leave it
    assert CW.due(_t(15, 45), {}, crons) == []                           # inside DELAY: give GitHub its chance
    assert CW.due(_t(16, 30), {}, crons) == []                           # 49 min old: let it go, 16:41 is next
    assert CW.due(now, {"warm-slates": _t(14, 41)}, crons) == ["warm-slates"]   # last ran an hour ago


def test_every_listed_workflow_has_crons_and_none_are_force_on_dispatch():
    for wf in CW.WORKFLOWS:
        assert CW.crons_of(wf), wf
    assert not {"daily-review", "morning-brief", "tuning-report", "capture-ufc-odds", "close-watch"} & set(CW.WORKFLOWS)
