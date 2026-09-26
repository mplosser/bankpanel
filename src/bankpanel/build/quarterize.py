"""Year-to-date to quarterly flows.

Every RIAD income-statement item on the Call Report is **year-to-date cumulative** and
resets each Q1. A panel that ignores this does not merely mis-scale: Q4 of a growing bank
looks like four quarters of income, and any quarter-over-quarter change is meaningless.

The conversion is ``flow(t) = ytd(t) - ytd(t-1)`` within a bank-year, with Q1 passing
through unchanged. That much is inherited from the legacy implementation, along with its
vectorized ``groupby.diff()`` core, which is genuinely fast.

The as-filed year-to-date column is **kept**, and the flow is written to a companion
column (``ytd_int_inc`` -> ``q_int_inc``). A bank that files an item only at Q4 has an
annual total, not a fourth-quarter flow: its ``ytd_`` column carries the total and its
``q_`` column is NaN for the whole year. Nothing is quarterized that cannot be.

Two correctness bugs are fixed here.

**Intra-year gaps.** ``groupby.diff()`` differences against the previous *present* row,
not the previous *calendar* quarter. A bank missing Q2 gets
``flow(Q3) = ytd(Q3) - ytd(Q1)`` -- two quarters of income booked as one, silently.

**Partial first years.** A bank whose first filing in a year is Q3 has no prior row, so
``diff()`` returns NaN, and the legacy ``.fillna(original)`` then recorded its
*year-to-date-through-Q3* as a single quarter's flow. This is not a rare corner: it hits
every de-novo bank's first partial year and every acquired bank's final year.

Both are now detected explicitly and handled by an opt-in policy, and every affected cell
is reported rather than absorbed.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

#: What to do where a clean one-quarter difference is not available.
GAP_POLICIES = ("nan", "spread", "keep")


class QuarterizeError(Exception):
    pass


def quarterize(
    df: pd.DataFrame,
    flows: Mapping[str, str],
    *,
    id_col: str = "RSSD_ID",
    date_col: str = "REPORTING_PERIOD",
    policy: str = "nan",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add a quarterly-flow column for each ``{ytd_column: flow_column}`` pair.

    The year-to-date columns are returned untouched; the flow columns are appended.

    ``df`` must contain whole bank-years: quarterization groups on ``(bank, year)``, so
    splitting a year across two calls would corrupt it. The panel is partitioned by year
    precisely so that this constraint is satisfied by construction.

    Policies:

    ``nan``
        Gaps and partial-year starts become NaN. Honest, and the default: a flow that
        cannot be computed is unknown, not zero and not a multi-quarter total.
    ``spread``
        A k-quarter difference is divided by k, giving the *average* quarterly flow over
        the gap, assigned to the observed quarter. Note this does not fabricate rows for
        the missing quarters -- there are none to fill. Useful for FFIEC 051 filers whose
        items are collected semiannually.
    ``keep``
        Legacy behaviour, reproducing the pre-bankpanel pipeline bug-for-bug so that a
        migration can be compared bitwise. Do not use for research.

    Returns ``(quarterized_df, gap_report)``.
    """
    if policy not in GAP_POLICIES:
        raise QuarterizeError(f"unknown gap policy {policy!r}; expected one of {GAP_POLICIES}")

    present = [c for c in flows if c in df.columns]
    out = df.sort_values([id_col, date_col]).reset_index(drop=True)
    if not present:
        return out, _empty_gap_report(id_col, date_col)

    if out.duplicated([id_col, date_col]).any():
        dupes = out.loc[out.duplicated([id_col, date_col]), [id_col, date_col]]
        raise QuarterizeError(
            f"{len(dupes)} duplicate (bank, quarter) rows; quarterization needs one row "
            f"per bank-quarter. First: {dupes.iloc[0].to_dict()}"
        )

    period = pd.DatetimeIndex(out[date_col])
    year = pd.Series(period.year, index=out.index)
    quarter = pd.Series(period.quarter, index=out.index)

    # Grouping on (bank, year) is what makes the annual YTD reset correct: no difference
    # can ever cross a year boundary, so no Q1 is ever differenced against a prior Q4.
    keys = [out[id_col], year]
    grouped = out.groupby(keys, sort=False)
    prev_quarter = quarter.groupby(keys, sort=False).shift(1)
    step = quarter - prev_quarter

    diffs = grouped[present].diff()

    is_q1_start = quarter.eq(1) & prev_quarter.isna()
    is_gap = step.gt(1)
    is_orphan = prev_quarter.isna() & quarter.ne(1)

    ytd_values = out[present]
    result = diffs.copy()

    if policy == "keep":
        # Reproduce the legacy implementation exactly, which was a single
        #     result = groupby.diff().fillna(raw_ytd)
        # That fallback fires wherever the within-year difference is undefined, which is
        # three distinct situations, only one of which is correct:
        #   1. the first row of a bank-year (Q1)  -- correct, year-to-date IS the flow;
        #   2. a bank-year that starts after Q1   -- wrong, books a multi-quarter total;
        #   3. the previous quarter's value is missing -- also wrong, and not structural:
        #      the row exists, only its value is absent, so it cannot be detected from
        #      the reporting calendar alone.
        # Case 3 is why this branch cannot be expressed with the row masks below.
        for col in present:
            result[col] = diffs[col].fillna(ytd_values[col])
        out = _with_flows(out, result, flows, present)
        return out, _gap_report(
            out, id_col, date_col, step, is_gap, is_orphan, policy, len(present)
        )

    # Q1 (or the first row of a bank-year that legitimately starts at Q1): YTD is the flow.
    result.loc[is_q1_start, present] = ytd_values.loc[is_q1_start, present].to_numpy()

    if policy == "nan":
        result.loc[is_gap | is_orphan, present] = np.nan
    elif policy == "spread":
        if is_gap.any():
            divisor = step.where(is_gap)
            result.loc[is_gap, present] = (
                diffs.loc[is_gap, present].div(divisor.loc[is_gap], axis=0).to_numpy()
            )
        result.loc[is_orphan, present] = np.nan

    out = _with_flows(out, result, flows, present)

    report = _gap_report(
        out, id_col, date_col, step, is_gap, is_orphan, policy, len(present)
    )
    return out, report


