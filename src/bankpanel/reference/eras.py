"""When each item's collection actually began, measured from the data.

This exists to serve one rule with real consequences: **never fabricate a zero before an
item was collected.**

Some Call Report items are NaN in two completely different senses. Schedule RI-A's
business-combination line is blank in a quarter where the bank did no acquisition -- that
blank means zero. The same line is also blank in every quarter before the item existed --
that blank means *unknown*, and filling it with zero invents a fact.

Telling them apart needs one number per item: the first quarter in which anybody reported
it. That is a whole-panel question, so it cannot be answered inside a per-year worker.
Hoisting it into a cheap pre-pass keeps the build a pure function of (configs, raw files,
reference data) and keeps the workers independent.

The scan reads only the handful of columns involved, via column projection.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ..build.source import QuarterFile, resolve_codes, schema_columns
from ..config import ConfigSet
from ..profiles import ReportProfile


def _codes_behind(cs: ConfigSet, column: str) -> set[str]:
    """The raw MDRM codes whose presence determines ``column``'s era.

    For a base variable that is its own code. For a derived variable it is the codes of
    every base variable that feeds it, since the derived value can only exist once one of
    its inputs does.
    """
    by_name = {v.variable_name: v for v in cs.base}
    if column in by_name:
        names = {column}
    else:
        names = cs.graph.transitive_inputs(column)
    codes: set[str] = set()
    for name in names:
        code = by_name[name].mdrm_code
        codes.add(code)
        if code.startswith("RCFD"):
            codes.add("RCON" + code[4:])
    return codes


def detect_eras(
    quarters: list[QuarterFile],
    cs: ConfigSet,
    profile: ReportProfile,
    columns: list[str],
) -> dict[str, pd.Timestamp]:
    """First quarter in which each column's underlying codes carry any value."""
    wanted = {col: _codes_behind(cs, col) for col in columns}
    found: dict[str, pd.Timestamp] = {}

    for qf in sorted(quarters, key=lambda q: (q.year, q.quarter)):
        outstanding = [c for c in columns if c not in found]
        if not outstanding:
            break
        available = set(schema_columns(qf.path))
        codes_here = sorted({c for col in outstanding for c in wanted[col]} & available)
        if not codes_here:
            continue
        resolved = resolve_codes(codes_here, available, profile)
        table = pq.read_table(qf.path, columns=sorted(set(resolved.values())))
        df = table.to_pandas()
        df.columns = [str(c).upper() for c in df.columns]
        for col in outstanding:
            present = [resolved[c] for c in wanted[col] if c in resolved]
            if present and df[present].notna().any().any():
                found[col] = qf.period
    return found


def in_era_columns(cs: ConfigSet) -> list[str]:
    """Zero-fill targets that need a measured era start (no explicit one in the config)."""
    return [r.column for r in cs.zero_fill if r.scope == "in_era" and not r.era_start]


def write_era_cache(eras: dict[str, pd.Timestamp], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {"variable_name": list(eras), "era_start": [pd.Timestamp(v) for v in eras.values()]}
    ).to_parquet(path, index=False)
    return path


def read_era_cache(path: str | Path) -> dict[str, pd.Timestamp]:
    df = pd.read_parquet(path)
    return dict(zip(df.variable_name, pd.to_datetime(df.era_start), strict=True))
