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
from ..config.model import BUILTIN_COLUMNS
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
    unverifiable: list[str] = []
    for var in configset.derived:
        if var.variable_name in zero_filled:
            continue
        name = var.variable_name
        inputs = sorted(graph.deps.get(name, ()))
        present = [c for c in inputs if c in df.columns]
        if name not in df.columns or not present:
            continue
        # A withheld ([INTERMEDIATE]) input is not in the panel, so its contribution cannot
        # be seen here. Testing against the inputs that ARE visible would flag every value
        # the withheld one supplied -- the pre-2011 half of a stitch, say -- as fabricated.
        if len(present) < len(inputs):
            unverifiable.append(name)
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
    out = pd.DataFrame(rows).sort_values("n_fabricated", ascending=False) if rows else pd.DataFrame(
        columns=["column", "n_fabricated", "share_of_panel", "all_zero", "formula", "config"]
    )
    out.attrs["unverifiable"] = unverifiable
    return out


def format_fabricated(found: pd.DataFrame) -> str:
    lines = ["", "-" * 78, "FABRICATED VALUES -- derived columns with a value but no inputs", "-" * 78]
    skipped = found.attrs.get("unverifiable", [])
    if skipped:
        lines.append(f"({len(skipped)} column(s) not checked: an input is [INTERMEDIATE], not in the panel)")
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


#: A component is treated as collected in a quarter when at least this share of the banks
#: reporting *any* component of the same sum report it. Deliberately blunt: the question is
#: only "was this line on the form", and an item on the form is answered by most filers.
LIVE_THRESHOLD = 0.5


