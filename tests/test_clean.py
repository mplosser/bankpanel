"""The opt-in cleaning layer, and its separation from the builder."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bankpanel.clean import (
    CleaningError,
    CleaningPlan,
    apply_plan,
    fix_unit_errors,
    interpolate_negative,
    repair_local_events,
    summarize_audit,
)
from bankpanel.clean.floors import apply_valued_balance_floor


def frame(rows, column="value"):
    return pd.DataFrame([
        {
            "RSSD_ID": bank,
            "REPORTING_PERIOD": pd.Period(period, freq="Q").end_time.normalize(),
            column: value,
        }
        for bank, period, value in rows
    ])


# --- unit errors ---------------------------------------------------------------------


def test_detects_and_corrects_a_1000x_segment():
    rows = [(1, f"20{y:02d}Q1", v) for y, v in zip(range(10, 14), [290_000.0] * 4, strict=True)]
    rows += [(1, f"20{y:02d}Q1", 294.0) for y in range(14, 18)]
    out, log = fix_unit_errors(frame(rows), ["value"])
    fixed = out.sort_values("REPORTING_PERIOD").value.tolist()
    assert fixed[:4] == [290.0] * 4
    assert fixed[4:] == [294.0] * 4
    assert len(log) == 4 and set(log.action) == {"corrected"}


def test_ordinary_growth_is_not_a_unit_error():
    """A series that merely grew has no two-level structure and must be left alone."""
    rows = [(1, f"20{y:02d}Q1", float(v)) for y, v in zip(range(10, 18), range(100, 900, 100), strict=True)]
    out, log = fix_unit_errors(frame(rows), ["value"])
    assert log.empty
    pd.testing.assert_frame_equal(out, frame(rows))


def test_exclusion_suppresses_a_correction():
    rows = [(1, f"20{y:02d}Q1", 290_000.0) for y in range(10, 14)]
    rows += [(1, f"20{y:02d}Q1", 294.0) for y in range(14, 18)]
    exclude = pd.DataFrame([{"id": 1, "column": "value"}])
    out, log = fix_unit_errors(frame(rows), ["value"], exclude=exclude)
    assert out.sort_values("REPORTING_PERIOD").value.tolist()[0] == 290_000.0
    assert set(log.action) == {"suppressed"}


# --- negative flows ------------------------------------------------------------------


def test_interpolates_an_impossible_negative():
    df = frame([(1, "2020Q1", 100.0), (1, "2020Q2", -50.0), (1, "2020Q3", 300.0)])
    out = interpolate_negative(df.copy(), "value")
    assert out.sort_values("REPORTING_PERIOD").value.tolist() == [100.0, 200.0, 300.0]


def test_positive_values_are_untouched():
    df = frame([(1, "2020Q1", 100.0), (1, "2020Q2", 150.0)])
    out = interpolate_negative(df.copy(), "value")
    assert out.value.tolist() == [100.0, 150.0]


# --- local-event repair --------------------------------------------------------------


def test_repairs_both_legs_of_a_sum_preserving_pair():
    """A year-to-date reset moves income between quarters, so the artifact is a PAIR.

    Repairing only the negative leg would leave the inflated twin standing -- and worse,
    let the repaired value interpolate from it.
    """
    values = [5.0, 5.0, -20.0, 30.0, 5.0, 5.0]
    df = frame([(1, f"2020Q{q}", v) for q, v in zip([1, 2, 3, 4], values[:4], strict=True)]
               + [(1, f"2021Q{q}", v) for q, v in zip([1, 2], values[4:], strict=True)])
    repaired, mask = repair_local_events(df.value, df.REPORTING_PERIOD, df.RSSD_ID)
    assert mask.iloc[2], "the negative leg must be flagged"
    assert mask.iloc[3], "its inflated twin must be flagged too"
    assert repaired.iloc[2] >= 0


def test_a_genuine_level_shift_is_not_repaired():
    """Detection is by local discontinuity, so a sustained move never triggers."""
    df = frame([(1, f"2020Q{q}", 5.0) for q in (1, 2, 3, 4)]
               + [(1, f"2021Q{q}", 50.0) for q in (1, 2, 3, 4)])
    repaired, mask = repair_local_events(df.value, df.REPORTING_PERIOD, df.RSSD_ID)
    assert not mask.iloc[-1] and not mask.iloc[-2]


def test_nan_input_never_becomes_a_value():
    df = frame([(1, "2020Q1", 5.0), (1, "2020Q2", np.nan), (1, "2020Q3", 5.0)])
    repaired, _ = repair_local_events(df.value, df.REPORTING_PERIOD, df.RSSD_ID)
    assert np.isnan(repaired.iloc[1])


# --- floors --------------------------------------------------------------------------


def test_valued_balance_floor_three_way():
    df = pd.DataFrame({
        "RSSD_ID": [1, 2, 3, 4],
        "REPORTING_PERIOD": [pd.Timestamp("2020-03-31")] * 4,
        "rate": [4.0, 99.0, 5.0, 6.0],
        "balance": [0.0, 10.0, 5000.0, 9000.0],
    })
    out = apply_valued_balance_floor(df.copy(), rate_col="rate", balance_col="balance")
    assert np.isnan(out.rate.iloc[0])          # nothing to value
    assert out.rate.iloc[1] == pytest.approx(5.5)   # immaterial -> per-date median
    assert out.rate.iloc[2] == 5.0 and out.rate.iloc[3] == 6.0  # real balances untouched


# --- plans and the audit trail --------------------------------------------------------


def test_plan_records_every_changed_cell():
    df = frame([(1, "2020Q1", 100.0), (1, "2020Q2", -50.0), (1, "2020Q3", 300.0)])
    plan = CleaningPlan().add("interpolate_negative", column="value")
    cleaned, audit = apply_plan(df, plan)
    assert len(audit) == 1
    row = audit.iloc[0]
    assert row.old == -50.0 and row.new == 200.0 and row.rule == "interpolate_negative"
    assert list(audit.columns[:4]) == ["RSSD_ID", "REPORTING_PERIOD", "column", "rule"]


def test_plan_leaves_the_input_frame_alone():
    df = frame([(1, "2020Q1", -5.0), (1, "2020Q2", 5.0)])
    before = df.copy()
    apply_plan(df, CleaningPlan().add("interpolate_negative", column="value"))
    pd.testing.assert_frame_equal(df, before)


def test_unknown_step_is_rejected():
    with pytest.raises(CleaningError, match="unknown cleaning step"):
        CleaningPlan([("scrub_it", {})])


def test_failing_step_names_itself():
    plan = CleaningPlan().add("interpolate_negative", column="not_a_column")
    with pytest.raises(CleaningError, match="interpolate_negative"):
        apply_plan(frame([(1, "2020Q1", 1.0)]), plan)


def test_plan_round_trips_through_json(tmp_path):
    plan = CleaningPlan().add("interpolate_negative", column="value")
    restored = CleaningPlan.from_json(plan.to_json(tmp_path / "plan.json"))
    assert restored.steps == plan.steps


def test_audit_summary_counts_by_rule_and_column():
    df = frame([(1, "2020Q1", 10.0), (1, "2020Q2", -5.0), (1, "2020Q3", 30.0)])
    _, audit = apply_plan(df, CleaningPlan().add("interpolate_negative", column="value"))
    summary = summarize_audit(audit)
    assert summary.iloc[0].n_changed == 1 and summary.iloc[0].column == "value"


# --- the boundary --------------------------------------------------------------------


def test_builder_and_reader_never_import_the_cleaning_layer():
    """The panel on disk must be exactly what the configs produced.

    Enforced structurally rather than by convention: if `build` or `io` could import
    `clean`, a future edit could quietly make cleaning part of the build.
    """
    root = Path(__file__).resolve().parents[1] / "src" / "bankpanel"
    offenders = []
    for package in ("build", "io"):
        for path in (root / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and "clean" in node.module:
                    offenders.append(f"{path.name}: {node.module}")
                if isinstance(node, ast.Import):
                    offenders += [
                        f"{path.name}: {a.name}" for a in node.names if "clean" in a.name
                    ]
    assert not offenders, f"cleaning must stay out of the build path: {offenders}"
