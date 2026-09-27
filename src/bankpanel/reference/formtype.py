"""Which FFIEC form a bank filed, over the whole 1976-2026 panel.

This matters far more than it looks. Since 2017 the *majority* of filers use the FFIEC
051 short form, which (a) omits many items entirely and (b) collects hundreds of others
only semiannually. Without a form_type column, a NaN is uninterpretable: it could mean
"reported as missing", "not collected from this filer", or "not collected this quarter".

The source data gives form type two different ways, on either side of the 2010Q4/2011Q1
change of upstream provider:

* **2011Q1 onward** (FFIEC CDR bulk files) carry an explicit
  ``FINANCIAL INSTITUTION FILING TYPE`` column with values 31 / 41 / 51.
* **1985Q1-2010Q4** (Chicago Fed) carry no such field. The usable proxy is ``CALL8786``,
  the *reporting level code*: 1 = fully consolidated including foreign offices, 2 =
  domestic only. That is the same distinction form 031 vs 041 encodes.

The proxy was validated against the boundary: crosstabbing 2010Q4 ``CALL8786`` against
2011Q1 filing type for the 6,920 banks present in both quarters gives

    FILING TYPE      31     41
    CALL8786
    1.0             109      4
    2.0               0   6807

109 of 113 exact, and nothing misassigned into the 41 bucket. The 4 discordant banks
genuinely changed form across the boundary.

**The level code alone is not enough in 1985-1988.** In those four years ``CALL8786 == 1``
also marks 360-470 small banks a year (median assets $163M in 1987Q2, against $2.7bn) that
file no foreign-office schedule at all -- domestic filers on a smaller form, whose blanks
on items that form did not collect (farmland, agricultural loans, intangibles, the
quarterly-average loan total, total loan interest) were being read as 031 blanks. A true
031 filer always carries the foreign-office schedule, so form 31 additionally requires
``RCFN2200`` (deposits in foreign offices) to be present. Measured on every Q4 1985-2010:
from 1989 on the two signals agree for every bank in every year (no level-1 bank lacks the
schedule, no level-2 bank has it), so the rule changes nothing outside 1985-1988.

Known limitation, documented rather than guessed around: before 2001 the ``8786 == 2``
bucket also contains FFIEC 032/033/034 filers, which that field cannot separate. Those
quarters are labelled 41 with ``form_type_source='call8786_inferred'``; consumers who
care must consult era metadata rather than trusting the 41 label pre-2001.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Explicit form-type field, present from 2011Q1 (FFIEC CDR era).
CDR_FILING_TYPE_COL = "FINANCIAL INSTITUTION FILING TYPE"

#: Reporting level code, present through 2010Q4 (Chicago Fed era).
LEGACY_REPORTING_LEVEL_COL = "CALL8786"

#: Deposits in foreign offices: present for every filer of the foreign-office schedule,
#: i.e. every true FFIEC 031 filer, and for no one else.
LEGACY_FOREIGN_OFFICE_COL = "RCFN2200"

#: Entity type code. NOT a form type -- values are 1/10/17 for domestic commercial,
#: savings and co-operative banks. Carried into the header dataset for reference only.
LEGACY_ENTITY_TYPE_COL = "RSSD9331"

VALID_FORM_TYPES = (31, 41, 51)

#: **Before 1984 the reporting level code carries no information** (level 1 for 0-6 banks a
#: quarter, against 140-200 banks reporting foreign-office items; from 1984Q1 the two line
#: up). So before 1984 a bank has foreign offices -- form 31 in the panel's terms -- when it
#: reports ANY foreign-office (RCFN) item, or its consolidated total assets differ from its
#: domestic total assets. Two signals because the files differ: 1983Q2-Q4 carry foreign-office
#: items but not RCFN2200 (197 banks), and 1976Q4 carries no RCFN item at all but consolidated
#: and domestic totals (133 banks differ). Where both exist, the asset test flags at most one
#: bank a quarter without foreign items. About 10 foreign-office banks a quarter have equal
#: totals; in 1976Q4 they are missed, and for them a domestic fill changes almost nothing.
PRE1984_END = pd.Timestamp("1983-12-31")
PRE1984_FOREIGN_ITEMS = ("RCFN2200", "RCFN2330", "RCFN2650", "RCFN3360", "RCFN6636",
                         "RCFN1403", "RCFN1404", "RCFN1407", "RCFN2077", "RCFN2621")
PRE1984_TOTAL_ASSETS = ("RCFD2170", "RCON2170")

#: Identity columns to carry into the narrow header dataset, by era.
CDR_HEADER_COLUMNS = (
    "FDIC CERTIFICATE NUMBER",
    "FINANCIAL INSTITUTION NAME",
    "FINANCIAL INSTITUTION ADDRESS",
    "FINANCIAL INSTITUTION CITY",
    "FINANCIAL INSTITUTION STATE",
    "FINANCIAL INSTITUTION ZIP CODE",
    "OCC CHARTER NUMBER",
    "OTS DOCKET NUMBER",
    "PRIMARY ABA ROUTING NUMBER",
    "LAST DATE/TIME SUBMISSION UPDATED ON",
)

LEGACY_HEADER_COLUMNS = (
    LEGACY_REPORTING_LEVEL_COL,
    LEGACY_ENTITY_TYPE_COL,
    "RSSD9017",
    "RSSD9050",
    "RSSD9130",
    "RSSD9200",
    "RSSD9220",
)

#: Renamed to stable snake_case in the header dataset.
HEADER_RENAMES = {
    "FDIC CERTIFICATE NUMBER": "fdic_cert",
    "FINANCIAL INSTITUTION NAME": "institution_name",
    "FINANCIAL INSTITUTION ADDRESS": "address",
    "FINANCIAL INSTITUTION CITY": "city",
    "FINANCIAL INSTITUTION STATE": "state",
    "FINANCIAL INSTITUTION ZIP CODE": "zip_code",
    "OCC CHARTER NUMBER": "occ_charter",
    "OTS DOCKET NUMBER": "ots_docket",
    "PRIMARY ABA ROUTING NUMBER": "aba_routing",
    "LAST DATE/TIME SUBMISSION UPDATED ON": "last_submission_update",
    LEGACY_REPORTING_LEVEL_COL: "reporting_level_code",
    LEGACY_ENTITY_TYPE_COL: "entity_type_code",
    "RSSD9017": "legacy_name",
    "RSSD9050": "legacy_city",
    "RSSD9130": "legacy_state",
    "RSSD9200": "legacy_country",
    "RSSD9220": "legacy_zip",
}


def header_source_columns() -> tuple[str, ...]:
    """Every raw column the form-type resolver or the header dataset may draw on.

    Must include the two *discriminator* columns, not just the identity fields. Omitting
    :data:`CDR_FILING_TYPE_COL` here does not raise -- the resolver simply falls through
    to the legacy branch, which then finds no ``CALL8786`` either, and every post-2011 row
    silently gets a null form type.
    """
    return (CDR_FILING_TYPE_COL,) + CDR_HEADER_COLUMNS + LEGACY_HEADER_COLUMNS


def resolver_source_columns() -> tuple[str, ...]:
    """What to read from a raw quarter: the header columns plus the foreign-office item the
    pre-2011 form rule needs. The latter is a balance-sheet value, not identity, so it is
    read for the resolver and kept out of the header dataset."""
    return header_source_columns() + tuple(dict.fromkeys(
        (LEGACY_FOREIGN_OFFICE_COL, *PRE1984_FOREIGN_ITEMS, *PRE1984_TOTAL_ASSETS)))


def _is_pre1984(df: pd.DataFrame) -> bool:
    if "REPORTING_PERIOD" not in df.columns or df.empty:
        return False
    return bool(pd.to_datetime(df["REPORTING_PERIOD"]).max() <= PRE1984_END)


def resolve_form_type(df: pd.DataFrame) -> pd.DataFrame:
    """Return a two-column frame ``form_type`` (Int8) and ``form_type_source``.

    ``df`` is one quarter's raw slice with uppercase columns.
    """
    n = len(df)
    if CDR_FILING_TYPE_COL in df.columns:
        raw = pd.to_numeric(df[CDR_FILING_TYPE_COL], errors="coerce")
        form_type = raw.where(raw.isin(VALID_FORM_TYPES))
        source = pd.Series(np.where(form_type.notna(), "cdr_field", "unknown"), index=df.index)
    elif _is_pre1984(df):
        foreign = df[[c for c in PRE1984_FOREIGN_ITEMS if c in df.columns]].notna().any(axis=1)
        if all(c in df.columns for c in PRE1984_TOTAL_ASSETS):
            cons, dom = (pd.to_numeric(df[c], errors="coerce") for c in PRE1984_TOTAL_ASSETS)
            foreign |= cons.notna() & dom.notna() & cons.ne(dom)
        form_type = pd.Series(np.where(foreign, 31.0, 41.0), index=df.index)
        source = pd.Series("pre1984_foreign_items", index=df.index)
    elif LEGACY_REPORTING_LEVEL_COL in df.columns:
        level = pd.to_numeric(df[LEGACY_REPORTING_LEVEL_COL], errors="coerce")
        # 1 = consolidated incl. foreign offices -> form 031; 2 = domestic only -> 041.
        # A level-1 bank with no foreign-office schedule is a domestic filer (1985-1988 only).
        if LEGACY_FOREIGN_OFFICE_COL in df.columns:
            foreign = pd.to_numeric(df[LEGACY_FOREIGN_OFFICE_COL], errors="coerce").notna()
        else:
            foreign = pd.Series(True, index=df.index)
        form_type = pd.Series(np.nan, index=df.index, dtype="float64")
        form_type[(level == 1) & foreign] = 31
        form_type[(level == 2) | ((level == 1) & ~foreign)] = 41
        source = pd.Series(
            np.where(form_type.notna(), "call8786_inferred", "unknown"), index=df.index
        )
    else:
        form_type = pd.Series(np.nan, index=df.index, dtype="float64")
        source = pd.Series("unknown", index=df.index)

    return pd.DataFrame(
        {
            "form_type": form_type.astype("Int8"),
            "form_type_source": pd.Series(source, dtype="string"),
        },
        index=df.index,
    ) if n else pd.DataFrame(
        {"form_type": pd.Series(dtype="Int8"), "form_type_source": pd.Series(dtype="string")}
    )
