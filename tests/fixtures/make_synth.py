"""Generate a tiny synthetic raw dataset that encodes every rule the builder implements.

Generated rather than committed, so the fixture is readable as code and cannot silently
rot into a binary nobody can explain.

The synthetic panel deliberately mirrors the awkward parts of the real data:

* a **provider change** at 2011Q1, before which form type is carried by ``CALL8786`` and
  after which it is carried by the CDR ``FINANCIAL INSTITUTION FILING TYPE`` field;
* an **all-numeric** RCFD/RCON pair that is byte-identical (as upstream cross-filling
  makes them) and an **alphanumeric** pair that is genuinely disjoint;
* an item reachable only through a **prefix alias** (RCFA -> RCOA);
* an item **absent entirely** from the early quarters;
* an item collected **only in Q2 and Q4** from short-form filers;
* year-to-date items with a **missing intra-year quarter** and a **partial first year**;
* a **1000x unit error** in one bank's series.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

N_BANKS = 12
BANKS = list(range(1, N_BANKS + 1))
QUARTERS = [f"{y}Q{q}" for y in (2009, 2010, 2011, 2012) for q in (1, 2, 3, 4)]

#: The synthetic analogue of the 2010Q4/2011Q1 upstream provider change.
PROVIDER_CHANGE = pd.Period("2011Q1", freq="Q")

#: Bank 1 is the only consolidated (form 031) filer.
FORM31_BANKS = {1}
#: Short-form (051) filers, post-change only.
FORM51_BANKS = {7, 8, 9, 10, 11, 12}

#: Bank 5 skips 2011Q2 entirely; bank 6 does not exist until 2011Q3.
MISSING_QUARTER = (5, pd.Period("2011Q2", freq="Q"))
LATE_ENTRY = (6, pd.Period("2011Q3", freq="Q"))

#: Bank 9 reports account counts in units rather than thousands before 2011.
UNIT_ERROR_BANK = 9

DESCRIPTIONS = {
    "RCFD2170": "TOTAL ASSETS",
    "RCON2170": "TOTAL ASSETS",
    "RCFDA570": "LOANS MATURING IN THREE MONTHS OR LESS",
    "RCONA570": "LOANS MATURING IN THREE MONTHS OR LESS",
    "RCOA1234": "AVERAGE CONSOLIDATED TOTAL ASSETS",
    "RCON9999": "LATE-INTRODUCED ITEM",
    "RCON8888": "SEMIANNUAL SHORT-FORM ITEM",
    "RIAD4107": "TOTAL INTEREST INCOME",
    "RIAD9001": "ITEM COLLECTED ONLY FROM 2011",
    "RCON7777": "DEPOSIT ACCOUNT COUNT",
}


def _banks_present(period: pd.Period) -> list[int]:
    banks = [b for b in BANKS if not (b == LATE_ENTRY[0] and period < LATE_ENTRY[1])]
    if (MISSING_QUARTER[0], period) == MISSING_QUARTER:
        banks = [b for b in banks if b != MISSING_QUARTER[0]]
    return banks


def _form_type(bank: int, period: pd.Period) -> int:
    if bank in FORM31_BANKS:
        return 31
    if period >= PROVIDER_CHANGE and bank in FORM51_BANKS:
        return 51
    return 41


def build_quarter_frame(period: pd.Period) -> pd.DataFrame:
    banks = _banks_present(period)
    n = len(banks)
    idx = np.arange(n)
    modern = period >= PROVIDER_CHANGE
    quarter_of_year = period.quarter
    seq = (period.year - 2009) * 4 + quarter_of_year

    df = pd.DataFrame({
        "RSSD_ID": banks,
        "REPORTING_PERIOD": pd.Timestamp(period.end_time.normalize()),
    })

    # All-numeric pair: identical on both sides, as upstream cross-filling produces.
    assets = 100_000.0 + 1_000.0 * np.array(banks) + 10.0 * seq
    df["RCFD2170"] = assets
    df["RCON2170"] = assets

    # Alphanumeric pair: disjoint. Pre-change everyone files RCFD; post-change only the
    # consolidated filer does, and everyone else moves to RCON.
    alnum = 500.0 + np.array(banks) + seq
    forms = np.array([_form_type(b, period) for b in banks])
    if modern:
        df["RCFDA570"] = np.where(forms == 31, alnum, np.nan)
        df["RCONA570"] = np.where(forms == 31, np.nan, alnum)
    else:
        df["RCFDA570"] = alnum
        df["RCONA570"] = np.nan

    # Reachable only via the RCFA -> RCOA prefix alias.
    df["RCOA1234"] = assets * 0.98

    # Absent entirely before the provider change.
    if modern:
        df["RCON9999"] = 42.0 + idx

    # Short-form filers report this only in Q2 and Q4.
    if modern:
        collected = np.isin(forms, [31, 41]) | (quarter_of_year in (2, 4))
        df["RCON8888"] = np.where(collected, 7.0 + idx, np.nan)

    # Year-to-date interest income: accumulates 100 per quarter within a year.
    df["RIAD4107"] = 100.0 * quarter_of_year * (1 + np.array(banks) / 100.0)

    # Collected only from the provider change onward -- exercises scope=in_era zero-fill.
    if modern:
        df["RIAD9001"] = np.where(idx % 3 == 0, 5.0, np.nan)

    # Account counts, with one bank reporting in units instead of thousands pre-change.
    counts = 200.0 + np.array(banks)
    if not modern:
        counts = np.where(np.array(banks) == UNIT_ERROR_BANK, counts * 1000.0, counts)
    df["RCON7777"] = counts

    # Form-type discriminators, one per era.
    if modern:
        df["FINANCIAL INSTITUTION FILING TYPE"] = forms
        df["FINANCIAL INSTITUTION NAME"] = [f"SYNTHETIC BANK {b}" for b in banks]
    else:
        # 1 = consolidated incl. foreign offices, 2 = domestic only.
        df["CALL8786"] = np.where(forms == 31, 1.0, 2.0)

    return df


def _table(df: pd.DataFrame) -> pa.Table:
    table = pa.Table.from_pandas(df, preserve_index=False)
    fields = [
        f.with_metadata({b"description": DESCRIPTIONS[f.name].encode()})
        if f.name in DESCRIPTIONS
        else f
        for f in table.schema
    ]
    return table.cast(pa.schema(fields))


def write_synth_raw(out_dir: str | Path) -> Path:
    """Write the synthetic quarterly parquets and return the directory."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for label in QUARTERS:
        period = pd.Period(label, freq="Q")
        pq.write_table(_table(build_quarter_frame(period)), out_dir / f"{label}.parquet")
    return out_dir


