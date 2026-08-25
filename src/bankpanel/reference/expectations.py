"""When each column is *supposed* to be reported, by form type and era.

This is the reference table that makes a NaN interpretable. Without it, three completely
different situations look identical in the data:

* the bank was asked and answered "none" -- but the item is a conditional line, so it
  left the cell blank;
* the bank was asked and failed to answer;
* **the bank was never asked.**

The third case dominates from 2017 onward, and not for the obvious reason. FFIEC 051
filers -- the majority of banks since 2017 -- do not merely omit items. Hundreds of items
are collected from them **only in Q2 and Q4**, and a few only in Q4. Measured for
``RCON3549`` across 2023, coverage among 051 filers runs 0.003 / 1.000 / 0.001 / 1.000.

A validator that computes ``n_notnull / n_banks`` therefore does not just emit false
alarms at the 2017 onboarding. It emits them *every quarter, forever*, because hundreds
of columns oscillate by 100 percentage points on a two-quarter cycle. The checker becomes
saturated, and a real break can no longer be seen. Changing the denominator to
``n_expected`` is the whole fix.

The table is built empirically -- from what the data actually does, per form type -- and
cross-checked against MDRM, rather than trusted from documentation. Where the two
disagree, the disagreement is reported for a human to resolve into an overrides ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

#: Collection patterns a column can follow within an era.
FREQUENCIES = ("quarterly", "semiannual_q2q4", "annual_q4", "annual_q2", "sparse", "absent")

#: A column counts as collected in a quarter when its coverage reaches this share of its
#: own best quarter that year. Relative, not absolute, because a conditional line item
#: legitimately has low coverage in every quarter -- what identifies a collection pattern
#: is the *shape* across quarters, not the level.
COLLECTED_RATIO = 0.5

#: Below this, nothing is being collected and the shape carries no information.
ABSENT_COVERAGE = 0.005

#: Consecutive years of a new label required before an era change is declared. Guards
#: against a one-year wobble creating spurious eras.
HYSTERESIS_YEARS = 3


@dataclass(frozen=True)
class ExpectationRow:
    column: str
    form_type: int
    era_start: pd.Timestamp
    era_end: pd.Timestamp
    frequency: str
    coverage_when_expected: float
    n_obs: int
    source: str = "empirical"


def _classify_year(coverage_by_quarter: dict[int, float]) -> str:
    """Label one (column, form_type, year) from its four quarterly coverages."""
    present = {q: c for q, c in coverage_by_quarter.items() if not np.isnan(c)}
    if not present:
        return "absent"
    best = max(present.values())
    if best < ABSENT_COVERAGE:
        return "absent"

    collected = {q for q, c in present.items() if c >= COLLECTED_RATIO * best}
    if collected == {1, 2, 3, 4}:
        return "quarterly"
    if collected == {2, 4}:
        return "semiannual_q2q4"
    if collected == {4}:
        return "annual_q4"
    if collected == {2}:
        return "annual_q2"
    return "sparse"


def _collapse_eras(labels: dict[int, str]) -> list[tuple[int, int, str]]:
    """Turn a year -> label mapping into ``(start_year, end_year, label)`` runs.

    A label must persist for :data:`HYSTERESIS_YEARS` before it replaces the incumbent,
    so a single anomalous year is absorbed rather than splitting an era in three.
    """
    years = sorted(labels)
    if not years:
        return []

    eras: list[list] = []
    current = labels[years[0]]
    start = years[0]
    pending: str | None = None
    pending_since: int | None = None

    for year in years[1:]:
        label = labels[year]
        if label == current:
            pending, pending_since = None, None
            continue
        if label != pending:
            pending, pending_since = label, year
        if pending_since is not None and year - pending_since + 1 >= HYSTERESIS_YEARS:
            eras.append([start, pending_since - 1, current])
            current, start = pending, pending_since
            pending, pending_since = None, None

    eras.append([start, years[-1], current])
    return [(int(a), int(b), c) for a, b, c in eras]


def build_expectations(
    df: pd.DataFrame,
    columns: list[str],
    *,
    id_col: str = "RSSD_ID",
    date_col: str = "REPORTING_PERIOD",
) -> pd.DataFrame:
    """Measure the collection pattern of each column, per form type and era.

    ``df`` must carry ``form_type`` and the requested columns.
    """
    if "form_type" not in df.columns:
        raise KeyError("build_expectations needs a form_type column")

    work = df[[date_col, "form_type", *columns]].copy()
    work["_year"] = pd.DatetimeIndex(work[date_col]).year
    work["_q"] = pd.DatetimeIndex(work[date_col]).quarter

    rows: list[dict] = []
    for form_type, block in work.groupby("form_type", observed=True):
        if pd.isna(form_type):
            continue
        # Coverage of each column by (year, quarter), among filers of this form only.
        # count()/size() rather than apply(notna().mean()): same answer, but it stays in
        # the vectorized path, which matters at ~700 columns x 1.4M rows.
        grouped = block.groupby(["_year", "_q"], observed=True)
        counts = grouped.size()
        coverage = grouped[columns].count().div(counts, axis=0)

        for column in columns:
            series = coverage[column]

            # Era boundaries are found at QUARTER granularity, but the frequency pattern
            # is classified per year. Both are needed: an item introduced or retired
            # mid-year would otherwise produce a year that is neither quarterly nor
            # absent, get labelled "sparse", and never be recognized as having stopped.
            active = [idx for idx, value in series.items() if value >= ABSENT_COVERAGE]
            if not active:
                rows.append(_absent_row(column, form_type, series, counts))
                continue
            first_active, last_active = min(active), max(active)

            labels: dict[int, str] = {}
            for year in sorted({y for y, _ in series.index}):
                if year < first_active[0] or year > last_active[0]:
                    continue
                by_quarter = {
                    q: float(series.get((year, q), np.nan))
                    for q in (1, 2, 3, 4)
                    if (year, q) >= first_active and (year, q) <= last_active
                }
                labels[year] = _classify_year(by_quarter)

            rows.extend(
                _boundary_rows(column, form_type, series, counts, first_active, last_active)
            )

            for start_year, end_year, frequency in _collapse_eras(labels):
                window = series.loc[
                    [(y, q) for (y, q) in series.index if start_year <= y <= end_year]
                ]
                expected_q = _expected_quarters(frequency)
                in_scope = [c for (y, q), c in window.items() if q in expected_q]
                n_obs = int(
                    counts.loc[
                        [(y, q) for (y, q) in counts.index if start_year <= y <= end_year]
                    ].sum()
                )
                era_start = pd.Timestamp(f"{start_year}-01-01")
                era_end = _q_end(end_year, 4)
                # Clip the first and last frequency era to the measured active window, so
                # they abut the absent eras rather than overlapping them.
                era_start = max(era_start, _q_start(*first_active))
                era_end = min(era_end, _q_end(*last_active))
                rows.append(
                    ExpectationRow(
                        column=column,
                        form_type=int(form_type),
                        era_start=era_start,
                        era_end=era_end,
                        frequency=frequency,
                        coverage_when_expected=float(np.nanmean(in_scope)) if in_scope else 0.0,
                        n_obs=n_obs,
                    ).__dict__
                )

    return pd.DataFrame(rows)


def _q_end(year: int, quarter: int) -> pd.Timestamp:
    return pd.Period(f"{year}Q{quarter}", freq="Q").end_time.normalize()


def _q_start(year: int, quarter: int) -> pd.Timestamp:
    return pd.Period(f"{year}Q{quarter}", freq="Q").start_time.normalize()


def _absent_row(column: str, form_type, series, counts) -> dict:
    """A column this form never reports at all."""
    years = sorted({y for y, _ in series.index})
    return ExpectationRow(
        column=column,
        form_type=int(form_type),
        era_start=_q_start(years[0], 1) if years else pd.Timestamp("1900-01-01"),
        era_end=_q_end(years[-1], 4) if years else pd.Timestamp("2100-12-31"),
        frequency="absent",
        coverage_when_expected=0.0,
        n_obs=int(counts.sum()),
    ).__dict__


def _boundary_rows(column, form_type, series, counts, first_active, last_active) -> list[dict]:
    """Explicit ``absent`` eras before an item was introduced and after it was retired.

    Without these, a retirement looks like a coverage collapse rather than the end of a
    collection era, and every era-piece variable in the config generates a finding at the
    exact quarter its stitch is designed to handle.
    """
    out = []
    years = sorted({y for y, _ in series.index})
    if not years:
        return out
    panel_start, panel_end = _q_start(years[0], 1), _q_end(years[-1], 4)

    intro = _q_start(*first_active)
    if intro > panel_start:
        out.append(ExpectationRow(
            column=column, form_type=int(form_type), era_start=panel_start,
            era_end=intro - pd.Timedelta(days=1), frequency="absent",
            coverage_when_expected=0.0, n_obs=0,
        ).__dict__)

    retired = _q_end(*last_active)
    if retired < panel_end:
        out.append(ExpectationRow(
            column=column, form_type=int(form_type),
            era_start=retired + pd.Timedelta(days=1), era_end=panel_end,
            frequency="absent", coverage_when_expected=0.0, n_obs=0,
        ).__dict__)
    return out


def _expected_quarters(frequency: str) -> set[int]:
    return {
        "quarterly": {1, 2, 3, 4},
        "semiannual_q2q4": {2, 4},
        "annual_q4": {4},
        "annual_q2": {2},
        "sparse": {1, 2, 3, 4},
        "absent": set(),
    }[frequency]


def expected_mask(
    df: pd.DataFrame,
    column: str,
    expectations: pd.DataFrame,
    *,
    date_col: str = "REPORTING_PERIOD",
) -> pd.Series:
    """Was each cell of ``column`` supposed to be reported?

    This is the piece researchers most need and currently have no way to get: it separates
    "not collected" from "reported as missing". A cell with no matching expectation row
    defaults to True, so an unmeasured column is never silently excused.
    """
    rules = expectations[expectations.column == column]
    period = pd.DatetimeIndex(df[date_col])
    out = pd.Series(True, index=df.index)
    if rules.empty:
        return out

    quarter = pd.Series(period.quarter, index=df.index)
    for _, rule in rules.iterrows():
        in_scope = (
            (df["form_type"] == rule.form_type)
            & (period >= rule.era_start)
            & (period <= rule.era_end)
        )
        if not in_scope.any():
            continue
        out.loc[in_scope] = quarter[in_scope].isin(_expected_quarters(rule.frequency))
    return out


def write_expectations(df: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def read_expectations(path: str | Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    for col in ("era_start", "era_end"):
        df[col] = pd.to_datetime(df[col])
    return df


def apply_overrides(expectations: pd.DataFrame, overrides_path: str | Path) -> pd.DataFrame:
    """Replace measured rows with human-approved ones.

    Schema: ``column, form_type, era_start, era_end, frequency, reason, approved_by,
    approved_at``. An override wins over anything measured for the same
    ``(column, form_type)`` window.
    """
    path = Path(overrides_path)
    if not path.exists():
        return expectations
    over = pd.read_csv(path)
    if over.empty:
        return expectations
    for col in ("era_start", "era_end"):
        over[col] = pd.to_datetime(over[col])
    over["source"] = "manual"
    keys = set(zip(over.column, over.form_type, strict=True))
    keep = ~expectations.apply(lambda r: (r.column, r.form_type) in keys, axis=1)
    columns = [c for c in expectations.columns if c in over.columns or c == "source"]
    return pd.concat([expectations[keep], over[columns]], ignore_index=True)
