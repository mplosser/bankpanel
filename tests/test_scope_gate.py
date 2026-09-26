"""The consolidated-vs-domestic substitution gate (validate/scope.py)."""

import pandas as pd

from bankpanel.validate import scope


def _scope(shares_equal, n=14, col="assets"):
    d = pd.date_range("2020-03-31", periods=len(shares_equal), freq="QE")
    return pd.DataFrame({"REPORTING_PERIOD": d, "column": col, "code": "RCFD2170",
                         "material_both": n, "material_equal": [round(s * n) for s in shares_equal]})


def test_full_copy_is_flagged():
    f = scope.substitution_findings(_scope([0.0] * 8 + [1.0]))
    assert len(f) == 1 and f.iloc[0].material_equal == 14


def test_stable_domestic_item_is_not_flagged():
    assert scope.substitution_findings(_scope([1.0] * 9)).empty


def test_small_sample_partial_jump_is_not_flagged():
    # 5 of 7 identical against a usual 20%: a jump of 51 points, but not the near-total
    # identity an upstream copy produces (the BHCKF601 2010Q4 case)
    s = _scope([0.2] * 8 + [5 / 7], n=7)
    s.loc[s.index[-1], "material_equal"] = 5
    assert scope.substitution_findings(s).empty


def test_too_few_banks_is_not_evaluated():
    assert scope.substitution_findings(_scope([0.0] * 8 + [1.0], n=4)).empty
