import itertools
import math
from fractions import Fraction

import pandas as pd
import pytest

from degen_sim.simulate import (
    PickInfo,
    build_pick_infos,
    compute_standings,
    implied_probability,
    p_value,
    win_distribution,
)


def brute_force_distribution(probs: list[Fraction]) -> list[Fraction]:
    """P(W = k) by enumerating every one of the 2^n win/loss outcomes."""
    pmf = [Fraction(0)] * (len(probs) + 1)
    for outcome in itertools.product([0, 1], repeat=len(probs)):
        pmf[sum(outcome)] += math.prod(p if won else 1 - p for p, won in zip(probs, outcome))
    return pmf


@pytest.mark.parametrize(
    ("odds", "expected"),
    [
        (-110, Fraction(110, 210)),
        (150, Fraction(2, 5)),
        (100, Fraction(1, 2)),
        (-100, Fraction(1, 2)),
        (-400, Fraction(4, 5)),
        (-112.5, Fraction(9, 17)),  # decimal odds stay exact too
    ],
)
def test_implied_probability_is_exact(odds, expected):
    assert implied_probability(odds) == expected


@pytest.mark.parametrize("odds", [0, 50, -99, 99.5, math.nan, math.inf, -math.inf])
def test_implied_probability_rejects_invalid_odds(odds):
    with pytest.raises(ValueError, match="Invalid American odds"):
        implied_probability(odds)


def test_build_pick_infos_counts_pushes_as_non_wins():
    picks = pd.DataFrame(
        {
            "Pick": ["Bob", "Ann", "Ann", "Ann"],
            "Odds": [100, -110, 150, -200],
            "Win": ["Y", "Y", "N", "P"],
        }
    )
    ann, bob = build_pick_infos(picks)

    assert (ann.name, bob.name) == ("Ann", "Bob")
    assert (ann.num_wins, ann.num_losses, ann.num_pushes) == (1, 1, 1)
    # Every pick is in the distribution -- the push included -- even though only wins count.
    assert ann.odds == [Fraction(110, 210), Fraction(2, 5), Fraction(200, 300)]
    assert (bob.num_wins, bob.odds) == (1, [Fraction(1, 2)])


PROBS = [implied_probability(o) for o in (-110, -110, 150, -200, 120, -150, 105, -300)]


def test_win_distribution_matches_brute_force_enumeration():
    assert win_distribution(PROBS) == brute_force_distribution(PROBS)


def test_win_distribution_ignores_pick_order():
    assert win_distribution(PROBS) == win_distribution(PROBS[::-1])


def test_win_distribution_of_no_picks_is_certain_zero_wins():
    assert win_distribution([]) == [1]


def info_with(wins: int, probs: list[Fraction] = PROBS, name: str = "Ann") -> PickInfo:
    return PickInfo(name, num_wins=wins, num_losses=len(probs) - wins, num_pushes=0, odds=probs)


@pytest.mark.parametrize("wins", range(len(PROBS) + 1))
def test_p_value_is_mid_p(wins):
    pmf = brute_force_distribution(PROBS)
    assert p_value(info_with(wins)) == sum(pmf[wins + 1 :]) + pmf[wins] / 2


def test_p_value_averages_one_half_under_no_skill():
    # The point of mid-p: weighting each possible record by how likely it is under
    # the implied odds, the p-value averages exactly 1/2 (plain P(W >= w) would not).
    pmf = win_distribution(PROBS)
    assert sum(pmf[w] * p_value(info_with(w)) for w in range(len(PROBS) + 1)) == Fraction(1, 2)


EVEN = Fraction(1, 2)


def test_p_value_of_fair_coin_flips():
    # 3 wins from 3 fair coin flips: P(W > 3) + P(W = 3) / 2 = 0 + (1/8) / 2.
    assert p_value(info_with(3, [EVEN] * 3)) == Fraction(1, 16)
    # 1 win from 2 fair coin flips is exactly average: P(W > 1) + P(W = 1) / 2 = 1/4 + 1/4.
    assert p_value(info_with(1, [EVEN] * 2)) == Fraction(1, 2)


def test_winless_p_value_depends_on_the_odds():
    # 0-for-1: 1 - P(lose) / 2. Missing a big favorite reads colder than missing a longshot.
    assert p_value(info_with(0, [implied_probability(-500)])) == 1 - Fraction(1, 6) / 2
    assert p_value(info_with(0, [implied_probability(300)])) == 1 - Fraction(3, 4) / 2


def test_compute_standings_skips_empty_pickers_and_sorts_best_first():
    infos = [
        PickInfo("Cold", num_wins=0, num_losses=3, num_pushes=0, odds=[EVEN] * 3),
        PickInfo("Nobody", num_wins=0, num_losses=0, num_pushes=0, odds=[]),
        PickInfo("Hot", num_wins=3, num_losses=0, num_pushes=0, odds=[EVEN] * 3),
    ]
    rows = compute_standings(infos)

    assert rows == [
        {"name": "Hot", "wins": 3, "losses": 0, "pushes": 0, "p_value": 0.0625, "rank": 1},
        {"name": "Cold", "wins": 0, "losses": 3, "pushes": 0, "p_value": 0.9375, "rank": 2},
    ]


def ranks(infos: list[PickInfo]) -> dict[str, int]:
    return {r["name"]: r["rank"] for r in compute_standings(infos)}


def test_compute_standings_ties_identical_records_whatever_the_pick_order():
    # e.g. several pickers going 1-0 at -105 in Week 1, or the same odds entered in a different order.
    infos = [
        info_with(3, PROBS, "Cat"),
        info_with(3, PROBS[::-1], "Ann"),
        info_with(3, PROBS[2:] + PROBS[:2], "Bob"),
        info_with(1, [implied_probability(-105)], "Dan"),
        info_with(1, [implied_probability(-105)], "Eve"),
    ]
    rows = compute_standings(infos)
    # Competition ranking (1, 1, 3, 3, 3), ties listed by name.
    assert [(r["name"], r["rank"]) for r in rows] == [("Dan", 1), ("Eve", 1), ("Ann", 3), ("Bob", 3), ("Cat", 3)]
    assert rows[2]["p_value"] == rows[3]["p_value"] == rows[4]["p_value"]


def test_compute_standings_ties_different_records_with_equal_p_values():
    # 1-1 and 2-2 on coin flips are both exactly average (p = 1/2), so they tie.
    assert ranks([info_with(1, [EVEN] * 2, "Ann"), info_with(2, [EVEN] * 4, "Bob")]) == {"Ann": 1, "Bob": 1}


def test_compute_standings_never_ties_different_records_that_round_together():
    # Both winless over 60 picks at slightly different odds: each p-value is 1 - 1/2 * P(W = 0),
    # within ~1e-17 of 1, so both are exactly 1.0 as floats -- but they're different records
    # and must not tie. Missing -115s (more likely to win) is the colder record.
    shorter = info_with(0, [implied_probability(-110)] * 60, "Ann")
    longer = info_with(0, [implied_probability(-115)] * 60, "Bob")
    rows = compute_standings([longer, shorter])
    assert [r["p_value"] for r in rows] == [1.0, 1.0]
    assert [(r["name"], r["rank"]) for r in rows] == [("Ann", 1), ("Bob", 2)]
