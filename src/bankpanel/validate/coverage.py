"""Detect reporting discontinuities across the whole panel history.

The archetype this exists to catch: an MDRM code moves, the config keeps pointing at the
old one, and a column that 99% of banks reported becomes a column 1% of banks report --
with nothing raised anywhere, because every individual value is still valid. The break is
only visible in the *share* of banks reporting, quarter over quarter.

The denominator is the whole design. Naively it is "banks filing this quarter", which is
wrong from 2017 onward: FFIEC 051 filers report hundreds of items only in Q2 and Q4, so
those columns swing by ~100 percentage points every single quarter. That does not merely
produce false alarms, it *saturates* the check -- hundreds of findings per run, in which a
real break cannot be seen. The denominator here is instead "banks that were **supposed**
to report this item this quarter", from the expectations matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..reference.expectations import _expected_quarters

#: Cached quarter sets per frequency label, resolved once at import.
_EXPECTED_QUARTERS = {
    f: _expected_quarters(f)
    for f in ("quarterly", "semiannual_q2q4", "annual_q4", "annual_q2", "sparse", "absent")
}


@dataclass(frozen=True)
class CoverageThresholds:
    #: Change in reporting share, in percentage points, that counts as a break.
    delta: float = 0.20
    #: At least one side must have this much reporting mass, so that a column reported by
    #: a handful of banks cannot generate findings from noise.
    mass_floor: float = 0.10
    #: If the panel's own bank count moves this much, the quarter is a panel-composition
    #: event and column-level changes cannot be attributed to reporting.
    bank_swing: float = 0.20
    #: Maximum quarters between two collection events still treated as adjacent. Beyond
    #: this the item was absent and later reintroduced, which the expectations matrix
    #: already records as an era boundary -- reporting it again as a "break" would just
    #: restate the era, and the from/to dates would be years apart.
    max_gap_quarters: int = 4


def _profile(
    df: pd.DataFrame, columns: list[str], date_col: str, by_form: bool
) -> tuple[pd.DataFrame, pd.Series]:
    """Reporting share per column, per quarter, optionally split by form type.

    Expectedness depends only on ``(column, form_type, quarter)``, never on the individual
    bank, so everything downstream works on this small grid -- a few hundred cells --
    rather than per row.
    """
    period = pd.Series(pd.DatetimeIndex(df[date_col]), index=df.index)
    keys = [period, df["form_type"]] if by_form else [period]
    grid = df.groupby(keys, observed=True)
    sizes = grid.size()
    share = grid[columns].count().div(sizes.replace(0, np.nan), axis=0)
    return share.astype("float64"), sizes


def find_discontinuities(
    df: pd.DataFrame,
    columns: list[str],
    *,
    panel: str = "panel",
    expectations: pd.DataFrame | None = None,
    thresholds: CoverageThresholds | None = None,
    date_col: str = "REPORTING_PERIOD",
) -> pd.DataFrame:
    """Flag transitions where a column's reporting share breaks.

    Two design choices do the real work here.

    **Compare within a form type, not across the pooled panel.** Filers of different forms
    are asked different questions, so a pooled share moves whenever the *mix* of filers
    moves -- which it does violently at 2017Q1, when most banks migrated to the 051 short
    form. Splitting by form type removes that confound entirely, and makes each finding
    actionable ("this broke for 051 filers"), rather than merely true of some blend.

    **Compare consecutive *collection events*, not consecutive calendar quarters.** For an
    item collected from 051 filers only in Q2 and Q4, the meaningful comparison is
    Q2 -> Q4 -> Q2. Comparing Q1 to Q2 asks whether a quarter in which nobody was asked
    differs from one in which everybody was, and the answer is always yes.
    """
    thresholds = thresholds or CoverageThresholds()
    by_form = expectations is not None and "form_type" in df.columns
    share, sizes = _profile(df, columns, date_col, by_form)
    if len(share) < 2:
        return pd.DataFrame()

    if not by_form:
        groups = [(None, share, sizes)]
    else:
        groups = []
        for form_type in sorted({f for _, f in share.index if not pd.isna(f)}):
            sel = [i for i in share.index if i[1] == form_type]
            block = share.loc[sel]
            block.index = pd.DatetimeIndex([i[0] for i in sel])
            counts = sizes.loc[sel]
            counts.index = block.index
            groups.append((int(form_type), block.sort_index(), counts.sort_index()))

    findings = []
    for form_type, block, counts in groups:
        bank_change = counts.pct_change().abs()
        expected_q = _expected_quarter_lookup(expectations, form_type, block.index)

        for column in block.columns:
            series = block[column]
            allowed = expected_q.get(column)
            if allowed is not None:
                series = series.where(allowed)
            series = series.dropna()
            if len(series) < 2:
                continue
            for i in range(1, len(series)):
                prev_q, this_q = series.index[i - 1], series.index[i]
                gap = (this_q.to_period("Q") - prev_q.to_period("Q")).n
                if gap > thresholds.max_gap_quarters:
                    continue
                # A quarter in which this form's own population moves sharply cannot
                # support column-level attribution: everything shifts at once. This is
                # what absorbs the 2017Q1 migration onto the 051 form.
                if bank_change.get(this_q, 0) > thresholds.bank_swing:
                    continue
                before, after = float(series.iloc[i - 1]), float(series.iloc[i])
                delta = after - before
                if abs(delta) < thresholds.delta or max(before, after) < thresholds.mass_floor:
                    continue
                findings.append({
                    "panel": panel,
                    "column": column,
                    "form_type": form_type,
                    "from_date": prev_q,
                    "to_date": this_q,
                    "share_before": before,
                    "share_after": after,
                    "delta": delta,
                    "direction": "drop" if delta < 0 else "surge",
                })

    return pd.DataFrame(findings)


def _expected_quarter_lookup(
    expectations: pd.DataFrame | None, form_type: int | None, index: pd.DatetimeIndex
) -> dict[str, pd.Series]:
    """Per column, a boolean series over ``index``: was collection expected that quarter?

    Columns with no measured rule are absent from the result and are therefore checked in
    every quarter -- an unmeasured column is never silently excused.
    """
    if expectations is None or form_type is None:
        return {}
    rules = expectations[expectations.form_type == form_type]
    quarter = pd.Series(index.quarter, index=index)
    out: dict[str, pd.Series] = {}
    for column, block in rules.groupby("column"):
        flag = pd.Series(True, index=index)
        for _, rule in block.iterrows():
            in_era = (index >= rule.era_start) & (index <= rule.era_end)
            if in_era.any():
                flag.loc[in_era] = quarter[in_era].isin(_EXPECTED_QUARTERS[rule.frequency])
        out[column] = flag
    return out


def coverage_scan(
    df: pd.DataFrame,
    columns: list[str],
    *,
    panel: str = "panel",
    expectations: pd.DataFrame | None = None,
    ledger_path: str | Path | None = None,
    thresholds: CoverageThresholds | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(new_findings, approved_findings)``."""
    from .approvals import load_ledger, partition

    findings = find_discontinuities(
        df, columns, panel=panel, expectations=expectations, thresholds=thresholds
    )
    if ledger_path is None:
        return findings, findings.iloc[0:0] if not findings.empty else findings
    return partition(findings, load_ledger(ledger_path))


