"""Rate and ratio surfaces: local-event repair.

The doctrine here is worth stating, because it replaced something that looked reasonable
and was subtly wrong.

A year-to-date reset -- caused by a merger, a divestiture, or a restatement -- is
approximately **sum-preserving**. Income that belongs to one quarter gets allocated to
another, so the artifact comes in PAIRS: a negative or collapsed quarter next to an
inflated one. Repairing only the impossible-looking leg leaves the inflated twin standing,
and worse, lets the repaired value be interpolated *from* it. The earlier one-sided
approach did exactly that, and inflated a ratio inside its own repair windows.

So detection is by **discontinuity against the entity's own local neighbourhood** -- the
median of its t±2 quarters -- rather than against a level threshold. That is level-free,
so a genuine rate cycle never triggers however high rates go, while a one-quarter
dislocation does. And the repair window WIDENS over any adjacent quarter that is itself
loosely anomalous, so both legs of a pair are replaced together and interpolation can only
anchor on clean quarters.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def repair_local_events(
    rate,
    dates,
    entities,
    *,
    combo=None,
    loose_ratio: float = 1.75,
    loose_dev: float = 0.5,
    extreme_ratio: float = 2.5,
    extreme_dev: float = 1.0,
    negative_impossible: bool = True,
) -> tuple[pd.Series, pd.Series]:
    """Repair artifact quarters in a rate or ratio surface.

    Three triggers:

    * an **impossible negative**, when the quantity is a gross-additive-flow ratio
      (``negative_impossible``);
    * a quarter flagged by ``combo`` (business combination, restatement) that is a *loose*
      local outlier in either direction -- a flag alone is not enough, since most mergers
      do not corrupt the series;
    * an unflagged **extreme** local outlier, on tighter thresholds, since without a flag
      the evidence has to come entirely from the data.

    Returns ``(repaired, event_mask)``. Non-event rows are returned bit-identical, and a
    NaN input never becomes a value.
    """
    values = pd.Series(rate).astype("float64")
    dates = pd.Series(dates)
    entities = pd.Series(entities)

    order = np.lexsort((dates.to_numpy(), entities.to_numpy()))
    inverse = np.empty_like(order)
    inverse[order] = np.arange(len(order))

    sorted_values = values.iloc[order].reset_index(drop=True)
    sorted_entities = entities.iloc[order].reset_index(drop=True)
    flags = (
        pd.Series(combo).iloc[order].reset_index(drop=True)
        if combo is not None
        else pd.Series(0.0, index=sorted_values.index)
    )

    def by_entity(series):
        return series.groupby(sorted_entities)

    neighbours = pd.concat([by_entity(sorted_values).shift(k) for k in (-2, -1, 1, 2)], axis=1)
    # At least two neighbours, so a single adjacent artifact cannot define the reference.
    reference = neighbours.median(axis=1).where(neighbours.notna().sum(axis=1) >= 2)
    deviation = sorted_values - reference
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = sorted_values / reference.replace(0, np.nan)

    negative = (sorted_values < 0) if negative_impossible else pd.Series(False, index=sorted_values.index)
    loose = ((ratio > loose_ratio) | (ratio < 1.0 / loose_ratio)) & (deviation.abs() > loose_dev)
    flagged = (flags.fillna(0) > 0) & loose & ~negative
    extreme = (
        ((ratio > extreme_ratio) | (ratio < 1.0 / extreme_ratio))
        & (deviation.abs() > extreme_dev)
        & ~negative
        & ~(flags.fillna(0) > 0)
    )

    event = negative | flagged | extreme
    # Widen over a loosely-anomalous neighbour: the correlated twin of a sum-preserving
    # reset. Without this the repair can anchor on the inflated half of the pair.
    shifted = [by_entity(event).shift(k).astype("boolean").fillna(False) for k in (1, -1)]
    adjacent = shifted[0] | shifted[1]
    window = event | (adjacent & (loose | negative) & ~event)

    repaired = sorted_values.mask(window)
    repaired = by_entity(repaired).transform(
        lambda s: s.interpolate(method="linear", limit_area="inside")
    )
    repaired = repaired.where(window, sorted_values)          # non-event rows exact
    repaired = repaired.where(repaired.notna(), reference)    # no interior anchors -> local ref
    repaired = repaired.where(repaired.notna() | ~window, sorted_values)  # last resort
    repaired = repaired.where(sorted_values.notna())          # never invent a value

    return (
        pd.Series(repaired.to_numpy()[inverse], index=values.index),
        pd.Series(window.to_numpy()[inverse], index=values.index),
    )


def interpolate_broken_ratio(
    df: pd.DataFrame,
    *,
    rate_col: str,
    id_col: str = "RSSD_ID",
    date_col: str = "REPORTING_PERIOD",
    combo_col: str | None = None,
    out_col: str | None = None,
    action_col: str | None = None,
    **kwargs,
) -> pd.DataFrame:
    """DataFrame adapter for :func:`repair_local_events`, in place."""
    repaired, mask = repair_local_events(
        df[rate_col], df[date_col], df[id_col],
        combo=df[combo_col] if combo_col and combo_col in df.columns else None,
        **kwargs,
    )
    df[out_col or rate_col] = repaired
    if action_col:
        df[action_col] = mask.astype("int8")
    return df
