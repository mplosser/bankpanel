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

import pandas as pd

from .reference.formtype import HEADER_RENAMES, header_source_columns, resolve_form_type, resolver_source_columns


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


#: The FFIEC Call Report (forms 031 / 041 / 051), as published by ``data_call_report``.
FFIEC_CALL = ReportProfile(
    name="ffiec_call",
    form_type_resolver=resolve_form_type,
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

#: The FR Y-9C (consolidated bank holding company financial statements), as published by
#: ``data_fry9``. One form, so no form type. BHCK is the consolidated prefix and BHDM the
#: domestic-office one -- the RCFD/RCON pairing; BHCA/BHCW are the standardized and
#: advanced-approaches capital columns -- the RCFA/RCFW pairing. BHBC carries the
#: income of predecessor institutions in the quarter of a business combination.
FRY9C = ReportProfile(
    name="fry9c",
    prefix_aliases=(),
    coalesce_rules=(("BHCK", "BHDM"),),
    form_type_resolver=None,
    header_columns=tuple(FRY9C_HEADER),
    header_renames=dict(FRY9C_HEADER),
    source_columns=tuple(FRY9C_HEADER),
)

PROFILES: dict[str, ReportProfile] = {FFIEC_CALL.name: FFIEC_CALL, FRY9C.name: FRY9C}


def get_profile(name: str) -> ReportProfile:
    try:
        return PROFILES[name]
    except KeyError:
        raise KeyError(
            f"unknown profile {name!r}. Available: {sorted(PROFILES)}"
        ) from None
