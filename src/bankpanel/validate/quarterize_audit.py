"""Report quarterized flows that cannot be right.

A gross additive flow -- interest income, interest expense, non-interest *expense*,
fiduciary income -- cannot be negative over a quarter. When one is, the year-to-date
series was reset mid-year, almost always by a merger, a divestiture, or a restatement, and
the difference picked up the reset instead of a flow.

Which columns this applies to is a *semantic* property, so it is declared in the config
(``sign=nonneg``) rather than guessed from the name. The implementation this replaces
matched name prefixes, which worked but was a proxy: net items -- trading revenue, gains
on sales of securities or OREO, tax benefits -- legitimately go negative, and telling them
apart by prefix means the rule silently depends on a naming convention nobody enforces.

Report-and-flag, never a hard gate. The right treatment is to NaN the artifact rather than
pass either a negative or a fabricated zero downstream, and that decision belongs to the
analysis, not to the ingest.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def audit(
    df: pd.DataFrame,
    nonneg_columns: list[str],
    *,
    flag_columns: list[str] | None = None,
    tolerance: float = 0.0,
    id_col: str = "RSSD_ID",
    date_col: str = "REPORTING_PERIOD",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(per_column_summary, flagged_rows)``.

    ``flag_columns`` are structural-event indicators (business combination, restatement,
    discontinued operations) used to attribute the negatives to a cause.
    """
    present = [c for c in nonneg_columns if c in df.columns]
    if not present:
        return pd.DataFrame(), pd.DataFrame()

    values = df[present]
    negative = values < -abs(tolerance)

    summary = pd.DataFrame({
        "column": present,
        "n_nonnull": [int(values[c].notna().sum()) for c in present],
        "n_negative": [int(negative[c].sum()) for c in present],
        "min": [float(values[c].min()) if values[c].notna().any() else np.nan for c in present],
    })
    summary["pct_negative"] = np.where(
        summary.n_nonnull > 0, summary.n_negative / summary.n_nonnull, np.nan
    )

    any_negative = negative.any(axis=1)
    flagged = df.loc[any_negative, [id_col, date_col]].copy()
    flagged["n_negative_columns"] = negative.loc[any_negative].sum(axis=1).to_numpy()

    for flag in flag_columns or []:
        if flag in df.columns:
            flagged[flag] = df.loc[any_negative, flag].to_numpy()

    return summary.sort_values("n_negative", ascending=False), flagged


def attribute(flagged: pd.DataFrame, flag_columns: list[str]) -> pd.DataFrame:
    """Share of flagged bank-quarters carrying each structural-event indicator.

    A quarter can carry more than one indicator, so these shares need not sum to one --
    which is also why ``unexplained`` is computed from rows carrying *no* indicator rather
    than as one minus the rest.
    """
    if flagged.empty:
        return pd.DataFrame()
    present = [c for c in flag_columns if c in flagged.columns]
    rows = []
    for flag in present:
        has = flagged[flag].fillna(0) != 0
        rows.append({"cause": flag, "n": int(has.sum()), "share": float(has.mean())})
    if present:
        none = ~(flagged[present].fillna(0) != 0).any(axis=1)
        rows.append({"cause": "unexplained", "n": int(none.sum()), "share": float(none.mean())})
    return pd.DataFrame(rows)


def format_report(
    summary: pd.DataFrame, flagged: pd.DataFrame, causes: pd.DataFrame, n_rows: int, limit: int = 20
) -> str:
    lines = ["=" * 78, "QUARTERIZE AUDIT -- impossible negative flows", "=" * 78]
    if summary.empty:
        lines.append("no columns declared sign=nonneg; nothing to check")
        return "\n".join(lines)

    total = int(summary.n_negative.sum())
    affected = len(flagged)
    lines.append(
        f"{total:,} impossible-negative cells across {int((summary.n_negative > 0).sum())} "
        f"column(s); {affected:,} bank-quarters affected ({affected / n_rows:.3%})"
    )
    lines.append("")
    lines.append(f"{'column':<34}{'nonnull':>12}{'negative':>10}{'pct':>9}{'min':>16}")
    for _, row in summary[summary.n_negative > 0].head(limit).iterrows():
        lines.append(
            f"{row['column'][:33]:<34}{row['n_nonnull']:>12,}{row['n_negative']:>10,}"
            f"{row['pct_negative']:>9.3%}{row['min']:>16,.0f}"
        )
    if not causes.empty:
        lines.append("")
        lines.append("attribution of affected bank-quarters:")
        for _, row in causes.iterrows():
            lines.append(f"  {row['cause']:<38}{row['n']:>10,}{row['share']:>9.1%}")
        lines.append("")
        lines.append("  (a quarter may carry more than one indicator, so shares can exceed 100%)")
    lines.append("")
    lines.append("Treatment: NaN the artifact. Passing a negative -- or a fabricated zero --")
    lines.append("into a rate calculation propagates silently.")
    return "\n".join(lines)
