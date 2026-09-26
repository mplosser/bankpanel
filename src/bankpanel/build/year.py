"""The per-year worker: build four quarters, quarterize, write one partition.

This is the unit of parallelism. It is self-contained because of one fact about the data:
year-to-date items reset on the calendar year, so everything a quarterization needs is
inside a single year. No worker needs to see another worker's output, and no global
reduction is required afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..config import ConfigSet
from ..profiles import ReportProfile
from .quarter import build_quarter
from .quarterize import quarterize
from .schema import header_schema, panel_schema
from .source import QuarterFile
from .writer import write_partition
from .zerofill import zero_fill_unless_reported


@dataclass
class YearResult:
    year: int
    n_rows: int
    n_quarters: int
    gaps: pd.DataFrame
    scope: pd.DataFrame = field(default_factory=pd.DataFrame)
    failures: list[str] = field(default_factory=list)


def build_year(
    year: int,
    quarter_files: list[QuarterFile],
    cs: ConfigSet,
    profile: ReportProfile,
    out_root: Path,
    *,
    era_starts: dict[str, pd.Timestamp] | None = None,
    gap_policy: str = "nan",
    keep_going: bool = False,
) -> YearResult:
    """Build and write one year's partition of both datasets."""
    out_root = Path(out_root)
    panel_parts: list[pd.DataFrame] = []
    header_parts: list[pd.DataFrame] = []
    scope_parts: list[pd.DataFrame] = []
    failures: list[str] = []

    for qf in sorted(quarter_files, key=lambda q: q.quarter):
        try:
            panel, header = build_quarter(qf, cs, profile, era_starts=era_starts, scope_sink=scope_parts)
        except Exception as exc:
            if not keep_going:
                raise
            failures.append(f"{qf.label}: {type(exc).__name__}: {exc}")
            continue
        panel_parts.append(panel)
        header_parts.append(header)

    if not panel_parts:
        return YearResult(year=year, n_rows=0, n_quarters=0, gaps=pd.DataFrame(), failures=failures)

    panel = pd.concat(panel_parts, ignore_index=True)
    header = pd.concat(header_parts, ignore_index=True)

    # Zero-fill that needs the bank's whole year. Before quarterization, so that a resolved
    # year-to-date zero yields a zero flow rather than an unknown one.
    for rule in cs.zero_fill:
        if rule.scope != "in_era_unless_reported":
            continue
        start = pd.Timestamp(rule.era_start) if rule.era_start else (era_starts or {}).get(rule.column)
        if start is None:
            raise KeyError(
                f"{rule.origin}: [ZERO_FILL] scope={rule.scope} for {rule.column!r} needs an era "
                f"start. Either set era_start in the config or run 'bankpanel eras build'."
            )
        var = cs.variable(rule.column)
        end = getattr(var, "era_end", None)
        scope = getattr(var, "form_scope", "all") or "all"
        zero_fill_unless_reported(
            panel, rule.column, id_col=profile.id_col, date_col=profile.date_col,
            era_start=start, era_end=pd.Timestamp(end) if end else None,
            forms=None if scope == "all" else frozenset(int(f) for f in scope.split("+")),
        )

    panel, gaps = quarterize(
        panel,
        cs.flow_columns(),
        id_col=profile.id_col,
        date_col=profile.date_col,
        policy=gap_policy,
    )

    write_partition(panel, out_root, "panel", year, panel_schema(cs, profile))
    write_partition(header, out_root, "header", year, header_schema(profile))

    return YearResult(
        year=year,
        n_rows=len(panel),
        n_quarters=len(panel_parts),
        gaps=gaps,
        scope=pd.concat(scope_parts, ignore_index=True) if scope_parts else pd.DataFrame(),
        failures=failures,
    )
