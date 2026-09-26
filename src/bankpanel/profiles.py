"""Report profiles: the small set of facts that differ between regulatory reports.

The build engine is deliberately report-agnostic. Everything specific to the FFIEC Call
Report -- its key columns, its prefix quirks, the fact that year-to-date items reset on
the calendar year -- lives in one frozen dataclass rather than being scattered through the
builder as literals.

Adding FR Y-9C later is then one new :class:`ReportProfile` (``BHCK``/``BHCT`` prefixes,
its own form-type resolver) and no changes to ``build/``. This is a seam, not a plugin
system: there is no registry, no entry points, and no dynamic discovery, because a
handful of reports does not justify any of that.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .reference.formtype import (
    HEADER_RENAMES,
    header_source_columns,
    resolve_form_type,
    resolver_source_columns,
)


@dataclass(frozen=True)
class ReportProfile:
    #: Short identifier recorded in the build manifest.
    name: str

    #: Key columns in the raw quarterly files.
    id_col: str = "RSSD_ID"
    date_col: str = "REPORTING_PERIOD"

    #: How to find the raw quarterly files.
    raw_glob: str = "*.parquet"

    #: Column-level prefix substitutions, tried when the configured code is absent.
    #: These are the FFIEC 031-vs-041 schedule-suffix variants: an item filed as RCFA on
    #: one form appears as RCOA on the other. Whole-column substitution, unlike the
    #: row-level coalesce below.
    prefix_aliases: tuple[tuple[str, str], ...] = (("RCFA", "RCOA"), ("RCFW", "RCOW"))

    #: Row-level coalesce pairs, ``(primary, fallback)``. The same numeric suffix under
    #: two prefixes is the same line item at two consolidation levels; take the primary
    #: where present and fill from the fallback where it is not.
    #: RCFA/RCOA is the same pairing on Schedule RC-R from 2015Q1 (Basel III): the 031 files
    #: the regulatory-capital items under RCFA (consolidated), the 041/051 under RCOA.
    coalesce_rules: tuple[tuple[str, str], ...] = (("RCFD", "RCON"), ("RCFA", "RCOA"))

    #: The coalesce pairs whose fallback is the DOMESTIC-offices figure of a CONSOLIDATED item
    #: (RCON for RCFD). OFFICIAL RULE (1.4): the domestic figure is used in place of the
    #: consolidated one only for a bank WITHOUT foreign offices, where the two are the same
    #: number by definition. For an international bank a consolidated item it does not report
    #: stays blank -- a domestic figure is never published under a consolidated name.
    #: RCFA/RCOA is not such a pair (both consolidated; one per form) and is unaffected.
    domestic_pairs: tuple[tuple[str, str], ...] = ()

    #: ``(raw slice, resolved form frame) -> (international, material_foreign)`` boolean
    #: Series. ``international``: the bank has foreign offices, so consolidated != domestic.
    #: ``material_foreign``: foreign offices hold more than 5% of its deposits -- where an
    #: exact consolidated == domestic match is evidence of an upstream substitution.
    foreign_offices: Callable[[pd.DataFrame, pd.DataFrame], tuple[pd.Series, pd.Series]] | None = None

    #: When year-to-date accumulation resets. Drives the quarterization grouping, and is
    #: the reason the panel is partitioned by year.
    ytd_reset: str = "calendar_year"

    #: Maps one quarter's raw slice to ``form_type`` / ``form_type_source``.
    form_type_resolver: Callable[[pd.DataFrame], pd.DataFrame] | None = None

    #: Optional MDRM dictionary parquet, used by ``bankpanel enrich``.
    dictionary_path: Path | None = field(default=None)

    #: Raw identity columns copied into the header dataset, and their stable names.
    header_columns: tuple[str, ...] = header_source_columns()
    header_renames: dict[str, str] = field(default_factory=lambda: dict(HEADER_RENAMES))
    #: Everything the resolver and header need read from a raw quarter.
    source_columns: tuple[str, ...] = resolver_source_columns()


def _foreign_share(raw: pd.DataFrame, domestic: tuple[str, ...], foreign: tuple[str, ...]) -> pd.Series:
    def total(cols):
        present = [c for c in cols if c in raw.columns]
        if not present:
            return pd.Series(np.nan, index=raw.index)
        vals = raw[present].apply(pd.to_numeric, errors="coerce")
        return vals.sum(axis=1, min_count=1)
    f, d = total(foreign), total(domestic)
    return (f / (f.fillna(0) + d)).where(f.notna() | d.notna())


def call_foreign_offices(raw: pd.DataFrame, form: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Call Report: a bank has foreign offices when it files the FFIEC 031 (form_type 31;
    before 2011 the form is resolved from the foreign-office schedule). Material when foreign
    offices hold more than 5% of its deposits (RCFN2200 against RCON2200)."""
    ft = pd.to_numeric(form["form_type"], errors="coerce") if "form_type" in form.columns else pd.Series(np.nan, index=raw.index)
    intl = ft.eq(31).fillna(False).astype(bool)
    material = intl & _foreign_share(raw, ("RCON2200",), ("RCFN2200",)).gt(0.05).fillna(False)
    return intl, material


