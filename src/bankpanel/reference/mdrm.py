"""The Fed's MDRM data dictionary: item names, date ranges, and reporting forms.

Two traps make this file harder to use than it looks, and both silently produce wrong
answers rather than errors.

**A code has up to 21 rows.** MDRM records one row per (code, reporting form, revision),
so the naive ``df[df.code == x].iloc[0]`` returns an arbitrary one. Read that way,
``RCON1415`` appears to have ended in **1983**. Aggregating ``min(Start Date)`` and
``max(End Date)`` across a code's rows instead reproduces the hand-authored era chains
exactly: RCON1415 ends 2007-12-31 handing to RCONF158 from 2007-03-31; RCFD3190 ends
2000-12-31; RCFD1403 ends 2016-12-31.

**MDRM dates describe the FORMS, not your source.** An item can leave the current forms
years before it stops appearing in a particular data extract -- RCON1415 is published
through 2010Q4 in ours. So MDRM is used here to *propose*, never to decide. Anything it
suggests is checked against measured coverage before it reaches a config.
"""

from __future__ import annotations

import functools
from pathlib import Path

import pandas as pd

CALL_PREFIXES = ("RCON", "RCFD", "RIAD", "RCFN", "RCOA", "RCFA", "RCOW", "RCFW")

#: Where the MDRM dump usually lives, relative to a checkout of the sibling repos.
DEFAULT_PATHS = (
    Path("../data_call_report/data/dictionary/MDRM.csv"),
    Path("c:/Users/Matthew/OneDrive/GitHub/data_call_report/data/dictionary/MDRM.csv"),
    Path("reference_data/MDRM.csv"),
)


def find_mdrm(path: str | Path | None = None) -> Path:
    if path is not None:
        found = Path(path)
        if not found.exists():
            raise FileNotFoundError(f"MDRM file not found: {found}")
        return found
    for candidate in DEFAULT_PATHS:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "could not find MDRM.csv. Pass --mdrm, or run 02_download_dictionary.py in "
        "data_call_report."
    )


@functools.lru_cache(maxsize=4)
def load_mdrm(path: str | Path | None = None) -> pd.DataFrame:
    """One row per MDRM code, with its full date span across every form.

    Columns: ``mdrm_code, item_name, start_date, end_date, forms, n_rows``.
    """
    source = find_mdrm(path)
    # Line 1 is a bare "PUBLIC" marker; the real header is line 2.
    raw = pd.read_csv(source, skiprows=1, low_memory=False)
    raw.columns = [c.strip() for c in raw.columns]
    raw = raw[raw["Mnemonic"].isin(CALL_PREFIXES)].copy()
    raw["mdrm_code"] = (
        raw["Mnemonic"].str.strip() + raw["Item Code"].astype(str).str.strip()
    ).str.upper()
    for col in ("Start Date", "End Date"):
        raw[col] = pd.to_datetime(raw[col], errors="coerce", format="mixed")

    grouped = raw.groupby("mdrm_code")
    out = pd.DataFrame({
        "item_name": grouped["Item Name"].first(),
        # min/max across every row for the code -- see the module docstring.
        "start_date": grouped["Start Date"].min(),
        "end_date": grouped["End Date"].max(),
        "forms": grouped["Reporting Form"].apply(
            lambda s: ",".join(sorted({str(v).strip() for v in s.dropna()}))
        ),
        "n_rows": grouped.size(),
    }).reset_index()
    return out


def lookup(codes: list[str], path: str | Path | None = None) -> pd.DataFrame:
    mdrm = load_mdrm(path)
    return mdrm[mdrm.mdrm_code.isin({c.upper() for c in codes})].reset_index(drop=True)


def candidate_chains(codes: list[str], path: str | Path | None = None) -> pd.DataFrame:
    """Group codes that share an item name, ordered by date span.

    Two codes with the same official item name and non-overlapping spans are the classic
    signature of a definition change: one item, two codes, a handover date. This proposes
    such groups; it does not confirm them. Measured coverage decides.
    """
    info = lookup(codes, path)
    if info.empty:
        return info
    info = info.assign(name_key=info.item_name.str.upper().str.strip())
    groups = info.groupby("name_key").filter(lambda g: len(g) > 1)
    return groups.sort_values(["name_key", "start_date"]).reset_index(drop=True)
