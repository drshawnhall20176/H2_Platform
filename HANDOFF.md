# H2 Sports Platform — Handoff (current as of Sat Nov 14, 2026)

This is the **current** picture: what runs, where, how it's set up, and the rules the owner has set.
`PLATFORM_CHECKPOINT.md` is the historical build log (July–October); where they disagree, this file wins.

Owner: Dr. Shawn Hall (H2 Sports, LLC; brand "H2 Sports Media"; co-owner Deezy). Repo:
`drshawnhall20176/H2_Platform`, branch `main`. 337 commits, 56 pages, 154 test files, **3,643 tests passing**
(`timeout 1700 python -m pytest -q -p no:cacheprovider --deselect
test_analyst_page.py::test_the_locked_calls_table_follows_the_time_slot_and_game_pickers`).

---

## 1. Where it runs

| Piece | Detail |
|---|---|
| Owner app | `h2ownersplatform.streamlit.app` — entrypoint `streamlit_app.py`, invitation-only on Streamlit Community Cloud |
| Public / Discord app | entrypoint `streamlit_app_discord.py`, secret `AUDIENCE = "public"`. Same as the owner app except the Bet Log and other owner data |
| Database | Postgres (Supabase) via `DATABASE_URL`; `model_store.py` falls back to SQLite `data/model.db` locally (delete it, never commit it) |
| Automation | GitHub Actions (section 4) |
| Python | 3.11 on Streamlit Cloud (Advanced settings); requirements pinned |

**Secrets**

| Secret | Where | Used for |
|---|---|---|
| `DATABASE_URL` | GitHub Actions + both Streamlit apps | everything stored |
| `ODDS_API_KEY` | GitHub Actions + both Streamlit apps | all book prices (props, game lines, alternates, soccer, tennis) |
| `CFBD_API_KEY` | GitHub Actions | college football data |
| `OWNER_BRIEF_WEBHOOK` | GitHub Actions — **not set yet** | private Discord channel for the morning brief / afternoon picks |
| `AUDIENCE` | public app only | `"public"` |

> **Odds API account (Nov 13):** the key was briefly **deactivated** ("cancelation or a failed payment"), then came
> back (≈99,000 credits left, 718 used this cycle). If prices stop updating platform-wide, check billing at
> the-odds-api.com first. A deactivated key returns `401 DEACTIVATED_KEY`; models, results, grading and live scores
> keep running without it.

---

## 2. Sports and their status

Only in-season sports are selectable (owner rule). In season now: **NFL, NCAAF, NBA, NCAAMB, NHL, UFC, Tennis,
International Hoops, Soccer.** Off-season: MLB, WNBA.

| Sport | What it does | Status |
|---|---|---|
| NBA, NHL, NFL, NCAAF, NCAAMB, WNBA, MLB | Player-prop projections vs real book lines; Best Bets, Edge Board, Position Matchups, My Coach; game-line labs (45 NCAAMB, 46 NBA, 47 NHL, 32 NCAAF, 34 NFL) | Live, graded nightly, auto-calibrated |
| UFC | Fight card (23), odds captured 8×/day | Live |
| Tennis (lab) | Tennis Lab (43): ATP/WTA match chances from ESPN results, books' prices | **Tracking.** Auto-calibration ON since Nov 13 (k = 0.70: a raw 75% reads 68%) |
| International Hoops (lab) | Page 44: EuroLeague, EuroCup, Champions League, FIBA Europe Cup, EuroCup Women, NBL, Lithuania NKL, Iceland, Bahrain, Estonia, Qatar | **Tracking only** (record not yet proven). NKL/Iceland/Bahrain/Estonia/Qatar have < 30 games — not rated yet, live score only |
| Soccer (lab) | Soccer Lab (55): 56 leagues in 8 groups, goals model + Pinnacle no-vig line + best US price, totals, Asian handicap, BTTS, player props on demand | **Tracking only** — backtest: model lost to the closing price in all 8 leagues tested; 📈 "US price beats sharp line" flags beat the close by 2–16% but only broke even |

College player props: books + **Underdog / Pick6** for college basketball (pick'em-only lines get a pick'em read).
Shown on Position Matchups, My Coach (sportsbook-priced only) and the college Game Labs' 🎯 Player props section.

---

## 3. Pages (owner app)

- **Daily use:** Command Center (0), Best Bets (1), Graded Picks (2), Edge Board (15), My Coach (51), Long Shots (53,
  NBA + NFL), Live Games (54), Bet Log (18), Home (morning brief + afternoon picks table).
- **Labs:** Game Labs (32/34/45/46/47), Tennis Lab (43), International Hoops (44), Soccer Lab (55), Matchup Labs,
  Hot Hand Engines, QB Labs, Anytime TD Engines, Position Matchups (38), Player Lines (26/31/33), Game Script (50).
- **Learning / records:** Postgame Review (41), Model Performance (49), Model Dashboard (17), Track Record (19),
  Retrospective (16), Analyst Desk / Record (39/40), Reports (48), Progression Plan (42), Data Health (20).
