"""Declarative data-quality checks."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bankpanel.config import ConfigError, ConfigSet, Origin
from bankpanel.config.model import Check
from bankpanel.validate.quality import failing_rows, gate, run_check, run_checks

BASE = """[BASE_VARIABLES]
mdrm_code,variable_name,schedule,flow_type
RCFD2170,assets,RC,stock
RCFD2122,loans,RC,stock

[DERIVED_VARIABLES]
variable_name,schedule,flow_type,description,formula
"""


def check(expression, name="c", severity="error"):
    return Check(
        name=name, expression=expression, severity=severity,
        description="test", origin=Origin(__import__("pathlib").Path("t.csv"), 1),
    )


FRAME = pd.DataFrame({
    "RSSD_ID": [1, 2, 3, 4],
    "REPORTING_PERIOD": [pd.Timestamp("2020-03-31")] * 4,
    "assets": [100.0, 200.0, 300.0, np.nan],
    "loans": [50.0, 250.0, 100.0, 10.0],
})


def test_passing_check():
    result = run_check(FRAME, check("assets >= 0"))
    assert result["status"] == "pass" and result["n_failed"] == 0


def test_failing_check_counts_rows():
    result = run_check(FRAME, check("loans <= assets"))
    assert result["status"] == "fail"
    assert result["n_failed"] == 1          # bank 2 only
    assert result["n_applicable"] == 3      # bank 4 has no assets, so is out of scope


def test_rows_with_a_missing_input_are_out_of_scope_not_failures():
    """Sparsity is not a quality failure.

    Most of a Call Report panel is legitimately empty; conflating "not reported" with
    "impossible" would make every check fail almost everywhere.
    """
    result = run_check(FRAME, check("assets >= 0"))
    assert result["n_applicable"] == 3


def test_check_on_a_missing_column_is_skipped_not_failed():
    result = run_check(FRAME, check("not_a_column >= 0"))
    assert result["status"] == "skipped" and "not in panel" in result["detail"]


def test_malformed_expression_is_reported_as_invalid():
    result = run_check(FRAME, check("assets >= "))
    assert result["status"] == "invalid"


def test_expression_must_pass_the_ast_gate():
    result = run_check(FRAME, check("assets.to_csv('x')"))
    assert result["status"] == "invalid"


def test_failing_rows_are_recoverable_for_diagnosis():
    rows = failing_rows(FRAME, check("loans <= assets"))
    assert len(rows) == 1
    assert rows.iloc[0].RSSD_ID == 2
    assert {"assets", "loans"} <= set(rows.columns)


def test_gate_fires_only_on_error_severity():
    failing = run_checks(FRAME, [check("loans <= assets", severity="warning")])
    assert gate(failing) == 0
    failing = run_checks(FRAME, [check("loans <= assets", severity="error")])
    assert gate(failing) == 1


def test_gate_fires_on_an_invalid_error_check():
    """A check that cannot be evaluated is not quietly a pass."""
    assert gate(run_checks(FRAME, [check("assets >= ", severity="error")])) == 1


# --- config integration ---------------------------------------------------------------


def test_checks_parse_from_config(write_config):
    text = BASE + """
[CHECKS]
name,expression,severity,description
loans_le_assets,loans <= assets,error,Loans are a component of assets
"""
    cs = ConfigSet.load(write_config(text))
    assert len(cs.checks) == 1
    assert cs.checks[0].name == "loans_le_assets"


def test_check_referencing_an_unknown_variable_is_a_lint_error(write_config):
    text = BASE + """
[CHECKS]
name,expression,severity,description
bad,loans <= nonexistent,error,references nothing
"""
    with pytest.raises(ConfigError, match="unknown variable"):
        ConfigSet.load(write_config(text)).lint()


def test_duplicate_check_names_rejected(write_config):
    text = BASE + """
[CHECKS]
name,expression,severity,description
dup,loans <= assets,error,first
dup,assets >= 0,error,second
"""
    with pytest.raises(ConfigError, match="already used"):
        ConfigSet.load(write_config(text)).lint()


def test_bad_severity_rejected(write_config):
    text = BASE + """
[CHECKS]
name,expression,severity,description
c,assets >= 0,catastrophic,bad severity
"""
    with pytest.raises(ConfigError, match="severity"):
        ConfigSet.load(write_config(text))


def test_undescribed_check_warns(write_config):
    text = BASE + """
