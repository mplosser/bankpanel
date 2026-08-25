"""Shared primitives for the cleaning functions."""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Ratio band that identifies a unit switch between consecutive values. Wide enough to
#: tolerate genuine growth on top of the switch, narrow enough that no plausible
#: quarter-over-quarter move in a balance-sheet series lands inside it.
JUMP_RATIO_LOW = 500
JUMP_RATIO_HIGH = 2000


def detect_jumps(values: np.ndarray, low: float, high: float) -> tuple[np.ndarray, list[int]]:
    """Positions of consecutive-pair jumps whose ratio falls in ``[low, high]``.

    Considers only positive, non-null values: a zero or a NaN carries no information
    about units, and dividing by one would manufacture a jump.
    """
    positive = np.where(~np.isnan(values) & (values > 0))[0]
    if len(positive) < 2:
        return positive, []
    jumps = []
    for i in range(1, len(positive)):
        ratio = values[positive[i]] / values[positive[i - 1]]
        if low <= ratio <= high or 1 / high <= ratio <= 1 / low:
            jumps.append(i)
    return positive, jumps


def segment_medians(positive: np.ndarray, jumps: list[int], values: np.ndarray) -> list[dict]:
    """Split the positive positions into segments at each jump, with each median."""
    boundaries = [0, *jumps, len(positive)]
    out = []
    for i in range(len(boundaries) - 1):
        positions = positive[boundaries[i]:boundaries[i + 1]]
        out.append({"positions": positions, "median": float(np.median(values[positions]))})
    return out


def classify_segments(segments: list[dict], low: float, high: float):
    """Split segments into a low and a high cluster, if the series really has two levels.

    The dividing line is the geometric mean of the smallest and largest segment medians,
    which is scale-free. A clean split needs at least one segment on each side AND the
    two cluster medians to differ by a factor inside the band -- otherwise the jumps were
    real movement rather than a change of units.
    """
    medians = np.array([s["median"] for s in segments])
    if len(medians) < 2:
        return None
    divide = np.sqrt(medians.min() * medians.max())
    low_idx = [i for i, m in enumerate(medians) if m <= divide]
    high_idx = [i for i, m in enumerate(medians) if m > divide]
    if not low_idx or not high_idx:
        return None
    low_median = float(np.median(medians[low_idx]))
    high_median = float(np.median(medians[high_idx]))
    if not (low <= high_median / low_median <= high):
        return None
    return low_idx, high_idx, low_median, high_median


def interpolate_within_entity(series: pd.Series, entities: pd.Series) -> pd.Series:
    """Linear interpolation inside each entity's own history, then edge-fill.

    Own history rather than a peer median, deliberately: a bank with a real balance and a
    broken numerator still has a well-defined own level, and its neighbours in time are a
    far better estimate of it than the cross-section.
    """
    filled = series.groupby(entities).transform(
        lambda s: s.interpolate(method="linear", limit_area="inside")
    )
    return filled.groupby(entities).transform(lambda s: s.ffill().bfill())
