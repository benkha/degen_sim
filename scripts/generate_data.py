"""Compute standings directly from the pick CSVs and update data.json for the website.

Run this any time after updating data/parlay_tracker_nfl.csv or data/parlay_tracker_cfb.csv:

    uv run python scripts/generate_data.py

This upserts a single checkpoint (by date) into data.json -- re-running for the same
date recomputes and replaces that entry; all other dates are left untouched.
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


def load_resolved_picks(filename: str) -> pd.DataFrame:
    df = pd.read_csv(Path(DATA_DIR) / filename)
    return df[~df["Win"].isna()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat(), help="Checkpoint date (YYYY-MM-DD), default: today")
    parser.add_argument("--trials", type=int, default=1_000_000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    nfl_picks = load_resolved_picks("parlay_tracker_nfl.csv")
    cfb_picks = load_resolved_picks("parlay_tracker_cfb.csv")
    combined_picks = pd.concat([nfl_picks, cfb_picks])

    pickers = sorted(set(nfl_picks["Pick"]) | set(cfb_picks["Pick"]))

    checkpoint_date = datetime.strptime(args.date, "%Y-%m-%d")
    checkpoint = {
        "date": checkpoint_date.strftime("%Y-%m-%d"),
        "label": checkpoint_date.strftime("%b %-d, %Y"),
        "combined": compute_standings(build_pick_infos(pickers, combined_picks), args.trials, args.seed),
        "nfl": compute_standings(build_pick_infos(pickers, nfl_picks), args.trials, args.seed),
        "cfb": compute_standings(build_pick_infos(pickers, cfb_picks), args.trials, args.seed),
    }

    data = json.loads(OUTPUT_PATH.read_text()) if OUTPUT_PATH.exists() else {"weeks": []}

    weeks = [w for w in data.get("weeks", []) if w["date"] != checkpoint["date"]]
    weeks.append(checkpoint)
    weeks.sort(key=lambda w: w["date"])

    all_pickers = sorted(set(pickers) | {row["name"] for week in weeks for row in week["combined"]})

    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pickers": all_pickers,
        "weeks": weeks,
    }

    OUTPUT_PATH.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote checkpoint for {checkpoint['date']} -> {len(weeks)} total weeks -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
