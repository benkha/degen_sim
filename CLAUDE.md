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

After updating `data/parlay_tracker_nfl.csv` / `data/parlay_tracker_cfb.csv` with a new week's picks, regenerate the site's data in one step:

```shell
uv run python scripts/generate_data.py               # upserts today's checkpoint into data.json
uv run python scripts/generate_data.py --date 2025-12-16   # backfill/recompute a specific date
```

This is idempotent per date — re-running for the same date recomputes and replaces just that entry in `data.json`; all other dates are untouched.

There is no test suite.

## Architecture

- `src/degen_sim/simulate.py` holds the core simulation logic: `implied_probability` (American odds -> implied win probability), `PickInfo`, `build_pick_infos` (per-picker win/loss/push counts + odds from a picks dataframe), and `compute_standings` (Monte Carlo p-value per picker, 1,000,000 trials by default, vectorized with NumPy).
- `scripts/generate_data.py` is the only entry point for producing results: read `data/parlay_tracker_nfl.csv` and `data/parlay_tracker_cfb.csv` -> drop unresolved (blank `Win`) rows from both -> `compute_standings` for three slices (Combined, NFL, CFB) -> upsert that date's checkpoint into `data.json`. It replaces an older notebook + markdown-report + parsing-script pipeline (see "Legacy pipeline" below).
- `data/parlay_tracker_nfl.csv` and `data/parlay_tracker_cfb.csv` are the raw input logs, one row per pick, columns: `Week, Pick (picker name), Bet, Odds (American), Win (Y/N/P)`. Updated by hand each week as game results come in.
- `index.html` + `data.json` (both at repo root) are a static website published via GitHub Pages, showing season standings, rank/p-value trend charts, and weekly snapshots. Plain vanilla JS (no build step, no framework) that fetches `data.json` client-side and renders tables/canvas charts — mirrors the pattern used in the sibling `top_chef_fantasy` repo. `data.json`'s `weeks` list is itself the season's historical record (each entry is a dated checkpoint with `combined`/`nfl`/`cfb` standings) — there's no other source of point-in-time snapshots, so don't regenerate it wholesale without preserving existing entries.

### Legacy pipeline (superseded, kept for history)

Weeks through 2025-12-16 were produced by manually running `notebooks/degen_sim.ipynb` (which duplicated the logic now in `simulate.py`) to write a `reports/degen_sim_<DATE>.md` file per week, then parsing all of those with a since-removed `scripts/build_site_data.py` to build `data.json`. The notebook and `common/notebook_utils.py` still exist but are unused by the current pipeline — do not extend them for new work. `reports/*.md` remain as an archival record linked from `README.md`; the very first report (`20251007`) used a `cdf` column instead of `p_value` (`data.json` converted it via `p_value = 1 - cdf`, flagged `"approx": true`).

## Known methodology limitations (not bugs — don't "fix" without discussion)

The Methodology section of each report and the website both document these; they're intentional simplifications, not oversights:

- **Vig is not removed.** `implied_probability` (in `simulate.py`) converts a bet's American odds straight to an implied probability, which still contains the sportsbook's built-in edge (e.g. -110 implies ~52.4%, when a truly fair coin-flip line would be 50%). This means the whole group's p-values trend systematically above 0.5 even at real, zero-edge skill — confirmed empirically across the season's reports (see `data.json`: most weeks have 8-10 of 10 pickers above p=0.5). p-values should be read as relative rankings within a week, not absolute "skill" proof. Properly de-vigging would require the odds on the *other* side of each line, which isn't captured in `data/*.csv`.
- **Pushes are intentionally included in the simulation, not excluded.** In `build_pick_infos`, `odds`/`num_games` include every pick (win, loss, *and* push), while `num_wins` (the value compared against) only counts wins. This looks like a bug at first glance — pushes appear to add an extra simulated coin flip with no real-world counterpart — but it isn't: `num_wins`/`num_games` implicitly model a binary **Win vs. Not-Win** event per pick (Not-Win = loss or push), and a real push *is* a real "Not-Win" observation, correctly counted as 0 toward `num_wins`. Dropping push picks from the simulation instead (as an "obvious fix") would actually be worse — it discards a real, informative outcome. The one legitimate residual nuance: `implied_probability` technically estimates P(Win | bet decided), not unconditional P(Win), so it's a mild over-estimate specifically for push-eligible bets (e.g. spreads/totals on common margins like 3 or 7) — a narrow, minor effect, unlike the vig issue above which touches every single pick.
