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

Everything is computed in exact rational arithmetic (fractions.Fraction), not floats.
That's what makes ties reliable: two pickers are tied exactly when their p-values are
mathematically equal, and are otherwise ranked by their exact values -- no float
rounding can merge two different records or split two equal ones. compute_standings
assigns the ranks here, so the website only displays them and never compares floats.
"""

import math
from dataclasses import dataclass
from fractions import Fraction

import pandas as pd


@dataclass
class PickInfo:
    name: str
    num_wins: int
    num_losses: int
    num_pushes: int
    odds: list[Fraction]  # implied win probability of each pick


def is_valid_american_odds(odds: float) -> bool:
    # American odds are always <= -100 or >= +100; anything in between (or NaN/inf)
    # is a data-entry mistake that would otherwise yield a plausible-looking probability.
    return math.isfinite(odds) and abs(odds) >= 100


def implied_probability(odds: float) -> Fraction:
    """Exact implied win probability, e.g. -110 -> 110/210."""
    if not is_valid_american_odds(odds):
        raise ValueError(f"Invalid American odds {odds!r}: must be <= -100 or >= +100")
    odds = Fraction(odds)
    if odds > 0:
        return 100 / (odds + 100)
    return -odds / (-odds + 100)


def build_pick_infos(picks: pd.DataFrame) -> list[PickInfo]:
    """Each picker's record and per-pick implied win probabilities, sorted by name.

    One pass over the rows rather than filtering the frame once per picker, which
    dominated the runtime once all-time checkpoints stack several seasons of picks.
    """
    infos: dict[str, PickInfo] = {}
    for name, odds, result in zip(picks["Pick"], picks["Odds"], picks["Win"]):
        info = infos.setdefault(name, PickInfo(name, 0, 0, 0, []))
        info.odds.append(implied_probability(odds))
        if result == "Y":
            info.num_wins += 1
        elif result == "N":
            info.num_losses += 1
        elif result == "P":
            info.num_pushes += 1
    return [infos[name] for name in sorted(infos)]


def win_weights(probs: list[Fraction]) -> tuple[list[int], int]:
    """Exact P(W = k) for k = 0..len(probs) as integer numerators over one shared denominator.

    Adds one pick at a time: with p = a/b, each existing count either stays put on a
    loss (weight b - a) or moves up one on a win (weight a), and the denominator picks
    up a factor of b. Plain integers rather than a list of Fractions, which would
    reduce every entry by a gcd at every step and run ~25x slower. O(n^2).
    """
    weights, denominator = [1], 1
    for p in probs:
        a, b = p.numerator, p.denominator
        weights = [stay * (b - a) + up * a for stay, up in zip(weights + [0], [0] + weights)]
        denominator *= b
    return weights, denominator


def win_distribution(probs: list[Fraction]) -> list[Fraction]:
    """Exact P(W = k) for k = 0..len(probs), W = total wins across independent picks."""
    weights, denominator = win_weights(probs)
    return [Fraction(w, denominator) for w in weights]


def p_value(pick_info: PickInfo) -> Fraction:
    """Exact mid-p value P(W > num_wins) + 1/2 * P(W = num_wins) under the picks' implied probabilities."""
    weights, denominator = win_weights(pick_info.odds)
    w = pick_info.num_wins
    return Fraction(2 * sum(weights[w + 1 :]) + weights[w], 2 * denominator)


def compute_standings(pick_infos: list[PickInfo]) -> list[dict]:
    """One row per picker with picks, best (lowest p-value) first, each with a "competition"
    rank (1, 2, 2, 4) shared by pickers whose exact p-values are equal.

    Ties are decided here on the exact values, never on the floats written out for
    display: equal records always tie, and different records never do, however close.
    """
    scored = sorted(
        ((p_value(info), info) for info in pick_infos if info.odds),
        key=lambda scored_info: (scored_info[0], scored_info[1].name),
    )
    rows = []
    for i, (p, info) in enumerate(scored):
        tied_with_previous = i > 0 and p == scored[i - 1][0]
        rows.append(
            {
                "name": info.name,
                "wins": info.num_wins,
                "losses": info.num_losses,
                "pushes": info.num_pushes,
                "p_value": float(p),
                "rank": rows[-1]["rank"] if tied_with_previous else i + 1,
            }
        )
    return rows
