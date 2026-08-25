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
