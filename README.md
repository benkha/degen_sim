# degen_sim

This repo measures how much skill (vs. luck) a group of friends shows in picking winning bets: each person's record is compared against the exact distribution of records their picks' odds could have produced.

Results are published as a website: https://benkha.github.io/degen_sim/

## Data Layout

Picks are organized by season under `data/<year>/`, each with a `season.json` config giving the date of Week 1 for each sport:

```
data/2025/parlay_tracker_nfl.csv
data/2025/parlay_tracker_cfb.csv
data/2025/season.json
data/2026/parlay_tracker_nfl.csv
data/2026/parlay_tracker_cfb.csv
data/2026/season.json
```

`season.json` looks like:

```json
{
  "nfl": { "week1_date": "2025-09-07" },
  "cfb": { "week1_date": "2025-08-30" },
  "cfb_week_offset": 1
}
```

Weeks are numbered from 1 in both sports — there's no Week 0 (a Week 0 row is rejected). If CFB has an official "Week 0", log it as Week 1 and set the CFB `week1_date` and `cfb_week_offset` to match. Every pick's calendar date is computed as `week1_date + 7 * (Week - 1) days` — NFL and CFB get their own timeline since their week numbers don't land on the same calendar dates. `cfb_week_offset` says how many weeks ahead CFB's numbering runs versus NFL's (`1` means CFB week 2 lines up with NFL week 1) — it's used to pair up the two sports' weeks for the **Combined** standings, so "Combined" reflects one real week of football rather than a checkpoint every time either sport's date ticks over.

To start a new season: create a `data/<year>/` folder with both CSVs (headers only, or even empty, is fine) and a `season.json`. If a sport's Week 1 date isn't known yet, set its `week1_date` to `null` — that's fine as long as that sport has no resolved picks yet; the script errors clearly if you add resolved picks before filling in the date.

## Update the Website

After updating a season's CSVs with a new week's picks and results, run:

```shell
uv run python scripts/generate_data.py
```

This rebuilds `data.json` from scratch. For every `data/<year>/` directory (4-digit year folders only — anything else under `data/` is ignored) it computes three independent checkpoint timelines — NFL and CFB each get one checkpoint per date they have a game on, and Combined gets one checkpoint per paired NFL/CFB week (see `cfb_week_offset` above) — plus an all-time rollup across every season. There's no incremental/upsert mode — it always fully regenerates from the CSVs + `season.json` configs, so it's safe to re-run any time. Before computing anything, every graded pick is checked (`Win` must be Y/N/P, `Odds` real American odds, `Week` a whole number from 1 to 25, `Pick` filled in); a bad row stops the run and names the file and line to fix. `season.json` is checked the same way (dates as `YYYY-MM-DD` or `null`, `cfb_week_offset` a whole number). Commit the updated `data.json`. The site itself (`index.html`) reads `data.json` directly — no build step needed. It's served via GitHub Pages from the `main` branch root.

### Local preview

Don't open `index.html` directly (`file://...`) — browsers block `fetch()` of local files under that scheme, so `data.json` will fail to load. Serve the folder instead:

```shell
python3 -m http.server 8000
```

then open http://localhost:8000/.

## Development

```shell
uv sync                 # install dependencies
uv run pytest           # tests
uv run ruff check .     # lint
```
