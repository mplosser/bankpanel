"""Guard the newest quarter against a break that just appeared.

Complementary to ``coverage.py``, which scans all history. This one asks a narrower and
more urgent question: did *this quarter's* data change in a way that suggests the source
moved under us? It is the check you want to fail a scheduled rebuild.

Every test is **year-over-year, same quarter**. That is not a detail. Many Call Report
items are seasonal by construction -- collected only in Q2, or only in Q4 -- so comparing
Q1 against the preceding Q4 would flag hundreds of columns every single quarter. Comparing
2025Q3 against 2024Q3 asks whether *this* quarter differs from what this quarter normally
looks like.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

#: Below this coverage a year ago, there is nothing to have collapsed from.
MIN_COVER = 0.05
#: Coverage falling to less than half its year-ago level.
COLLAPSE = 0.50
#: Non-zero share falling to less than a tenth of its year-ago level.
ZERO_COLLAPSE = 0.10
#: Level shift in the per-quarter median of non-zero values.
LEVEL_WARN = 3.0
LEVEL_CRIT = 10.0
#: Fewer non-zero reporters than this and the median is not a stable statistic.
MIN_NONZERO_BANKS = 30


@dataclass(frozen=True)
class Break:
    column: str
    test: str
    severity: str
    this_quarter: float
    year_ago: float
    detail: str


def _quarter_stats(df: pd.DataFrame, columns: list[str], date_col: str) -> pd.DataFrame:
    """Coverage, non-zero share, and median magnitude per column per quarter."""
    period = pd.Series(pd.DatetimeIndex(df[date_col]), index=df.index)
    out = []
    for quarter, block in df.groupby(period, observed=True):
        n = len(block)
        for column in columns:
            values = block[column]
            nonzero = values[(values.notna()) & (values != 0)]
            out.append({
                "quarter": quarter,
                "column": column,
                "coverage": values.notna().sum() / n if n else np.nan,
                "nonzero_share": len(nonzero) / n if n else np.nan,
                # Median, not mean: a unit or definition change rescales every bank and
                # moves the median, while one large bank's one-off does not.
                "median_abs": float(nonzero.abs().median()) if len(nonzero) else np.nan,
                "n_nonzero": len(nonzero),
            })
    return pd.DataFrame(out)


def check_latest_quarter(
    df: pd.DataFrame,
    columns: list[str],
    *,
    date_col: str = "REPORTING_PERIOD",
) -> pd.DataFrame:
    """Compare the newest quarter against the same quarter a year earlier."""
    stats = _quarter_stats(df, columns, date_col)
    if stats.empty:
        return pd.DataFrame()

    quarters = sorted(stats.quarter.unique())
    latest = quarters[-1]
    year_ago = pd.Timestamp(latest) - pd.DateOffset(years=1)
    if year_ago not in set(quarters):
        return pd.DataFrame()

    now = stats[stats.quarter == latest].set_index("column")
    then = stats[stats.quarter == year_ago].set_index("column")
    shared = now.index.intersection(then.index)

    findings: list[Break] = []
    for column in shared:
        a, b = now.loc[column], then.loc[column]

        if b.coverage >= MIN_COVER and a.coverage < COLLAPSE * b.coverage:
            findings.append(Break(
                column, "coverage_collapse", "CRITICAL", a.coverage, b.coverage,
                f"reported by {a.coverage:.1%} of banks, was {b.coverage:.1%} a year ago",
            ))

        if b.nonzero_share >= MIN_COVER and a.nonzero_share < ZERO_COLLAPSE * b.nonzero_share:
            findings.append(Break(
                column, "zero_flip", "CRITICAL", a.nonzero_share, b.nonzero_share,
                f"non-zero for {a.nonzero_share:.1%} of banks, was {b.nonzero_share:.1%}",
            ))

        if (
            a.n_nonzero >= MIN_NONZERO_BANKS
            and b.n_nonzero >= MIN_NONZERO_BANKS
            and b.median_abs
            and not np.isnan(a.median_abs)
        ):
            ratio = a.median_abs / b.median_abs
            factor = max(ratio, 1 / ratio) if ratio > 0 else np.inf
            if factor >= LEVEL_WARN:
                findings.append(Break(
                    column, "level_break",
                    "CRITICAL" if factor >= LEVEL_CRIT else "WARNING",
                    a.median_abs, b.median_abs,
                    f"median non-zero value moved {factor:.1f}x year over year",
                ))

    result = pd.DataFrame([f.__dict__ for f in findings])
    if not result.empty:
        result.insert(0, "quarter", latest)
    return result


def format_report(findings: pd.DataFrame, latest: str = "") -> str:
    lines = ["=" * 78, f"SERIES BREAKS{f' -- {latest}' if latest else ''}", "=" * 78]
    if findings.empty:
        lines.append("no breaks against the same quarter a year ago")
        return "\n".join(lines)
    critical = findings[findings.severity == "CRITICAL"]
    lines.append(f"{len(critical)} critical, {len(findings) - len(critical)} warning")
    lines.append("")
    for _, row in findings.sort_values("severity").iterrows():
        lines.append(f"  [{row.severity:<8}] {row.column:<32} {row.test:<18} {row.detail}")
    return "\n".join(lines)


def gate(findings: pd.DataFrame) -> int:
    """Exit code: non-zero if anything critical appeared in the newest quarter."""
    if findings.empty:
        return 0
    return 1 if (findings.severity == "CRITICAL").any() else 0
