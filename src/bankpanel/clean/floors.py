"""Valued-balance floors.

A rate is only meaningful where there is a balance to earn it on, and large enough to
support one. Below that size the flow-over-balance quotient is noise, but the bank still
belongs in the panel -- so it takes the cross-section rather than being dropped.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def apply_valued_balance_floor(
    df: pd.DataFrame,
    *,
    rate_col: str,
    balance_col: str,
    date_col: str = "REPORTING_PERIOD",
    min_balance: float = 1000.0,
) -> pd.DataFrame:
    """Floor a rate by the size of the balance it is earned on, in place.

    ``balance <= 0`` becomes NaN -- nothing to value. ``0 < balance < min_balance`` takes
    the per-date median: the position is immaterial but real, and its own quotient is
    noise. Anything larger keeps its own rate untouched.

    Apply AFTER any repair, so that a real balance keeps its repaired own rate and only
    the tiny tail is overridden.
    """
    balance = df[balance_col]
    rate = df[rate_col]
    median = rate.groupby(df[date_col]).transform("median")
    df[rate_col] = np.where(balance <= 0, np.nan, np.where(balance < min_balance, median, rate))
    return df
