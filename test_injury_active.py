"""Nov 26: a player ESPN lists as Active is cleared, whatever his old note says."""
import injury_check as IC


def test_active_status_beats_an_old_questionable_note():
    assert IC.classify("Active", "Jackson (elbow) is listed as questionable for Thursday's game.") is None
    assert IC.classify("Questionable", "Jackson (elbow) is listed as questionable.") == "questionable"
    assert IC.classify("Out", "") == "out"
