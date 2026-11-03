"""
Game Lab (college basketball) — spreads, totals and moneylines for every D-I game the books price (Nov 3). TRACKING
ONLY until the record proves it. Owner only; shown when NCAAMB is the selected sport.

Recency-weighted opponent-adjusted ratings (last ~13 months, 45-day half-life, last season discounted) so the model
works from opening night; refreshed every 3 hours by capture-intl. Model: intl_hoops.py; capture / grading / record:
intl_picks.py; the view: hoops_games_page.py.
"""
import components as C
import hoops_games_page as HG

C.base_css()
C.page_header("🏟️", "Game Lab",
              "College basketball: the ratings model's margin, total and win chance against the spread, total and "
              "moneyline for every game the books price.")
HG.render("NCAAMB", search=True)
