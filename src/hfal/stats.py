"""Small statistics helpers shared by score.py and sizecheck.py."""

import random


def cluster_ci(pairs: list[tuple[int, int]], resamples: int = 2000, seed: int = 20261110) -> tuple[float, float] | None:
    """95% interval for an error rate, from whole hospitals. pairs = [(errors, judgments)] one per hospital.

    A hospital's 18 judgments share its documents, so they are not independent; an interval that treats every
    judgment as independent would be too narrow. This resamples hospitals (with replacement, fixed seed, so the
    same run always gives the same interval) and reads off the 2.5th and 97.5th percentile. With fewer than 2
    hospitals there is nothing to resample: None."""
    pairs = [p for p in pairs if p[1]]
    if len(pairs) < 2:
        return None
    rng = random.Random(seed)
    rates = []
    for _ in range(resamples):
        pick = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        rates.append(sum(e for e, _ in pick) / sum(n for _, n in pick))
    rates.sort()
    return rates[int(0.025 * resamples)], rates[int(0.975 * resamples) - 1]
