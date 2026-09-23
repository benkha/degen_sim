import math

import numpy as np
import pandas as pd
import pytest

from degen_sim.simulate import PickInfo, build_pick_infos, compute_standings, implied_probability, simulate_p_value


def exact_p_value(probs: list[float], wins: int) -> float:
    """P(W >= wins) for a sum of independent Bernoullis (Poisson-binomial), computed exactly."""
    pmf = np.array([1.0])
    for p in probs:
        pmf = np.convolve(pmf, [1 - p, p])
    return float(pmf[wins:].sum())


@pytest.mark.parametrize(
    ("odds", "expected"),
    [(-110, 110 / 210), (150, 0.4), (100, 0.5), (-100, 0.5), (-400, 0.8)],
)
def test_implied_probability(odds, expected):
    assert implied_probability(odds) == pytest.approx(expected)


@pytest.mark.parametrize("odds", [0, 50, -99, 99.5, math.nan])
def test_implied_probability_rejects_invalid_odds(odds):
    with pytest.raises(ValueError, match="Invalid American odds"):
        implied_probability(odds)


def test_build_pick_infos_counts_pushes_as_simulated_non_wins():
    picks = pd.DataFrame(
        {
            "Pick": ["Ann", "Ann", "Ann", "Bob"],
            "Odds": [-110, 150, -200, 100],
            "Win": ["Y", "N", "P", "Y"],
        }
    )
    ann, bob, cat = build_pick_infos(["Ann", "Bob", "Cat"], picks)

    assert (ann.num_wins, ann.num_losses, ann.num_pushes) == (1, 1, 1)
    # Every pick is simulated -- the push included -- even though only wins count.
    assert ann.odds == pytest.approx([110 / 210, 0.4, 200 / 300])
    assert (bob.num_wins, bob.odds) == (1, [0.5])
    assert (cat.num_wins, cat.odds) == (0, [])


def test_simulate_p_value_matches_exact_distribution():
    probs = [implied_probability(o) for o in (-110, -110, 150, -200, 120, -150, 105, -300)]
    info = PickInfo("Ann", num_wins=5, num_losses=3, num_pushes=0, odds=probs)
    assert simulate_p_value(info, num_trials=200_000) == pytest.approx(exact_p_value(probs, 5), abs=0.005)


def test_simulate_p_value_is_one_with_zero_wins():
    info = PickInfo("Ann", num_wins=0, num_losses=2, num_pushes=0, odds=[0.5, 0.8])
    assert simulate_p_value(info, num_trials=1_000) == 1.0


def test_compute_standings_skips_empty_pickers_and_sorts_best_first():
    infos = [
        PickInfo("Cold", num_wins=0, num_losses=3, num_pushes=0, odds=[0.5] * 3),
        PickInfo("Nobody", num_wins=0, num_losses=0, num_pushes=0, odds=[]),
        PickInfo("Hot", num_wins=3, num_losses=0, num_pushes=0, odds=[0.5] * 3),
    ]
    rows = compute_standings(infos, num_trials=10_000)

    assert [r["name"] for r in rows] == ["Hot", "Cold"]
    assert rows[0] == {"name": "Hot", "wins": 3, "losses": 0, "pushes": 0, "p_value": pytest.approx(0.125, abs=0.01)}
    assert rows[1]["p_value"] == 1.0
