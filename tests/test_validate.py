"""Expectations matrix and the three validators."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bankpanel.io.reader import read_panel
from bankpanel.reference.expectations import (
    build_expectations,
    expected_mask,
)
from bankpanel.validate.approvals import load_ledger, partition
from bankpanel.validate.breaks import check_latest_quarter
from bankpanel.validate.coverage import find_discontinuities
from bankpanel.validate.quarterize_audit import attribute, audit

COLUMNS = ["assets_total", "loans_3mo", "semiannual_item", "late_item", "int_inc_total"]


@pytest.fixture(scope="module")
def panel(synth_panel):
    return read_panel(columns=COLUMNS, root=synth_panel, verify=False)


@pytest.fixture(scope="module")
def expectations(panel):
    return build_expectations(panel, COLUMNS)


# --- expectations ------------------------------------------------------------------


def test_detects_the_semiannual_pattern(expectations):
    """The fixture's short-form filers report semiannual_item only in Q2 and Q4."""
    rule = expectations[
        (expectations.column == "semiannual_item") & (expectations.form_type == 51)
    ]
    assert "semiannual_q2q4" in set(rule.frequency)


def test_quarterly_items_are_labelled_quarterly(expectations):
    rule = expectations[
        (expectations.column == "assets_total") & (expectations.form_type == 41)
    ]
    assert set(rule.frequency) == {"quarterly"}


def test_absent_era_before_introduction(expectations):
    """late_item does not exist before the fixture's provider change."""
    rules = expectations[
        (expectations.column == "late_item") & (expectations.form_type == 41)
    ]
    absent = rules[rules.frequency == "absent"]
    assert not absent.empty
    assert absent.era_end.min() < pd.Timestamp("2011-01-01")


def test_expected_mask_marks_uncollected_quarters(panel, expectations):
    mask = expected_mask(panel, "semiannual_item", expectations)
    modern_51 = (panel.REPORTING_PERIOD >= "2011-01-01") & (panel.form_type == 51)
    q1 = modern_51 & (panel.REPORTING_PERIOD.dt.quarter == 1)
    q2 = modern_51 & (panel.REPORTING_PERIOD.dt.quarter == 2)
    assert not mask[q1].any()
    assert mask[q2].all()


def test_unmeasured_column_defaults_to_expected(panel, expectations):
    """A column with no rule must never be silently excused from checking."""
    assert expected_mask(panel, "not_a_column", expectations).all()


# --- coverage: the headline regression ---------------------------------------------


def test_semiannual_reporting_is_not_flagged_when_expectation_aware(panel, expectations):
    """THE regression test for this release.

    A short-form item collected only in Q2 and Q4 swings by ~100 percentage points every
    quarter. Under a naive denominator that is a finding every single quarter, forever --
    which does not merely add noise, it saturates the checker so real breaks cannot be
    seen. Expectation-aware, it is not a finding at all.
    """
    naive = find_discontinuities(panel, COLUMNS, expectations=None)
    aware = find_discontinuities(panel, COLUMNS, expectations=expectations)

    naive_hits = naive[naive.column == "semiannual_item"] if not naive.empty else naive
    aware_hits = aware[aware.column == "semiannual_item"] if not aware.empty else aware

    assert len(naive_hits) > 0, "the naive control should flag the semiannual pattern"
    assert len(aware_hits) == 0, "expectation-aware scan must not flag it"


def test_a_real_break_is_still_caught(panel, expectations):
    """Suppressing the 051 artifact must not suppress genuine breaks."""
    broken = panel.copy()
    hit = broken.REPORTING_PERIOD >= "2012-01-01"
    broken.loc[hit, "assets_total"] = np.nan
    findings = find_discontinuities(broken, COLUMNS, expectations=expectations)
    assert (findings.column == "assets_total").any()


