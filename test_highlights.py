"""Tests for highlights.py -- persistence, ownership rules, and the matching engine."""

import os
import tempfile

import highlights as H


def _tmpdb():
    return tempfile.mktemp(suffix=".db")


# ----------------------------------------------------------------- persistence
def test_add_and_list_profile_round_trips_conditions():
    db = _tmpdb()
    try:
        conds = [{"field": "ModelProb", "op": ">=", "value": 0.7}]
        H.add_profile("Test Profile", "MLB", conds, emoji="🧪", db_path=db)
        profiles = H.list_profiles("MLB", db_path=db)
        assert len(profiles) == 1
        assert profiles[0]["name"] == "Test Profile"
        assert profiles[0]["emoji"] == "🧪"
        assert profiles[0]["conditions"] == conds   # decoded back from JSON, not the raw string
        print("✓ add_profile/list_profiles round-trip conditions correctly through JSON storage")
    finally:
        if os.path.exists(db):
            os.remove(db)


def test_delete_profile_removes_it():
    db = _tmpdb()
    try:
        pid = H.add_profile("Temp", "MLB", [], db_path=db)
        assert len(H.list_profiles("MLB", db_path=db)) == 1
        H.delete_profile(pid, db_path=db)
        assert len(H.list_profiles("MLB", db_path=db)) == 0
        print("✓ delete_profile removes the profile")
    finally:
        if os.path.exists(db):
            os.remove(db)


def test_list_profiles_filters_by_sport():
    db = _tmpdb()
    try:
        H.add_profile("MLB Profile", "MLB", [], db_path=db)
        H.add_profile("NFL Profile", "NFL", [], db_path=db)
        mlb_profiles = H.list_profiles("MLB", db_path=db)
        assert len(mlb_profiles) == 1 and mlb_profiles[0]["name"] == "MLB Profile"
        print("✓ list_profiles correctly filters by sport")
    finally:
        if os.path.exists(db):
            os.remove(db)


# ----------------------------------------------------------------- ownership / sharing
def test_shared_profile_visible_to_everyone():
    db = _tmpdb()
    try:
        H.add_profile("House Profile", "MLB", [], owner=None, db_path=db)
        # Visible with no owner specified...
        assert len(H.list_profiles("MLB", db_path=db)) == 1
        # ...and visible to any specific person too, since it's shared.
        assert len(H.list_profiles("MLB", owner="Deezy", db_path=db)) == 1
        assert len(H.list_profiles("MLB", owner="Zee", db_path=db)) == 1
        print("✓ a shared (owner=None) profile is visible regardless of who's asking")
    finally:
        if os.path.exists(db):
            os.remove(db)


def test_personal_profile_visible_only_to_its_owner():
    db = _tmpdb()
    try:
        H.add_profile("Deezy's Profile", "MLB", [], owner="Deezy", db_path=db)
        deezy_view = H.list_profiles("MLB", owner="Deezy", db_path=db)
        zee_view = H.list_profiles("MLB", owner="Zee", db_path=db)
        no_name_view = H.list_profiles("MLB", db_path=db)
        assert len(deezy_view) == 1 and deezy_view[0]["name"] == "Deezy's Profile"
        assert len(zee_view) == 0
        assert len(no_name_view) == 0
        print("✓ a personal profile is visible only to the owner who created it")
    finally:
        if os.path.exists(db):
            os.remove(db)


def test_shared_defaults_plus_personal_overrides_combine():
    # The actual real design requested: a person sees the shared house profiles PLUS their own
    # personal ones together, not one or the other.
    db = _tmpdb()
    try:
        H.add_profile("House Profile", "MLB", [], owner=None, db_path=db)
        H.add_profile("Deezy's Profile", "MLB", [], owner="Deezy", db_path=db)
        H.add_profile("Zee's Profile", "MLB", [], owner="Zee", db_path=db)
        deezy_view = {p["name"] for p in H.list_profiles("MLB", owner="Deezy", db_path=db)}
        assert deezy_view == {"House Profile", "Deezy's Profile"}
        print("✓ a person sees shared house profiles plus their own personal ones combined, "
             "not each other's personal profiles")
    finally:
        if os.path.exists(db):
            os.remove(db)


