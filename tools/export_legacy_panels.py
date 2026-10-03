"""Emit the three legacy bec_migration panel files from a bankpanel build.

This is the cutover shim. BEC's pipeline reads ``assets.parquet``, ``liabilities.parquet``
and ``income_statement.parquet`` from one directory, by the legacy column names; this
writes exactly those files from a bankpanel panel root, so BEC can run on a bankpanel
build with no code change -- ``BEC_PANELS_DIR=<out> python -m pipeline.run --all``.

What it reproduces, and what it does not:

* **Column sets** come from the legacy files themselves (``--legacy-dir``), so each output
  carries the columns BEC expects and nothing else. A legacy column bankpanel withholds
  (its ``[INTERMEDIATE]`` detail pieces) is omitted with a note; none is read by BEC.
* **Names** are mapped back through ``reference_data/legacy_names.csv``, including the
  legacy quarterize spellings (``q_int_inc`` -> ``qint_inc``). The as-filed ``ytd_``
  columns are not exported: the legacy files carried only the flows.
* **Dtypes and order** match the legacy files: ``RSSD_ID`` float64, ``REPORTING_PERIOD``
  microsecond timestamps, rows sorted by (RSSD_ID, REPORTING_PERIOD). ``custody_bank`` is
  written back as the legacy ``"true"``/``"false"`` text. (Three legacy rows read ``"FALSE"``
  in capitals -- a filer's typing, which bankpanel normalises to 0 and this writes back as
  ``"false"``. BEC does not read the column.)
* **Passthrough** (``PASSTHROUGH``): a few bankpanel columns BEC reads under their own
  names -- the successors of legacy names bankpanel retired or split -- are appended after
  the legacy set. Their absence from a build is an error, not an omission.
* **Values** are whatever the bankpanel build produced. Under ``--gap-policy keep`` that is
  bit-identical to legacy on every column except the ones deliberately fixed, which is the
  point: the difference in BEC's output is then exactly the effect of those fixes.

Usage:
    python tools/export_legacy_panels.py --panel-root <root> --out <dir>
        [--legacy-dir c:/.../bec_migration/data/call_reports/panels]
"""

from __future__ import annotations

import argparse
import os
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

# bankpanel columns BEC reads under their OWN names, appended after the legacy set. These
# are the successors of legacy names bankpanel retired or split (reference_data/
# legacy_retired.csv); BEC's cutover checklist records which stage consumes each.
PASSTHROUGH = {
    "assets": [
        "accrued_int_loans_pre01",  # imp2 coalesces: accrued_int.fillna(accrued_int_loans_pre01)
        "ln_cc_incl_revolving",     # p1/dd1/a1 cc_share (consistent 1984-present)
        "ln_consumer_oth",          # p1/a1 cons_share (consistent 1984-present)
        "ln_revolving_oth",         # B539, 2001-; kept next to the two above for audit
    ],
    "liabilities": [
        "pref_stock",               # RCFD3838, 1990-; a3 TCE / MATCE subtract it (STATA a3_combine_v2.do:91-94)
    ],
}


def legacy_map() -> dict[str, str]:
    """Our name -> legacy name."""
    path = Path(__file__).resolve().parents[1] / "reference_data" / "legacy_names.csv"
    table = pd.read_csv(path, keep_default_na=False)
    return dict(zip(table["name"], table["legacy_name"], strict=True))


def to_legacy(name: str, renamed: dict[str, str]) -> str:
    """Legacy spelling, from reference_data/legacy_names.csv (which carries the legacy
    quarterize spellings, q_int_inc -> qint_inc). ytd_ columns have no legacy twin."""
    return renamed.get(name, name)


def export(panel_root: Path, legacy_dir: Path, out: Path, start: str | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    dataset = ds.dataset(panel_root / "panel", partitioning="hive")
    renamed = legacy_map()
    ours_by_legacy = {to_legacy(c, renamed): c for c in dataset.schema.names if c not in KEYS}

    for name in LEGACY_FILES:
        template = pq.ParquetFile(legacy_dir / f"{name}.parquet").schema_arrow
        wanted = [f.name for f in template if f.name not in KEYS]
        have = [c for c in wanted if c in ours_by_legacy]
        missing = [c for c in wanted if c not in ours_by_legacy]
        extra = PASSTHROUGH.get(name, [])
        absent = [c for c in extra if c not in dataset.schema.names]
        if absent:
            raise SystemExit(f"{name}: passthrough column(s) not in this build: {absent}")

        # Arrow only, in row chunks: the pandas round trip held three copies of a 391-column
        # table (~13 GB peak) and tripped the machine's memory safeguard. Here the table is
        # held once; the sort is an index permutation and rows are written in slices.
        import pyarrow.compute as pc

        flt = None
        if start:   # e.g. BEC's panels begin 1985Q1 even though the build runs from 1976
            flt = ds.field("REPORTING_PERIOD") >= pa.scalar(pd.Timestamp(start).to_pydatetime(), pa.timestamp("us"))
        table = dataset.to_table(columns=KEYS + [ours_by_legacy[c] for c in have] + extra, filter=flt)
        table = table.rename_columns([{**{ours_by_legacy[c]: c for c in have}}.get(n, n) for n in table.column_names])
        have = have + extra   # the passthrough columns keep their own names
        order = pc.sort_indices(table.select(KEYS), sort_keys=[(k, "ascending") for k in KEYS])
        fields = [pa.field("RSSD_ID", pa.float64()), pa.field("REPORTING_PERIOD", pa.timestamp("us"))]
        for c in have:
            fields.append(pa.field(c, pa.large_string() if c in BOOLEAN_TEXT else pa.float64()))
        schema = pa.schema(fields)
        with pq.ParquetWriter(out / f"{name}.parquet", schema, compression="snappy") as writer:
            for row0 in range(0, len(order), 200_000):
                chunk = table.take(order.slice(row0, 200_000)).select([f.name for f in fields])
                cols = []
                for f in fields:
                    col = chunk[f.name]
                    if f.name in BOOLEAN_TEXT:
                        col = pc.if_else(pc.equal(col.cast(pa.float64()), 1.0), "true",
                                         pc.if_else(pc.equal(col.cast(pa.float64()), 0.0), "false", pa.scalar(None, pa.string()))).cast(pa.large_string())
                    else:
                        col = col.cast(f.type)
                    cols.append(col)
                writer.write_table(pa.table(cols, schema=schema))
        n_rows = len(order)
        print(f"{name:<17} {n_rows:>10,} rows x {len(have) + 2:>4} cols -> {out / (name + '.parquet')}")
        if missing:
            print(f"{'':<17} omitted {len(missing)} legacy column(s) bankpanel withholds: {missing}")
        if extra:
            print(f"{'':<17} appended {len(extra)} bankpanel column(s) under their own names: {extra}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--legacy-dir",
        default=os.environ.get("BANKPANEL_LEGACY_PANELS", "../bec_migration/data/call_reports/panels"),
    )
    ap.add_argument("--start", default=None, help="first REPORTING_PERIOD to export (YYYY-MM-DD)")
    args = ap.parse_args()
    export(Path(args.panel_root), Path(args.legacy_dir), Path(args.out), args.start)
