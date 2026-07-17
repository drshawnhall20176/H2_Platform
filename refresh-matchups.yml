# Auto-refresh the pitch-level Matchup Lab cache — entirely in the cloud, no local step.
#
# WHAT IT DOES:
#   Once a day (and on demand) this pulls the season's PITCH-LEVEL Statcast from Baseball Savant
#   via pybaseball, aggregates it into two compact tables, writes them to data/, and commits them
#   back to the repo. That commit triggers a Streamlit Cloud redeploy, so the Matchup Lab page
#   flips from its empty state to live with zero manual work.
#     data/pitcher_arsenals.csv      (pitcher x pitch-type: usage, whiff, put-away, velo)
#     data/hitter_pitch_splits.csv   (batter x family: whiff, SLG-against, xwOBA-against)
#
# HEAVY: a full-season pitch-level pull is far larger than the barrel-rate pull, so this job
#   runs longer and uses more memory (fine on a GitHub runner; NEVER do this in the app).
#
# ONE-TIME SETUP:
#   1) Commit the updated .gitignore that un-ignores the two CSVs above (folder stays ignored).
#   2) Commit this workflow at .github/workflows/refresh-matchups.yml
#   3) Actions tab -> "refresh-matchups" -> "Run workflow" to populate the tables immediately.
#
# NOTES:
#   - The app only READS the CSVs; pybaseball is installed here in the runner, not in the app.
#   - If pybaseball drifts on column names, pin it below (pip install "pybaseball==2.2.7") and
#     tell Claude so we can adjust the aggregation in matchup_data.py.

name: refresh-matchups

on:
  schedule:
    - cron: "0 10 * * *"      # 10:00 UTC daily (offset from refresh-statcast at 11:00 to avoid
                              # two jobs pushing at the same time)
  workflow_dispatch: {}       # manual "Run workflow" button

permissions:
  contents: write             # allow the job to commit the refreshed tables back to the repo

jobs:
  refresh:
    runs-on: ubuntu-latest
    timeout-minutes: 120        # a full-season pitch pull can take a while
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install pybaseball pandas numpy

      - name: Pull pitch-level Statcast and build the matchup tables
        run: python refresh_matchups.py     # defaults to the current season

      - name: Validate the cache with the app's own loader
        # Use the SAME load() the page uses, so if this passes the Matchup Lab WILL light up.
        run: |
          python - <<'PY'
          import sys
          import matchup_data as MD
          arsenals, splits = MD.load()
          print(f"Loaded {len(arsenals)} pitchers, {len(splits)} hitters")
          if len(arsenals) < 50 or len(splits) < 50:
              print("Tables look empty or invalid — refusing to commit.")
              sys.exit(1)
          PY

      - name: Commit the refreshed tables (only if they changed)
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/pitcher_arsenals.csv data/hitter_pitch_splits.csv data/hitter_pitch_type_splits.csv
          if git diff --staged --quiet; then
            echo "No change in matchup tables — nothing to commit."
          else
            git commit -m "Auto-refresh matchup cache ($(date -u +%Y-%m-%d))"
            git push
          fi
