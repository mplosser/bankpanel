"""Reading the raw quarterly files: discovery, column projection, prefix aliasing.

Two things here are load-bearing for the whole build.

**Projection.** A raw quarter has 2,600-4,100 columns; a config wants a few hundred. We
resolve the wanted MDRM codes to physical column names from the parquet *schema* (which
costs a footer read, not a data read) and pass that list to ``read_table``. Nothing else
is ever materialized.

**Loud failure.** The legacy engine wrapped each file in
``except Exception: print(...); continue``, so an unreadable quarter silently vanished
from the panel and the message scrolled past inside a progress bar. Here a bad file
raises; ``--keep-going`` is an explicit opt-in that records the casualty in the manifest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ..profiles import ReportProfile

_QUARTER_RE = re.compile(r"(\d{4})Q([1-4])", re.IGNORECASE)


class SourceError(Exception):
    """A raw file is missing, unreadable, or lacks the profile's key columns."""


@dataclass(frozen=True)
class QuarterFile:
    path: Path
    year: int
    quarter: int

    @property
    def period(self) -> pd.Timestamp:
        return pd.Period(f"{self.year}Q{self.quarter}", freq="Q").end_time.normalize()

    @property
    def label(self) -> str:
        return f"{self.year}Q{self.quarter}"


def discover_quarters(
    raw_dir: str | Path,
    profile: ReportProfile,
    *,
    years: tuple[int, int] | None = None,
) -> list[QuarterFile]:
    """Find quarterly files and parse their period from the filename."""
    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        raise SourceError(f"raw directory not found: {raw_dir}")

    found: list[QuarterFile] = []
    unparsed: list[str] = []
    for path in sorted(raw_dir.glob(profile.raw_glob)):
        match = _QUARTER_RE.search(path.stem)
        if not match:
            unparsed.append(path.name)
            continue
        year, quarter = int(match.group(1)), int(match.group(2))
        if years and not (years[0] <= year <= years[1]):
            continue
        found.append(QuarterFile(path=path, year=year, quarter=quarter))

    if not found:
        raise SourceError(
            f"no quarterly files matched {profile.raw_glob!r} in {raw_dir}"
            + (f" (skipped {len(unparsed)} unparseable names)" if unparsed else "")
        )
    return found


def schema_columns(path: Path) -> list[str]:
    """Column names, read from the parquet footer only."""
    return [name.upper() for name in pq.ParquetFile(path).schema_arrow.names]


def column_descriptions(path: Path) -> dict[str, str]:
    """MDRM labels from pyarrow field metadata, as written by ``data_call_report``."""
    out: dict[str, str] = {}
    for field in pq.ParquetFile(path).schema_arrow:
        if not field.metadata:
            continue
        desc = field.metadata.get(b"description", b"").decode("utf-8", "replace")
        if desc:
            out[field.name.upper()] = desc
    return out


def resolve_codes(
    wanted: list[str], available: set[str], profile: ReportProfile
) -> dict[str, str]:
    """Map each wanted MDRM code to the physical column that carries it, if any.

    Applies the profile's column-level prefix aliases (RCFA->RCOA, RCFW->RCOW): the same
    item filed under a different schedule suffix on a different form.
    """
    resolved: dict[str, str] = {}
    for code in wanted:
        if code in available:
            resolved[code] = code
            continue
        for src_prefix, dst_prefix in profile.prefix_aliases:
            if code.startswith(src_prefix):
                alt = dst_prefix + code[len(src_prefix):]
                if alt in available:
                    resolved[code] = alt
                    break
    return resolved


def read_quarter(
    qf: QuarterFile,
    wanted_codes: list[str],
    profile: ReportProfile,
    *,
    extra_columns: tuple[str, ...] = (),
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Read one quarter, projected to the columns actually needed.

    Returns the frame (with uppercase column names, keyed by the profile's id/date
    columns) and the ``code -> physical column`` resolution map for that quarter.
    """
    available = set(schema_columns(qf.path))
    for required in (profile.id_col, profile.date_col):
        if required not in available:
            raise SourceError(
                f"{qf.path.name}: missing key column {required!r}. "
                f"Is this a {profile.name} file?"
            )

    resolved = resolve_codes(wanted_codes, available, profile)
    physical = list(dict.fromkeys(
        [profile.id_col, profile.date_col]
        + list(resolved.values())
        + [c for c in extra_columns if c in available]
    ))

    table = pq.read_table(qf.path, columns=physical)
    df = table.to_pandas()
    df.columns = [str(c).upper() for c in df.columns]

    df[profile.id_col] = pd.to_numeric(df[profile.id_col], errors="coerce").astype("int64")
    # Set the period from the filename rather than reading it per row. Verified across
    # all 163 upstream files: each carries exactly one distinct REPORTING_PERIOD and it
    # always equals the filename's quarter. Deriving it makes the partition label and
    # the date column incapable of drifting apart, and normalizes the timestamp.
    df[profile.date_col] = qf.period
    return df, resolved
