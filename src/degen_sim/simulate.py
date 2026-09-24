"""Skill-vs-luck p-values for weekly picks.

For each picker, converts the American odds of every pick into an implied win
probability, then computes the exact distribution of possible win counts (a
Poisson-binomial: the sum of independent win/lose picks, each with its own
probability) and a mid-p value against their real win count w:
P(W > w) + 1/2 * P(W = w). A low p-value means the record would be rare by
chance alone (skill); a high p-value means the odds predicted a better record
than they actually posted.

Mid-p (counting an exact tie with w as half) rather than the plain P(W >= w) is
deliberate. W is a whole number, so P(W >= w) counts the chance of matching w
exactly as "at least as good", which biases it upward: a no-skill picker averages
1/2 + 1/2 * sum_k P(W = k)^2 (~0.59 at 10 picks), a record exactly at expectation
reads as cold, and every winless picker lands at exactly 1.0 whatever their odds.
Mid-p averages exactly 1/2 under no skill at any sample size, and its "cold"
counterpart P(W < w) + 1/2 * P(W = w) is exactly 1 - mid-p, so one scale reads
hot and cold symmetrically.

Pushes count toward the picks in the distribution (`odds` has one entry per pick,
wins + losses + pushes) but not toward the win target (`num_wins`) they're judged
against -- this models
each pick as a binary Win vs. Not-Win event, where Not-Win covers both a
loss and a push. That's intentional, not a bug: a push is itself a real
"not a win" observation, so dropping it from the distribution would discard
real information rather than fix anything.

Ties: compute_standings treats p-values within TIE_TOLERANCE of each other as tied and
assigns the ranks here, so the website only displays them and never compares floats.
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

# p-values closer than this are a tie. Float rounding in win_distribution leaves the same
# record (e.g. the same odds entered in a different order) ~1e-16 apart, and different
# records that are mathematically equal (1-1 and 2-2 on coin flips are both exactly 0.5)
# land within that too, so both tie. Genuinely different records are far further apart --
# except at the extremes: two records whose p-values are both within ~1e-12 of 0 or 1
# (e.g. two pickers winless over 40+ picks at different odds) tie too. A known, accepted
# limitation -- no realistic record gets there.
TIE_TOLERANCE = 1e-12


@dataclass
class PickInfo:
    name: str
    num_wins: int
    num_losses: int
    num_pushes: int
    odds: list[float]  # implied win probability of each pick


def is_valid_american_odds(odds: float) -> bool:
    # American odds are always <= -100 or >= +100; anything in between (or NaN/inf)
    # is a data-entry mistake that would otherwise yield a plausible-looking probability.
    return math.isfinite(odds) and abs(odds) >= 100


def implied_probability(odds: float) -> float:
    if not is_valid_american_odds(odds):
        raise ValueError(f"Invalid American odds {odds!r}: must be <= -100 or >= +100")
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def build_pick_infos(picks: pd.DataFrame) -> list[PickInfo]:
    """Each picker's record and per-pick implied win probabilities, sorted by name.

    One pass over the rows rather than filtering the frame once per picker, which
    dominated the runtime once all-time checkpoints stack several seasons of picks.
    """
    infos: dict[str, PickInfo] = {}
    for name, odds, result in zip(picks["Pick"], picks["Odds"], picks["Win"]):
        info = infos.setdefault(name, PickInfo(name, 0, 0, 0, []))
        # Anything else would still land in the distribution but count as a silent Not-Win.
        if result == "Y":
            info.num_wins += 1
        elif result == "N":
            info.num_losses += 1
        elif result == "P":
            info.num_pushes += 1
        else:
            raise ValueError(f"Invalid result {result!r} for {name!r}: must be 'Y', 'N' or 'P'")
        info.odds.append(implied_probability(odds))
    return [infos[name] for name in sorted(infos)]


def win_distribution(probs: list[float]) -> np.ndarray:
    """Exact P(W = k) for k = 0..len(probs), W = total wins across independent picks.

    Adds one pick at a time: convolving with [1 - p, p] turns the distribution over
    the first i picks into the one over the first i + 1 (each existing count either
    stays put on a loss or moves up one on a win). O(n^2), exact up to float rounding.
    """
    pmf = np.ones(1)
    for p in probs:
        pmf = np.convolve(pmf, [1 - p, p])
    return pmf


def p_value(pick_info: PickInfo) -> float:
    """Mid-p value P(W > num_wins) + 1/2 * P(W = num_wins) under the picks' implied probabilities."""
    pmf = win_distribution(pick_info.odds)
    w = pick_info.num_wins
    return float(pmf[w + 1 :].sum() + 0.5 * pmf[w])


def compute_standings(pick_infos: list[PickInfo]) -> list[dict]:
    """One row per picker with picks, best (lowest p-value) first, each with a "competition"
    rank (1, 2, 2, 4) shared by tied pickers.

    A row ties with the one above it when their p-values are within TIE_TOLERANCE, so a
    tie group is a run of neighbors each within tolerance of the next. Ties are listed by
    name: tied rows are sorted by name after grouping, not by their (noise-level) p-value
    differences.
    """
    scored = sorted(((p_value(info), info) for info in pick_infos if info.odds), key=lambda scored_info: scored_info[0])
    groups: list[list[tuple[float, PickInfo]]] = []
    for i, (p, info) in enumerate(scored):
        if i > 0 and p - scored[i - 1][0] < TIE_TOLERANCE:
            groups[-1].append((p, info))
        else:
            groups.append([(p, info)])

    rows = []
    for group in groups:
        rank = len(rows) + 1
        for p, info in sorted(group, key=lambda scored_info: scored_info[1].name):
            rows.append(
                {
                    "name": info.name,
                    "wins": info.num_wins,
                    "losses": info.num_losses,
                    "pushes": info.num_pushes,
                    "p_value": p,
                    "rank": rank,
                }
            )
    return rows
