"""Year-to-date to quarterly conversion, including the two bugs this version fixes."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bankpanel.build.quarterize import QuarterizeError, quarterize


def _frame(rows):
    return pd.DataFrame([
        {
            "RSSD_ID": bank,
            "REPORTING_PERIOD": pd.Period(period, freq="Q").end_time.normalize(),
            "ytd": value,
        }
        for bank, period, value in rows
    ])


CLEAN = [(1, "2020Q1", 10.0), (1, "2020Q2", 25.0), (1, "2020Q3", 45.0), (1, "2020Q4", 70.0)]
GAP = [(2, "2020Q1", 10.0), (2, "2020Q3", 45.0), (2, "2020Q4", 70.0)]
LATE = [(3, "2020Q3", 45.0), (3, "2020Q4", 70.0)]


def _values(df, bank):
    sub = df[df.RSSD_ID == bank].sort_values("REPORTING_PERIOD")
    return sub.q.tolist()


def test_year_to_date_column_is_kept_as_filed():
    out, _ = quarterize(_frame(GAP), {"ytd": "q"}, policy="nan")
    sub = out[out.RSSD_ID == 2].sort_values("REPORTING_PERIOD")
    assert sub.ytd.tolist() == [10.0, 45.0, 70.0]
    assert list(out.columns) == ["RSSD_ID", "REPORTING_PERIOD", "ytd", "q"]


def test_blank_prior_quarter_leaves_flow_nan_and_total_in_place():
    """An annual filer: the Q4 year-to-date is the year's total, not a Q4 flow."""
    rows = [(4, "2020Q1", np.nan), (4, "2020Q2", np.nan), (4, "2020Q3", np.nan), (4, "2020Q4", 70.0)]
    out, _ = quarterize(_frame(rows), {"ytd": "q"}, policy="nan")
    sub = out[out.RSSD_ID == 4].sort_values("REPORTING_PERIOD")
    assert sub.ytd.tolist()[-1] == 70.0
    assert sub.q.isna().all()


@pytest.mark.parametrize("policy", ["nan", "spread", "keep"])
def test_clean_year_differences_correctly(policy):
    out, _ = quarterize(_frame(CLEAN), {"ytd": "q"}, policy=policy)
    assert _values(out, 1) == [10.0, 15.0, 20.0, 25.0]


def test_q1_passes_through():
    out, _ = quarterize(_frame(CLEAN), {"ytd": "q"}, policy="nan")
    assert _values(out, 1)[0] == 10.0


def test_gap_is_nan_by_default():
    """Legacy would have booked (45 - 10) = 35 as a single quarter's flow."""
    out, _ = quarterize(_frame(GAP), {"ytd": "q"}, policy="nan")
    assert np.isnan(_values(out, 2)[1])


def test_gap_spread_divides_by_span():
    out, _ = quarterize(_frame(GAP), {"ytd": "q"}, policy="spread")
    assert _values(out, 2)[1] == pytest.approx(17.5)


def test_gap_keep_reproduces_the_legacy_double_count():
    out, _ = quarterize(_frame(GAP), {"ytd": "q"}, policy="keep")
    assert _values(out, 2)[1] == 35.0


def test_partial_year_start_is_nan_by_default():
    """A bank whose first filing of the year is Q3 has no computable Q3 flow."""
    out, _ = quarterize(_frame(LATE), {"ytd": "q"}, policy="nan")
    assert np.isnan(_values(out, 3)[0])


def test_partial_year_start_keep_reproduces_ytd_as_flow():
    out, _ = quarterize(_frame(LATE), {"ytd": "q"}, policy="keep")
    assert _values(out, 3)[0] == 45.0


def test_gaps_are_reported_not_absorbed():
    _, report = quarterize(_frame(GAP + LATE), {"ytd": "q"}, policy="nan")
    assert set(report.kind) == {"gap", "partial_year_start"}


def test_year_boundary_never_differenced():
    """The annual reset means Q1 must never be differenced against the prior Q4."""
    rows = CLEAN + [(1, "2021Q1", 12.0), (1, "2021Q2", 26.0)]
    out, _ = quarterize(_frame(rows), {"ytd": "q"}, policy="nan")
    assert _values(out, 1)[4] == 12.0


def test_year_partition_independence():
    """The load-bearing claim of the architecture: quarterizing per year partition gives
    exactly the same answer as quarterizing the whole panel at once."""
    rows = CLEAN + [(1, "2021Q1", 12.0), (1, "2021Q2", 26.0), (1, "2021Q3", 40.0)] + GAP
    whole, _ = quarterize(_frame(rows), {"ytd": "q"}, policy="nan")

    df = _frame(rows)
    parts = [
        quarterize(part, {"ytd": "q"}, policy="nan")[0]
        for _, part in df.groupby(df.REPORTING_PERIOD.dt.year)
    ]
    per_year = pd.concat(parts, ignore_index=True).sort_values(
        ["RSSD_ID", "REPORTING_PERIOD"]
    ).reset_index(drop=True)

    pd.testing.assert_frame_equal(whole, per_year)


def test_non_ytd_columns_untouched():
    df = _frame(CLEAN)
    df["stock"] = [1.0, 2.0, 3.0, 4.0]
    out, _ = quarterize(df, {"ytd": "q"}, policy="nan")
    assert out.sort_values("REPORTING_PERIOD").stock.tolist() == [1.0, 2.0, 3.0, 4.0]


def test_duplicate_bank_quarter_rejected():
    with pytest.raises(QuarterizeError, match="duplicate"):
        quarterize(_frame(CLEAN + [(1, "2020Q2", 99.0)]), {"ytd": "q"}, policy="nan")


def test_missing_predecessor_value_is_nan_by_default():
    """The third failure mode: the previous row exists but its value is missing.

    Legacy computed ytd(Q4) - NaN = NaN and then fell back to the raw year-to-date,
    booking a whole year of income as one quarter's flow. It is not detectable from the
    reporting calendar, because no quarter is actually absent.
    """
    rows = [(4, "2020Q3", None), (4, "2020Q4", 509.0)]
    out, _ = quarterize(_frame(rows), {"ytd": "q"}, policy="nan")
    assert np.isnan(_values(out, 4)[1])


def test_missing_predecessor_value_keep_reproduces_legacy():
    rows = [(4, "2020Q3", None), (4, "2020Q4", 509.0)]
    out, _ = quarterize(_frame(rows), {"ytd": "q"}, policy="keep")
    assert _values(out, 4)[1] == 509.0


def test_unknown_policy_rejected():
    with pytest.raises(QuarterizeError, match="unknown gap policy"):
        quarterize(_frame(CLEAN), {"ytd": "q"}, policy="invent")
