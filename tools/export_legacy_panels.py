"""Emit the three legacy bec_migration panel files from a bankpanel build.

This is the cutover shim. BEC's pipeline reads ``assets.parquet``, ``liabilities.parquet``
and ``income_statement.parquet`` from one directory, by the legacy column names; this
writes exactly those files from a bankpanel panel root, so BEC can run on a bankpanel
build with no code change -- ``BEC_PANELS_DIR=<out> python -m pipeline.run --all``.

What it reproduces, and what it does not:

* **Column sets** come from the legacy files themselves (``--legacy-dir``), so each output
  carries the columns BEC expects and nothing else. A legacy column bankpanel withholds
  (its ``[INTERMEDIATE]`` detail pieces) is omitted with a note; none is read by BEC.
* **Names** are mapped back through ``reference_data/legacy_names.csv`` and the legacy
  quarterize rename (``ytd_X`` -> ``qX``).
* **Dtypes and order** match the legacy files: ``RSSD_ID`` float64, ``REPORTING_PERIOD``
  microsecond timestamps, rows sorted by (RSSD_ID, REPORTING_PERIOD). ``custody_bank`` is
  written back as the legacy ``"true"``/``"false"`` text. (Three legacy rows read ``"FALSE"``
  in capitals -- a filer's typing, which bankpanel normalises to 0 and this writes back as
  ``"false"``. BEC does not read the column.)
* **Values** are whatever the bankpanel build produced. Under ``--gap-policy keep`` that is
  bit-identical to legacy on every column except the ones deliberately fixed, which is the
  point: the difference in BEC's output is then exactly the effect of those fixes.

Usage:
    python tools/export_legacy_panels.py --panel-root <root> --out <dir>
        [--legacy-dir c:/.../bec_migration/data/call_reports/panels]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

KEYS = ["RSSD_ID", "REPORTING_PERIOD"]
LEGACY_FILES = ["assets", "liabilities", "income_statement"]
BOOLEAN_TEXT = {"custody_bank"}  # legacy stores these as "true"/"false" strings


def legacy_map() -> dict[str, str]:
    """Our name -> legacy name."""
    path = Path(__file__).resolve().parents[1] / "reference_data" / "legacy_names.csv"
    table = pd.read_csv(path, keep_default_na=False)
    return dict(zip(table["name"], table["legacy_name"], strict=True))


def to_legacy(name: str, renamed: dict[str, str]) -> str:
    if name in renamed:
        return renamed[name]
    if name.startswith("ytd_"):
        return "q" + name[4:]
    if name.startswith("ytd"):
        return "q" + name[3:]
    return name


def export(panel_root: Path, legacy_dir: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    dataset = ds.dataset(panel_root / "panel", partitioning="hive")
    renamed = legacy_map()
    ours_by_legacy = {to_legacy(c, renamed): c for c in dataset.schema.names if c not in KEYS}

    for name in LEGACY_FILES:
        template = pq.ParquetFile(legacy_dir / f"{name}.parquet").schema_arrow
        wanted = [f.name for f in template if f.name not in KEYS]
        have = [c for c in wanted if c in ours_by_legacy]
        missing = [c for c in wanted if c not in ours_by_legacy]

        table = dataset.to_table(columns=KEYS + [ours_by_legacy[c] for c in have])
        df = table.to_pandas().rename(columns={ours_by_legacy[c]: c for c in have})
        df = df.sort_values(KEYS).reset_index(drop=True)

        # Match the legacy file's own representation, not ours.
        df["RSSD_ID"] = df["RSSD_ID"].astype("float64")
        df["REPORTING_PERIOD"] = df["REPORTING_PERIOD"].astype("datetime64[us]")
        for col in BOOLEAN_TEXT & set(df.columns):
            df[col] = df[col].map({1.0: "true", 0.0: "false"}).astype("object")

        fields = [pa.field("RSSD_ID", pa.float64()), pa.field("REPORTING_PERIOD", pa.timestamp("us"))]
        for c in have:
            fields.append(pa.field(c, pa.large_string() if c in BOOLEAN_TEXT else pa.float64()))
        pq.write_table(
            pa.Table.from_pandas(df[KEYS + have], schema=pa.schema(fields), preserve_index=False),
            out / f"{name}.parquet", compression="snappy",
        )
        print(f"{name:<17} {len(df):>10,} rows x {len(have) + 2:>4} cols -> {out / (name + '.parquet')}")
        if missing:
            print(f"{'':<17} omitted {len(missing)} legacy column(s) bankpanel withholds: {missing}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--legacy-dir",
        default="c:/Users/Matthew/OneDrive/GitHub/bec_migration/data/call_reports/panels",
    )
    args = ap.parse_args()
    export(Path(args.panel_root), Path(args.legacy_dir), Path(args.out))