- **Logging everywhere:** every pick table ticks rows into the shared log panel (`log_ui.py`): singles / parlay / both,
  coach grade, red-flag confirm, then "📝 Log to Bet Log". Logged bets settle automatically when graded.

Key page behaviour:
- **Live Games (54):** auto-refresh (default 30 s). Basketball/NHL/football: win chance, projected final, live props
  and box score. Tennis: DraftKings-style scorecard, server, sets, tiebreaks, trend arrows; retired/walkover handled
  (below). Soccer: every slate league — win/draw/win from here, projected score, over/under, next goal, red cards.
  International: all 11 leagues (FIBA pages + FIBA LiveStats).
- **International Hoops / Soccer Lab / Live Games** list only leagues with a game **today or tomorrow (New York days)**
  — saved slates `intl_slate` and `soccer_slate` from each capture.
- **Long Shots (53):** alternate rungs vs the "honest" (tail-corrected) chance. NBA defaults to Assists; NFL to Rush
  Yards (the only markets that made money in testing). Look-back by date. ~10 credits per game load.

---

## 4. Automation (GitHub Actions)

**GitHub skips or delays most scheduled runs on this repo.** Every important job therefore also starts when other
jobs finish (`workflow_run`) and guards itself against running twice.

| Workflow | Schedule (UTC) | Also starts after | What it does |
|---|---|---|---|
| `settle-results` | every 30 min 00–08, 11–14 | — | grades props, settles the Bet Log |
| `daily-review` | :30 hourly 07–15 | settle-results, capture-closing-lines, warm-slates, script-learn, close-watch, capture-intl, refresh-*, settle-analyst, capture-game-picks | **the morning learning run** (does nothing before 3 AM ET or once done for the day): grading, calibration, tennis + game-league calibration, saved reports |
| `morning-brief` | 11–15 :05, 20–23 :20 | daily-review, warm-slates | kind `auto` sends by clock: morning brief after the review; afternoon picks note after ~3 PM ET (rebuilds any props board older than 2 h first) |
| `warm-slates` | :41 hourly 14–03 | — | builds & saves props boards (NBA, NFL, NHL, NCAAF, NCAAMB) |
| `capture-intl` | :23 every 3 h | morning-brief, warm-slates, settle-results, capture-closing-lines, close-watch, daily-review | international hoops + tennis capture, then soccer. Triggered runs skip if the last run was < 150 min ago |
| `capture-game-picks` | 15, 21, 00, 03 | — | game-line picks for the Game Labs |
| `capture-closing-lines` | every 15–30 min | — | closing prices (CLV) |
| `capture-line-snapshots` | 14, 18, 21, 00 | — | line history |
| `capture-ufc-odds` | 8×/day | — | UFC prices |
| `close-watch` | 15:40, 20:40, 01:40 | — | pre-game close watch |
| `script-learn` | 10:17, 21:17 | — | game-script learning |
| `refresh-matchups` / `refresh-ncaaf` / `refresh-statcast` | 10:00 / 11:00 / 11:00 | — | data refreshes |
| `settle-analyst` | 12:41 | — | Analyst Desk grading |
| `tuning-report` | Tue 13:17 | — | weekly model-weight proposals — **apply themselves** after a held-out check |
| `refresh-calibration` | Sun 09:00 | — | weekly calibration refresh |
| `research` | manual | — | runs `research/<script>.py` on any branch (backtests, probes, live checks) |

Owner's morning routine: he asks Claude every morning to confirm all actions ran and the learning took place. If
`daily-review` hasn't run by ~5 AM ET, dispatch it by hand (`gh api -X POST
repos/drshawnhall20176/H2_Platform/actions/workflows/daily-review.yml/dispatches -f ref=main`); the brief follows.

---

## 5. The learning loop (all automatic — owner rule: calibrations apply without approval)

- **Nightly grading** of every model read (props and game lines) → Postgame Review, Model Performance, Reports.
- **Prop calibration** per sport/market/side, refitted each morning; applied when it holds up on held-out days.
- **Tennis calibration** (`tennis_calibration.py`): `p' = 0.5 + k(p − 0.5)`; refit daily; applied only if it wins on
  ≥ 2/3 of walk-forward held-out days with positive total gain; needs 100 matches over 6 days. Live since Nov 13 at
  k = 0.70.
- **Game-league calibration:** same rule for every Game Lab / International Hoops league (`game_calibration:<LEAGUE>`),
  reported as GAME_LINES in the brief. Nov 12 check: NCAAMB honest (82% vs 80%); NBA/NHL favourites won more than
  said but < 100 games; international leagues too few.
- **Weekly weight tuning** applies itself after a held-out check (no approvals).
- **Morning brief** (Home + Discord webhook once set): job health, what the model learned, yesterday's scorecard per
  sport (international hoops and tennis included), the owner's bets. **Afternoon picks note:** My Coach's 🟢 Good
  bets (props, college basketball included) plus every playable game-line / international hoops / tennis read.

