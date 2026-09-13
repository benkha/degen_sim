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

After updating a season's CSVs (`data/<year>/parlay_tracker_nfl.csv` / `parlay_tracker_cfb.csv`) with a new week's picks, regenerate the site's data in one step:

```shell
uv run python scripts/generate_data.py                                   # today's date, season = its year
uv run python scripts/generate_data.py --season 2025 --date 2025-12-16   # backfill/recompute a specific season+date
```

This is idempotent per (season, date) — re-running for the same one recomputes and replaces just that entry in `data.json`; all other checkpoints are untouched. Every run also recomputes the `all_time` rollup from scratch across every `data/<year>/` directory found on disk, regardless of which season was targeted.

There is no test suite.

## Architecture

- `src/degen_sim/simulate.py` holds the core simulation logic: `implied_probability` (American odds -> implied win probability), `PickInfo`, `build_pick_infos` (per-picker win/loss/push counts + odds from a picks dataframe), and `compute_standings` (Monte Carlo p-value per picker, 1,000,000 trials by default, vectorized with NumPy).
- `data/<year>/parlay_tracker_nfl.csv` and `data/<year>/parlay_tracker_cfb.csv` are the raw input logs for that season, one row per pick, columns: `Week, Pick (picker name), Bet, Odds (American), Win (Y/N/P)`. Updated by hand each week as game results come in. Note: **`data/` is gitignored** (`/data/*` in `.gitignore`) — the pick history itself is not committed to this repo; only the derived `data.json` is. Worth confirming with whoever maintains the CSVs that they're backed up some other way.
- `scripts/generate_data.py` is the only entry point for producing results: discover every `data/<year>/` directory -> for each, drop unresolved (blank `Win`) rows from both CSVs and `compute_standings` for three slices (Combined, NFL, CFB) -> upsert the target season's checkpoint into `data.json["seasons"][year]["weeks"]` -> recompute `data.json["all_time"]` from the concatenation of every season's raw picks (a true cross-season Monte Carlo p-value, not an average of per-season p-values). Every discovered season gets at least an empty `{pickers: [], weeks: []}` entry so the website always has a tab for it, even before any picks are logged.
- `index.html` + `data.json` (both at repo root) are a static website published via GitHub Pages. Plain vanilla JS (no build step, no framework) that fetches `data.json` client-side and renders tables/canvas charts — mirrors the pattern used in the sibling `top_chef_fantasy` repo. The page has a season tab bar (each season found in `data.json.seasons`, newest first, plus "All-Time") on top of the existing sport tabs (Combined/NFL/CFB). In season mode, charts/snapshot cards are keyed by week (`season.weeks`); in all-time mode, by season (`all_time.by_season`) — both shapes carry `{label, combined, nfl, cfb}` so the same render functions (`getCheckpoints`/`getPickers`/`ranksForSport`, etc.) work for either. The all-time *standings table* specifically uses `all_time.combined/nfl/cfb` (the true merged-season simulation), not just the latest `by_season` entry. `data.json` **is** the season's historical record — there's no other source of point-in-time snapshots, so never regenerate it wholesale; only upsert via `scripts/generate_data.py`. The very first tracked week (`2025-10-07`) was computed from an earlier `cdf` metric before it switched to `p_value`; those rows carry `"approx": true` (converted via `p_value = 1 - cdf`).

## Known methodology limitations (not bugs — don't "fix" without discussion)

The website's Methodology section documents these; they're intentional simplifications, not oversights:

- **Vig is not removed.** `implied_probability` (in `simulate.py`) converts a bet's American odds straight to an implied probability, which still contains the sportsbook's built-in edge (e.g. -110 implies ~52.4%, when a truly fair coin-flip line would be 50%). This means the whole group's p-values trend systematically above 0.5 even at real, zero-edge skill — confirmed empirically across the season's reports (see `data.json`: most weeks have 8-10 of 10 pickers above p=0.5). p-values should be read as relative rankings within a week, not absolute "skill" proof. Properly de-vigging would require the odds on the *other* side of each line, which isn't captured in the CSVs.
- **Pushes are intentionally included in the simulation, not excluded.** In `build_pick_infos`, `odds`/`num_games` include every pick (win, loss, *and* push), while `num_wins` (the value compared against) only counts wins. This looks like a bug at first glance — pushes appear to add an extra simulated coin flip with no real-world counterpart — but it isn't: `num_wins`/`num_games` implicitly model a binary **Win vs. Not-Win** event per pick (Not-Win = loss or push), and a real push *is* a real "Not-Win" observation, correctly counted as 0 toward `num_wins`. Dropping push picks from the simulation instead (as an "obvious fix") would actually be worse — it discards a real, informative outcome. The one legitimate residual nuance: `implied_probability` technically estimates P(Win | bet decided), not unconditional P(Win), so it's a mild over-estimate specifically for push-eligible bets (e.g. spreads/totals on common margins like 3 or 7) — a narrow, minor effect, unlike the vig issue above which touches every single pick.
