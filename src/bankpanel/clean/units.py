"""Unit-of-measure errors.

Call Report dollar items are reported in thousands and counts in thousands, and some
banks report a stretch of quarters in raw units instead. The result is a segment of one
bank's series sitting a factor of 1,000 above the rest of it -- individually plausible
values, collectively impossible.

The correction is scale-free and per bank per column: split the series at ~1000x jumps,
cluster the resulting segments into a high and a low level about the geometric mean of
their medians, and only act if the two clusters really differ by about the factor. A
series that merely grew a lot has no such structure and is left alone.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ._helpers import (
    JUMP_RATIO_HIGH,
    JUMP_RATIO_LOW,
    classify_segments,
    detect_jumps,
    segment_medians,
)


def fix_unit_errors(
    df: pd.DataFrame,
    columns: list[str],
    *,
    id_col: str = "RSSD_ID",
    date_col: str = "REPORTING_PERIOD",
    factor: float = 1000.0,
    low: float = JUMP_RATIO_LOW,
    high: float = JUMP_RATIO_HIGH,
    exclude: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Divide mis-scaled segments by ``factor``.

    ``exclude`` suppresses a correction for specific ``(id, column)`` pairs -- for a bank
    whose series genuinely steps by three orders of magnitude. Corrections are entity-level,
    so no date is needed.

    Returns ``(corrected_df, log)``. The log has one row per changed value, carrying the
    segment median and the reference median so a reviewer can see why it fired.
    """
    out = df.copy()
    suppressed = set()
    if exclude is not None and len(exclude):
        missing = {"id", "column"} - set(exclude.columns)
        if missing:
            raise ValueError(f"exclude is missing column(s) {sorted(missing)}")
        suppressed = set(zip(exclude["id"], exclude["column"], strict=True))

    rows = []
    for column in columns:
        if column not in out.columns:
            continue
        for entity, group in out.groupby(id_col, sort=False):
            values = group[column].to_numpy(dtype="float64", copy=True)
            positive, jumps = detect_jumps(values, low, high)
            if not jumps:
                continue
            segments = segment_medians(positive, jumps, values)
            classified = classify_segments(segments, low, high)
            if classified is None:
                continue
            _, high_idx, low_median, _ = classified

            skip = (entity, column) in suppressed
            dates = group[date_col].to_numpy()
            index = group.index
            for seg in high_idx:
                for pos in segments[seg]["positions"]:
                    original = float(values[pos])
                    corrected = original / factor
                    if not skip:
                        out.at[index[pos], column] = corrected
                    rows.append({
                        id_col: entity,
                        date_col: pd.Timestamp(dates[pos]),
                        "column": column,
                        "rule": "fix_unit_errors",
                        "old": original,
                        "new": original if skip else corrected,
                        "segment_median": segments[seg]["median"],
                        "reference_median": low_median,
                        "action": "suppressed" if skip else "corrected",
                    })

    log = pd.DataFrame(rows)
    if len(log):
        log = log.sort_values([id_col, "column", date_col]).reset_index(drop=True)
    return out, log


def find_unit_errors(
    df: pd.DataFrame, columns: list[str], **kwargs
) -> pd.DataFrame:
    """Report suspected unit errors without changing anything."""
    _, log = fix_unit_errors(df, columns, **kwargs)
    return log


__all__ = ["fix_unit_errors", "find_unit_errors", "np"]
