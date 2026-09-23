"""The FR Y-9C profile end to end on a tiny synthetic Y-9 file: BHCK/BHDM coalesce, the size
tier, the header fields, predecessor items left alone by the quarterizer, and the config
generator's translation rules."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from bankpanel.build.runner import build
from bankpanel.profiles import get_profile
from bankpanel.io.reader import read_header, read_panel

QUARTERS = ["2020Q1", "2020Q2", "2020Q3", "2020Q4", "2021Q1"]


def _raw(period: str) -> pd.DataFrame:
    """Four holding companies. Bank 3 files the quarterly-average item only under BHDM;
    bank 4 is above $5bn; bank 2 acquires someone in 2020Q2 (predecessor item filed once)."""
    q = pd.Period(period, freq="Q")
    n = (q.year - 2020) * 4 + q.quarter          # 1..5
    df = pd.DataFrame({
        "RSSD_ID": [1, 2, 3, 4],
        "REPORTING_PERIOD": pd.Timestamp(q.end_time.normalize()),
        "RSSD9017": ["ALPHA BANCORP", "BETA HOLDINGS", "GAMMA CORP", "DELTA FINANCIAL"],
        "RSSD9200": ["NY", "TX", "OH", "CA"],
        "BHCK2170": [1_000_000.0, 2_000_000.0, 3_000_000.0, 9_000_000.0],
        # year-to-date interest income: 100/quarter for everyone, reset each Q1
        "BHCK4107": [100.0 * q.quarter] * 4,
        # quarterly average loans: bank 3 files it under BHDM only
        "BHCK3516": [500.0, 600.0, np.nan, 900.0],
        "BHDM3516": [np.nan, np.nan, 700.0, np.nan],
        # predecessor interest income: bank 2, acquisition quarter only
        "BHBC4107": [np.nan, 42.0 if period == "2020Q2" else np.nan, np.nan, np.nan],
    })
    return df


CONFIG = """[BASE_VARIABLES]
mdrm_code,variable_name,schedule,flow_type,form_scope,era_start,era_end,sign,notes
BHCK2170,assets,HC,stock,all,,,,
BHCK4107,ytd_int_inc,HI,ytd,all,,,nonneg,
BHCK3516,qavg_loans,HC-K,stock,all,,,,
BHBC4107,pred_ytd_int_inc,HI,ytd_event,all,,,,
[DERIVED_VARIABLES]
variable_name,schedule,flow_type,description,formula,unit,sign
"""


@pytest.fixture(scope="module")
def y9c_panel(tmp_path_factory):
    raw = tmp_path_factory.mktemp("y9c_raw")
    for period in QUARTERS:
        df = _raw(period)
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), raw / f"{period}.parquet")
    cfg = tmp_path_factory.mktemp("y9c_cfg")
    (cfg / "hc.csv").write_text(CONFIG, encoding="utf-8")
    out = tmp_path_factory.mktemp("y9c_panel")
    build(raw_dir=raw, out=out, config_dir=cfg, profile=get_profile("fry9c"), jobs=1, progress=False)
    return out


def test_bhdm_fallback_fills_a_blank_bhck(y9c_panel):
    p = read_panel(columns=["qavg_loans"], root=y9c_panel, verify=False)
    assert p[p.RSSD_ID == 3].qavg_loans.eq(700.0).all()
    assert p[p.RSSD_ID == 1].qavg_loans.eq(500.0).all()


def test_size_tier_is_the_form_type(y9c_panel):
    p = read_panel(columns=["assets"], root=y9c_panel, verify=False)
    tier = p.groupby("RSSD_ID").form_type.first()
    assert tier.to_dict() == {1: 1, 2: 1, 3: 1, 4: 2}
    h = read_header(root=y9c_panel)
    assert set(h.form_type_source) == {"size_tier_5bn"}
    assert h[h.RSSD_ID == 4].institution_name.iloc[0] == "DELTA FINANCIAL"
    assert h[h.RSSD_ID == 4].state.iloc[0] == "CA"


def test_ytd_is_quarterized_and_predecessor_item_is_not(y9c_panel):
    p = read_panel(columns=["ytd_int_inc", "q_int_inc", "pred_ytd_int_inc"], root=y9c_panel, verify=False)
    b1 = p[p.RSSD_ID == 1].sort_values("REPORTING_PERIOD")
    assert b1.ytd_int_inc.tolist() == [100.0, 200.0, 300.0, 400.0, 100.0]
    assert b1.q_int_inc.tolist() == [100.0] * 5
    assert "q_pred_ytd_int_inc" not in p.columns and "q_pred_int_inc" not in p.columns
    b2 = p[p.RSSD_ID == 2].sort_values("REPORTING_PERIOD")
    assert b2.pred_ytd_int_inc.tolist()[1] == 42.0
    assert b2.pred_ytd_int_inc.drop(b2.index[1]).isna().all()


def test_generator_translation_rules():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "derive", Path(__file__).resolve().parents[1] / "tools" / "derive_y9c_configs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.schedule_name("RC-C") == "HC-C" and mod.schedule_name("RI-B") == "HI-B"
    assert mod.schedule_name("RC") == "HC" and mod.schedule_name("CROSS") == "CROSS"
    assert mod.PREFIX["RCFD"] == "BHCK" and mod.PREFIX["RCON"] == "BHDM"
    assert mod.PREFIX["RIAD"] == "BHCK" and mod.PREFIX["RCFA"] == "BHCA"
