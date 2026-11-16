# H2 Sports Platform — Handoff (current as of Mon Nov 16, 2026, 6 AM ET)

This is the **current** picture: what runs, where, how it's set up, and the rules the owner has set.
`PLATFORM_CHECKPOINT.md` is the historical build log (July–October); where they disagree, this file wins.

Owner: Dr. Shawn Hall (H2 Sports, LLC; brand "H2 Sports Media"; co-owner Deezy). Repo:
`drshawnhall20176/H2_Platform`, branch `main`. 375 commits, 56 pages, 161 test files, **~3,690 tests passing**
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
| `script-learn` | 06:17, 09:17 (backup), 21:17 | — | game-script learning (morning run moved before the brief Nov 16; the brief counts any run in the last ~day) |
| `refresh-matchups` / `refresh-ncaaf` / `refresh-statcast` | 10:00 / 11:00 / 11:00 | — | data refreshes |
| `settle-analyst` | 12:41 | — | Analyst Desk grading |
| `tuning-report` | daily 13:17 | daily-review (once a day) | model-vs-market blend weights — **apply themselves** after a held-out check |
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
- **Daily weight tuning** (blend weights) applies itself after a held-out check (no approvals).
- **Short seasons (NFL / NCAAF):** 63-day window, held-out checks by game (5 folds), 2 slates minimum; older graded
  reads are rescaled to today's factors so the whole window counts. First result Nov 16: NFL Unders 0.57 → 0.70
  (held up on 4 of 5 game groups).
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
- Every pick table supports tick-to-log (UFC included since Nov 15); logged bets settle automatically.
- **One model, one answer (Nov 15):** no page may show a second, competing player projection. Older tools (Hot Hand,
  Matchup / QB Labs, Anytime TD, Player Lines) lead with the model's read via `model_view.py`; their own numbers are
  the explanation, flagged ✅/⚠️ when they'd point the other way. Coin flips (< 52%) say "Toss-up".
- **Consistent symbols everywhere:** the Use column (⛔ Pass / 🎯 Single / 🎟️ Parlay leg / Parlay + Single) on every
  pick table, game lines included; A–F grades live in the log box.
- A pick logged as a single and as a parlay leg counts **once** in records (`betlog.dedupe_picks`).

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

