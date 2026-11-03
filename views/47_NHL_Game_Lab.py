"""
Game Lab (NHL) — spreads (puck lines), totals and moneylines for every game the books price (Nov 3). Owner page; shown
when NHL is the selected sport. Recency-weighted opponent-adjusted ratings (last ~13 months, 45-day half-life, last
season discounted), refreshed every 3 hours by capture-intl. Picks only where research/backtest_pro_games.py found an
edge. Model: intl_hoops.py; capture / grading / record: intl_picks.py; the view: hoops_games_page.py.
"""
import components as C
import hoops_games_page as HG

C.base_css()
C.page_header("🏟️", "Game Lab",
              "NHL: the ratings model's margin, total and win chance against the puck line, total and moneyline for every "
              "game the books price.")
HG.render("NHL", search=True)
