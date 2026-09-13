"""Compute standings directly from the pick CSVs and update data.json for the website.

Data is organized by season: data/<season>/parlay_tracker_nfl.csv and
data/<season>/parlay_tracker_cfb.csv. Run this any time after updating a season's CSVs:

    uv run python scripts/generate_data.py                              # today's date, season = its year
    uv run python scripts/generate_data.py --season 2025 --date 2025-12-16   # backfill a specific season/date

This upserts a single weekly checkpoint (by date) into that season's entry in data.json,
then recomputes the all-time rollup (combining every season found under data/) from scratch.
Every season directory found under data/ is guaranteed an entry in data.json (even an empty
one), so the website always has a tab to show for it.
"""

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from degen_sim.common.constants import DATA_DIR
from degen_sim.simulate import build_pick_infos, compute_standings

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT_DIR / "data.json"

EMPTY_PICKS = pd.DataFrame(columns=["Pick", "Odds", "Win"])


def load_resolved_picks(season_dir: Path, filename: str) -> pd.DataFrame:
    path = season_dir / filename
    if not path.exists():
        return EMPTY_PICKS
    df = pd.read_csv(path)
    return df[~df["Win"].isna()]


def season_standings(season_dir: Path, trials: int, seed: int) -> dict:
    nfl_picks = load_resolved_picks(season_dir, "parlay_tracker_nfl.csv")
    cfb_picks = load_resolved_picks(season_dir, "parlay_tracker_cfb.csv")
    combined_picks = pd.concat([nfl_picks, cfb_picks])
    pickers = sorted(set(nfl_picks["Pick"]) | set(cfb_picks["Pick"]))
    return {
        "pickers": pickers,
        "combined": compute_standings(build_pick_infos(pickers, combined_picks), trials, seed),
        "nfl": compute_standings(build_pick_infos(pickers, nfl_picks), trials, seed),
        "cfb": compute_standings(build_pick_infos(pickers, cfb_picks), trials, seed),
        "nfl_picks": nfl_picks,
        "cfb_picks": cfb_picks,
    }


def discover_seasons() -> list[str]:
    data_dir = Path(DATA_DIR)
    return sorted(p.name for p in data_dir.iterdir() if p.is_dir())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat(), help="Checkpoint date (YYYY-MM-DD), default: today")
    parser.add_argument("--season", default=None, help="Season folder under data/ (default: the year of --date)")
    parser.add_argument("--trials", type=int, default=1_000_000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    checkpoint_date = datetime.strptime(args.date, "%Y-%m-%d")
    season = args.season or str(checkpoint_date.year)

    season_dir = Path(DATA_DIR) / season
    if not season_dir.is_dir():
        raise SystemExit(
            f"No data/{season}/ directory found. Create it with parlay_tracker_nfl.csv / "
            f"parlay_tracker_cfb.csv first."
        )

    data = json.loads(OUTPUT_PATH.read_text()) if OUTPUT_PATH.exists() else {}
    seasons_data = data.setdefault("seasons", {})

    # Compute standings for every season directory once, reusing the result for both
    # that season's own checkpoint (if it's the target) and the all-time rollup below.
    computed = {}
    for s in discover_seasons():
        computed[s] = season_standings(Path(DATA_DIR) / s, args.trials, args.seed)

    target = computed[season]
    if target["combined"]:
        checkpoint = {
            "date": checkpoint_date.strftime("%Y-%m-%d"),
            "label": checkpoint_date.strftime("%b %-d, %Y"),
            "combined": target["combined"],
            "nfl": target["nfl"],
            "cfb": target["cfb"],
        }
        season_entry = seasons_data.setdefault(season, {"pickers": [], "weeks": []})
        weeks = [w for w in season_entry["weeks"] if w["date"] != checkpoint["date"]]
        weeks.append(checkpoint)
        weeks.sort(key=lambda w: w["date"])
        season_entry["weeks"] = weeks
        season_entry["pickers"] = sorted(set(target["pickers"]) | {r["name"] for w in weeks for r in w["combined"]})
        print(f"Wrote {season} checkpoint for {checkpoint['date']} -> {len(weeks)} weeks")
    else:
        print(f"No resolved picks in data/{season}/ yet -- skipping checkpoint")

    # Every discovered season gets at least an empty entry, so the website always has a tab.
    for s in computed:
        seasons_data.setdefault(s, {"pickers": [], "weeks": []})

    # Recompute the all-time rollup from scratch across every season found on disk.
    all_nfl = pd.concat([c["nfl_picks"] for c in computed.values()], ignore_index=True) if computed else EMPTY_PICKS
    all_cfb = pd.concat([c["cfb_picks"] for c in computed.values()], ignore_index=True) if computed else EMPTY_PICKS
    all_combined = pd.concat([all_nfl, all_cfb], ignore_index=True)
    all_pickers = sorted(set(all_nfl["Pick"]) | set(all_cfb["Pick"]))

    by_season = [
        {"season": s, "label": s, "combined": c["combined"], "nfl": c["nfl"], "cfb": c["cfb"]}
        for s, c in sorted(computed.items())
        if c["combined"]
    ]

    data["seasons"] = seasons_data
    data["all_time"] = {
        "pickers": all_pickers,
        "combined": compute_standings(build_pick_infos(all_pickers, all_combined), args.trials, args.seed),
        "nfl": compute_standings(build_pick_infos(all_pickers, all_nfl), args.trials, args.seed),
        "cfb": compute_standings(build_pick_infos(all_pickers, all_cfb), args.trials, args.seed),
        "by_season": by_season,
    }
    data["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    OUTPUT_PATH.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Recomputed all-time rollup across seasons: {list(computed)} -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
