"""Era-stitch continuity: does the level step when the source changes?"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bankpanel.config import ConfigSet
from bankpanel.validate.stitches import CONSTRUCTED, _chain, find_stitch_steps, gate

STITCH = """[BASE_VARIABLES]
mdrm_code,variable_name,schedule,flow_type
RCFD1000,old_code,RC,stock
RCFD2000,new_code,RC,stock

[DERIVED_VARIABLES]
variable_name,schedule,flow_type,description,formula
total,RC,stock,Stitched,new_code.fillna(old_code)
"""

N_BANKS = 400
QUARTERS = pd.period_range("2000Q1", "2010Q4", freq="Q")
SWITCH = pd.Period("2005Q1", freq="Q")


def _panel(step: float, seed: int = 0) -> pd.DataFrame:
    """A panel that grows smoothly, with `step` applied once at the switch quarter."""
    rng = np.random.default_rng(seed)
    rows = []
    level = dict.fromkeys(range(N_BANKS), 1000.0)
    for quarter in QUARTERS:
        factor = (1 + step) if quarter == SWITCH else 1.0
        for bank in range(N_BANKS):
            level[bank] *= 1.01 * float(np.exp(rng.normal(0, 0.01)))
            value = level[bank] * factor
            rows.append({
                "RSSD_ID": bank,
                "REPORTING_PERIOD": quarter.to_timestamp(how="end").normalize(),
                "old_code": None if quarter >= SWITCH else value,
                "new_code": value if quarter >= SWITCH else None,
            })
        if quarter == SWITCH:
            for bank in range(N_BANKS):
                level[bank] *= 1 + step
    df = pd.DataFrame(rows)
    df["total"] = df.new_code.fillna(df.old_code)
    return df


def test_chain_names_a_coalesce():
    assert _chain("a.fillna(b).fillna(c)") == ["a", "b", "c"]


def test_expression_fallback_has_no_name():
    """A reported total falling back to a SUM has no second column to name."""
    assert _chain("reported.fillna(x.fillna(0) + y.fillna(0))") == ["reported"]


def test_smooth_handoff_is_not_flagged(write_config):
    cs = ConfigSet.load(write_config(STITCH))
    assert find_stitch_steps(_panel(0.0), cs).empty


def test_level_step_at_handoff_is_flagged(write_config):
    cs = ConfigSet.load(write_config(STITCH))
    found = find_stitch_steps(_panel(0.25), cs)
    assert len(found) == 1
    row = found.iloc[0]
    assert row.quarter == "2005Q1"
    assert row.from_source == "old_code" and row.to_source == "new_code"
    assert 0.20 < row.jump < 0.30
    assert row.severity == "critical"
    assert gate(found) == 1


def test_step_is_scored_against_the_column_own_volatility(write_config):
    """A jump that is ordinary FOR THIS SERIES must not fire.

    Threshold is a robust z on the column's own quarterly moves, not a fixed percentage,
    so a volatile series is not flagged for a move a quiet one would be flagged for.
    """
    cs = ConfigSet.load(write_config(STITCH))
    rng = np.random.default_rng(1)
    df = _panel(0.25)
    period = pd.PeriodIndex(df.REPORTING_PERIOD, freq="Q")
    # Make every quarter move as much as the handoff does.
    shock = pd.Series(period.map({q: float(np.exp(rng.normal(0, 0.25))) for q in QUARTERS}))
    for column in ("old_code", "new_code", "total"):
        df[column] = df[column].to_numpy() * shock.to_numpy()
    found = find_stitch_steps(df, cs)
    assert found.empty or found.iloc[0].severity == "info"


def test_constructed_branch_is_labelled(write_config):
    """Reported -> reconstructed-from-subcomponents is the transition worth naming."""
    text = STITCH.replace(
        "total,RC,stock,Stitched,new_code.fillna(old_code)",
        "total,RC,stock,Reported else rebuilt,old_code.fillna(new_code * 2)",
    )
    cs = ConfigSet.load(write_config(text))
    df = _panel(0.25)
    df["total"] = df.old_code.fillna(df.new_code * 2)
    found = find_stitch_steps(df, cs)
    assert not found.empty
    assert found.iloc[0].to_source == CONSTRUCTED
