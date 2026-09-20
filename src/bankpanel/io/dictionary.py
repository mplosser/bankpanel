"""The data dictionary: the panel's self-documentation, shipped alongside it.

Every column in the panel appears here with its MDRM code (or formula), its schedule, its
era bounds, and the official MDRM label pulled from the source parquet's field metadata.
A panel without this is a wall of 2,000 opaque column names.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..build.source import QuarterFile, column_descriptions
from ..config import ConfigSet

DICTIONARY_COLUMNS = [
    "variable_name", "variable_type", "published", "schedule", "flow_type", "unit", "sign",
    "mdrm_code", "form_scope", "era_start", "era_end", "description", "formula", "inputs",
    "source_config",
]

#: Measured columns appended by :func:`measure_dictionary`. Kept separate because they
#: describe one *built panel*, not the configs -- rebuild with different raw data and
#: these change while everything above stays put.
MEASURED_COLUMNS = ["n_obs", "coverage", "first_quarter", "last_quarter", "pct_zero", "total"]


def collect_descriptions(quarters: list[QuarterFile], codes: set[str]) -> dict[str, str]:
    """Accumulate MDRM labels across quarters, first occurrence wins.

    Reads parquet footers only, never data. Scanning every quarter rather than just the
    newest matters: a code retired in 1996 has no label in a 2025 file.
    """
    out: dict[str, str] = {}
    for qf in quarters:
        for code, desc in column_descriptions(qf.path).items():
            if code in codes and code not in out:
                out[code] = desc
    return out


def build_dictionary(cs: ConfigSet, descriptions: dict[str, str] | None = None) -> pd.DataFrame:
    """One row per panel column."""
    descriptions = descriptions or {}
    withheld = cs.intermediate_columns()
    deps = cs.graph.deps
    rows: list[dict[str, object]] = []

    for cfg in cs.configs:
        for var in cfg.base:
            rows.append({
                "variable_name": var.variable_name,
                "variable_type": "base",
                "published": var.variable_name not in withheld,
                "schedule": var.schedule,
                "flow_type": var.flow_type,
                "unit": "thousands_usd" if var.flow_type in ("stock", "ytd") else "",
                "sign": var.sign,
                "mdrm_code": var.mdrm_code,
                "form_scope": var.form_scope,
                "era_start": var.era_start or "",
                "era_end": var.era_end or "",
                # Prefer the official MDRM label; fall back to the config's own note.
                "description": descriptions.get(var.mdrm_code, "") or var.notes,
                "formula": "",
                "inputs": "",
                "source_config": cfg.path.name,
            })
        for var in cfg.derived:
            rows.append({
                "variable_name": var.variable_name,
                "variable_type": "derived",
                "published": var.variable_name not in withheld,
                "schedule": var.schedule,
                "flow_type": var.flow_type,
                "unit": var.unit,
                "sign": var.sign,
                "mdrm_code": "",
                "form_scope": "",
                "era_start": "",
                "era_end": "",
                "description": var.description,
                "formula": var.formula,
                "inputs": " ".join(sorted(deps.get(var.variable_name, ()))),
                "source_config": cfg.path.name,
            })

    by_name = {r["variable_name"]: r for r in rows}
    for ytd_name, flow_name in cs.flow_columns().items():
        src = by_name[ytd_name]
        rows.append({
            **src,
            "variable_name": flow_name,
            "variable_type": "flow",
            "published": True,
            "flow_type": "quarterly",
            "mdrm_code": "",
            "description": f"Quarterly flow of {ytd_name}: {src['description']}",
            "formula": (f"{ytd_name}(t) - {ytd_name}(t-1) within the bank-year; Q1 = {ytd_name}; "
                        f"NaN where the prior quarter is missing or blank (an annual filer's "
                        f"Q4 total stays in {ytd_name}, its flows are NaN)"),
            "inputs": ytd_name,
        })

    return pd.DataFrame(rows, columns=DICTIONARY_COLUMNS)


def write_dictionary(df: pd.DataFrame, root: Path) -> tuple[Path, Path]:
    """Write ``dictionary.csv`` and a human-readable ``dictionary.md``."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    csv_path = root / "dictionary.csv"
    df.to_csv(csv_path, index=False)

    lines = ["# Data dictionary", ""]
    lines.append(f"{len(df)} columns across {df.schedule.nunique()} schedules.")
    lines.append("")
    for schedule, group in df.groupby("schedule", sort=True):
        lines.append(f"## {schedule}")
        lines.append("")
        lines.append("| variable | type | flow | source | description |")
        lines.append("| --- | --- | --- | --- | --- |")
        for _, row in group.iterrows():
            source = row["mdrm_code"] or f"`{row['formula']}`"
            desc = str(row["description"]).replace("|", r"\|")
            lines.append(
                f"| `{row['variable_name']}` | {row['variable_type']} | "
                f"{row['flow_type']} | {source} | {desc} |"
            )
        lines.append("")
    md_path = root / "dictionary.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, md_path


def measure_dictionary(df: pd.DataFrame, panel_root: str | Path) -> pd.DataFrame:
    """Append measured coverage to the config-derived dictionary.

    Scans the panel one **year partition at a time** and accumulates counts. Reading the
    whole panel to describe it would need ~12 GB for a 1,000-column build, which is a
    silly amount of memory to spend on a summary; per-partition accumulation costs one
    year's worth at a time and gives identical answers for every statistic here.

    ``total`` is a sum rather than a median for the same reason: sums accumulate across
    partitions, order statistics do not.
    """
    import pyarrow.dataset as pads

    root = Path(panel_root)
    dataset = pads.dataset(root / "panel", partitioning="hive")
    available = [c for c in df.variable_name if c in dataset.schema.names]

    n_rows = 0
    obs = pd.Series(0, index=available, dtype="int64")
    nonzero = pd.Series(0, index=available, dtype="int64")
    total = pd.Series(0.0, index=available, dtype="float64")
    first: dict[str, pd.Period] = {}
    last: dict[str, pd.Period] = {}

    for fragment in sorted(dataset.get_fragments(), key=lambda f: f.path):
        part = fragment.to_table(columns=["REPORTING_PERIOD", *available]).to_pandas()
        n_rows += len(part)
        period = pd.PeriodIndex(part.REPORTING_PERIOD, freq="Q")
        filled = part[available].notna()
        obs += filled.sum()
        nonzero += (part[available].fillna(0) != 0).sum()
        total += part[available].sum()
        for column in available:
            mask = filled[column].to_numpy()
            if not mask.any():
                continue
            seen = period[mask]
            lo, hi = seen.min(), seen.max()
            if column not in first or lo < first[column]:
                first[column] = lo
            if column not in last or hi > last[column]:
                last[column] = hi

    measured = pd.DataFrame({
        "variable_name": available,
        "n_obs": obs.reindex(available).to_numpy(),
        "coverage": (obs.reindex(available) / n_rows).round(4).to_numpy(),
        "first_quarter": [str(first.get(c, "")) for c in available],
        "last_quarter": [str(last.get(c, "")) for c in available],
        # Share of REPORTED values that are exactly zero. A column at 0.99 here is
        # technically covered and analytically empty -- the distinction coverage alone
        # cannot make, and the one that decided which RC-N itemisations to publish.
        # NaN where the column has no observations at all: "share of reported values
        # that are zero" is undefined, not zero, when nothing was reported.
        "pct_zero": (
            1 - nonzero.reindex(available) / obs.reindex(available).where(lambda s: s > 0)
        ).round(4).to_numpy(),
        "total": total.reindex(available).round(0).to_numpy(),
    })
    return df.merge(measured, on="variable_name", how="left")
