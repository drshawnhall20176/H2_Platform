"""Nov 18: the Owner Office -- its own password, fails closed, and its pages leave the sport sidebars."""
import office as OF


def test_office_password_fails_closed():
    assert OF.check("pw", "pw") and not OF.check("x", "pw")
    assert not OF.check("", "pw") and not OF.check("pw", None) and not OF.check("", "")


def test_office_pages_and_modes():
    for k in ("16", "17", "18", "19", "20", "21", "22", "40", "41", "42", "48", "49", "51", "56"):
        assert OF.is_office_page(k)
    assert not OF.is_office_page("1") and not OF.is_office_page("39")
    assert not OF.active({}) and not OF.active({OF.MODE: True})
    assert OF.active({OF.UNLOCKED: True, OF.MODE: True}) and not OF.active({OF.UNLOCKED: True})
    assert set(OF.PAGES.values()) <= set(OF.SECTION_ORDER)


def test_office_menu_has_today_link_that_leaves_the_office():
    # Nov 18 (owner): a way out of the Office -- a Today link above Owner Office; picking it leaves the Office.
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("streamlit_app.py", default_timeout=120)
    at.secrets["AUDIENCE"] = "owner"
    at.secrets["OWNER_OFFICE_PASSWORD"] = "pw"
    at.session_state[OF.UNLOCKED] = True
    at.session_state[OF.MODE] = True
    at.run()
    assert not at.exception and "🔒 Lock the Office" in [b.label for b in at.button]   # the door is still the landing page
    at.switch_page("Today.py")
    at.run()
    assert not at.exception and at.session_state[OF.MODE] is False and at.session_state[OF.UNLOCKED] is True


def test_owner_office_works_while_previewing_the_commercial_layout():
    # Nov 25 (owner: "What happened to my Owner Office"): the preview keeps his Office (owner build only)
    from streamlit.testing.v1 import AppTest
    import nav_layout as NL
    at = AppTest.from_file("streamlit_app.py", default_timeout=120)
    at.secrets["AUDIENCE"] = "owner"
    at.secrets["OWNER_OFFICE_PASSWORD"] = "pw"
    at.session_state[NL.PREVIEW_KEY] = True
    at.session_state[OF.UNLOCKED] = True
    at.session_state[OF.MODE] = True
    at.run()
    assert not at.exception and "🔒 Lock the Office" in [b.label for b in at.button]


def test_the_owner_preview_keeps_the_game_lab_log_boxes(monkeypatch):
    import hoops_games_page as HG
    import nav_layout as NL
    import streamlit as st
    monkeypatch.setattr(st, "secrets", {"AUDIENCE": "owner"})
    monkeypatch.setattr(st, "session_state", {NL.PREVIEW_KEY: True})
    assert HG._commercial() is False                         # the owner previewing: his own Game Lab
    monkeypatch.setattr(st, "secrets", {"AUDIENCE": "commercial"})
    assert HG._commercial() is True                          # a real customer: no log boxes


def test_the_preview_still_runs_with_the_owner_section():
    from streamlit.testing.v1 import AppTest
    import nav_layout as NL
    at = AppTest.from_file("streamlit_app.py", default_timeout=120)
    at.secrets["AUDIENCE"] = "owner"
    at.session_state[NL.PREVIEW_KEY] = True
    at.run()
    assert not at.exception
    assert 'sections["🔐 OWNER (only you see this)"]' in open("streamlit_app.py").read()


def test_the_office_sidebar_has_a_real_sport_picker():
    # Nov 25 (owner): change sport inside the Office without going back to Today
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("streamlit_app.py", default_timeout=120)
    at.secrets["AUDIENCE"] = "owner"
    at.secrets["OWNER_OFFICE_PASSWORD"] = "pw"
    at.session_state[OF.UNLOCKED] = True
    at.session_state[OF.MODE] = True
    at.run()
    assert not at.exception
    pick = at.sidebar.selectbox(key="_office_sport")
    other = "NHL" if pick.value != "NHL" else "NBA"
    pick.set_value(other).run()
    assert not at.exception and at.session_state["sport"] == other