def _with_flows(out: pd.DataFrame, result: pd.DataFrame, flows: Mapping[str, str], present: list[str]) -> pd.DataFrame:
    """Append the flow companions in one concat (one insert per column fragments the frame)."""
    companions = result[present].astype("float64").rename(columns={c: flows[c] for c in present})
    return pd.concat([out, companions], axis=1)


def _empty_gap_report(id_col: str, date_col: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            id_col: pd.Series(dtype="int64"),
            date_col: pd.Series(dtype="datetime64[ns]"),
            "kind": pd.Series(dtype="string"),
            "step": pd.Series(dtype="float64"),
            "policy": pd.Series(dtype="string"),
            "n_columns": pd.Series(dtype="int64"),
        }
    )


def _gap_report(
    out: pd.DataFrame,
    id_col: str,
    date_col: str,
    step: pd.Series,
    is_gap: pd.Series,
    is_orphan: pd.Series,
    policy: str,
    n_columns: int,
) -> pd.DataFrame:
    flagged = is_gap | is_orphan
    if not flagged.any():
        return _empty_gap_report(id_col, date_col)
    report = pd.DataFrame(
        {
            id_col: out.loc[flagged, id_col].to_numpy(),
            date_col: out.loc[flagged, date_col].to_numpy(),
            "kind": np.where(is_gap[flagged], "gap", "partial_year_start"),
            "step": step[flagged].to_numpy(),
            "policy": policy,
            "n_columns": n_columns,
        }
    )
    report["kind"] = report["kind"].astype("string")
    report["policy"] = report["policy"].astype("string")
    return report