**Latest state (Mon Nov 16, 6 AM ET).** All overnight jobs ran; brief rebuilt and clean. Sunday's bets: singles
7–8, parlay 0–1, **−$3.82**. NFL so far: nothing tested profitable after 6 slates (T+A leans lost; Receptions, Solo
Tackles, Rush Yards slightly positive on small samples). Open bets: **#743 Tiafoe +4.5 games (−110, $3)** and
**#744 Cobolli +3.5 games (+100, $3)**, ATP Finals Nov 16, settle themselves from the tennis records. Odds API ≈ 75k
credits left.


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
| Regression to the mean (Nov 14) | `props_engine.shrink_toward`; NBA `player_props.RATE_SHRINK_MIN` (reb/ast/3s 45 min, blk/tov 110, stl 220; points and points combos own rate); football `MARKET_SHRINK["Interceptions"]=1200`; NHL `SHRINK_MIN["sog"]=90`. Evidence: research/stability_audit.py, regression_test.py, regression_validate.py |
| Regression, round 2 (Nov 14) | Soccer ratings = 50% goals + 50% shots-based xG (`soccer_picks.XG_WEIGHT`, team shots cached as results_archive `SOCCERT_<league>`; research/soccer_xg_test.py). Tested, NOT adopted: NBA points toward the player's own longer rate (research/nba_points_own.py: flat) and NFL interception-worthy throws (research/int_worthy_test.py: log loss 1.0874 -> 1.0861, too small to justify a play-by-play pipeline; the 1,200-attempt INT shrink already captures it). NBA points' real issue is the outcome spread (calibration slope 0.30), handled by the side factor for now. |
| Learning loops, round 3 (Nov 14) | Daily: auto side/overall calibration (daily_review → calibration.auto_side/auto_global) and, from Nov 14, the model-vs-market blend weights (tuning-report: cron + after daily-review, once a day; auto-applies only on held-out wins). Weekly: refresh-calibration (grading-history corrections). NBA regression target = position group G/F/C, `RATE_SHRINK_MIN` reb/ast/3s 22.5 min, blk/tov 55, stl 110 (real-line check: research/nba_real_lines_eval.py). Parlay correlation measured per sport: `slip_sim.MEASURED_RHO` (research/loop_audit.py). Records show a 90% range (`pick_records.margin`). Finding: on real NBA lines the model ≈ market overall (log loss ~.6925); edges are market-specific (Assists, Threes, Rebounds +3-10% ROI on leans; Points/combos negative). Outcome-width test on proxy lines was uninformative (proxy lines sit at the player's own median); width is handled by the learned blend weight + side factors on real lines. |
| Short seasons (Nov 15) | NFL / NCAAF (`WEEKLY_SPORTS` in calibration.py, tuning_report.py, postgame.py): 63-day window (`daily_review.WEEKLY_TREND_DAYS`, tuning report 63 days); held-out checks by GAME (5 folds; tunings leave-one-game-out) instead of by day; 2 slates minimum. All sports: graded chances are rescaled from the factor active when the read was saved to today's (`calibration.rescale` / `factor_history`), and weekly tunings rescale projections the same way (`postgame._tuning_history`), so the whole window counts instead of only the days since the last change. Dry run Nov 15: NFL/NCAAF factors evaluated on 1,000+ reads per side; current factors held (no change earned). |
| One model (Nov 15) | `model_view.py`: every player page shows THE model's read (the day's newest saved board read — same as Today's best / Best Bets / My Coach): Line, Model proj, Model call (the likelier side; under 52% it says "Toss-up"), Chance, Use. Pages' own numbers are relabeled as the explanation ("Form × matchup", "Recent scoring rate") with an Agrees ✅/⚠️ column. Wired into Hot Hand Engines (10, 25, 35), Matchup Labs (11, 12, 30: model read table + model line on every chart), QB Labs (14, 29), Anytime TD Engines (13, 36: ranked by Model TD %), Player Lines (31, 33: board line replaces the old "model default" line). Measured before: Hot Hand vs model same side only 75%. |
| Lab long shots (Nov 14, tracking) | `lab_long_shots.py`: tennis / intl hoops / soccer underdogs +300 (free, from lab records); soccer anytime goalscorers +400, 5+ starts, scanned every 6 h from `long_shots_scan.run` (≤24 matches, ~3 credits each); Home shows them under 💎, plus soccer rows in the game-lines table and a 📈 soccer price-flag list |
| Fixes Nov 15–16 | NCAAF game-line bets log as NCAAF and settle from finals (#251); NFL string player ids (#253); pick dedupe (#254); morning brief job window for game-script learning (#256); box-score settlement accepts basketball display names "Reb+Ast" / "Blocks+Steals" / "Turnovers" (#257 — #742 had sat open) |
| Odds API credits (Nov 16) | `odds_meter.py` counts each call's cost from the API's own `x-requests-last` header, per New York day / job / feed (table `odds_usage`, `model_store.add_odds_usage`); Data Health shows the totals. Hooked into every fetch helper that reaches the Odds API. Two trims the same day: line snapshots price only games starting within 24 h (`capture_line_snapshots.SNAPSHOT_HOURS`; was every listed game), and the long-shots scan reuses the props offers warm-slates just saved (`best_bets_data.recent_offers`, fresh for 45 min) instead of paying for the slate again. Savings are estimated from the code, not yet measured: read the meter after a full day. |
| Long Shots and Analyst Desk lead (Nov 16) | **Long Shots**: today's view opens on "Tonight's top long shots", up to four cards from the scheduled scan's saved result (`long_shots_scan.lead_cards`; no credits): price, honest chance vs the book's, game, and whether the market is one that tested positive (those first) or one that lost in testing; an expander lists every value long shot in the scan. The game picker and the owner's load button follow under "Dig into one game". **Analyst Desk**: the Desk tab opens on three tiles: calls on today's slate, hidden gems, and the desk's graded record (hit rate, calls graded, what the model said), then the write-up as before. |
| Live Games leads with the closest game (Nov 16) | `live_lead.py` + the main board in `views/54_Live_Games.py` (basketball, hockey, football, international): a summary row first (live now, the closest game and who is ahead, the biggest win-chance swing since the start when it is 10+ points, still to start, final), then the live cards **closest first** (the leader's win chance nearest 50%; it was start order), the top one tagged "⚖️ Closest game" when its leader is under 65%. "Later today" is now "Next up": start, starts in, the pre-game favourite and projected score for the next 8 games (the Game Lab's projection; football: the books' line), open by default when nothing is live. The tennis and soccer boards are separate fragments and keep their own order. |
| Find a team, every Game Lab (Nov 16) | `components.team_select`: a "Find a team" dropdown (the teams playing, A to Z, "All teams" by default; type in it to search) on every Game Lab: NBA / NHL / college basketball / international (`hoops_games_page`, both the priced and the fair-price leagues; it replaces the free-text box that only some leagues had), the NCAAF ratings slate and the NFL slate. It matches a team exactly, so "Duke" no longer also returns "Duke State". Not on the Tennis or Soccer labs (their own pages). |
| Game simulation in every Game Lab (Nov 16) | `game_sim.py` + `hoops_games_page._one_game`: the basketball / hockey / international Game Labs now have the football labs' two one-game sections under the slate ("One game, up close"): **Team scoring context** (recent avg scored / allowed over the last 5 games vs the season, from `results_archive`) and **Moneyline / spread / total — simulated** (20,000 games). One model, one answer: the simulation runs AROUND the ratings model's own projection, so the projected score, spread, total and the win chance are the model's (the stored `model_p`); the simulation adds likely scoring ranges (8 of 10 games), how often the game is close or a blowout, and for hockey the overtime rate. Basketball: correlated scores spread by `todays_best.MARGIN_SD / TOTAL_SD`; hockey: Poisson goals, regulation ties to a 50/50 overtime. Seeded per game so numbers don't flicker. Deliberately NOT shown: a simulated chance of covering the book's spread or total (the long backtest says the model's side covers ~51% whatever the gap, so that number would overstate). |
| Position Matchups, results first (Nov 16) | The Player props tab (the Players page's default "By position" view) opened on a paragraph, an open lines panel and four switches before any read. Now: Market, then the best reads and the team tables. Folded away, one click each: "ℹ️ How to read this" (the two long explanations), "🎲 Game lines, rest & the market" (starts closed; its label says whether book lines are loaded), "⚙️ Options" (my own lines, the model's working, side, news check; its label lists what is switched on, and it opens by itself in edit mode). No control was removed and no key changed. Hot Hand, Matchup Lab, QB Lab and Anytime TD already lead with their boards and were left as they are. |
| Start here on Best Bets (Nov 16) | `start_here.py`: up to four cards above the filters and the full board, on every build: the strongest playable reads from the board the page already built (no extra fetch), one per player, none held for news or carrying a warning, never a pick type with a losing 30-day record; winning pick types first, then 🔒, then chance. Each card shows chance, best price, game and the pick type's record. Boards with no Use tags (MLB / WNBA) fall back to the highest-chance reads with conviction 1.2+ and say they have no record. Owner direction this day: every page should open on something to browse and act on (site-wide pass in progress; done so far: Game Labs, Best Bets). |
| Game previews (Nov 16) — the standard on every build | `game_previews.py` + `hoops_games_page._previews`: the basketball / hockey / international Game Labs list upcoming games as previews, not a wall of ⛔ Pass (owner rule, Nov 16: this is the standard on the owner and Discord builds too, not only the commercial view). Each game: the side the model leans to, the gap in points, **form** (how leans of that size have done over the last 30 days: 🔥 Hot 55%+ of 20+ games, ➖ Even, ❄️ Cold under 47.6%, 🆕 New), projected score, the model's winner, book line vs model line; a "Worth a look first" list (biggest gaps whose size is running hot, never cold); a "Biggest disagreements first" switch. Owner / Discord builds keep the Use column plus Long backtest, Tracking pick and the game-specific Why (`pick_records.spread_why`), and the owner still ticks rows to log; the commercial view shows a Pick column only where a tested rule tagged a game. Nothing is called a pick without a tested rule; form is labelled recent results, not an edge. Football (same day): the NCAAF Game Lab's ratings-model slate uses the same previews with form (tracking pick and news check kept); the NFL Game Lab opens on "The slate at a glance" (projected score, the model's winner, model spread and total for every game, from the page's own simulation; `game_previews.sim_row`) above the one-game detail. NFL has no stored book lines or graded game leans, so no lean, gap or form there yet: that needs NFL added to capture-game-picks. |
| Commercial layout (Nov 16, preview) | `nav_layout.py`: the customer sidebar, shown by a deployment with `AUDIENCE = "commercial"` or by the owner app's sidebar switch "👀 Preview the commercial layout" (layout only; pages keep the owner's log boxes). Four sections with plain names: Today (Today, All picks, Live, Long shots) / Research (Games, Players, Schedule, Daily write-up) / Track record / Beta · tracking only (Tennis, International hoops, Soccer). NBA and NFL: 10 pages vs 31 on the owner app. **Today** (57, `customer_today.py`) replaces Home for customers: the day's prop picks and playable game lines across all in-season sports from saved boards (no credits), each with its pick type's 30-day record; losing pick types never shown, too-new ones only on request. **Players** (58, `players_hub.py`): one switcher over the sport's player tools, running the chosen tool's own script unchanged. **Model Record** (56, `model_record.py`): the model's graded 30-day record, nothing from the Bet Log. The owner and public Discord sidebars are unchanged until the owner switches. Not done: the tools inside Players are still the owner's workbench pages (many controls), and no sign-in or billing exists. |
| College football (Nov 14–15) | Unbiased spread model (home bias removed), Spread / Total / Model columns, lean record split by gap size, NCAAF Game Lab caching + schedule-only list (#234, #249, #250); Long Shots now NBA, NFL, NHL, NCAAF (NCAAF Rush / Receiving Yards tested, Pass Yards skipped) |
| Research | `research/*.py` (backtests: soccer, tennis, live models, long shots, calibration). Nov 15: `hh_vs_model.py` (Hot Hand vs model agreement), `pitcin_tonight.py`, `today_bids.py`, `health_nov16.py` |
