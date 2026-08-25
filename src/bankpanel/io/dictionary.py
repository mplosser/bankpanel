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
    "variable_name", "variable_type", "schedule", "flow_type", "unit", "sign",
    "mdrm_code", "form_scope", "era_start", "era_end", "description", "formula",
    "source_config",
]


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
    rows: list[dict[str, object]] = []

    for cfg in cs.configs:
        for var in cfg.base:
            rows.append({
                "variable_name": var.variable_name,
                "variable_type": "base",
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
                "source_config": cfg.path.name,
            })
        for var in cfg.derived:
            rows.append({
                "variable_name": var.variable_name,
                "variable_type": "derived",
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
                "source_config": cfg.path.name,
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
