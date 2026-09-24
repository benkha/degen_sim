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

Weeks are numbered from 1 in both sports, and that's deliberate: there is no Week 0.
If CFB's schedule has an official "Week 0", log it as Week 1 and set cfb.week1_date
(and cfb_week_offset) to match -- a Week 0 row is rejected like any other bad row.

Resolved picks (a non-blank Win) are validated on load -- Win must be Y/N/P, Odds must be
valid American odds, Week a whole number from 1 to MAX_WEEK -- and any bad row aborts the
run with its file and line number, rather than silently skewing the results. So does a
file that isn't valid CSV (e.g. a quote that's never closed, which would otherwise swallow
the rows after it) or isn't UTF-8, and picker names that differ only in capitalization or
spacing (e.g. "Ben" and "ben"), which would otherwise split one person into two. season.json
is validated too (dates as YYYY-MM-DD, cfb_week_offset a whole number that pairs NFL week 1
with the CFB week in the same calendar week, no unknown keys, so a misspelled key can't
silently fall back to a default). Seasons must also run in order:
a week1_date that makes one season's checkpoints overlap an earlier season's aborts the
run too, since the All-Time timeline would otherwise go back in time.

This always rebuilds data.json from scratch by reading every data/<year>/ directory --
there is no incremental/upsert mode. Run it any time after updating a season's CSVs:

    uv run python scripts/generate_data.py
