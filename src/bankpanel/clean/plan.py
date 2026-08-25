"""Cleaning plans, and the audit trail that makes them defensible.

Cleaning is the step most likely to be questioned and least likely to be documented. A
plan makes it explicit and repeatable: an ordered list of named steps with their
parameters, serialisable to CSV or JSON, and applied to an in-memory frame.

The audit frame is the point of the exercise. Every changed cell is recorded with its
before and after value and the rule responsible, so "we cleaned the data" becomes a claim
somebody else can check, quantify, and disagree with. Steps are not asked to report their
own changes -- the runner diffs the frame around each step, so the audit cannot drift out
of step with what actually happened.

Nothing here ever touches the panel on disk. The built panel is exactly what the configs
produced; cleaning is applied by the consumer, in memory, on purpose.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .denominators import rescale_denominator
from .floors import apply_valued_balance_floor
from .flows import interpolate_negative
from .rates import interpolate_broken_ratio
from .units import fix_unit_errors

AUDIT_COLUMNS = ["RSSD_ID", "REPORTING_PERIOD", "column", "rule", "old", "new"]


def _fix_unit_errors_step(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    out, _ = fix_unit_errors(df, **kwargs)
    return out


#: Steps a plan may name. Each takes a frame and returns one.
STEPS: dict[str, Callable[..., pd.DataFrame]] = {
    "fix_unit_errors": _fix_unit_errors_step,
    "interpolate_negative": interpolate_negative,
    "interpolate_broken_ratio": interpolate_broken_ratio,
    "apply_valued_balance_floor": apply_valued_balance_floor,
    "rescale_denominator": rescale_denominator,
}


class CleaningError(Exception):
    pass


@dataclass
class CleaningPlan:
    """An ordered list of ``(step_name, kwargs)``."""

    steps: list[tuple[str, dict]] = field(default_factory=list)

    def __post_init__(self) -> None:
        unknown = [name for name, _ in self.steps if name not in STEPS]
        if unknown:
            raise CleaningError(
                f"unknown cleaning step(s) {unknown}. Available: {sorted(STEPS)}"
            )

    def add(self, step: str, **kwargs) -> CleaningPlan:
        if step not in STEPS:
            raise CleaningError(f"unknown cleaning step {step!r}. Available: {sorted(STEPS)}")
        self.steps.append((step, kwargs))
        return self

    # --- serialisation ---------------------------------------------------------------

    def to_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(
            json.dumps([{"step": s, "kwargs": k} for s, k in self.steps], indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def from_json(cls, path: str | Path) -> CleaningPlan:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([(entry["step"], entry.get("kwargs", {})) for entry in data])


def _diff(
    before: pd.DataFrame, after: pd.DataFrame, columns: list[str], rule: str,
    id_col: str, date_col: str,
) -> pd.DataFrame:
    """Every cell that changed, as audit rows. NaN-to-NaN is not a change."""
    frames = []
    for column in columns:
        if column not in before.columns or column not in after.columns:
            continue
        old = pd.to_numeric(before[column], errors="coerce")
        new = pd.to_numeric(after[column], errors="coerce")
        changed = ~((old == new) | (old.isna() & new.isna()))
        if not changed.any():
            continue
        frames.append(pd.DataFrame({
            id_col: after.loc[changed, id_col].to_numpy(),
            date_col: after.loc[changed, date_col].to_numpy(),
            "column": column,
            "rule": rule,
            "old": old[changed].to_numpy(),
            "new": new[changed].to_numpy(),
        }))
    if not frames:
        return pd.DataFrame(columns=AUDIT_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def apply_plan(
    df: pd.DataFrame,
    plan: CleaningPlan,
    *,
    id_col: str = "RSSD_ID",
    date_col: str = "REPORTING_PERIOD",
    verbose: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run a plan over a copy of ``df``. Returns ``(cleaned, audit)``.

    The frame is sorted by ``(id, date)`` first: every repair here reads a bank's own
    neighbouring quarters, and an unsorted frame would silently interpolate against the
    wrong rows.
    """
    for required in (id_col, date_col):
        if required not in df.columns:
            raise CleaningError(f"cleaning needs a {required!r} column")

    out = df.sort_values([id_col, date_col]).reset_index(drop=True)
    audits = []

    for name, kwargs in plan.steps:
        before = out.copy()
        try:
            out = STEPS[name](out, **kwargs)
        except Exception as exc:
            raise CleaningError(f"step {name!r} failed: {type(exc).__name__}: {exc}") from exc
        if out is None:
            raise CleaningError(f"step {name!r} returned None; steps must return a frame")

        touched = [c for c in out.columns if c not in (id_col, date_col)]
        changes = _diff(before, out, touched, name, id_col, date_col)
        audits.append(changes)
        if verbose:
            print(f"  {name}: {len(changes):,} cell(s) changed")

    audit = (
        pd.concat(audits, ignore_index=True) if audits
        else pd.DataFrame(columns=AUDIT_COLUMNS)
    )
    return out, audit


def summarize_audit(audit: pd.DataFrame) -> pd.DataFrame:
    """Per (rule, column): how many cells changed, and by how much."""
    if audit.empty:
        return pd.DataFrame(columns=["rule", "column", "n_changed", "n_to_nan", "median_abs_change"])
    work = audit.copy()
    work["to_nan"] = work["new"].isna()
    delta = (work["new"] - work["old"]).abs()
    grouped = work.assign(delta=delta).groupby(["rule", "column"], dropna=False)
    return (
        grouped.agg(
            n_changed=("column", "size"),
            n_to_nan=("to_nan", "sum"),
            median_abs_change=("delta", "median"),
        )
        .reset_index()
        .sort_values("n_changed", ascending=False)
    )


__all__ = [
    "CleaningPlan", "CleaningError", "apply_plan", "summarize_audit", "STEPS",
    "AUDIT_COLUMNS", "np",
]
