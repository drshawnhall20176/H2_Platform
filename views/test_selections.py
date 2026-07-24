"""
test_selections.py — offline tests for selections.py (no network).

    python test_selections.py    # or: pytest test_selections.py
"""

import selections as S


def test_filter_known_pitcher_drops_tbd_and_blank():
    plays = [
        {"Player": "A", "Opp": "NYY"},
        {"Player": "B", "Opp": "TBD"},
        {"Player": "C", "Opp": ""},
        {"Player": "D", "Opp": None},
    ]
    out = S.filter_known_pitcher(plays)
    assert [p["Player"] for p in out] == ["A"]


def test_filter_known_pitcher_passes_through_wnba_plays_unchanged():
    # WNBA plays always carry a real opponent team name — never TBD — so this is a harmless
    # no-op for WNBA, not something that needs its own version.
    plays = [{"Player": "Star", "Opp": "Seattle Storm"}, {"Player": "Role", "Opp": "Las Vegas Aces"}]
    assert S.filter_known_pitcher(plays) == plays


def test_attach_live_ev_uses_default_mlb_market_map():
    plays = [{"Player": "A. Player", "Market": "Batter HR", "Side": "Over", "Line": 0.5}]
    edges = [{"Player": "A. Player", "Market": "batter_home_runs", "Side": "Over",
             "Line": 0.5, "Price": -150, "EV%": 4.2}]
    out = S.attach_live_ev(plays, edges)
    assert out[0]["LivePrice"] == -150 and out[0]["EV"] == 4.2


def test_attach_live_ev_accepts_custom_market_map_for_wnba():
    wnba_map = {"Points": "player_points"}
    plays = [{"Player": "Star Player", "Market": "Points", "Side": "Over", "Line": 15.5}]
    edges = [{"Player": "Star Player", "Market": "player_points", "Side": "Over",
             "Line": 15.5, "Price": -120, "EV%": 6.7}]
    out = S.attach_live_ev(plays, edges, market_map=wnba_map)
    assert out[0]["LivePrice"] == -120 and out[0]["EV"] == 6.7
    print("✓ attach_live_ev works for WNBA markets when given a custom market_map")


def test_attach_live_ev_no_match_leaves_blank():
    plays = [{"Player": "Nobody", "Market": "Points", "Side": "Over", "Line": 15.5}]
    out = S.attach_live_ev(plays, [], market_map={"Points": "player_points"})
    assert out[0]["LivePrice"] is None and out[0]["EV"] is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); print(f"PASS  {t.__name__}"); passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
