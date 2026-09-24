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

Resolved picks (a non-blank Win) are validated on load -- Win must be Y/N/P, Odds must be
valid American odds, Week a whole number from 1 to MAX_WEEK -- and any bad row aborts the run with its file
and line number, rather than silently skewing the results. Seasons must also run in
order: a week1_date that makes one season's checkpoints overlap an earlier season's
aborts the run too, since the All-Time timeline would otherwise go back in time.

This always rebuilds data.json from scratch by reading every data/<year>/ directory --
there is no incremental/upsert mode. Run it any time after updating a season's CSVs:

    uv run python scripts/generate_data.py
"""

import argparse
import csv
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from degen_sim.simulate import PickInfo, build_pick_infos, compute_standings, is_valid_american_odds

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_PATH = ROOT_DIR / "data.json"

SPORTS = ("combined", "nfl", "cfb")
REQUIRED_COLUMNS = ["Week", "Pick", "Odds", "Win"]
VALID_RESULTS = {"Y", "N", "P"}
# Both sports number their weeks from 1. No season runs past ~22 weeks (NFL's 18 plus
# playoffs), so anything beyond this is a typo -- caught here rather than becoming a
# checkpoint months in the future (or overflowing the date math entirely).
MAX_WEEK = 25
EMPTY_PICKS = pd.DataFrame(columns=["Week", "Pick", "Odds", "Win", "Date"])

# A checkpoint's cutoff date plus every pick that counts toward it.
Cut = tuple[date, pd.DataFrame]


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
    return anchor + timedelta(weeks=int(week) - 1)


def concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
    # Skipping empty frames avoids pandas' FutureWarning about concatenating them.
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else EMPTY_PICKS.copy()


def read_csv_rows(path: Path) -> pd.DataFrame:
    """Every non-blank record as strings, indexed by the file line it starts on.

    Parsed with the csv module rather than pd.read_csv so that (a) every value stays
    literal text -- pandas would turn a picker named "NA"/"None" or a Win of "N/A" into
    missing values -- and (b) error line numbers stay right even when a quoted field
    spans several lines. A record with extra non-blank fields is an error rather than
    pandas' behavior of silently shifting its columns.
    """
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        rows, lines, extra = [], [], []
        start = reader.line_num + 1
        for record in reader:
            if any(v.strip() for v in record[len(header) :]):
                extra.append(f"  line {start}: has {len(record)} fields, expected {len(header)}")
            if any(v.strip() for v in record):
                rows.append((record + [""] * len(header))[: len(header)])
                lines.append(start)
            start = reader.line_num + 1
    if extra:
        raise SystemExit(f"{path} has rows with too many fields:\n" + "\n".join(extra))
    return pd.DataFrame(rows, columns=header, index=lines, dtype="object")


def load_dated_picks(season_dir: Path, filename: str, week1_date: str | None) -> pd.DataFrame:
    path = season_dir / filename
    if not path.exists():
        return EMPTY_PICKS.copy()

    df = read_csv_rows(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SystemExit(f"{path} is missing column(s): {', '.join(missing)}")

    # A blank (or whitespace-only) Win means the game hasn't been graded yet. The raw
    # values stay in df so error messages quote what's actually in the file.
    result = df["Win"].str.strip().str.upper()
    df, result = df[result != ""].copy(), result[result != ""]

    pick = df["Pick"].str.strip()
    odds = pd.to_numeric(df["Odds"], errors="coerce")
    week = pd.to_numeric(df["Week"], errors="coerce")
    checks = [
        (pick == "", "Pick (picker name) is blank", "Pick"),
        (~result.isin(VALID_RESULTS), "Win must be Y, N or P", "Win"),
        (~odds.map(is_valid_american_odds), "Odds must be American odds (<= -100 or >= +100)", "Odds"),
        (~week.between(1, MAX_WEEK) | (week % 1 != 0), f"Week must be a whole number from 1 to {MAX_WEEK}", "Week"),
    ]
    problems = sorted(
        (line, f"{msg} (got {df.at[line, col]!r})") for mask, msg, col in checks for line in df.index[mask]
    )
    if problems:
        details = "\n".join(f"  line {line}: {msg}" for line, msg in problems)
        raise SystemExit(f"{path} has invalid resolved picks:\n{details}")

    df["Pick"] = pick
    df["Win"] = result
    df["Odds"] = odds
    df["Week"] = week.astype(int)
    if df.empty:
        df["Date"] = pd.Series(dtype="object")
        return df

    if not week1_date:
        raise SystemExit(
            f"{path} has resolved picks but no week1_date is set in {season_dir / 'season.json'} -- fill it in."
        )
    df["Date"] = df["Week"].apply(lambda w: week_date(week1_date, w))
    return df


def sport_cuts(picks: pd.DataFrame) -> list[Cut]:
    """One cut per distinct date this sport has a game on."""
    return [(d, picks[picks["Date"] <= d]) for d in sorted(set(picks["Date"]))]


def combined_cuts(
    nfl_picks: pd.DataFrame,
    cfb_picks: pd.DataFrame,
    nfl_week1_date: str | None,
    cfb_week1_date: str | None,
    cfb_week_offset: int,
) -> list[Cut]:
    """One cut per NFL week, paired with the CFB week cfb_week_offset weeks ahead."""
    aligned_nfl_weeks = sorted(set(nfl_picks["Week"]) | {w - cfb_week_offset for w in cfb_picks["Week"]})

    cuts = []
    for nfl_w in aligned_nfl_weeks:
        cfb_w = nfl_w + cfb_week_offset
        nfl_subset = nfl_picks[nfl_picks["Week"] <= nfl_w]
        cfb_subset = cfb_picks[cfb_picks["Week"] <= cfb_w]

        # Only count a sport's week toward the checkpoint date if it actually has
        # picks by then -- otherwise a not-yet-started sport (e.g. NFL before its
        # season opens) would push the date later for no real reason.
        candidate_dates = []
        if len(nfl_subset):
            candidate_dates.append(week_date(nfl_week1_date, nfl_w))
        if len(cfb_subset):
            candidate_dates.append(week_date(cfb_week1_date, cfb_w))

        cuts.append((max(candidate_dates), concat([nfl_subset, cfb_subset])))
    return cuts


def load_season(season_dir: Path) -> dict:
    config = load_season_config(season_dir)
    nfl_week1_date = config.get("nfl", {}).get("week1_date")
    cfb_week1_date = config.get("cfb", {}).get("week1_date")
    cfb_week_offset = config.get("cfb_week_offset", 0)

    nfl_picks = load_dated_picks(season_dir, "parlay_tracker_nfl.csv", nfl_week1_date)
    cfb_picks = load_dated_picks(season_dir, "parlay_tracker_cfb.csv", cfb_week1_date)

    return {
        "pickers": sorted(set(nfl_picks["Pick"]) | set(cfb_picks["Pick"])),
        "picks": {"combined": concat([nfl_picks, cfb_picks]), "nfl": nfl_picks, "cfb": cfb_picks},
        "cuts": {
            "combined": combined_cuts(nfl_picks, cfb_picks, nfl_week1_date, cfb_week1_date, cfb_week_offset),
            "nfl": sport_cuts(nfl_picks),
            "cfb": sport_cuts(cfb_picks),
        },
    }


def discover_seasons(data_dir: Path) -> list[str]:
    # Only 4-digit year folders are seasons, so a stray folder (e.g. data/backup/) is
    # ignored rather than aborting the run for lacking a season.json.
    return sorted(p.name for p in data_dir.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}", p.name))


def pick_infos(picks: pd.DataFrame) -> dict[str, PickInfo]:
    return {info.name: info for info in build_pick_infos(sorted(set(picks["Pick"])), picks)}


def merge_pick_infos(a: dict[str, PickInfo], b: dict[str, PickInfo]) -> dict[str, PickInfo]:
    """Each picker's combined record and odds across both sets of picks."""
    merged = dict(a)
    for name, info in b.items():
        if name in merged:
            prev = merged[name]
            info = PickInfo(
                name,
                prev.num_wins + info.num_wins,
                prev.num_losses + info.num_losses,
                prev.num_pushes + info.num_pushes,
                prev.odds + info.odds,
            )
        merged[name] = info
    return merged


