import json
from datetime import date
from pathlib import Path

import pytest

import generate_data

TRIALS = 2_000
CONFIG = {"nfl": {"week1_date": "2025-09-07"}, "cfb": {"week1_date": "2025-08-30"}, "cfb_week_offset": 1}
HEADER = "Week,Pick,Bet,Odds,Win\n"


def write_season(data_dir: Path, year: str, nfl: str = "", cfb: str = "", config: dict = CONFIG) -> Path:
    season_dir = data_dir / year
    season_dir.mkdir(parents=True)
    (season_dir / "season.json").write_text(json.dumps(config))
    (season_dir / "parlay_tracker_nfl.csv").write_text(HEADER + nfl)
    (season_dir / "parlay_tracker_cfb.csv").write_text(HEADER + cfb)
    return season_dir


def load_nfl(season_dir: Path):
    return generate_data.load_dated_picks(season_dir, "parlay_tracker_nfl.csv", "2025-09-07")


def test_load_dated_picks_normalizes_and_dates_resolved_rows(tmp_path):
    season_dir = write_season(
        tmp_path,
        "2025",
        nfl=(
            "1, Ann ,Lions -3,-110, y \n"  # stray whitespace / lowercase is tolerated
            "2,Bob,Jets +3,120,N\n"
            "2,Ann,Bills -7,-150,\n"  # blank Win = not graded yet
            "2,Bob,Colts +1,-105,   \n"  # whitespace-only Win = not graded yet
        ),
    )
    df = load_nfl(season_dir)

    assert df[["Week", "Pick", "Odds", "Win"]].values.tolist() == [[1, "Ann", -110, "Y"], [2, "Bob", 120, "N"]]
    assert df["Date"].tolist() == [date(2025, 9, 7), date(2025, 9, 14)]


def test_load_dated_picks_reports_every_bad_row_with_its_line(tmp_path):
    season_dir = write_season(
        tmp_path,
        "2025",
        nfl=(
            "1,Ann,Lions -3,-110,Y\n"  # line 2: fine
            "1,Bob,Jets +3,120,W\n"  # line 3: bad Win
            "\n"  # line 4: blank line, must not shift the numbering
            "1,Cat,Bills -7,50,N\n"  # line 5: bad Odds
            "x,Dan,Colts +1,-105,P\n"  # line 6: bad Week
            "1,,Colts +1,-105,P\n"  # line 7: blank Pick
            "1,Eve,Colts +1,,Y\n"  # line 8: missing Odds
            "1,Fay,Colts +1,50,\n"  # ungraded rows aren't validated
        ),
    )
    with pytest.raises(SystemExit) as exc:
        load_nfl(season_dir)

    message = str(exc.value)
    assert "line 2" not in message
    assert "line 3: Win must be Y, N or P (got 'W')" in message
    assert "line 5: Odds must be American odds" in message
    assert "line 6: Week must be a whole number" in message
    assert "line 7: Pick (picker name) is blank" in message
    assert "line 8: Odds must be American odds" in message
    assert "Fay" not in message


def test_load_dated_picks_requires_week1_date_once_picks_are_resolved(tmp_path):
    season_dir = write_season(tmp_path, "2025", nfl="1,Ann,Lions -3,-110,Y\n")
    with pytest.raises(SystemExit, match="no week1_date"):
        generate_data.load_dated_picks(season_dir, "parlay_tracker_nfl.csv", None)


def test_discover_seasons_ignores_non_year_folders(tmp_path):
    for name in ("2026", "backup", "2025", "20251"):
        (tmp_path / name).mkdir()
    (tmp_path / "2024").write_text("a file, not a folder")
    assert generate_data.discover_seasons(tmp_path) == ["2025", "2026"]


def test_combined_cuts_pair_nfl_week_with_cfb_week_ahead(tmp_path):
    season_dir = write_season(
        tmp_path,
        "2025",
        nfl="1,Ann,Lions -3,-110,Y\n2,Ann,Lions -3,-110,N\n",
        cfb="1,Bob,Bama -7,-110,Y\n2,Bob,Bama -7,-110,Y\n3,Bob,Bama -7,-110,N\n",
    )
    cuts = generate_data.load_season(season_dir)["cuts"]["combined"]

    # CFB week 1 has no NFL partner (NFL week 0), so it's dated by CFB alone rather
    # than being pushed out to a not-yet-started NFL week.
    assert [(d, sorted(zip(picks["Pick"], picks["Week"]))) for d, picks in cuts] == [
        (date(2025, 8, 30), [("Bob", 1)]),
        (date(2025, 9, 7), [("Ann", 1), ("Bob", 1), ("Bob", 2)]),
        (date(2025, 9, 14), [("Ann", 1), ("Ann", 2), ("Bob", 1), ("Bob", 2), ("Bob", 3)]),
    ]


def test_build_data_all_time_stacks_earlier_seasons(tmp_path):
    write_season(tmp_path, "2025", nfl="1,Ann,Lions -3,-110,Y\n2,Ann,Lions -3,-110,Y\n")
    write_season(
        tmp_path,
        "2026",
        nfl="1,Ann,Lions -3,-110,N\n1,Bob,Jets +3,120,Y\n",
        config={**CONFIG, "nfl": {"week1_date": "2026-09-13"}},
    )
    write_season(tmp_path, "2027", config={"nfl": {"week1_date": None}, "cfb": {"week1_date": None}})

    data = generate_data.build_data(tmp_path, TRIALS, seed=0)

    # Every season gets an entry, even one with no picks yet.
    assert data["seasons"]["2027"] == {"pickers": [], "weeks": {"combined": [], "nfl": [], "cfb": []}}
    assert data["all_time"]["pickers"] == ["Ann", "Bob"]

    season_nfl = data["seasons"]["2026"]["weeks"]["nfl"]
    all_time_nfl = data["all_time"]["weeks"]["nfl"]
    assert [w["date"] for w in all_time_nfl] == ["2025-09-07", "2025-09-14", "2026-09-13"]
    # The first season's all-time checkpoints are just its own.
    assert all_time_nfl[:2] == data["seasons"]["2025"]["weeks"]["nfl"]

    def records(week):
        return {r["name"]: (r["wins"], r["losses"]) for r in week["standings"]}

    assert records(season_nfl[0]) == {"Ann": (0, 1), "Bob": (1, 0)}
    # 2026 Week 1 all-time already includes Ann's 2-0 from 2025.
    assert records(all_time_nfl[2]) == {"Ann": (2, 1), "Bob": (1, 0)}