def fry9c_foreign_offices(raw: pd.DataFrame, form: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """FR Y-9C: one form for all holding companies, so foreign offices are read from the
    balance sheet: any deposits in foreign offices (BHFN6631 + BHFN6636) above zero."""
    share = _foreign_share(raw, ("BHDM6631", "BHDM6636"), ("BHFN6631", "BHFN6636"))
    intl = share.gt(0).fillna(False).astype(bool)
    return intl, intl & share.gt(0.05).fillna(False)


#: The FFIEC Call Report (forms 031 / 041 / 051), as published by ``data_call_report``.
FFIEC_CALL = ReportProfile(
    name="ffiec_call",
    form_type_resolver=resolve_form_type,
    domestic_pairs=(("RCFD", "RCON"),),
    foreign_offices=call_foreign_offices,
    source_columns=resolver_source_columns() + ("RCON2200",),
)

#: Raw identity fields on the FR Y-9 files (Chicago Fed and FFIEC eras share them).
FRY9C_HEADER = {
    "RSSD9017": "institution_name",
    "RSSD9010": "short_name",
    "RSSD9130": "city",
    "RSSD9200": "state",
    "RSSD9220": "zip_code",
    "RSSD9050": "legacy_country",
    "RSSD9053": "date_end",
    "RSSD9032": "entity_type_code",
    "RSSD9146": "financial_sub_indicator",
}

#: Size tier that governs reporting frequency on the FR Y-9C. Holding companies below the
#: threshold file a set of items (the CECL amortized-cost detail, among others) at Q2 and Q4
#: only. Measured on 2024-2025 off-quarters: 3% of filers under $5bn report those items, 94-96%
#: of filers at or above it. The tier plays the role form_type plays for the Call Report --
#: the population key the expectations matrix measures frequency within -- and is published
#: in the ``form_type`` column with ``form_type_source = "size_tier_5bn"``.
FRY9C_TIER_THRESHOLD = 5_000_000  # thousands of dollars: $5bn total assets (BHCK2170)


def resolve_size_tier(df: pd.DataFrame) -> pd.DataFrame:
    """1 = total assets under $5bn (semiannual filer of the tiered items), 2 = $5bn and over."""
    assets = pd.to_numeric(df.get("BHCK2170"), errors="coerce") if "BHCK2170" in df.columns else pd.Series(pd.NA, index=df.index)
    tier = pd.Series(pd.NA, index=df.index, dtype="Int8")
    tier[assets < FRY9C_TIER_THRESHOLD] = 1
    tier[assets >= FRY9C_TIER_THRESHOLD] = 2
    source = pd.Series(["size_tier_5bn" if pd.notna(t) else "unknown" for t in tier], index=df.index, dtype="string")
    return pd.DataFrame({"form_type": tier, "form_type_source": source}, index=df.index)


#: The FR Y-9C (consolidated bank holding company financial statements), as published by
#: ``data_fry9``. One form; the population key is the $5bn size tier (see above). BHCK is the
#: consolidated prefix and BHDM the
#: domestic-office one -- the RCFD/RCON pairing; BHCA/BHCW are the standardized and
#: advanced-approaches capital columns -- the RCFA/RCFW pairing. BHBC carries the
#: income of predecessor institutions in the quarter of a business combination.
FRY9C = ReportProfile(
    name="fry9c",
    prefix_aliases=(),
    coalesce_rules=(("BHCK", "BHDM"),),
    form_type_resolver=resolve_size_tier,
    domestic_pairs=(("BHCK", "BHDM"),),
    foreign_offices=fry9c_foreign_offices,
    header_columns=tuple(FRY9C_HEADER),
    header_renames=dict(FRY9C_HEADER),
    source_columns=tuple(FRY9C_HEADER) + ("BHCK2170", "BHDM6631", "BHDM6636", "BHFN6631", "BHFN6636"),
)

PROFILES: dict[str, ReportProfile] = {FFIEC_CALL.name: FFIEC_CALL, FRY9C.name: FRY9C}


def get_profile(name: str) -> ReportProfile:
    try:
        return PROFILES[name]
    except KeyError:
        raise KeyError(
            f"unknown profile {name!r}. Available: {sorted(PROFILES)}"
        ) from None
