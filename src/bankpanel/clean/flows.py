"""Gross-additive flows that came out negative.

Interest income, interest expense, non-interest expense, fiduciary income and charge-offs
are all gross and additive: over a quarter they cannot be negative. When one is, the
year-to-date series was reset mid-year and the difference picked up the reset instead of a
flow.

Recoveries are deliberately NOT on that list. A recovery can be reversed, so a negative
quarterly recovery can be real, and repairing it would destroy genuine data. Only pass a
column declared ``sign=nonneg`` in the configs.

The gate is simply ``value < 0``. It is deliberately NOT conditioned on a structural-event
flag: the value is impossible whatever caused it, and most causes are not flagged.

For a rate or ratio surface prefer `clean.rates.repair_local_events`, which treats both
legs of a sum-preserving reset. This one-sided repair is appropriate for a raw flow
BEFORE any ratio is built on it, where there is no correlated twin to worry about yet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ._helpers import interpolate_within_entity


def interpolate_negative(
    df: pd.DataFrame,
    column: str,
    *,
    id_col: str = "RSSD_ID",
    out_col: str | None = None,
    action_col: str | None = None,
) -> pd.DataFrame:
    """Blank impossible negatives and interpolate them from the entity's own history.

    Requires ``df`` sorted by ``(id, date)``. Adds ``action_col`` = 1 where a value was
    replaced, if given.
    """
    values = df[column]
    triggered = values < 0
    interpolated = interpolate_within_entity(values.where(~triggered), df[id_col])
    applied = triggered & interpolated.notna()
    df[out_col or column] = np.where(applied, interpolated, values)
    if action_col:
        df[action_col] = applied.astype("int8").to_numpy()
    return df