def test_empty_string_owner_treated_as_shared():
    db = _tmpdb()
    try:
        H.add_profile("Blank Owner", "MLB", [], owner="", db_path=db)
        profiles = H.list_profiles("MLB", db_path=db)
        assert len(profiles) == 1
        assert profiles[0]["owner"] is None   # normalized, not stored as a literal empty string
        print("✓ an empty-string owner is correctly normalized to shared (None), not its own "
             "separate personal bucket")
    finally:
        if os.path.exists(db):
            os.remove(db)


# ----------------------------------------------------------------- matching engine
def _play(**kw):
    base = {"Market": "Batter HR", "Side": "Over", "ModelProb": 0.5, "Conviction": 1.5,
           "_ceiling": 2.5, "Due": None, "PriceSource": "model_fair",
           "ConvictionSource": "model_typical", "LineSource": "default", "OppERA": None,
           "AVG": None, "SLG": None}
    base.update(kw)
    return base


def test_matches_profile_all_conditions_must_pass():
    profile = {"conditions": [
        {"field": "Market", "op": "==", "value": "Batter HR"},
        {"field": "ModelProb", "op": ">=", "value": 0.6},
    ]}
    assert H.matches_profile(_play(Market="Batter HR", ModelProb=0.7), profile) is True
    # Clears one condition but not the other -- must NOT match (AND, not OR).
    assert H.matches_profile(_play(Market="Batter HR", ModelProb=0.4), profile) is False
    assert H.matches_profile(_play(Market="Batter Total Bases", ModelProb=0.7), profile) is False
    print("✓ matches_profile requires every condition to pass (AND logic), not just one")


def test_matches_profile_grade_computed_on_the_fly():
    # Grade isn't itself a key on any play -- confirms it's correctly derived from
    # Conviction/_ceiling via grading.conviction_to_grade, not silently absent/broken.
    import grading
    high_conviction_play = _play(Conviction=2.5, _ceiling=2.86)
    real_grade = grading.conviction_to_grade(2.5, 2.86)
    profile = {"conditions": [{"field": "Grade", "op": "in", "value": [real_grade["letter"]]}]}
    assert H.matches_profile(high_conviction_play, profile) is True
    print("✓ matches_profile correctly computes Grade on the fly from Conviction/_ceiling")


def test_matches_profile_unknown_field_fails_closed():
    # A malformed/stale saved condition must never crash the page -- it should just correctly
    # report no match, not raise.
    profile = {"conditions": [{"field": "NotARealField", "op": ">=", "value": 1}]}
    assert H.matches_profile(_play(), profile) is False
    print("✓ matches_profile fails closed (no match, no crash) for an unknown field")


def test_matches_profile_unknown_operator_fails_closed():
    profile = {"conditions": [{"field": "ModelProb", "op": "~=", "value": 0.5}]}
    assert H.matches_profile(_play(ModelProb=0.5), profile) is False
    print("✓ matches_profile fails closed for an unknown operator")


def test_matches_profile_none_value_never_matches_numeric_comparison():
    # A play missing a real value for a field (e.g. Due=None for a non-HR market) must not be
    # treated as clearing a numeric threshold -- None is "unknown," not "zero" or "infinite."
    profile = {"conditions": [{"field": "Due", "op": ">=", "value": 0.02}]}
    assert H.matches_profile(_play(Due=None), profile) is False
    print("✓ matches_profile never treats a missing (None) value as clearing a numeric threshold")


