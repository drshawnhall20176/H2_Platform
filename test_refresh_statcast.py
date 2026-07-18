"""
test_refresh_statcast.py — offline tests for refresh_statcast.py's main(), specifically the
catcher-framing failure path.

No network required.
"""

import io
import sys
from contextlib import redirect_stdout
from unittest.mock import patch

import pandas as pd

import refresh_statcast as RS
import statcast_data as SC


def test_catcher_framing_failure_emits_visible_warning_annotation():
    # Regression guard for a real diagnosis gap found via an actual failed workflow run: a plain
    # print() on catcher-framing failure was easy to miss (buried in one step's raw log, not
    # visible from the Actions run list). "::warning::" is a real GitHub Actions workflow command
    # that surfaces on the run's own summary page — this locks in that the annotation actually
    # gets printed, not just written and assumed correct.
    def fake_refresh(year, out_path=SC.DEFAULT_PATH):
        return out_path

    def fake_load(path=SC.DEFAULT_PATH):
        return {1: {}}, 0.05

    def fake_refresh_catcher_framing(year, out_path=SC.CATCHER_FRAMING_PATH):
        raise ValueError("simulated Savant column drift")

    buf = io.StringIO()
    with patch.object(SC, "refresh", fake_refresh), \
        patch.object(SC, "load", fake_load), \
        patch.object(SC, "refresh_catcher_framing", fake_refresh_catcher_framing), \
        patch.object(sys, "argv", ["refresh_statcast.py", "2026"]), \
        redirect_stdout(buf):
        rc = RS.main()

    output = buf.getvalue()
    assert rc == 0   # catcher framing failure must NOT fail the whole script
    assert "::warning::" in output
    assert "simulated Savant column drift" in output
    assert "Full traceback:" in output
    assert "Traceback (most recent call last)" in output   # the real traceback, not just str(e)
    print("✓ a catcher framing failure emits a visible ::warning:: annotation with the full traceback, and does not fail the script")


def test_catcher_framing_success_no_warning():
    def fake_refresh(year, out_path=SC.DEFAULT_PATH):
        return out_path

    def fake_load(path=SC.DEFAULT_PATH):
        return {1: {}}, 0.05

    def fake_refresh_catcher_framing(year, out_path=SC.CATCHER_FRAMING_PATH):
        return out_path

    def fake_load_catcher_framing(path=SC.CATCHER_FRAMING_PATH):
        return {1: {}, 2: {}}

    buf = io.StringIO()
    with patch.object(SC, "refresh", fake_refresh), \
        patch.object(SC, "load", fake_load), \
        patch.object(SC, "refresh_catcher_framing", fake_refresh_catcher_framing), \
        patch.object(SC, "load_catcher_framing", fake_load_catcher_framing), \
        patch.object(sys, "argv", ["refresh_statcast.py", "2026"]), \
        redirect_stdout(buf):
        rc = RS.main()

    output = buf.getvalue()
    assert rc == 0
    assert "::warning::" not in output
    assert "Cached 2 catchers." in output


def test_team_enrichment_respects_called_pitches_floor_and_writes_team_names(tmp_path):
    def fake_refresh(year, out_path=SC.DEFAULT_PATH):
        return out_path

    def fake_load(path=SC.DEFAULT_PATH):
        return {1: {}}, 0.05

    cf_path = str(tmp_path / "catcher_framing.csv")

    def fake_refresh_catcher_framing(year, out_path=SC.CATCHER_FRAMING_PATH):
        return cf_path

    def fake_load_catcher_framing(path=SC.CATCHER_FRAMING_PATH):
        return {
            111: {"name": "Qualified Catcher", "called_pitches": 4000.0, "strike_rate": 0.52, "framing_runs": 10.0},
            222: {"name": "Thin Sample Catcher", "called_pitches": 20.0, "strike_rate": 0.50, "framing_runs": 0.1},
        }

    team_lookup_calls = []

    def fake_get_team(pid):
        team_lookup_calls.append(pid)
        return {"id": 109, "name": "Arizona Diamondbacks"} if pid == 111 else None

    buf = io.StringIO()
    with patch.object(SC, "refresh", fake_refresh), \
        patch.object(SC, "load", fake_load), \
        patch.object(SC, "refresh_catcher_framing", fake_refresh_catcher_framing), \
        patch.object(SC, "load_catcher_framing", fake_load_catcher_framing), \
        patch.object(RS.E, "get_player_current_team", fake_get_team), \
        patch.object(sys, "argv", ["refresh_statcast.py", "2026"]), \
        redirect_stdout(buf):
        rc = RS.main()

    assert rc == 0
    # Only the qualified catcher (>= 100 called pitches) triggers a team lookup — the thin-sample
    # catcher never does, confirming the floor is actually enforced, not just documented.
    assert team_lookup_calls == [111]

    written = pd.read_csv(cf_path)
    assert len(written) == 1   # the thin-sample catcher was dropped, not just left with a blank team
    assert written.iloc[0]["name"] == "Qualified Catcher"
    assert written.iloc[0]["team_id"] == 109   # the real matching key
    assert written.iloc[0]["team"] == "Arizona Diamondbacks"   # the display name
    print("✓ team enrichment respects the called-pitches floor and correctly writes both the resolved team_id and display name")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