"""

import argparse
import csv
import io
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from degen_sim.simulate import build_pick_infos, compute_standings, is_valid_american_odds

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_PATH = ROOT_DIR / "data.json"

SPORTS = ("combined", "nfl", "cfb")
REQUIRED_COLUMNS = ["Week", "Pick", "Odds", "Win"]
VALID_RESULTS = {"Y", "N", "P"}
# Both sports number their weeks from 1 -- Week 0 is rejected on purpose (see the module
# docstring). No season runs past ~22 weeks (NFL's 18 plus playoffs), so anything beyond
# this is a typo -- caught here rather than becoming a checkpoint months in the future (or
# overflowing the date math entirely).
MAX_WEEK = 25

# A checkpoint's cutoff date plus every pick that counts toward it.
Cut = tuple[date, pd.DataFrame]


def empty_picks() -> pd.DataFrame:
    return pd.DataFrame(columns=["Week", "Pick", "Odds", "Win", "Date"])


CONFIG_EXAMPLE = '{"nfl": {"week1_date": "YYYY-MM-DD"}, "cfb": {"week1_date": "YYYY-MM-DD"}, "cfb_week_offset": 1}'


@dataclass
class SeasonConfig:
    nfl_week1_date: date | None  # None = not known yet (fine until that sport has resolved picks)
    cfb_week1_date: date | None
    cfb_week_offset: int


def parse_week1_date(config: dict, sport: str, problems: list[str]) -> date | None:
    section = config.get(sport, {})
    if not isinstance(section, dict):
        problems.append(f'"{sport}" must be an object like {{"week1_date": "YYYY-MM-DD"}} (got {section!r})')
        return None
    unknown = sorted(set(section) - {"week1_date"})
    if unknown:
        problems.append(f'"{sport}" has unknown key(s) {", ".join(map(repr, unknown))} (expected "week1_date")')
    raw = section.get("week1_date")
    if raw in (None, ""):
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        problems.append(f'"{sport}.week1_date" must be a YYYY-MM-DD date or null (got {raw!r})')
        return None


def load_season_config(season_dir: Path) -> SeasonConfig:
    config_path = season_dir / "season.json"
    if not config_path.exists():
        raise SystemExit(
            f"Missing {config_path}. Create it with each sport's Week 1 date and the "
            f"CFB/NFL week offset, e.g.:\n  {CONFIG_EXAMPLE}"
        )
    try:
        config = json.loads(config_path.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(f"{config_path} isn't valid JSON: {e}") from None
    if not isinstance(config, dict):
        raise SystemExit(f"{config_path} must be a JSON object, e.g.:\n  {CONFIG_EXAMPLE}")

    # A misspelled key (e.g. "cfbWeekOffset") would otherwise be ignored and the setting
    # would silently fall back to its default.
    problems = []
    unknown = sorted(set(config) - {"nfl", "cfb", "cfb_week_offset"})
    if unknown:
        problems.append(f'unknown key(s) {", ".join(map(repr, unknown))} (expected "nfl", "cfb", "cfb_week_offset")')
    nfl_week1_date = parse_week1_date(config, "nfl", problems)
    cfb_week1_date = parse_week1_date(config, "cfb", problems)
    cfb_week_offset = config.get("cfb_week_offset", 0)
    # bool is a subclass of int, but `true` is certainly a mistake here.
    if not isinstance(cfb_week_offset, int) or isinstance(cfb_week_offset, bool):
        problems.append(f'"cfb_week_offset" must be a whole number (got {cfb_week_offset!r})')
    elif nfl_week1_date and cfb_week1_date:
        # Combined pairs NFL week 1 with CFB week 1 + cfb_week_offset, so those should fall
        # in the same calendar week. A typo (e.g. 10 for 1) would otherwise silently pair
        # the wrong weeks and push Combined's checkpoint dates months ahead.
        paired_cfb_date = week_date(cfb_week1_date, 1 + cfb_week_offset)
        if abs((paired_cfb_date - nfl_week1_date).days) >= 7:
            problems.append(
                f'"cfb_week_offset" of {cfb_week_offset} pairs NFL week 1 ({nfl_week1_date}) with CFB week '
                f"{1 + cfb_week_offset} ({paired_cfb_date}), which isn't the same week -- check the offset and "
                f"both week1_dates"
            )
    if problems:
        raise SystemExit(f"{config_path} is invalid:\n" + "\n".join(f"  {p}" for p in problems))
    return SeasonConfig(nfl_week1_date, cfb_week1_date, cfb_week_offset)


def week_date(week1_date: date, week: int) -> date:
    return week1_date + timedelta(weeks=int(week) - 1)


def concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
    # Skipping empty frames avoids pandas' FutureWarning about concatenating them.
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else empty_picks()


def read_csv_rows(path: Path) -> pd.DataFrame:
    """Every non-blank record as strings, indexed by the file line it starts on.

    Parsed with the csv module rather than pd.read_csv so that (a) every value stays
    literal text -- pandas would turn a picker named "NA"/"None" or a Win of "N/A" into
    missing values -- and (b) error line numbers stay right even when a quoted field
    spans several lines. A record with extra non-blank fields is an error rather than
    pandas' behavior of silently shifting its columns.

    A quote that's never closed is an error too, not just a long field: csv would
    otherwise read the lines after it into that one field until some later quote
    happens to close it, silently dropping those picks -- and, if the record still
    ends up with every field, crediting the swallowed row's Odds/Win to this one.
    strict mode catches a quote left open to the end of the file (or closed mid-field
    by a later quote). Otherwise, a field spanning lines that contains a comma is
    flagged: swallowed text always has one (the rest of the row, or a whole later
    row), while a deliberate line break in a cell (e.g. "Lions<newline>-3") rarely does.

    The header is the first non-blank line; an empty (or all-blank) file gives a frame
    with no columns at all.
    """
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        line = raw[: e.start].count(b"\n") + 1
        raise SystemExit(
            f"{path} line {line}: isn't valid UTF-8 ({e.reason}) -- re-save/export the file as UTF-8 CSV."
        ) from None

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    header, rows, lines, problems = [], [], [], []
    start = 1  # the line the record being read starts on
    try:
        for record in reader:
            if any(v.strip() for v in record):
                # Spreadsheet exports often pad names (e.g. "Win "), which would otherwise
                # read as a missing Win column, or slip past the duplicate check below.
                header = [c.strip() for c in record]
                break
            start = reader.line_num + 1
        dupes = sorted({c for c in header if c and header.count(c) > 1})
        if dupes:
            raise SystemExit(f"{path} line {start}: duplicate column(s) in the header: {', '.join(dupes)}")
        start = reader.line_num + 1
        for record in reader:
            if any(v.strip() for v in record[len(header) :]):
                problems.append(f"  line {start}: has {len(record)} fields, expected {len(header)}")
            elif any("\n" in v and "," in v for v in record):
                problems.append(
                    f"  line {start}: a quoted field runs on to line {reader.line_num} and has a comma in it -- "
                    f"probably a missing closing quote (if the line break is meant to be there, remove the comma)"
                )
            if any(v.strip() for v in record):
                rows.append((record + [""] * len(header))[: len(header)])
                lines.append(start)
            start = reader.line_num + 1
    except csv.Error as e:
        raise SystemExit(
            f"{path}: the row starting on line {start} isn't valid CSV ({e} on line {reader.line_num}) -- "
            f"probably a missing closing quote"
        ) from None
    if problems:
        raise SystemExit(f"{path} has malformed rows:\n" + "\n".join(problems))
    return pd.DataFrame(rows, columns=header, index=lines, dtype="object")


def load_dated_picks(season_dir: Path, filename: str, week1_date: date | None) -> pd.DataFrame:
    path = season_dir / filename
    if not path.exists():
        return empty_picks()

    df = read_csv_rows(path)
    if df.columns.empty:  # an empty file, e.g. one just created for a new season
        return empty_picks()
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
    if df.empty:  # nothing graded yet
        return empty_picks()

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
    nfl_week1_date: date | None,
    cfb_week1_date: date | None,
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
    nfl_picks = load_dated_picks(season_dir, "parlay_tracker_nfl.csv", config.nfl_week1_date)
    cfb_picks = load_dated_picks(season_dir, "parlay_tracker_cfb.csv", config.cfb_week1_date)

    # Every timeline's last cut holds all of that sport's picks for the season (build_data
    # relies on this to stack earlier seasons under the All-Time checkpoints).
    return {
        "pickers": sorted(set(nfl_picks["Pick"]) | set(cfb_picks["Pick"])),
        # Where each name is first spelled that way (the index is the CSV line number).
        "name_sources": {
            f"{season_dir / filename} line {line}": name
            for filename, picks in (("parlay_tracker_nfl.csv", nfl_picks), ("parlay_tracker_cfb.csv", cfb_picks))
            for line, name in picks["Pick"].drop_duplicates().items()
        },
        "cuts": {
            "combined": combined_cuts(
                nfl_picks, cfb_picks, config.nfl_week1_date, config.cfb_week1_date, config.cfb_week_offset
            ),
            "nfl": sport_cuts(nfl_picks),
            "cfb": sport_cuts(cfb_picks),
        },
    }


def discover_seasons(data_dir: Path) -> list[str]:
    if not data_dir.is_dir():
        raise SystemExit(
            f"{data_dir} doesn't exist. It should hold one data/<year>/ folder per season (CSVs + "
            f"season.json) -- data/ is gitignored, so on a fresh clone it has to be restored separately."
        )
    # Only 4-digit year folders are seasons, so a stray folder (e.g. data/backup/) is
    # ignored rather than aborting the run for lacking a season.json.
    return sorted(p.name for p in data_dir.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}", p.name))


def check_name_spellings(name_sources: dict[str, str]) -> None:
    """Abort if any picker's name is spelled more than one way (differing only in
    capitalization or spacing), e.g. "Ben" in one row and "ben" in another -- that would
    otherwise quietly split one person's record across two pickers."""
    spellings: dict[str, dict[str, str]] = defaultdict(dict)
    for source, name in name_sources.items():
        spellings[" ".join(name.split()).casefold()].setdefault(name, source)
    clashes = [variants for variants in spellings.values() if len(variants) > 1]
    if clashes:
        details = "\n".join(
            "  " + "; ".join(f"{name!r} ({source})" for name, source in variants.items()) for variants in clashes
        )
        raise SystemExit(f"Picker names spelled more than one way -- make each person's name match exactly:\n{details}")


