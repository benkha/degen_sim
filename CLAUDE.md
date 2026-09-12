# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo does

A weekly Monte Carlo simulation that measures how much skill (vs. luck) each person in a friend group shows when picking sports bets. For each picker, their realized record (wins/losses/pushes) and the American odds of each pick are used to compute an implied win probability per bet (assuming no house edge). A 1,000,000-trial Monte Carlo simulation then produces the distribution of possible win counts under those implied probabilities, and a p-value `P(W >= w)` is computed against the picker's actual win count `w`. Lower p-value = more likely their record reflects skill rather than chance.

## Commands

Dependency management uses `uv`.

```shell
uv sync                 # install dependencies
uv run ruff check .     # lint
```

Generate a weekly report by executing the notebook (this is the primary workflow — there is no separate script):

```shell
uv run jupyter nbconvert --to HTML --execute notebooks/degen_sim.ipynb --output-dir=reports/ --output="degen_sim_<YYYYMMDD>"
```

Despite `--to HTML`, output files in `reports/` are committed as `.md`. Before running, update the `DATE` variable near the top of `notebooks/degen_sim.ipynb` (cell defining `DATE = "..."`) to the new report date — this both names the output file and is stamped into the report content.

There is no test suite.

## Architecture

- `notebooks/degen_sim.ipynb` is the actual pipeline — all simulation logic lives here, not in `src/`. Data flows: read `data/parlay_tracker_nfl.csv` and `data/parlay_tracker_cfb.csv` -> filter incomplete rows -> build a `PickInfo` per picker (win/loss/push counts + implied probabilities from odds) -> Monte Carlo simulate each picker's win-count distribution -> compute p-values -> write results to `reports/degen_sim_<DATE>.md` for three slices: Combined (NFL+CFB), NFL only, CFB only.
- `src/degen_sim/` is a thin installable package providing shared helpers imported by the notebook:
  - `common/constants.py` — `DATA_DIR`/`REPORTS_DIR`/`ROOT_DIR` computed relative to the installed package location, so paths resolve correctly regardless of cwd.
  - `common/notebook_utils.py` — notebook display helpers (`markdown()`, `hide_raw_cells()`).
- `data/parlay_tracker_nfl.csv` and `data/parlay_tracker_cfb.csv` are the raw input logs, one row per pick, columns: `Week, Pick (picker name), Bet, Odds (American), Win (Y/N/P)`. These are updated by hand each week as game results come in; rows with a blank `Win` (games not yet played) are filtered out before simulation.
- `reports/` contains one committed markdown report per week (`degen_sim_YYYYMMDD.md`), each linked from `README.md`. The convention (see commit history) is one PR per week titled `Add MM/DD report`, adding both the new CSV rows for that week and the regenerated report.
