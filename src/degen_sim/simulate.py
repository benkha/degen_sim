"""Monte Carlo skill-vs-luck simulation for weekly picks.

For each picker, converts the American odds of every pick into an implied win
probability, then simulates the distribution of possible win counts to compute
a p-value against their real win count: P(simulated wins >= real wins). A low
p-value means the record would be rare by chance alone (skill); a high
p-value means the odds predicted a better record than they actually posted.

Pushes count toward the number of picks simulated (`num_games`) but not
toward the win target (`num_wins`) they're judged against -- this models
each pick as a binary Win vs. Not-Win event, where Not-Win covers both a
loss and a push. That's intentional, not a bug: a push is itself a real
"not a win" observation, so dropping it from the simulation would discard
real information rather than fix anything.
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PickInfo:
    name: str
    num_wins: int
    num_losses: int
    num_pushes: int
    odds: list[float]


def implied_probability(odds: float) -> float:
    # American odds are always <= -100 or >= +100; anything in between (or NaN)
    # is a data-entry mistake that would otherwise yield a plausible-looking probability.
    if math.isnan(odds) or abs(odds) < 100:
        raise ValueError(f"Invalid American odds {odds!r}: must be <= -100 or >= +100")
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def build_pick_infos(pickers: list[str], picks: pd.DataFrame) -> list[PickInfo]:
    pick_infos = []
    for picker in pickers:
        sub_df = picks[picks["Pick"] == picker]
        odds = [implied_probability(o) for o in sub_df["Odds"]]
        num_wins = int((sub_df["Win"] == "Y").sum())
        num_losses = int((sub_df["Win"] == "N").sum())
        num_pushes = int((sub_df["Win"] == "P").sum())
        pick_infos.append(PickInfo(picker, num_wins, num_losses, num_pushes, odds))
    return pick_infos


def simulate_p_value(pick_info: PickInfo, num_trials: int = 1_000_000, seed: int = 0) -> float:
    odds = np.array(pick_info.odds)
    rng = np.random.default_rng(seed)
    draws = rng.random((num_trials, len(odds)))
    simulated_wins = (draws <= odds).sum(axis=1)
    return float((simulated_wins >= pick_info.num_wins).mean())


def compute_standings(pick_infos: list[PickInfo], num_trials: int = 1_000_000, seed: int = 0) -> list[dict]:
    rows = []
    for pick_info in pick_infos:
        if pick_info.num_wins + pick_info.num_losses + pick_info.num_pushes == 0:
            continue
        rows.append(
            {
                "name": pick_info.name,
                "wins": pick_info.num_wins,
                "losses": pick_info.num_losses,
                "pushes": pick_info.num_pushes,
                "p_value": round(simulate_p_value(pick_info, num_trials, seed), 6),
            }
        )
    rows.sort(key=lambda r: r["p_value"])
    return rows
