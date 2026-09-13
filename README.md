# degen_sim

This repo is for running Monte Carlo simulations to measure accuracy in picking winning bets.

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

Every pick's calendar date is computed as `week1_date + 7 * (Week - 1) days` — NFL and CFB get their own timeline since their week numbers don't land on the same calendar dates. `cfb_week_offset` says how many weeks ahead CFB's numbering runs versus NFL's (`1` means CFB week 2 lines up with NFL week 1) — it's used to pair up the two sports' weeks for the **Combined** standings, so "Combined" reflects one real week of football rather than a checkpoint every time either sport's date ticks over.

To start a new season: create a `data/<year>/` folder with both CSVs (headers only is fine) and a `season.json`. If a sport's Week 1 date isn't known yet, set its `week1_date` to `null` — that's fine as long as that sport has no resolved picks yet; the script errors clearly if you add resolved picks before filling in the date.

## Update the Website

After updating a season's CSVs with a new week's picks and results, run:

```shell
uv run python scripts/generate_data.py
```

This rebuilds `data.json` from scratch. For every `data/<year>/` directory it computes three independent checkpoint timelines — NFL and CFB each get one checkpoint per date they have a game on, and Combined gets one checkpoint per paired NFL/CFB week (see `cfb_week_offset` above) — plus an all-time rollup across every season. There's no incremental/upsert mode — it always fully regenerates from the CSVs + `season.json` configs, so it's safe to re-run any time. Commit the updated `data.json`. The site itself (`index.html`) reads `data.json` directly — no build step needed. It's served via GitHub Pages from the `main` branch root.

### Local preview

Don't open `index.html` directly (`file://...`) — browsers block `fetch()` of local files under that scheme, so `data.json` will fail to load. Serve the folder instead:

```shell
python3 -m http.server 8000
```

then open http://localhost:8000/.