def test_long_gap_between_collection_events_is_not_a_break(panel, expectations):
    """Two collection events years apart describe an era boundary, not a discontinuity."""
    findings = find_discontinuities(panel, COLUMNS, expectations=expectations)
    if findings.empty:
        return
    spans = (
        pd.PeriodIndex(findings.to_date, freq="Q") - pd.PeriodIndex(findings.from_date, freq="Q")
    ).map(lambda x: x.n)
    assert spans.max() <= 4


# --- approvals ----------------------------------------------------------------------


def test_ledger_suppresses_a_known_finding(tmp_path):
    findings = pd.DataFrame([{
        "panel": "p", "column": "x",
        "from_date": pd.Timestamp("2011-03-31"), "to_date": pd.Timestamp("2011-06-30"),
    }])
    path = tmp_path / "ledger.csv"
    load_ledger(path)  # auto-creates
    pd.DataFrame([{
        "panel": "p", "column": "x", "from_date": "2011-03-31", "to_date": "2011-06-30",
        "reason": "known MDRM retirement", "approved_by": "tester", "approved_at": "2026-01-01",
    }]).to_csv(path, index=False)

    new, approved = partition(findings, load_ledger(path))
    assert len(new) == 0 and len(approved) == 1


def test_ledger_does_not_absolve_a_different_quarter(tmp_path):
    """Matching is on all four keys, so one approval cannot cover a later break."""
    findings = pd.DataFrame([{
        "panel": "p", "column": "x",
        "from_date": pd.Timestamp("2015-03-31"), "to_date": pd.Timestamp("2015-06-30"),
    }])
    path = tmp_path / "ledger.csv"
    pd.DataFrame([{
        "panel": "p", "column": "x", "from_date": "2011-03-31", "to_date": "2011-06-30",
        "reason": "different event", "approved_by": "tester", "approved_at": "2026-01-01",
    }]).to_csv(path, index=False)
    new, approved = partition(findings, load_ledger(path))
    assert len(new) == 1 and len(approved) == 0


# --- breaks -------------------------------------------------------------------------


def test_seasonal_item_does_not_trip_the_latest_quarter_gate(panel):
    """Year-over-year same-quarter comparison is what makes seasonality safe."""
    findings = check_latest_quarter(panel, COLUMNS)
    assert "semiannual_item" not in set(findings.column if not findings.empty else [])


def test_coverage_collapse_in_the_newest_quarter_is_critical(panel):
    broken = panel.copy()
    latest = broken.REPORTING_PERIOD.max()
    broken.loc[broken.REPORTING_PERIOD == latest, "assets_total"] = np.nan
    findings = check_latest_quarter(broken, COLUMNS)
    hit = findings[(findings.column == "assets_total") & (findings.test == "coverage_collapse")]
    assert len(hit) == 1 and hit.iloc[0].severity == "CRITICAL"


# --- quarterize audit ---------------------------------------------------------------


def test_audit_counts_impossible_negatives(panel):
    broken = panel.copy()
    broken.loc[broken.index[:5], "int_inc_total"] = -100.0
    summary, flagged = audit(broken, ["int_inc_total"])
    assert int(summary.iloc[0].n_negative) == 5
    assert len(flagged) == 5


def test_audit_ignores_columns_not_declared_nonneg(panel):
    broken = panel.copy()
    broken.loc[broken.index[:5], "assets_total"] = -100.0
    summary, flagged = audit(broken, ["int_inc_total"])
    assert flagged.empty


def test_attribution_reports_unexplained_share(panel):
    broken = panel.copy()
    broken["flag_combo"] = 0.0
    broken.loc[broken.index[:4], "int_inc_total"] = -100.0
    broken.loc[broken.index[:1], "flag_combo"] = 1.0
    _, flagged = audit(broken, ["int_inc_total"], flag_columns=["flag_combo"])
    causes = attribute(flagged, ["flag_combo"])
    assert float(causes[causes.cause == "flag_combo"].iloc[0].share) == pytest.approx(0.25)
    assert float(causes[causes.cause == "unexplained"].iloc[0].share) == pytest.approx(0.75)
