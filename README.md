# degen_sim

This repo is for running Monte Carlo simulations to measure accuracy in picking winning bets.

Results are published as a website: https://benkha.github.io/degen_sim/

## Data Layout

Picks are organized by season under `data/<year>/`:

```
data/2025/parlay_tracker_nfl.csv
data/2025/parlay_tracker_cfb.csv
data/2026/parlay_tracker_nfl.csv
data/2026/parlay_tracker_cfb.csv
```

To start a new season, create a `data/<year>/` folder with both CSVs (headers only is fine) — the website will automatically pick up the new season tab next time `scripts/generate_data.py` runs.

## Update the Website

After updating a season's CSVs with a new week's picks and results, run:

```shell
uv run python scripts/generate_data.py
```

This recomputes standings straight from the CSVs for the season matching the current year, upserts that checkpoint into `data.json`, and recomputes the all-time rollup across every season found under `data/`. Commit the updated `data.json`. The site itself (`index.html`) reads `data.json` directly — no build step needed. It's served via GitHub Pages from the `main` branch root.

To regenerate a specific season/date (e.g. to backfill or fix a past entry), pass `--season YYYY --date YYYY-MM-DD`.