def standings(infos: dict[str, PickInfo]) -> list[dict]:
    return compute_standings([infos[name] for name in sorted(infos)])


def checkpoint(cutoff: date, rows: list[dict]) -> dict:
    return {"date": cutoff.strftime("%Y-%m-%d"), "label": cutoff.strftime("%b %-d, %Y"), "standings": rows}


def build_data(data_dir: Path) -> dict:
    seasons = {s: load_season(data_dir / s) for s in discover_seasons(data_dir)}

    seasons_data = {}
    all_time_weeks = {sport: [] for sport in SPORTS}
    last_cutoff: dict[str, date] = {}
    prior_infos = {sport: {} for sport in SPORTS}  # every earlier season's records, per picker
    for s, season in seasons.items():  # oldest first
        weeks = {}
        for sport in SPORTS:
            weeks[sport] = []
            for cutoff, picks in season["cuts"][sport]:
                infos = pick_infos(picks)
                rows = standings(infos)
                weeks[sport].append(checkpoint(cutoff, rows))

                # All-time reuses this season's own cuts (so Combined keeps its NFL/CFB week
                # pairing) but stacks every earlier season's picks underneath -- e.g. 2026
                # Week 1 already includes all of 2025. With no earlier seasons that's just
                # this season's standings again.
                prev = last_cutoff.get(sport)
                if prev and cutoff <= prev:
                    raise SystemExit(
                        f"All-time {sport} checkpoints go back in time: {s} has one on {cutoff} but an "
                        f"earlier one is already on {prev}. Check the week1_date values in "
                        f"{data_dir / s / 'season.json'} and the previous season's."
                    )
                last_cutoff[sport] = cutoff
                all_time_rows = standings(merge_pick_infos(prior_infos[sport], infos)) if prior_infos[sport] else rows
                all_time_weeks[sport].append(checkpoint(cutoff, all_time_rows))
            prior_infos[sport] = merge_pick_infos(prior_infos[sport], pick_infos(season["picks"][sport]))
        seasons_data[s] = {"pickers": season["pickers"], "weeks": weeks}

    return {
        "seasons": seasons_data,
        "all_time": {
            "pickers": sorted(set().union(*(season["pickers"] for season in seasons.values()))),
            "weeks": all_time_weeks,
        },
    }


def main():
    # No options -- this just gives `--help` the docstring above.
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()

    data = build_data(DATA_DIR)
    OUTPUT_PATH.write_text(json.dumps(data, indent=2) + "\n")

    for s, season in data["seasons"].items():
        print(f"{s}: { {sport: len(season['weeks'][sport]) for sport in SPORTS} }")
    print(f"all_time: { {sport: len(data['all_time']['weeks'][sport]) for sport in SPORTS} }")
    print(f"Rebuilt {OUTPUT_PATH} from scratch across seasons: {list(data['seasons'])}")


if __name__ == "__main__":
    main()
