"""Nov 26: the game card's environment -- the market's scoring and game script beside the model's, and plain verdicts."""
import game_card as GC


def test_script_frac_from_the_market_spread():
    assert GC.script_frac("NFL", GC.scores(-1.0, 56)) < 0.15                    # Bears @ Lions, Lions -1
    assert GC.script_word(GC.script_frac("NFL", GC.scores(-1.0, 56))) == "coin flip"
    assert GC.script_word(GC.script_frac("NFL", GC.scores(14.5, 44))) == "blowout"
    assert GC.script_word(GC.script_frac("NCAAMB", GC.scores(8.5, 140))) == "clear favorite"
    assert GC.script_frac("NHL", GC.scores(1.5, 6)) is None                     # the puck line is fixed
    assert GC.script_frac("NFL", None) is None


def test_environment_line_says_when_model_and_market_differ():
    assert GC.environment_line(0.62, 0.66) == "Model and market agree: a slightly high-scoring game."
    assert GC.environment_line(0.30, 0.80) == ("The market expects a high-scoring game; our model expects less "
                                               "scoring (slightly low-scoring).")
    assert GC.environment_line(None, 0.10) == "The market expects a low-scoring game."
    assert GC.environment_line(0.5, None) == ""


def test_matchup_lines_name_who_is_better():
    bears, lions = {"off_rank": 7, "def_rank": 9}, {"off_rank": 5, "def_rank": 17}
    assert GC.matchup_lines(bears, lions, "Chicago Bears", "Detroit Lions") == [
        "**Detroit Lions** scores more (#5 vs #7).", "**Chicago Bears** has the tougher defense (#9 vs #17)."]
    assert GC.matchup_lines({"off_rank": 3}, {"off_rank": 3}, "A", "B") == ["Even on offense (#3 each)."]
    assert GC.matchup_lines(None, lions, "A", "B") == []


def test_average_takes_an():
    assert GC.environment_line(None, 0.5) == "The market expects an average-scoring game."