def find_within_era_zerofill(df: pd.DataFrame, configset, *, id_col: str = "REPORTING_PERIOD"):
    """Sums that zero-fill a component which WAS being collected that quarter.

    Distinct from :func:`find_fabricated_values`, which catches a total built where no
    component exists at all. This catches the subtler and far more common case: inside the
    collection era, one component is blank for one bank, ``fillna(0)`` treats it as zero,
    and the total is quietly understated.

    The distinction that matters is *why* the cell is blank:

    * outside its collection era -- zero-filling is the era stitch working as intended, and
      is how a four-piece stitch is written as a sum in the first place;
    * inside its era -- the bank either had nothing to report or did not report. Those are
      indistinguishable in the data, so the zero is an assumption, not a measurement.

    So liveness is established per quarter from the cross-section rather than from the
    config's declared era: what the panel shows banks actually reporting beats what the
    era bounds claim, and it needs no maintenance as items come and go.

    A blank component is only counted when the zero it produces actually reaches the
    output. Formulas branch: ``na_tot`` is ``reported.fillna(<22-term sum>)``, so the
    sum -- and every ``fillna(0)`` in it -- is evaluated only where the reported code is
    missing, which is 11.5% of rows. Counting components on all of them overstated the
    exposure by 3x. Rather than parse the branch structure, each suspect cell is perturbed
    and the formula re-evaluated: if the output does not move, the zero never mattered on
    that row. That is exact for any formula shape, including ones not yet written.

    Reported, never gated. Blank overwhelmingly does mean zero on a Call Report -- banks
    leave inapplicable lines empty rather than typing 0 -- so failing a build on this would
    fail every build. The point is that the assumption is counted and visible.
    """
    import re

    graph = configset.graph
    period = pd.PeriodIndex(df[id_col], freq="Q")
    rows = []
    for var in configset.derived:
        name = var.variable_name
        # `.fillna(other_column)` is an era coalesce, not a zero-fill; only `.fillna(0)`
        # substitutes a value that was never reported.
        if name not in df.columns or not re.search(r"\.fillna\(\s*0\s*\)", var.formula):
            continue
        inputs = [c for c in sorted(graph.deps.get(name, ())) if c in df.columns]
        if len(inputs) < 2:
            continue
        # Only a name written as `X.fillna(0)` has its blank replaced by a zero. The head
        # of a coalesce -- the `a` in `a.fillna(b)` -- is blank on purpose there: that is
        # the fallback firing, not an assumption, and counting it flagged every era stitch.
        # `X.where(cond).fillna(0)` zero-fills X just as `X.fillna(0)` does -- the where()
        # only narrows which rows X contributes to -- so the name is still a candidate.
        zero_filled = set(re.findall(
            r"(\w+)(?:\.where\([^()]*\))?\s*\.fillna\(\s*0\s*\)", var.formula
        ))
        candidates = [c for c in inputs if c in zero_filled]
        if not candidates:
            continue

        present = df[inputs].notna()
        any_input = present.any(axis=1)
        denominator = any_input.groupby(period).sum().replace(0, np.nan)
        built = df[name].notna().to_numpy()

        namespace = {c: df[c] for c in inputs}
        # Builtins are not dependencies but a formula may read them; without them the
        # re-evaluation raises and every blank is counted as "cannot prove it is inert".
        namespace.update({b: df[b] for b in BUILTIN_COLUMNS if b in df.columns})
        actual = df[name]

        affected = np.zeros(len(df), dtype=bool)
        cells = 0
        worst_name, worst_count = "", 0
        for column in candidates:
            coverage = present[column].groupby(period).sum() / denominator
            live = period.map(coverage >= LIVE_THRESHOLD).to_numpy(dtype=bool)
            zeroed = live & ~present[column].to_numpy() & built
            if not zeroed.any():
                continue
            # Does this blank actually reach the output? Perturb it and re-evaluate: an
            # unchanged result means the term sat in a branch this row never took.
            probe = namespace.copy()
            probe[column] = df[column].mask(zeroed, 1.0)
            try:
                moved = pd.Series(
                    evaluate(var.formula, probe, where=str(var.origin)), index=df.index
                ).ne(actual).to_numpy()
            except FormulaError:
                moved = np.ones(len(df), dtype=bool)  # cannot prove it is inert
            zeroed &= moved
            if not zeroed.any():
                continue
            affected |= zeroed
            cells += int(zeroed.sum())
            if int(zeroed.sum()) > worst_count:
                worst_name, worst_count = column, int(zeroed.sum())
        if worst_count:
            live_rows = int(
                period.map(
                    present[worst_name].groupby(period).sum() / denominator >= LIVE_THRESHOLD
                ).to_numpy(dtype=bool).sum()
            )
            worst_share = worst_count / max(live_rows, 1)
        else:
            worst_share = 0.0

        if affected.any():
            rows.append({
                "column": name,
                "n_inputs": len(inputs),
                "n_rows": int(affected.sum()),
                "share_of_built": round(float(affected.sum() / max(built.sum(), 1)), 4),
                "n_cells": cells,
                "worst_input": worst_name,
                "worst_input_share": round(worst_share, 4),
            })
    columns = ["column", "n_inputs", "n_rows", "share_of_built", "n_cells",
               "worst_input", "worst_input_share"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows).sort_values("n_rows", ascending=False)


def format_within_era_zerofill(found: pd.DataFrame) -> str:
    lines = ["", "-" * 78,
             "ASSUMED ZEROS -- components blank while their line was being collected",
             "-" * 78]
    if found.empty:
        lines.append("none: every zero-filled component was outside its collection era")
        return "\n".join(lines)
    lines.append(f"{len(found)} column(s). Outside its era a blank component is a stitch;")
    lines.append("inside it, the zero is an assumption and the total is understated if wrong.")
    lines.append("")
    lines.append(f"  {'column':<28}{'rows':>10}{'of built':>10}{'cells':>10}  worst component")
    for _, row in found.iterrows():
        lines.append(
            f"  {row['column']:<28}{row.n_rows:>10,}{row.share_of_built:>10.1%}"
            f"{row.n_cells:>10,}  {row.worst_input} ({row.worst_input_share:.1%} of its live rows)"
        )
    return "\n".join(lines)
