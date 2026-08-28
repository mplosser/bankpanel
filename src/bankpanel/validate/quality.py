"""Data-quality measures: assertions about VALUES, not about reporting.

The other three validators ask whether an item was reported as expected. This one asks
whether what was reported can be true. They catch different failures:

* a coverage break says a column stopped being filled in;
* a quality failure says the column is filled in with something impossible -- a capital
  ratio above 1, a component larger than its total, a balance sheet that does not foot.

Checks are declared in config as boolean expressions in the same language as derived
formulas, so bounds, orderings and accounting identities are all the same kind of object
and all pass through the same AST gate.

**Applicability is separate from failure.** A check is evaluated only on rows where every
input is present; a row missing an input is not a failure, it is out of scope. Conflating
the two would make every check fail wherever the data is simply sparse, which is most of
a Call Report panel.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Check
from ..expr import FormulaError, dependencies, evaluate


def run_check(df: pd.DataFrame, check: Check) -> dict:
    """Evaluate one check. Returns a summary row."""
    where = str(check.origin)
    try:
        deps = sorted(dependencies(check.expression, where=where))
    except FormulaError as exc:
        return {
            "name": check.name, "severity": check.severity, "status": "invalid",
            "detail": str(exc).splitlines()[0], "n_applicable": 0, "n_failed": 0,
            "fail_rate": np.nan, "description": check.description,
        }

    missing = [d for d in deps if d not in df.columns]
    if missing:
        return {
            "name": check.name, "severity": check.severity, "status": "skipped",
            "detail": f"column(s) not in panel: {missing}", "n_applicable": 0,
            "n_failed": 0, "fail_rate": np.nan, "description": check.description,
        }

    # Out of scope wherever any input is missing -- sparsity is not a quality failure.
    applicable = pd.Series(True, index=df.index)
    for dep in deps:
        applicable &= df[dep].notna()

    if not applicable.any():
        return {
            "name": check.name, "severity": check.severity, "status": "no_data",
            "detail": "no row has every input present", "n_applicable": 0, "n_failed": 0,
            "fail_rate": np.nan, "description": check.description,
        }

    namespace = {dep: df.loc[applicable, dep] for dep in deps}
    try:
        result = evaluate(check.expression, namespace, where=where)
    except FormulaError as exc:
        return {
            "name": check.name, "severity": check.severity, "status": "invalid",
            "detail": str(exc).splitlines()[0], "n_applicable": int(applicable.sum()),
            "n_failed": 0, "fail_rate": np.nan, "description": check.description,
        }

    holds = pd.Series(result, index=df.index[applicable]).fillna(False).astype(bool)
    n_applicable = int(len(holds))
    n_failed = int((~holds).sum())
    return {
        "name": check.name,
        "severity": check.severity,
        "status": "fail" if n_failed else "pass",
        "detail": "",
        "n_applicable": n_applicable,
        "n_failed": n_failed,
        "fail_rate": n_failed / n_applicable if n_applicable else np.nan,
        "description": check.description,
    }


def failing_rows(
    df: pd.DataFrame, check: Check, *, id_col: str = "RSSD_ID",
    date_col: str = "REPORTING_PERIOD", limit: int | None = 500,
) -> pd.DataFrame:
    """The individual rows a check fails on, for diagnosis."""
    deps = sorted(dependencies(check.expression, where=str(check.origin)))
    if any(d not in df.columns for d in deps):
        return pd.DataFrame()
    applicable = pd.Series(True, index=df.index)
    for dep in deps:
        applicable &= df[dep].notna()
    if not applicable.any():
        return pd.DataFrame()
    namespace = {dep: df.loc[applicable, dep] for dep in deps}
    holds = pd.Series(
        evaluate(check.expression, namespace, where=str(check.origin)),
        index=df.index[applicable],
    ).fillna(False).astype(bool)
    bad = holds.index[~holds]
    keep = [c for c in (id_col, date_col, *deps) if c in df.columns]
    out = df.loc[bad, keep].copy()
    out.insert(0, "check", check.name)
    return out.head(limit) if limit else out


def run_checks(df: pd.DataFrame, checks: list[Check]) -> pd.DataFrame:
    """Evaluate every check. Returns one row per check."""
    if not checks:
        return pd.DataFrame(columns=[
            "name", "severity", "status", "detail", "n_applicable", "n_failed",
            "fail_rate", "description",
        ])
    return pd.DataFrame([run_check(df, c) for c in checks])


def find_fabricated_values(df: pd.DataFrame, configset) -> pd.DataFrame:
    """Derived columns that carry a value where NONE of their inputs do.

    A structural check rather than a declared one, because it applies to every derived
    column and needs no author to think of it.

    The failure it catches is easy to write and hard to see. A ``.fillna(0)`` chain is the
    right way to tolerate one missing component inside an era -- but across an era
    boundary, where every component is absent, it turns "not collected" into a confident
    zero. Two series here did exactly that, one of them for 568,102 rows, and both looked
    perfectly healthy on a coverage report: fabricated zeros IMPROVE coverage.

    The fix is a ``.where(a.notna() | b.notna() | ...)`` guard, not removing the fillna.
    """
    # A column with an explicit [ZERO_FILL] rule is excluded: filling it is a recorded
    # human decision with a written reason, not an accident of a formula.
    zero_filled = {rule.column for rule in configset.zero_fill}
    graph = configset.graph
    rows = []
    for var in configset.derived:
        if var.variable_name in zero_filled:
            continue
        name = var.variable_name
        inputs = sorted(graph.deps.get(name, ()))
        present = [c for c in inputs if c in df.columns]
        if name not in df.columns or not present:
            continue
        any_input = df[present].notna().any(axis=1)
        fabricated = int((df[name].notna() & ~any_input).sum())
        if fabricated:
            values = df.loc[df[name].notna() & ~any_input, name]
            rows.append({
                "column": name,
                "n_fabricated": fabricated,
                "share_of_panel": round(fabricated / len(df), 4),
                "all_zero": bool((values == 0).all()),
                "formula": var.formula[:90],
                "config": var.origin.path.name,
            })
    return pd.DataFrame(rows).sort_values("n_fabricated", ascending=False) if rows else pd.DataFrame(
        columns=["column", "n_fabricated", "share_of_panel", "all_zero", "formula", "config"]
    )


def format_fabricated(found: pd.DataFrame) -> str:
    lines = ["", "-" * 78, "FABRICATED VALUES -- derived columns with a value but no inputs", "-" * 78]
    if found.empty:
        lines.append("none: every derived value rests on at least one reported input")
        return "\n".join(lines)
    lines.append(f"{len(found)} column(s). A fillna(0) chain across an era boundary turns")
    lines.append('"not collected" into a confident zero, and RAISES coverage while doing it.')
    lines.append("")
    for _, row in found.iterrows():
        lines.append(
            f"  {row['column']:<32}{row.n_fabricated:>10,} rows "
            f"({row.share_of_panel:.1%})  all_zero={row.all_zero}"
        )
        lines.append(f"      {row.formula}")
    return "\n".join(lines)


def format_report(results: pd.DataFrame, *, limit: int = 40) -> str:
    lines = ["=" * 78, "DATA QUALITY", "=" * 78]
    if results.empty:
        lines.append("no checks declared. Add a [CHECKS] section to a config.")
        return "\n".join(lines)

    counts = results.status.value_counts().to_dict()
    lines.append(
        f"{len(results)} check(s): "
        + ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
    )
    lines.append("")
    lines.append(f"{'check':<34}{'sev':>8}{'status':>9}{'applicable':>12}{'failed':>9}{'rate':>9}")
    ordered = results.sort_values(
        ["status", "fail_rate"], ascending=[True, False], na_position="last"
    )
    for _, row in ordered.head(limit).iterrows():
        rate = "" if pd.isna(row.fail_rate) else f"{row.fail_rate:.3%}"
        lines.append(
            f"{row['name'][:33]:<34}{row.severity:>8}{row.status:>9}"
            f"{row.n_applicable:>12,}{row.n_failed:>9,}{rate:>9}"
        )
    problems = results[results.status.isin({"fail", "invalid"})]
    if not problems.empty:
        lines.append("")
        for _, row in problems.iterrows():
            note = row.detail or row.description
            lines.append(f"  {row['name']}: {note}")
    return "\n".join(lines)


def gate(results: pd.DataFrame) -> int:
    """Exit code: non-zero if any error-severity check failed or is invalid."""
    if results.empty:
        return 0
    bad = results[(results.severity == "error") & results.status.isin({"fail", "invalid"})]
    return 1 if len(bad) else 0
