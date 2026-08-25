"""Denominators for income ratios, and the rates built on them.

An income ratio needs an average balance, and the obvious average -- the mean of this
quarter's and last quarter's endpoints -- is wrong in exactly the quarters that matter.
When a bank acquires, divests, or grows fast mid-quarter, the two endpoints straddle a
level shift and their mean describes neither period. The ratio then spikes or collapses
for a reason that has nothing to do with the bank's economics.

Schedule RC-K reports the true within-quarter average directly. These functions use it,
but only where the endpoint proxy is *suspect* -- a do-no-harm swap rather than a
wholesale source change, so ordinary quarters are left exactly as they were.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ._helpers import interpolate_within_entity

#: Suspect-quarter categories, in priority order.
CATEGORY_NONE = 0
CATEGORY_COMBO = 1
CATEGORY_MATERIAL = 2
CATEGORY_DEGENERATE = 3


def rescale_denominator(
    df: pd.DataFrame,
    *,
    level_col: str,
    reported_col: str,
    combo_col: str | None = None,
    id_col: str = "RSSD_ID",
    material: float = 0.10,
    tau_degenerate: float = 0.10,
    floor: float = 1000.0,
    out_col: str = "avg_base",
    category_col: str = "denom_category",
) -> pd.DataFrame:
    """Replace a two-endpoint average with the reported average in suspect quarters.

    A quarter is suspect when any of:

    * ``combo`` — a business combination is flagged;
    * ``material`` — the reported average and the endpoint proxy disagree by more than
      ``material`` in logs, so the endpoints demonstrably mis-state the period;
    * ``degenerate`` — one of the two endpoints is near zero, so their mean is meaningless.

    Priority is combo > degenerate > material. Unlike a rate rescale there is no inferred
    scale factor to second-guess: the reported average is a directly reported and superior
    measure, so a suspect quarter simply adopts it.

    Requires ``df`` sorted by ``(id, date)``. Adds ``out_col`` and ``category_col`` in place.
    """
    level = df[level_col]
    lagged = level.groupby(df[id_col]).shift(1)
    endpoint = (level + lagged) / 2
    reported = df[reported_col]

    with np.errstate(divide="ignore", invalid="ignore"):
        material_hit = (
            (np.abs(np.log(reported / endpoint)) > material) & (reported > 0) & (endpoint > 0)
        )
        lo = np.minimum(level, lagged)
        hi = np.maximum(level, lagged)
        degenerate = (lo / hi) < tau_degenerate

    combo = (
        (df[combo_col].fillna(0) != 0)
        if combo_col and combo_col in df.columns
        else pd.Series(False, index=df.index)
    )
    combo = combo.to_numpy()
    material_hit = material_hit.fillna(False).to_numpy()
    degenerate = degenerate.fillna(False).to_numpy()

    category = np.where(
        combo, CATEGORY_COMBO,
        np.where(degenerate, CATEGORY_DEGENERATE,
                 np.where(material_hit, CATEGORY_MATERIAL, CATEGORY_NONE)),
    )
    suspect = combo | material_hit | degenerate
    # Also adopt the reported average where the endpoint cannot be formed at all -- the
    # bank's first quarter has no lag.
    use_reported = (suspect | endpoint.isna().to_numpy()) & (reported.to_numpy() > 0)
    base = np.where(use_reported, reported.to_numpy(), endpoint.to_numpy())

    # Valued-balance floor: below this there is nothing to form a ratio against.
    df[out_col] = np.where(base >= floor, base, np.nan)
    df[category_col] = category
    return df


def implied_rate(
    flow,
    reported_avg,
    simple_sum,
    valued_balance,
    dates,
    entities=None,
    *,
    min_balance: float = 1000.0,
    winsor_pct: tuple[float, float] = (1.0, 99.0),
    ann_reported: float = 400.0,
    ann_simple: float = 800.0,
) -> pd.Series:
    """Implied rate = flow / average balance, with a floor and a two-way fallback.

    The structure that matters is what happens when a rate cannot be inferred:

    ``valued_balance <= 0``
        NaN. There is nothing to value, and a rate on nothing is not a number.
    ``0 < valued_balance < min_balance``
        the per-date **median**. An immaterial balance still belongs in the panel, but
        ``flow / tiny`` is noise and the bank has no reliable own rate at that size.
    ``valued_balance >= min_balance`` **but the numerator is broken**
        the bank's **own history**, interpolated. A real balance with a reset numerator
        still has a well-defined own yield, and its neighbouring quarters estimate it far
        better than the cross-section does. Falls back to the median only if the bank has
        no usable history at all.

    Inferred rates are winsorized per date at ``winsor_pct``, both tails.
    """
    flow = pd.Series(flow)
    reported_avg = pd.Series(reported_avg)
    simple_sum = pd.Series(simple_sum)
    valued_balance = pd.Series(valued_balance)
    dates = pd.Series(dates)

    with np.errstate(divide="ignore", invalid="ignore"):
        inferred = np.where(
            reported_avg > 0, flow / reported_avg * ann_reported,
            np.where(simple_sum > 0, flow / simple_sum * ann_simple, np.nan),
        )
    inferred = pd.Series(inferred, index=flow.index)

    good = (valued_balance >= min_balance) & (inferred >= 0) & inferred.notna()
    base = inferred.where(good)

    lo_pct, hi_pct = winsor_pct
    lo = base.groupby(dates).transform(
        lambda x: np.nanpercentile(x, lo_pct) if x.notna().any() else np.nan
    )
    hi = base.groupby(dates).transform(
        lambda x: np.nanpercentile(x, hi_pct) if x.notna().any() else np.nan
    )
    base = base.clip(lower=lo, upper=hi)
    result = base.where(good)

    if entities is not None:
        own = interpolate_within_entity(base, pd.Series(entities))
        real_but_uninferable = (valued_balance >= min_balance) & ~good
        result = result.where(good, own.where(real_but_uninferable))

    median = base.groupby(dates).transform("median")
    fill = result.isna() & (valued_balance > 0)
    return result.where(~fill, median)
