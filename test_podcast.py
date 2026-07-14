"""
test_podcast.py — offline tests for podcast.py's sport-aware script assembly (no network).

    python test_podcast.py    # or: pytest test_podcast.py
"""

import podcast as PC


def _headliner(market="Points", side="Over"):
    return {"Player": "Star Player", "Team": "Atlanta Dream", "Market": market, "Side": side,
           "Line": 15.5, "ModelProb": 0.65, "Fair": -140, "Why": "strong recent form",
           "Opp": "Chicago Sky", "Conviction": 1.3}


# ----------------------------------------------------------------- rotating_teaching
def test_rotating_teaching_defaults_to_mlb_library():
    t = PC.rotating_teaching("2026-07-14")
    assert t in PC.TEACHING_SEGMENTS


def test_rotating_teaching_uses_wnba_library_when_asked():
    t = PC.rotating_teaching("2026-07-14", sport="WNBA")
    assert t in PC.TEACHING_SEGMENTS_WNBA
    assert t not in PC.TEACHING_SEGMENTS


def test_rotating_teaching_covers_every_wnba_segment_across_a_week():
    seen = {PC.rotating_teaching(f"2026-01-0{d}", sport="WNBA")["topic"] for d in range(1, 6)}
    assert len(seen) == len(PC.TEACHING_SEGMENTS_WNBA)   # 5 distinct dates -> all 5 segments, no repeats


# ----------------------------------------------------------------- assemble_script
def test_assemble_script_defaults_to_mlb_backward_compat():
    sections = PC.assemble_script("2026-07-14", [], [], None, None)   # no sport= passed
    text = PC.script_to_text("2026-07-14", sections)
    assert "ejection" in text
    assert "Skubal" in text
    print("✓ assemble_script defaults to MLB phrasing when sport isn't specified")


def test_assemble_script_wnba_has_no_leaked_mlb_terms():
    retro = {"graded": 10, "hits": 6, "hit_rate": 0.6}
    caught = [{"Player": "Hot Player", "Rank": 1}]
    sections = PC.assemble_script("2026-07-14", [_headliner()], [], retro, caught, sport="WNBA")
    text = PC.script_to_text("2026-07-14", sections)
    bad_terms = ["baseball", "pitcher", "park/weather", "went deep", "ejection", "walk-off",
                "LeBron/Jordan", "Skubal", "bats before", "pitchers'"]
    leaked = [t for t in bad_terms if t.lower() in text.lower()]
    assert not leaked, f"MLB-specific terms leaked into WNBA script: {leaked}"
    print("✓ WNBA script has zero leaked MLB-specific terms")


def test_assemble_script_wnba_uses_wnba_push_line():
    sections = PC.assemble_script("2026-07-14", [_headliner(market="Points")], [], None, None, sport="WNBA")
    text = PC.script_to_text("2026-07-14", sections)
    assert "UNDER it" in text   # from _DEEZY_PUSH["Points"]
    print("✓ WNBA selections use the Points-specific push-back line, not the MLB default")


def test_assemble_script_produces_all_seven_sections_for_both_sports():
    for sport in ("MLB", "WNBA"):
        sections = PC.assemble_script("2026-07-14", [], [], None, None, sport=sport)
        assert len(sections) == 7
        assert sections[0]["title"] == "🎬 Yesterday in Review"
        assert sections[-1]["title"] == "👋 Sign-off"


def test_assemble_script_handles_no_retro_gracefully():
    sections = PC.assemble_script("2026-07-14", [], [], None, None, sport="WNBA")
    text = PC.script_to_text("2026-07-14", sections)
    assert "results not pulled yet" in text


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
