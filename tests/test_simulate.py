import itertools
import math

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


def brute_force_distribution(probs: list[float]) -> list[float]:
    """P(W = k) by enumerating every one of the 2^n win/loss outcomes."""
    pmf = [0.0] * (len(probs) + 1)
    for outcome in itertools.product([0, 1], repeat=len(probs)):
        pmf[sum(outcome)] += math.prod(p if won else 1 - p for p, won in zip(probs, outcome))
    return pmf


@pytest.mark.parametrize(
    ("odds", "expected"),
    [(-110, 110 / 210), (150, 0.4), (100, 0.5), (-100, 0.5), (-400, 0.8)],
)
def test_implied_probability(odds, expected):
    assert implied_probability(odds) == pytest.approx(expected)


@pytest.mark.parametrize("odds", [0, 50, -99, 99.5, math.nan, math.inf, -math.inf])
def test_implied_probability_rejects_invalid_odds(odds):
    with pytest.raises(ValueError, match="Invalid American odds"):
        implied_probability(odds)


def test_build_pick_infos_counts_pushes_as_non_wins():
    picks = pd.DataFrame(
        {
            "Pick": ["Ann", "Ann", "Ann", "Bob"],
            "Odds": [-110, 150, -200, 100],
            "Win": ["Y", "N", "P", "Y"],
        }
    )
    ann, bob, cat = build_pick_infos(["Ann", "Bob", "Cat"], picks)

    assert (ann.num_wins, ann.num_losses, ann.num_pushes) == (1, 1, 1)
    # Every pick is in the distribution -- the push included -- even though only wins count.
    assert ann.odds == pytest.approx([110 / 210, 0.4, 200 / 300])
    assert (bob.num_wins, bob.odds) == (1, [0.5])
    assert (cat.num_wins, cat.odds) == (0, [])


PROBS = [implied_probability(o) for o in (-110, -110, 150, -200, 120, -150, 105, -300)]


def test_win_distribution_matches_brute_force_enumeration():
    assert win_distribution(PROBS).tolist() == pytest.approx(brute_force_distribution(PROBS), abs=1e-12)


def test_win_distribution_ignores_pick_order():
    # Bit-identical, not just approximately equal: the site detects ties by exact equality.
    assert win_distribution(PROBS).tolist() == win_distribution(PROBS[::-1]).tolist()


def test_win_distribution_of_no_picks_is_certain_zero_wins():
    assert win_distribution([]).tolist() == [1.0]


def info_with(wins: int, probs: list[float] = PROBS) -> PickInfo:
    return PickInfo("Ann", num_wins=wins, num_losses=len(probs) - wins, num_pushes=0, odds=probs)


@pytest.mark.parametrize("wins", range(len(PROBS) + 1))
def test_p_value_is_mid_p(wins):
    pmf = brute_force_distribution(PROBS)
    assert p_value(info_with(wins)) == pytest.approx(sum(pmf[wins + 1 :]) + pmf[wins] / 2, abs=1e-12)


def test_p_value_averages_one_half_under_no_skill():
    # The point of mid-p: weighting each possible record by how likely it is under
    # the implied odds, the p-value averages exactly 1/2 (plain P(W >= w) would not).
    pmf = win_distribution(PROBS)
    assert sum(pmf[w] * p_value(info_with(w)) for w in range(len(PROBS) + 1)) == pytest.approx(0.5, abs=1e-12)


def test_p_value_of_fair_coin_flips():
    # 3 wins from 3 fair coin flips: P(W > 3) + P(W = 3) / 2 = 0 + (1/8) / 2.
    assert p_value(info_with(3, [0.5] * 3)) == pytest.approx(1 / 16)
    # 1 win from 2 fair coin flips is exactly average: P(W > 1) + P(W = 1) / 2 = 1/4 + 1/4.
    assert p_value(info_with(1, [0.5] * 2)) == pytest.approx(0.5)


def test_winless_p_value_depends_on_the_odds():
    # 0-for-1: 1 - P(lose) / 2. Missing a big favorite reads colder than missing a longshot.
    assert p_value(info_with(0, [implied_probability(-500)])) == pytest.approx(1 - (1 / 6) / 2)
    assert p_value(info_with(0, [implied_probability(300)])) == pytest.approx(1 - 0.75 / 2)


def test_compute_standings_skips_empty_pickers_and_sorts_best_first():
    infos = [
        PickInfo("Cold", num_wins=0, num_losses=3, num_pushes=0, odds=[0.5] * 3),
        PickInfo("Nobody", num_wins=0, num_losses=0, num_pushes=0, odds=[]),
        PickInfo("Hot", num_wins=3, num_losses=0, num_pushes=0, odds=[0.5] * 3),
    ]
    rows = compute_standings(infos)

    assert [r["name"] for r in rows] == ["Hot", "Cold"]
    assert rows[0] == {"name": "Hot", "wins": 3, "losses": 0, "pushes": 0, "p_value": 0.0625}
    assert rows[1]["p_value"] == 0.9375
