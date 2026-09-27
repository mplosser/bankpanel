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
from .zerofill import blank_annual_zeros, zero_fill_unless_reported


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
    prior_year_root: Path | None = None,
) -> YearResult:
    """Build and write one year's partition of both datasets.

    ``prior_year_root``: for an UNFINISHED year (no Q4 yet), the panel root holding the
    previous year's finished partition. Its pattern decides which blanks the in-era zero-fill
    leaves alone (see ``zerofill.py``). Without it, an unfinished year gets no such zero-fill.
    """
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

    # Written zeros that mean "not collected this quarter" (annual Q4-only filers before
    # 2005Q3) are blanked first, so the column means the same thing on both sides of 2005Q3.
    for rule in cs.blank_annual_zeros:
        blank_annual_zeros(panel, rule.column, id_col=profile.id_col, date_col=profile.date_col,
                           era_end=pd.Timestamp(rule.era_end))

    # Zero-fill that needs the bank's whole year. Before quarterization, so that a resolved
    # year-to-date zero yields a zero flow rather than an unknown one.
    rules = [r for r in cs.zero_fill if r.scope == "in_era_unless_reported"]
    last_month = max(pd.Timestamp(q.period).month for q in quarter_files)
    unfinished = last_month < 12
    keep_blank: dict[str, set] = {}
    if unfinished and rules:
        keep_blank = _prior_year_late_reporters(prior_year_root, year - 1, [r.column for r in rules],
                                                profile, last_month)
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
        if unfinished and rule.column not in keep_blank:
            continue  # no finished prior year to read the pattern from: never invent a zero
        zero_fill_unless_reported(
            panel, rule.column, id_col=profile.id_col, date_col=profile.date_col,
            era_start=start, era_end=pd.Timestamp(end) if end else None,
            forms=None if scope == "all" else frozenset(int(f) for f in scope.split("+")),
            keep_blank=keep_blank.get(rule.column),
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


def _prior_year_late_reporters(
    root: Path | None, prior_year: int, columns: list[str], profile: ReportProfile, last_month: int
) -> dict[str, set]:
    """Per column, the banks that last year reported a non-zero value ONLY in quarters after
    ``last_month`` (e.g. only at Q4 when this year's build ends at Q2). Empty dict when the
    prior year's finished partition is not available."""
    if root is None:
        return {}
    path = Path(root) / "panel" / f"year={prior_year}" / "part-0.parquet"
    if not path.exists():
        return {}
    import pyarrow.parquet as pq

    have = set(pq.read_schema(path).names)
    cols = [c for c in columns if c in have]
    prior = pd.read_parquet(path, columns=[profile.id_col, profile.date_col, *cols])
    late = pd.DatetimeIndex(prior[profile.date_col]).month > last_month
    out: dict[str, set] = {}
    for c in cols:
        rep = prior[c].fillna(0).ne(0)
        early_ids = set(prior.loc[rep & ~late, profile.id_col])
        late_ids = set(prior.loc[rep & late, profile.id_col])
        out[c] = late_ids - early_ids
    for c in columns:
        out.setdefault(c, set())  # column absent last year: nobody has a later-only pattern
    return out
