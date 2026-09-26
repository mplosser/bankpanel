"""Writing the partitioned dataset and its build manifest.

Layout::

    panel_root/
      _build_manifest.json
      dictionary.csv
      panel/  year=1985/part-0.parquet ... year=2025/part-0.parquet
      header/ year=1985/part-0.parquet ...
      quarterize_gaps.parquet

Partitioned by **year**, not quarter. Two reasons, and the second is the important one:
year gives ~41 files of a sensible size rather than 163 tiny ones, and -- decisively --
year-to-date accumulation resets annually, so partitioning by year makes quarterization
strictly partition-local. Build and quarterize then collapse into a single parallel pass
with no global state. Quarter partitioning would break that.

Compression is zstd rather than snappy: the panel is sparse float64 with long NaN runs,
which zstd handles far better at negligible read cost.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

COMPRESSION = "zstd"
COMPRESSION_LEVEL = 3
ROW_GROUP_SIZE = 25_000


def _conform(df: pd.DataFrame, schema: pa.Schema) -> pa.Table:
    """Coerce a frame to the frozen schema, adding missing fields as nulls."""
    missing = [f.name for f in schema if f.name not in df.columns]
    for name in missing:
        df[name] = pd.NA
    ordered = df[[f.name for f in schema]]
    return pa.Table.from_pandas(ordered, schema=schema, preserve_index=False)


def write_partition(
    df: pd.DataFrame, root: Path, dataset: str, year: int, schema: pa.Schema
) -> Path:
    """Write one year's slice of one dataset."""
    out_dir = root / dataset / f"year={year}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "part-0.parquet"
    pq.write_table(
        _conform(df, schema),
        path,
        compression=COMPRESSION,
        compression_level=COMPRESSION_LEVEL,
        row_group_size=ROW_GROUP_SIZE,
    )
    return path


@dataclass
class BuildManifest:
    """What produced this panel, recorded so a reader can detect drift."""

    bankpanel_version: str
    profile: str
    config_hash: str
    config_files: list[str]
    raw_dir: str
    gap_policy: str
    years: list[int] = field(default_factory=list)
    n_rows: int = 0
    n_columns: int = 0
    date_min: str = ""
    date_max: str = ""
    built_at: str = ""
    failures: list[str] = field(default_factory=list)

    def write(self, root: Path) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / "_build_manifest.json"
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path

    @classmethod
    def read(cls, root: str | Path) -> BuildManifest:
        path = Path(root) / "_build_manifest.json"
        if not path.exists():
            raise FileNotFoundError(
                f"no build manifest at {path}. Is {root} a bankpanel panel root?"
            )
        return cls(**json.loads(path.read_text(encoding="utf-8")))