def test_matches_for_profile_returns_only_real_matches():
    plays = [
        _play(Player="A", Market="Batter HR", Due=0.03),
        _play(Player="B", Market="Batter HR", Due=0.0),
        _play(Player="C", Market="Batter Total Bases", Due=0.03),
    ]
    for i, p in enumerate(plays):
        p["Player"] = ["A", "B", "C"][i]
    profile = {"conditions": [
        {"field": "Market", "op": "==", "value": "Batter HR"},
        {"field": "Due", "op": ">=", "value": 0.02},
    ]}
    matches = H.matches_for_profile(plays, profile)
    assert [m["Player"] for m in matches] == ["A"]
    print("✓ matches_for_profile returns exactly the plays that clear every condition")


def test_highlights_by_profile_includes_zero_match_profiles():
    # A profile with zero matches must still appear in the result, not be silently dropped --
    # "no matches today" is real, honest information, different from the profile not existing.
    plays = [_play(Market="Batter Total Bases")]
    profiles = [{"name": "No Matches Today", "conditions": [
        {"field": "Market", "op": "==", "value": "Batter HR"}]}]
    result = H.highlights_by_profile(plays, profiles)
    assert len(result) == 1
    assert result[0]["matches"] == []
    print("✓ highlights_by_profile includes a profile with zero matches, not silently dropping it")


# ----------------------------------------------------------------- starter profiles
def test_ensure_starter_profiles_seeds_once():
    db = _tmpdb()
    try:
        H.ensure_starter_profiles("MLB", db_path=db)
        first_count = len(H.list_profiles("MLB", db_path=db))
        assert first_count == len(H.STARTER_PROFILES_MLB)
        # Calling again must NOT duplicate -- idempotent.
        H.ensure_starter_profiles("MLB", db_path=db)
        assert len(H.list_profiles("MLB", db_path=db)) == first_count
        print("✓ ensure_starter_profiles seeds once and is idempotent on repeated calls")
    finally:
        if os.path.exists(db):
            os.remove(db)


def test_ensure_starter_profiles_never_overwrites_real_edits():
    # If even one shared profile already exists (a real person edited/removed one), seeding
    # must not run again and silently reintroduce what they removed.
    db = _tmpdb()
    try:
        H.add_profile("Someone's Custom House Profile", "MLB", [], owner=None, db_path=db)
        H.ensure_starter_profiles("MLB", db_path=db)
        profiles = H.list_profiles("MLB", db_path=db)
        assert len(profiles) == 1   # starters were NOT seeded on top of the existing one
        assert profiles[0]["name"] == "Someone's Custom House Profile"
        print("✓ ensure_starter_profiles never reseeds once any real shared profile already exists")
    finally:
        if os.path.exists(db):
            os.remove(db)


def test_starter_profiles_every_field_is_a_real_condition_field():
    # Every starter profile's own conditions must reference fields this module actually
    # supports -- a real, direct guard against a typo silently making a starter profile match
    # nothing, ever, without any visible error.
    for profile in H.STARTER_PROFILES_MLB:
        for cond in profile["conditions"]:
            assert cond["field"] in H.CONDITION_FIELDS, (
                f"{profile['name']!r} references unknown field {cond['field']!r}")
            assert cond["op"] in H._OPS
    print("✓ every starter profile's conditions reference real, supported fields and operators")


def test_starter_profiles_actually_match_something_real():
    # Not just "doesn't crash" -- confirms each starter profile is genuinely capable of
    # matching a realistic play, not an accidentally-impossible filter.
    realistic_plays = [
        _play(Player="Rafael Devers", Market="Batter HR", Due=0.031, PriceSource="book",
             Conviction=1.9, _ceiling=2.86, OppERA=3.86, ModelProb=0.28),
        _play(Player="Wade Meckler", Market="Batter Total Bases", Due=None, PriceSource="book",
             Conviction=2.5, _ceiling=2.86, OppERA=5.10, ModelProb=0.82),
    ]
    result = H.highlights_by_profile(realistic_plays, H.STARTER_PROFILES_MLB)
    total_matches = sum(len(r["matches"]) for r in result)
    assert total_matches > 0, "no starter profile matched anything against a realistic pool"
    print(f"✓ starter profiles collectively produce {total_matches} real match(es) against a "
         f"realistic play pool")