[CHECKS]
name,expression,severity,description
c,assets >= 0,warning,
"""
    issues = ConfigSet.load(write_config(text)).lint()
    assert any("no description" in i.message for i in issues)


# --- assumed zeros: blank while the line was being collected ---------------------------

ERA_SUM = """[BASE_VARIABLES]
mdrm_code,variable_name,schedule,flow_type
RCFD1000,old_code,RC,stock
RCFD2000,new_code,RC,stock
RCFD3000,partner,RC,stock

[DERIVED_VARIABLES]
variable_name,schedule,flow_type,description,formula
total,RC,stock,Stitched total,old_code.fillna(0) + new_code.fillna(0) + partner.fillna(0)
"""


def _frame(periods, old, new, partner):
    return pd.DataFrame({
        "REPORTING_PERIOD": pd.to_datetime(periods),
        "old_code": old, "new_code": new, "partner": partner,
        "total": [1.0] * len(old),
    })


def test_era_pieces_are_not_assumed_zeros(write_config):
    """A component outside its era is a stitch, not an assumption."""
    from bankpanel.config import ConfigSet
    from bankpanel.validate.quality import find_within_era_zerofill

    cs = ConfigSet.load(write_config(ERA_SUM))
    # old_code lives only in 2000, new_code only in 2001; never both.
    df = _frame(
        ["2000-03-31"] * 4 + ["2001-03-31"] * 4,
        [1.0, 2.0, 3.0, 4.0] + [None] * 4,
        [None] * 4 + [1.0, 2.0, 3.0, 4.0],
        [1.0] * 8,
    )
    assert find_within_era_zerofill(df, cs).empty


def test_blank_while_live_is_flagged(write_config):
    """A component most banks report, blank for one, is an assumed zero."""
    from bankpanel.config import ConfigSet
    from bankpanel.validate.quality import find_within_era_zerofill

    cs = ConfigSet.load(write_config(ERA_SUM))
    df = _frame(
        ["2000-03-31"] * 4,
        [1.0, 2.0, 3.0, 4.0],
        [1.0, 2.0, None, 4.0],   # reported by 3 of 4 -> live, and blank for one
        [1.0] * 4,
    )
    found = find_within_era_zerofill(df, cs)
    assert len(found) == 1
    assert found.iloc[0]["n_rows"] == 1
    assert found.iloc[0]["worst_input"] == "new_code"


def test_coalesce_is_not_a_zero_fill(write_config):
    """`.fillna(other)` chooses between eras; only `.fillna(0)` invents a value."""
    from bankpanel.config import ConfigSet
    from bankpanel.validate.quality import find_within_era_zerofill

    text = ERA_SUM.replace(
        "old_code.fillna(0) + new_code.fillna(0) + partner.fillna(0)",
        "old_code.fillna(new_code).fillna(partner)",
    )
    cs = ConfigSet.load(write_config(text))
    df = _frame(["2000-03-31"] * 4, [1.0, 2.0, None, 4.0], [1.0] * 4, [1.0] * 4)
    assert find_within_era_zerofill(df, cs).empty


def test_dead_branch_zerofill_is_not_counted(write_config):
    """A fillna(0) inside a branch the row never takes did not affect the output.

    pdl_tot_non is `reported.fillna(<22-term sum>)`: on the 88.5% of rows carrying the
    reported code, the sum is never evaluated. Counting its blanks there overstated the
    exposure threefold.
    """
    from bankpanel.config import ConfigSet
    from bankpanel.validate.quality import find_within_era_zerofill

    text = ERA_SUM.replace(
        "total,RC,stock,Stitched total,old_code.fillna(0) + new_code.fillna(0) + partner.fillna(0)",
        "total,RC,stock,Reported else rebuilt,old_code.fillna(new_code.fillna(0) + partner.fillna(0))",
    )
    cs = ConfigSet.load(write_config(text))
    df = _frame(
        ["2000-03-31"] * 4,
        [9.0, 9.0, 9.0, None],       # reported on 3 of 4 rows
        [1.0, 1.0, None, 1.0],       # live, blank on row 2 -- but row 2 has old_code
        [1.0] * 4,
    )
    df["total"] = [9.0, 9.0, 9.0, 2.0]
    # The only blank sits on a row that took the reported branch, so nothing is assumed.
    assert find_within_era_zerofill(df, cs).empty