def standings(picks: pd.DataFrame) -> list[dict]:
    return compute_standings(build_pick_infos(picks))


def checkpoint(cutoff: date, rows: list[dict]) -> dict:
    return {"date": cutoff.strftime("%Y-%m-%d"), "label": cutoff.strftime("%b %-d, %Y"), "standings": rows}


def build_data(data_dir: Path) -> dict:
    seasons = {s: load_season(data_dir / s) for s in discover_seasons(data_dir)}
    check_name_spellings(
        {source: name for season in seasons.values() for source, name in season["name_sources"].items()}
    )

    seasons_data = {}
    all_time_weeks = {sport: [] for sport in SPORTS}
    last_cutoff: dict[str, date] = {}
    prior_picks = {sport: empty_picks() for sport in SPORTS}  # every earlier season's picks
    for s, season in seasons.items():  # oldest first
        weeks = {}
        for sport in SPORTS:
            weeks[sport] = []
            for cutoff, picks in season["cuts"][sport]:
                rows = standings(picks)
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
                all_time_rows = standings(concat([prior_picks[sport], picks])) if len(prior_picks[sport]) else rows
                all_time_weeks[sport].append(checkpoint(cutoff, all_time_rows))
            if season["cuts"][sport]:
                prior_picks[sport] = concat([prior_picks[sport], season["cuts"][sport][-1][1]])
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
