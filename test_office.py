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
