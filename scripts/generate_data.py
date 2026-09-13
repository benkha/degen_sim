"""Compute standings directly from the pick CSVs and rebuild data.json for the website.

Each season directory (data/<year>/) needs a season.json config giving the date of
Week 1 for each sport, plus how many weeks ahead CFB's numbering runs relative to NFL's
(cfb_week_offset), e.g. data/2025/season.json:

    {
      "nfl": {"week1_date": "2025-09-07"},
      "cfb": {"week1_date": "2025-08-30"},
      "cfb_week_offset": 1
    }

A pick's calendar date is week1_date + 7 * (Week - 1) days, computed separately per sport
since NFL and CFB week numbers don't land on the same calendar dates. The NFL and CFB tabs
each get their own checkpoint timeline (one per distinct date that sport has a game on).
The Combined tab instead pairs up each NFL week with the CFB week cfb_week_offset weeks
ahead of it (e.g. CFB week 2 with NFL week 1) into one checkpoint, dated by whichever of
the two week's dates is later.

This always rebuilds data.json from scratch by reading every data/<year>/ directory --
there is no incremental/upsert mode. Run it any time after updating a season's CSVs:

    uv run python scripts/generate_data.py
"""

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from degen_sim.common.constants import DATA_DIR
from degen_sim.simulate import build_pick_infos, compute_standings

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT_DIR / "data.json"

EMPTY_PICKS = pd.DataFrame(columns=["Week", "Pick", "Odds", "Win", "Date"])


def load_season_config(season_dir: Path) -> dict:
    config_path = season_dir / "season.json"
    if not config_path.exists():
        raise SystemExit(
            f"Missing {config_path}. Create it with each sport's Week 1 date and the "
            f"CFB/NFL week offset, e.g.:\n"
            '  {"nfl": {"week1_date": "YYYY-MM-DD"}, "cfb": {"week1_date": "YYYY-MM-DD"}, '
            '"cfb_week_offset": 1}'
        )
    return json.loads(config_path.read_text())


def week_date(week1_date: str, week: int) -> date:
    anchor = datetime.strptime(week1_date, "%Y-%m-%d").date()
    return anchor + timedelta(weeks=week - 1)


def load_dated_picks(season_dir: Path, filename: str, week1_date: str | None) -> pd.DataFrame:
    path = season_dir / filename
    if not path.exists():
        return EMPTY_PICKS.copy()

    df = pd.read_csv(path)
    df = df[~df["Win"].isna()].copy()
    if df.empty:
        df["Date"] = pd.Series(dtype="object")
        return df

    if not week1_date:
        raise SystemExit(
            f"{path} has resolved picks but no week1_date is set in "
            f"{season_dir / 'season.json'} -- fill it in."
        )
    df["Date"] = df["Week"].apply(lambda w: week_date(week1_date, int(w)))
    return df


def standings_through(pickers: list[str], picks: pd.DataFrame, cutoff, trials: int, seed: int) -> list[dict]:
    subset = picks[picks["Date"] <= cutoff] if len(picks) else picks
    return compute_standings(build_pick_infos(pickers, subset), trials, seed)


def sport_weeks(pickers: list[str], picks: pd.DataFrame, trials: int, seed: int) -> list[dict]:
    """One checkpoint per distinct date this sport has a game on."""
    dates = sorted(set(picks["Date"])) if len(picks) else []
    return [
        {
            "date": d.strftime("%Y-%m-%d"),
            "label": d.strftime("%b %-d, %Y"),
            "standings": standings_through(pickers, picks, d, trials, seed),
        }
        for d in dates
    ]


def combined_weeks(
    pickers: list[str],
    nfl_picks: pd.DataFrame,
    cfb_picks: pd.DataFrame,
    nfl_week1_date: str | None,
    cfb_week1_date: str | None,
    cfb_week_offset: int,
    trials: int,
    seed: int,
) -> list[dict]:
    """One checkpoint per NFL week, paired with the CFB week cfb_week_offset weeks ahead."""
    nfl_week_nums = set(nfl_picks["Week"]) if len(nfl_picks) else set()
    cfb_week_nums = set(cfb_picks["Week"]) if len(cfb_picks) else set()
    aligned_nfl_weeks = sorted(nfl_week_nums | {w - cfb_week_offset for w in cfb_week_nums})

    checkpoints = []
    for nfl_w in aligned_nfl_weeks:
        cfb_w = nfl_w + cfb_week_offset
        nfl_subset = nfl_picks[nfl_picks["Week"] <= nfl_w] if len(nfl_picks) else nfl_picks
        cfb_subset = cfb_picks[cfb_picks["Week"] <= cfb_w] if len(cfb_picks) else cfb_picks
        combined_subset = pd.concat([nfl_subset, cfb_subset], ignore_index=True)

        # Only count a sport's week toward the checkpoint date if it actually has
        # picks by then -- otherwise a not-yet-started sport (e.g. NFL before its
        # season opens) would push the date later for no real reason.
        candidate_dates = []
        if len(nfl_subset):
            candidate_dates.append(week_date(nfl_week1_date, nfl_w))
        if len(cfb_subset):
            candidate_dates.append(week_date(cfb_week1_date, cfb_w))
        cutoff = max(candidate_dates)

        checkpoints.append(
            {
                "date": cutoff.strftime("%Y-%m-%d"),
                "label": cutoff.strftime("%b %-d, %Y"),
                "standings": compute_standings(build_pick_infos(pickers, combined_subset), trials, seed),
            }
        )
    return checkpoints


