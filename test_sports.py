"""Tests for sports.py — the sport registry and Stage 2 routing helpers (active sport lookup,
the require_live_engine guard that lets engine-backed pages degrade gracefully for sports that
aren't wired end-to-end yet) — plus the owner/public audience gate in streamlit_app.py."""

import re
from pathlib import Path

import sports as S

_HERE = Path(__file__).parent


def test_registry_has_all_seven_leagues():
    assert set(S.REGISTRY.keys()) == {"MLB", "NFL", "WNBA", "NBA", "NHL", "NCAAF", "NCAAMB"}
    print("✓ all 7 leagues registered")


def test_only_mlb_enabled_today():
    live = [s.key for s in S.enabled_sports()]
    assert live == ["MLB"], f"expected only MLB live, got {live}"
    print("✓ MLB is the only enabled/live sport (NFL engine present but not flipped on)")


def test_get_falls_back_to_default_for_unknown_key():
    assert S.get("XFL").key == S.DEFAULT_SPORT
    print("✓ unknown sport key falls back to the default (MLB)")


def test_active_defaults_to_mlb_outside_streamlit():
    # No st.session_state available here (no Streamlit runtime) -> active() must not crash,
    # and should fall back to the default sport.
    assert S.active_key() == "MLB"
    assert S.active().key == "MLB"
    print("✓ active()/active_key() degrade to MLB default without a Streamlit runtime")


def test_require_live_engine_true_for_mlb(monkeypatch):
    import streamlit as st
    st.session_state["sport"] = "MLB"
    assert S.require_live_engine("Edge Board") is True
    print("✓ require_live_engine passes for MLB (markets configured)")


def test_require_live_engine_false_for_unwired_sport(monkeypatch):
    import streamlit as st
    st.session_state["sport"] = "NFL"   # engine module present, but markets=[] (not wired)
    assert S.require_live_engine("Edge Board") is False
    st.session_state["sport"] = "MLB"   # reset for other tests
    print("✓ require_live_engine blocks a sport with no markets configured yet, no crash")


def test_market_map_present_only_for_mlb():
    assert S.REGISTRY["MLB"].market_map, "MLB must have a market_map (CLV capture depends on it)"
    for key in ("NFL", "WNBA", "NBA", "NHL", "NCAAF", "NCAAMB"):
        assert S.REGISTRY[key].market_map == {}, f"{key} should still be a placeholder"
    print("✓ only MLB has a filled market_map; the rest are honest placeholders")


def test_owner_only_pages_match_expected_titles():
    # Regression guard for the Discord/public split: Bet Log, Media Room, Podcast Studio, and
    # Edge Board must stay in the owner-only gate, and the gate must resolve against real page
    # titles that exist in _META (a typo here would silently fail to hide a page from the public
    # build).
    src = (_HERE / "streamlit_app.py").read_text()
    m = re.search(r'_OWNER_ONLY_TITLES = \{([^}]*)\}', src)
    assert m, "streamlit_app.py must define _OWNER_ONLY_TITLES"
    gated = {t.strip().strip('"') for t in m.group(1).split(",") if t.strip()}
    assert gated == {"Bet Log", "Media Room", "Podcast Studio", "Edge Board"}, gated
    all_titles = set(re.findall(r'\("([^"]+)",\s*"[^"]*",\s*"[^"]*"\)', src))
    assert gated <= all_titles, f"gated titles not found in _META: {gated - all_titles}"
    print("✓ owner-only gate targets exactly Bet Log / Media Room / Podcast Studio / Edge Board, "
          "by real title")


def test_public_audience_defaults_safe():
    # Missing/unset AUDIENCE secret must default to "owner" (fail toward showing the owner
    # everything on unconfigured/local runs), never silently default to "public".
    src = (_HERE / "streamlit_app.py").read_text()
    assert 'st.secrets.get("AUDIENCE", "owner")' in src
    print("✓ AUDIENCE defaults to 'owner' when unset (safe default for local/dev runs)")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(None); passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
