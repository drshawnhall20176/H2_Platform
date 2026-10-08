"""position_logview.py — the aligned HTML game-log table."""
import position_logview as PV
import position_matchups as PM


def row(order, opp, venue, result, score, who, pid, rec, rec_yds, pts, date="2026-09-06"):
    return {"order": order, "date": date, "opp": opp, "venue": venue, "result": result, "score": score, "who": who, "pid": pid,
            "stats": {"rec": rec, "rec_yds": rec_yds, "tgt_share": 25.0}, "pts": pts, "primetime": None, "setting": None, "role": None}


def log(rows=None):
    rows = rows if rows is not None else [row(202605, "OFF4", "Away", "W", "24-10", "Star <b>", "p1", 7.0, 90.0, 16.0),
                                          row(202604, "HOU", "Home", "L", "17-27", "Sub", "p2", 2.0, 20.0, 4.0),
                                          row(202603, "NYG", None, None, "", "", "p3", 0.0, 0.0, 0.0)]
    avg = {"stats": {"rec": 3.0, "rec_yds": 36.7, "tgt_share": 25.0}, "pts": 6.7} if rows else None
    return {"rows": rows, "avg": avg, "stat_cols": (("rec", "REC"), ("rec_yds", "REC YDS"), ("tgt_share", "SHARE")), "games": len(rows),
            "period": "Full Game", "period_ok": True}


NAMES = {"OFF4": "Off Four FC", "HOU": "Houston Texans", "NYG": "NY Giants"}


def test_value_formats():
    assert PV.fmt_value("tgt_share", 25.4, True) == "25%" and PV.fmt_value("rush_share", 0.0, True) == "0%"
    assert PV.fmt_value("rec", 7.0, True) == "7" and PV.fmt_value("rec", 7.0, True, average=True) == "7.0"
    assert PV.fmt_value("pts", 16.0, True) == "16.0" and PV.fmt_value("rec", 7.0, False) == "7.0"


def test_rows_show_opponent_result_player_and_every_column():
    html = PV.log_html(log(), NAMES, "Fantasy pts", whole=True)
    assert html.count("<tr>") == 1 + 3 and "FANTASY PTS" in html and "REC YDS" in html
    assert "at Off Four FC" in html and "vs Houston Texans" in html and "NY Giants" in html
    assert '<span class="w">W</span> <small>24-10</small>' in html and '<span class="lo">L</span>' in html
    assert "AVG (3 games)" in html and ">37<" not in html and "36.7" in html


def test_everything_supplied_is_escaped_and_only_https_images_render():
    html = PV.log_html(log(), {"OFF4": "<script>x</script>"}, "Pts", logos={"OFF4": "http://insecure/x.png", "HOU": 'https://ok/"x.png'},
                       headshots={"p1": "javascript:alert(1)", "p2": "https://ok/h.png"})
    assert "<script>" not in html and "Star <b>" not in html and "Star &lt;b&gt;" in html
    assert "insecure" not in html and "javascript:" not in html
    assert 'src="https://ok/&quot;x.png"' in html and 'class="hs" src="https://ok/h.png"' in html


def test_cells_are_shaded_against_their_own_column_and_the_hookup_is_used(monkeypatch):
    calls = []
    real = PM.heat_css
    monkeypatch.setattr(PM, "heat_css", lambda vals: (calls.append(list(vals)), real(vals))[1])
    html = PV.log_html(log(), NAMES, "Pts")
    assert [90.0, 20.0, 0.0] in calls and [16.0, 4.0, 0.0] in calls and len(calls) == 4          # 3 stat columns + the headline
    assert 'style="' in html


def test_hit_rate_and_best_line_rows_appear_only_when_lines_are_loaded():
    plain = PV.log_html(log(), NAMES, "Pts")
    assert "HIT RATE" not in plain and "BEST OVER" not in plain and "LINE" not in plain.replace("OVERLINE", "")
    hits = PM.hit_rates(log()["rows"], {"rec_yds": 25.0})
    best = {"rec_yds": {"point": 25.5, "over": ("dk", -110), "under": ("fd", 120), "books": 3}}
    html = PV.log_html(log(), NAMES, "Pts", hits=hits, best=best)
    assert "HIT RATE" in html and "33%" in html and "1/3" in html and 'class="hit-lo"' in html
    assert "LINE" in html and "25.5" in html and "BEST OVER" in html and "-110" in html and "+120" in html
    assert "<td>—</td>" in html                                                                   # columns with no line


def test_hit_rate_colours_by_threshold():
    mk = lambda pct: {"rec": {"hits": 3, "games": 5, "pct": pct}}
    assert 'class="hit-hi"' in PV.log_html(log(), NAMES, "P", hits=mk(60.0)) and 'class="hit-lo"' in PV.log_html(log(), NAMES, "P", hits=mk(40.0))
    assert 'class="hit-hi"' not in PV.log_html(log(), NAMES, "P", hits=mk(59.9)) and 'class="hit-lo"' not in PV.log_html(log(), NAMES, "P", hits=mk(40.1))
    mid = PV.log_html(log(), NAMES, "P", hits=mk(50.0))
    assert 'class="hit-hi"' not in mid and 'class="hit-lo"' not in mid


def test_a_single_game_reads_singular_and_an_empty_log_has_no_average_row():
    one = log([row(1, "HOU", "Home", "W", "3-0", "A", "p", 1.0, 5.0, 1.0)])
    assert "AVG (1 game)" in PV.log_html(one, NAMES, "P")
    assert "AVG" not in PV.log_html(log([]), NAMES, "P")