def compute_season(season_dir: Path, trials: int, seed: int) -> dict:
    config = load_season_config(season_dir)
    nfl_week1_date = config.get("nfl", {}).get("week1_date")
    cfb_week1_date = config.get("cfb", {}).get("week1_date")
    cfb_week_offset = config.get("cfb_week_offset", 0)

    nfl_picks = load_dated_picks(season_dir, "parlay_tracker_nfl.csv", nfl_week1_date)
    cfb_picks = load_dated_picks(season_dir, "parlay_tracker_cfb.csv", cfb_week1_date)
    pickers = sorted(set(nfl_picks["Pick"]) | set(cfb_picks["Pick"]))

    weeks = {
        "combined": combined_weeks(
            pickers, nfl_picks, cfb_picks, nfl_week1_date, cfb_week1_date, cfb_week_offset, trials, seed
        ),
        "nfl": sport_weeks(pickers, nfl_picks, trials, seed),
        "cfb": sport_weeks(pickers, cfb_picks, trials, seed),
    }

    return {"pickers": pickers, "weeks": weeks, "nfl_picks": nfl_picks, "cfb_picks": cfb_picks}


def discover_seasons() -> list[str]:
    return sorted(p.name for p in Path(DATA_DIR).iterdir() if p.is_dir())


def all_time_weekly(computed: dict, trials: int, seed: int) -> dict:
    """All-time weekly checkpoints, one per sport.

    Reuses each season's own checkpoint dates (so Combined still pairs NFL/CFB
    weeks correctly within a season), but standings at each date are computed
    from *every* season's picks up to that date, not just the current season's --
    so e.g. 2026 Week 1's checkpoint already includes all of 2025's picks as part
    of the distribution, not a fresh restart.
    """
    weeks = {}
    for sport, pick_key in (("combined", None), ("nfl", "nfl_picks"), ("cfb", "cfb_picks")):
        if sport == "combined":
            frames = [pd.concat([c["nfl_picks"], c["cfb_picks"]], ignore_index=True) for c in computed.values()]
        else:
            frames = [c[pick_key] for c in computed.values()]
        sport_picks = pd.concat(frames, ignore_index=True) if frames else EMPTY_PICKS
        sport_pickers = sorted(set(sport_picks["Pick"])) if len(sport_picks) else []

        checkpoint_dates = sorted(
            {datetime.strptime(w["date"], "%Y-%m-%d").date() for c in computed.values() for w in c["weeks"][sport]}
        )
        weeks[sport] = [
            {
                "date": d.strftime("%Y-%m-%d"),
                "label": d.strftime("%b %-d, %Y"),
                "standings": standings_through(sport_pickers, sport_picks, d, trials, seed),
            }
            for d in checkpoint_dates
        ]
    return weeks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=1_000_000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    computed = {s: compute_season(Path(DATA_DIR) / s, args.trials, args.seed) for s in discover_seasons()}

    seasons_data = {s: {"pickers": c["pickers"], "weeks": c["weeks"]} for s, c in computed.items()}
    all_pickers = sorted(set().union(*(set(c["pickers"]) for c in computed.values()))) if computed else []

    all_time_weeks = all_time_weekly(computed, args.trials, args.seed)
    latest_standings = {
        sport: all_time_weeks[sport][-1]["standings"] if all_time_weeks[sport] else []
        for sport in ("combined", "nfl", "cfb")
    }

    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seasons": seasons_data,
        "all_time": {
            "pickers": all_pickers,
            **latest_standings,
            "weeks": all_time_weeks,
        },
    }

    OUTPUT_PATH.write_text(json.dumps(data, indent=2) + "\n")
    for s, c in sorted(computed.items()):
        counts = {sport: len(c["weeks"][sport]) for sport in ("combined", "nfl", "cfb")}
        print(f"{s}: {counts}")
    all_time_counts = {sport: len(all_time_weeks[sport]) for sport in ("combined", "nfl", "cfb")}
    print(f"all_time: {all_time_counts}")
    print(f"Rebuilt {OUTPUT_PATH} from scratch across seasons: {list(computed)}")


if __name__ == "__main__":
    main()
