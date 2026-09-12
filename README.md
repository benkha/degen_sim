# degen_sim

This repo is for running Monte Carlo simulations to measure accuracy in picking winning bets.

Results are published as a website: https://benkha.github.io/degen_sim/

## Update the Website

After updating `data/parlay_tracker_nfl.csv` and/or `data/parlay_tracker_cfb.csv` with a new week's picks and results, run:

```shell
uv run python scripts/generate_data.py
```

This recomputes standings straight from the CSVs and upserts today's checkpoint into `data.json` (re-running for the same day just replaces that entry). Commit the updated `data.json`. The site itself (`index.html`) reads `data.json` directly — no build step needed. It's served via GitHub Pages from the `main` branch root.

To regenerate a specific date's checkpoint (e.g. to backfill or fix a past entry), pass `--date YYYY-MM-DD`.