---

## 6. Standing rules (set by the owner)

**How Claude works on this repo**
- **Build and merge** as judged best: branch → PR → squash-merge (standing permission). Commit trailers:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` + `Claude-Session: <session url>`; PR body ends with
  "🤖 Generated with [Claude Code](https://claude.com/claude-code)".
- Run the full test suite before merging; research/backtests go through the `research` workflow (branch
  `research/calibration-audit`, merge main into it with `-X theirs` first).
- **Plain, honest language; no conflicting statements; no fabricated numbers.** Say when something is untested,
  tracking-only or lost in a backtest. Build only what the evidence supports, and say so when it doesn't (e.g. NFL
  long shots lost overall; chasing price drops lost; soccer/international models lost to the market).

**Product rules**
- Only in-season sports are selectable; tennis, international hoops and soccer are picked from the sport selector.
- **Every table listing games is sorted by start time, earliest first**; game pages get date / time-slot / game filters.
- Soccer and international hoops show **only leagues with games today or tomorrow** (New York days); soccer prices and
  fits only those (Odds API credits: a league is priced at most every 6 h, every run inside 12 h of kickoff).
- **No sport is left out** of the morning review or afternoon picks when it has value.
- Model calibrations apply automatically as the model learns.
- Public Discord build = owner build minus the Bet Log and owner data (Matchup Lab and Position Matchups are public).
- Every pick table supports tick-to-log; logged bets settle automatically.

**Betting rules the coach enforces (My Coach / log panel)**
- **Singles only** for model picks (after Nov 8); parlay limit 2 per day; daily budget and stop-loss from the owner's
  limits (defaults $40 / $25); red flags must be acknowledged before logging.
- **Long shots:** flat $1–2, never chase; same-player rungs never in one parlay; Assists (NBA) / Rush Yards (NFL) are
  the only tested-positive markets.
- **Tennis:** 70%+ favourites were held as "not proven" until the calibration passed (lifted automatically on Nov 13).
  A retirement **after a full set stands** for the moneyline (the books' rule); before a full set, or a walkover,
  is void. Spread / total-games bets on a retired match are void.
- **Soccer:** three-way results grade draws; quarter-line handicaps / totals settle **by hand** (no half-win in the Bet
  Log).

---

## 7. Open items / waiting on the owner

1. **Add `OWNER_BRIEF_WEBHOOK`** (private Discord channel → Integrations → Webhooks) so the brief and picks reach his
   phone. Until then they're on Home only.
2. **Public app secrets:** copy `DATABASE_URL` and `ODDS_API_KEY` into the public app's Streamlit secrets.
3. **Odds API billing:** confirm the subscription after the Nov 13 deactivation.
4. **Agent roadmap** (owner's order): ✅ 1 morning brief + afternoon picks → **2 "ask the platform" chat** (needs an
   Anthropic API key secret; not started) → 3 Discord agent → 4 injury/lineup watcher.
5. Soccer: Switzerland returns no ESPN results (unrated); Montenegro, Northern Ireland, Croatia Cup, Slovakia, Slovenia
   and J2 aren't carried by any reachable feed. Soccer isn't yet in the morning scorecard / picks note (add once
   graded results exist).
6. International: NKL, Iceland, Bahrain, Estonia, Qatar need 30 games before ratings and live win chances appear.
7. NBA / NHL game-line calibration will apply itself once each reaches 100 graded games (likely to *raise* favourites).
8. Older backlog items still listed under "NOT YET DONE" in `PLATFORM_CHECKPOINT.md` (MLB/WNBA off-season items, IDP
   scoring config, NCAAF QB Lab views) — review in the spring.

---

## 8. Key modules (where to look)

| Area | Files |
|---|---|
| Sports registry / sidebar | `sports.py`, `streamlit_app.py`, `streamlit_app_discord.py` |
| Props pipeline | `*_engine.py`, `props_engine.py`, `best_bets_data.py`, `odds_api.py`, `book_menu.py` |
| Coach / logging | `coach.py`, `log_ui.py`, `todays_best.py`, `betlog.py` |
| Learning | `daily_review.py`, `tuning_report.py`, `tennis_calibration.py`, `pick_records.py`, `model_store.py` |
| Brief | `morning_brief.py`, `.github/workflows/morning-brief.yml` |
| Live | `live_games.py`, `live_model.py`, `live_props.py`, `soccer_live.py`, `views/54_Live_Games.py` |
| International hoops / tennis | `intl_hoops.py`, `intl_picks.py`, `tennis_model.py`, `hoops_games_page.py` |
| Soccer | `soccer_model.py`, `soccer_data.py`, `soccer_picks.py`, `soccer_props.py`, `views/55_Soccer_Lab.py` |
| Long shots | `long_shots.py`, `views/53_Long_Shots.py` |
| Research | `research/*.py` (backtests: soccer, tennis, live models, long shots, calibration) |