CONFIG = """[META]
key,value
panel_name,synth
profile,ffiec_call

[BASE_VARIABLES]
mdrm_code,variable_name,schedule,flow_type,form_scope,era_start,era_end,sign,notes
RCFD2170,assets_total,RC,stock,all,,,,Numeric-code pair
RCFDA570,loans_3mo,RC-C,stock,all,,,,Alphanumeric pair needing the row-level coalesce
RCFA1234,avg_assets,RC-K,stock,all,,,,Reachable only through the RCFA to RCOA alias
RCON9999,late_item,RC,stock,all,2011-03-31,,,Absent before the provider change
RCON8888,semiannual_item,RC,stock,041+051,2011-03-31,,,Short-form filers report only in Q2 and Q4
RIAD4107,int_inc_total,RI,ytd,all,,,nonneg,Year-to-date interest income
RIAD9001,event_flag,RI-A,ytd,all,,,,Collected only from 2011; zero-filled in era
RCON7777,deposit_accounts,RC-E,count,all,,,,Carries a 1000x unit error for one bank

[DERIVED_VARIABLES]
variable_name,schedule,flow_type,description,formula,unit,sign
assets_less_loans,CROSS,stock,Assets net of short-maturity loans,assets_total - loans_3mo,thousands_usd,
late_or_assets,RC,stock,Late item where present else assets,late_item.fillna(assets_total),thousands_usd,

[ZERO_FILL]
column,scope,reason
event_flag,in_era,Structural-event item; NaN means no event once collection began but means not collected before
"""


def write_synth_config(out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "synth.csv"
    path.write_text(CONFIG, encoding="utf-8")
    return out_dir


if __name__ == "__main__":  # pragma: no cover
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    print(write_synth_raw(tmp / "raw"))
    print(write_synth_config(tmp / "configs"))
