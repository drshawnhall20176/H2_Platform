"""
test_ufc_engine.py — offline tests for ufc_engine.py (no network).

    python test_ufc_engine.py     # or: pytest test_ufc_engine.py
"""

import ufc_engine as U


def test_eastern_date_str_uses_real_us_eastern_calendar_date():
    # Regression guard for a real bug found in a broader sweep after fixing the same pattern in
    # odds_api.py: get_ufc_events compared a raw UTC commence_time date-prefix directly against
    # an Eastern-context date_str as plain strings. UFC main cards routinely run 10pm ET or later
    # -- exactly the window where commence_time rolls to the NEXT calendar day in UTC, so this
    # silently excluded main events (and sometimes entire cards) from "today's" results.
    assert U._eastern_date_str("2026-07-29T03:15:00Z") == "2026-07-28"   # 11:15 PM ET main event
    assert U._eastern_date_str("2026-07-28T22:00:00Z") == "2026-07-28"   # 6:00 PM ET prelims, same day either way
    assert U._eastern_date_str(None) is None
    assert U._eastern_date_str("not a real timestamp") is None
    print("✓ _eastern_date_str resolves a fight card's real US/Eastern calendar date, not the "
         "UTC date its commence_time happens to be stamped in")


def test_get_ufc_events_includes_late_night_main_events_that_roll_to_next_utc_day():
    # The exact live scenario this bug caused: an 11:15 PM ET main event has a UTC commence_time
    # on the FOLLOWING calendar date. The old raw-string comparison dropped it from "today's"
    # card; the fix correctly keeps it.
    fake_events = [
        {"id": "evt_prelims", "commence_time": "2026-07-28T22:00:00Z"},   # 6:00 PM ET same day
        {"id": "evt_main", "commence_time": "2026-07-29T03:15:00Z"},      # 11:15 PM ET same Eastern day
        {"id": "evt_other_day", "commence_time": "2026-07-29T22:00:00Z"},  # genuinely the next day
    ]

    def fake_get(path, params):
        return fake_events, {}

    orig_get = U._get
    U._get = fake_get
    try:
        events = U.get_ufc_events("fake_key", date_str="2026-07-28")
    finally:
        U._get = orig_get

    ids = {e["id"] for e in events}
    assert ids == {"evt_prelims", "evt_main"}
    print("✓ get_ufc_events includes an 11:15 PM ET main event (next-day in UTC) in the correct "
         "Eastern date's card, and still correctly excludes a genuinely different day's event")


def test_get_ufc_events_returns_everything_when_no_date_filter():
    fake_events = [{"id": "evt_1", "commence_time": "2026-07-28T22:00:00Z"}]

    def fake_get(path, params):
        return fake_events, {}

    orig_get = U._get
    U._get = fake_get
    try:
        events = U.get_ufc_events("fake_key")   # no date_str
    finally:
        U._get = orig_get

    assert events == fake_events
    print("✓ get_ufc_events returns everything, unfiltered, when no date_str is given")


def test_get_ufc_events_raises_a_real_error_on_api_failure():
    # Regression guard for the actual fix requested: this used to fail soft (return []),
    # which was the real obstacle to diagnosing a genuine reported bug -- "odds not pulling in"
    # looked identical whether the cause was truly no odds posted yet, or a real, fixable API
    # error (rate limit, invalid market, bad key). Now raises a real OddsAPIError with a
    # descriptive message instead, matching odds_api.py's own established pattern for MLB/NFL,
    # so the view can show it and a real cause is actually diagnosable.
    def fake_get(path, params):
        raise U.OddsAPIError("HTTP 422: invalid market")

    orig_get = U._get
    U._get = fake_get
    try:
        try:
            U.get_ufc_events("fake_key", date_str="2026-07-28")
            assert False, "should have raised OddsAPIError"
        except U.OddsAPIError as e:
            assert "invalid market" in str(e)
    finally:
        U._get = orig_get
    print("✓ get_ufc_events raises a real, descriptive OddsAPIError on a real API failure, "
         "no longer silently returning an empty list")


def test_get_event_odds_raises_a_real_error_on_api_failure():
    def fake_get(path, params):
        raise U.OddsAPIError("429 — out of quota for this period.")

    orig_get = U._get
    U._get = fake_get
    try:
        try:
            U.get_event_odds("evt_1", "fake_key")
            assert False, "should have raised OddsAPIError"
        except U.OddsAPIError as e:
            assert "out of quota" in str(e)
    finally:
        U._get = orig_get
    print("✓ get_event_odds raises a real, descriptive OddsAPIError on a real API failure, "
         "no longer silently returning {}")


def test_underlying_get_raises_descriptive_errors_for_real_status_codes():
    import requests

    class _FakeResponse:
        def __init__(self, status_code, text=""):
            self.status_code = status_code
            self.text = text

    orig_requests_get = U.requests.get
    for status, expect_substr in [(401, "Unauthorized"), (429, "quota"), (422, "HTTP 422")]:
        U.requests.get = lambda *a, status=status, **kw: _FakeResponse(status, "invalid market")
        try:
            try:
                U._get("sports/mma_mixed_martial_arts/events", {"apiKey": "x"})
                assert False, f"should have raised for status {status}"
            except U.OddsAPIError as e:
                assert expect_substr in str(e)
        finally:
            U.requests.get = orig_requests_get
    print("✓ _get raises a real, descriptive OddsAPIError for 401/429/other real HTTP failures")


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