def format_report(new: pd.DataFrame, approved: pd.DataFrame, *, limit: int = 40) -> str:
    lines = []
    lines.append("=" * 78)
    lines.append(f"COVERAGE: {len(new)} new finding(s), {len(approved)} already approved")
    lines.append("=" * 78)
    if new.empty:
        lines.append("no unexplained reporting discontinuities")
        return "\n".join(lines)

    show = new.sort_values("delta", key=lambda s: s.abs(), ascending=False).head(limit)
    lines.append("")
    lines.append(f"{'column':<34}{'from':>12}{'to':>12}{'before':>9}{'after':>9}{'delta':>9}")
    for _, row in show.iterrows():
        lines.append(
            f"{row['column'][:33]:<34}"
            f"{pd.Timestamp(row['from_date']).strftime('%Y-%m-%d'):>12}"
            f"{pd.Timestamp(row['to_date']).strftime('%Y-%m-%d'):>12}"
            f"{row['share_before']:>9.3f}{row['share_after']:>9.3f}{row['delta']:>9.3f}"
        )
    if len(new) > limit:
        lines.append(f"... and {len(new) - limit} more")
    lines.append("")
    lines.append("Each finding is either a config bug or a real, explainable transition.")
    lines.append("Record the explained ones in the approvals ledger so they stop reappearing.")
    return "\n".join(lines)
