"""Nov 20: the public report card (report_card.py)."""
import report_card as RC


def test_card_counts_each_slate_once_from_its_latest_review():
    reviews = {
        ("NBA", "2026-11-19"): {"slates": {"2026-11-18": {"money": {"hits": 2, "misses": 1, "profit": 0.3, "needed": 0.45,
                                                                    "clv_beat": 2, "clv_lost": 1},
                                                          "most_probable": {"hits": 5, "misses": 1, "profit": 0.05,
                                                                            "priced": 6, "needed": 0.6}}}},
        ("NBA", "2026-11-20"): {"slates": {"2026-11-18": {"money": {"hits": 3, "misses": 1, "profit": 0.5, "needed": 0.45,
                                                                    "clv_beat": 3, "clv_lost": 1}},       # finished later
                                           "2026-11-19": {"money": {"hits": 0, "misses": 2, "profit": -1.0,
                                                                    "needed": 0.5}}}}}
    rows = RC.card(["NBA", "NHL"], load=lambda sp, m: reviews.get((sp, m)), today="2026-11-20")
    money = [r for r in rows if r["kind"] == "money"][0]
    assert (money["hits"], money["misses"]) == (3, 3) and abs(money["units"] - 0.0) < 1e-9
    assert money["clv"] == 0.75 and money["clv_n"] == 4
    lock = [r for r in rows if r["kind"] == "lock"]
    assert lock == []                                              # the 18th's later review had no 🔒 record
    t = RC.table(rows)
    assert t[0]["Picks"].startswith("💰") and t[0]["Record"] == "3–3" and t[0]["Beat the close"] == "75% of 4"
