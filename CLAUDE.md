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

After adding a new weekly report, rebuild the website's data file:

```shell
uv run python scripts/build_site_data.py
```

There is no test suite.

## Architecture

- `notebooks/degen_sim.ipynb` is the actual pipeline — all simulation logic lives here, not in `src/`. Data flows: read `data/parlay_tracker_nfl.csv` and `data/parlay_tracker_cfb.csv` -> filter incomplete rows -> build a `PickInfo` per picker (win/loss/push counts + implied probabilities from odds) -> Monte Carlo simulate each picker's win-count distribution -> compute p-values -> write results to `reports/degen_sim_<DATE>.md` for three slices: Combined (NFL+CFB), NFL only, CFB only.
- `src/degen_sim/` is a thin installable package providing shared helpers imported by the notebook:
  - `common/constants.py` — `DATA_DIR`/`REPORTS_DIR`/`ROOT_DIR` computed relative to the installed package location, so paths resolve correctly regardless of cwd.
  - `common/notebook_utils.py` — notebook display helpers (`markdown()`, `hide_raw_cells()`).
- `data/parlay_tracker_nfl.csv` and `data/parlay_tracker_cfb.csv` are the raw input logs, one row per pick, columns: `Week, Pick (picker name), Bet, Odds (American), Win (Y/N/P)`. These are updated by hand each week as game results come in; rows with a blank `Win` (games not yet played) are filtered out before simulation.
- `reports/` contains one committed markdown report per week (`degen_sim_YYYYMMDD.md`), each linked from `README.md`. The convention (see commit history) is one PR per week titled `Add MM/DD report`, adding both the new CSV rows for that week and the regenerated report.
- `index.html` + `data.json` (both at repo root) are a static website published via GitHub Pages, showing season standings, rank/p-value trend charts, and weekly snapshots. It's plain vanilla JS (no build step, no framework) that fetches `data.json` client-side and renders tables/canvas charts — mirrors the pattern used in the sibling `top_chef_fantasy` repo.
- `scripts/build_site_data.py` regenerates `data.json` by parsing every `reports/*.md` file (this is the only source of truth for historical weekly standings — the CSVs alone don't preserve point-in-time snapshots). The very first report (`20251007`) used a `cdf` column instead of `p_value`; the script converts it via `p_value = 1 - cdf` and flags those rows with `"approx": true`.

## Known methodology limitations (not bugs — don't "fix" without discussion)

The Methodology section of each report and the website both document these; they're intentional simplifications, not oversights:

- **Vig is not removed.** `american_to_implied_prob` converts a bet's American odds straight to an implied probability, which still contains the sportsbook's built-in edge (e.g. -110 implies ~52.4%, when a truly fair coin-flip line would be 50%). This means the whole group's p-values trend systematically above 0.5 even at real, zero-edge skill — confirmed empirically across the season's reports (see `data.json`: most weeks have 8-10 of 10 pickers above p=0.5). p-values should be read as relative rankings within a week, not absolute "skill" proof. Properly de-vigging would require the odds on the *other* side of each line, which isn't captured in `data/*.csv`.
- **Pushes are intentionally included in the simulation, not excluded.** In `get_pick_infos`, `odds`/`num_games` include every pick (win, loss, *and* push), while `num_wins` (the value compared against) only counts wins. This looks like a bug at first glance — pushes appear to add an extra simulated coin flip with no real-world counterpart — but it isn't: `num_wins`/`num_games` implicitly model a binary **Win vs. Not-Win** event per pick (Not-Win = loss or push), and a real push *is* a real "Not-Win" observation, correctly counted as 0 toward `num_wins`. Dropping push picks from the simulation instead (as an "obvious fix") would actually be worse — it discards a real, informative outcome. The one legitimate residual nuance: `american_to_implied_prob` technically estimates P(Win | bet decided), not unconditional P(Win), so it's a mild over-estimate specifically for push-eligible bets (e.g. spreads/totals on common margins like 3 or 7) — a narrow, minor effect, unlike the vig issue above which touches every single pick.
