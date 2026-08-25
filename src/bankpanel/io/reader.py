"""Reading the panel.

This module is the contract with users, and it is deliberately a little opinionated.

``columns`` is **required**. A finished panel is ~2,000 float64 columns over ~1.4M
bank-quarters; materializing all of it is ~23 GB and nobody wants it. Parquet is a column
store, so asking for the twelve columns you need costs roughly what a twelve-column file
would. Making ``columns=None`` mean "everything" would turn the single most convenient
call into the single worst one, so it raises instead and points at the discovery helpers.

The same reasoning drives ``max_memory_gb``: the size of a request is knowable from
partition metadata before any data is read, so an accidental 40 GB request should fail
in milliseconds with an explanation rather than after ten minutes of swapping.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds

from ..build.writer import BuildManifest

WARN_COLUMNS = 250
KEY_COLUMNS = ("RSSD_ID", "REPORTING_PERIOD")


class PanelTooLargeError(MemoryError):
    """The requested slice exceeds the caller's memory budget."""


class PanelNotFoundError(FileNotFoundError):
    pass


def default_root() -> Path:
    """Panel root from ``BANKPANEL_PANEL_ROOT``, else ``./panel_root``."""
    return Path(os.environ.get("BANKPANEL_PANEL_ROOT", "panel_root"))


def _resolve_root(root: str | Path | None) -> Path:
    path = Path(root) if root is not None else default_root()
    if not (path / "panel").is_dir():
        raise PanelNotFoundError(
            f"no panel dataset at {path / 'panel'}. Build one with 'bankpanel build', "
            f"or set BANKPANEL_PANEL_ROOT."
        )
    return path


def _dataset(root: Path, name: str) -> ds.Dataset:
    return ds.dataset(root / name, partitioning="hive")


def _period_bounds(start: str | None, end: str | None) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    lo = pd.Period(start, freq="Q").start_time if start else None
    hi = pd.Period(end, freq="Q").end_time.normalize() if end else None
    return lo, hi


def _filter_expression(start: str | None, end: str | None, form_types: tuple[int, ...] | None):
    expr = None
    lo, hi = _period_bounds(start, end)
    if lo is not None:
        expr = ds.field("REPORTING_PERIOD") >= pd.Timestamp(lo)
    if hi is not None:
        clause = ds.field("REPORTING_PERIOD") <= pd.Timestamp(hi)
        expr = clause if expr is None else expr & clause
    if form_types:
        clause = pc.is_in(ds.field("form_type"), value_set=pa.array(list(form_types), type=pa.int8()))
        expr = clause if expr is None else expr & clause
    return expr


def _estimate_rows(dataset: ds.Dataset, start: str | None, end: str | None) -> int:
    """Row count for the requested window, from partition statistics."""
    lo, hi = _period_bounds(start, end)
    total = 0
    for fragment in dataset.get_fragments():
        year = None
        for part in str(fragment.path).replace("\\", "/").split("/"):
            if part.startswith("year="):
                year = int(part.split("=", 1)[1])
        if year is not None:
            if lo is not None and year < lo.year:
                continue
            if hi is not None and year > hi.year:
                continue
        total += fragment.count_rows()
    return total


def read_panel(
    columns: list[str] | None = None,
    *,
    start: str | None = None,
    end: str | None = None,
    form_types: tuple[int, ...] | None = None,
    with_header: bool = False,
    dtype: str = "float64",
    max_memory_gb: float = 4.0,
    force: bool = False,
    verify: bool = True,
    root: str | Path | None = None,
) -> pd.DataFrame:
    """Read selected columns of the panel.

    Parameters
    ----------
    columns
        Variable names to read. Required. Keys and ``form_type`` are added automatically.
    start, end
        Quarter strings such as ``'2000Q1'``.
    form_types
        Restrict to filers of these FFIEC forms, e.g. ``(41,)``. Note this *filters banks*,
        not just columns -- see docs/CAVEATS.md on building a form-consistent panel.
    dtype
        ``'float64'`` (default) or ``'float32'``. float32 halves memory but its 24-bit
        mantissa is exact only to 16,777,216; values are in thousands of USD, so balances
        above ~$16.8bn lose exactness and accounting identities stop closing exactly.
    """
    panel_root = _resolve_root(root)
    if not columns:
        raise ValueError(
            "read_panel(columns=...) is required. The panel is far too wide to load "
            "whole. Discover columns with list_variables(), columns_for_schedule('RC-C'), "
            "or search_variables('nonaccrual')."
        )
    if verify:
        _verify(panel_root)

    dataset = _dataset(panel_root, "panel")
    available = set(dataset.schema.names)
    missing = [c for c in columns if c not in available]
    if missing:
        raise KeyError(
            f"not in this panel: {missing}. Check dictionary.csv, or rebuild if the "
            f"config has changed since this panel was built."
        )

    wanted = list(dict.fromkeys([*KEY_COLUMNS, "form_type", *columns]))
    if len(wanted) > WARN_COLUMNS:
        warnings.warn(
            f"reading {len(wanted)} columns; consider narrowing the request.",
            stacklevel=2,
        )

    n_rows = _estimate_rows(dataset, start, end)
    itemsize = 4 if dtype == "float32" else 8
    est_gb = n_rows * len(columns) * itemsize / 1024**3
    if est_gb > max_memory_gb and not force:
        raise PanelTooLargeError(
            f"request is about {est_gb:.1f} GB ({n_rows:,} rows x {len(columns)} columns "
            f"x {itemsize} bytes), over the {max_memory_gb} GB budget. Narrow columns or "
            f"the date range, raise max_memory_gb, or pass force=True."
        )

    table = dataset.to_table(columns=wanted, filter=_filter_expression(start, end, form_types))
    df = table.to_pandas()

    if dtype == "float32":
        floats = [c for c in df.columns if pd.api.types.is_float_dtype(df[c])]
        df[floats] = df[floats].astype("float32")

    df = df.sort_values(list(KEY_COLUMNS)).reset_index(drop=True)
    if with_header:
        df = df.merge(read_header(start=start, end=end, root=panel_root), on=list(KEY_COLUMNS), how="left")
    return df


def read_header(
    *,
    start: str | None = None,
    end: str | None = None,
    columns: list[str] | None = None,
    root: str | Path | None = None,
) -> pd.DataFrame:
    """Read the narrow identity dataset (names, addresses, charter numbers, form type)."""
    panel_root = _resolve_root(root)
    dataset = _dataset(panel_root, "header")
    wanted = None
    if columns:
        wanted = list(dict.fromkeys([*KEY_COLUMNS, *columns]))
    table = dataset.to_table(columns=wanted, filter=_filter_expression(start, end, None))
    return table.to_pandas().sort_values(list(KEY_COLUMNS)).reset_index(drop=True)


# --- discovery -------------------------------------------------------------------


def dictionary(root: str | Path | None = None) -> pd.DataFrame:
    panel_root = _resolve_root(root)
    path = panel_root / "dictionary.csv"
    if not path.exists():
        raise PanelNotFoundError(f"no dictionary.csv at {path}")
    return pd.read_csv(path, keep_default_na=False)


def list_variables(schedule: str | None = None, root: str | Path | None = None) -> pd.DataFrame:
    df = dictionary(root)
    if schedule:
        df = df[df.schedule.str.upper() == schedule.upper()]
    return df.reset_index(drop=True)


def columns_for_schedule(schedule: str, root: str | Path | None = None) -> list[str]:
    return list_variables(schedule, root).variable_name.tolist()


def search_variables(pattern: str, root: str | Path | None = None) -> pd.DataFrame:
    df = dictionary(root)
    hit = (
        df.variable_name.str.contains(pattern, case=False, regex=True)
        | df.description.str.contains(pattern, case=False, regex=True)
    )
    return df[hit].reset_index(drop=True)


EXPECTATIONS_FILE = "reporting_expectations.parquet"


def expectations(root: str | Path | None = None) -> pd.DataFrame:
    """The reporting-expectations matrix built from this panel."""
    from ..reference.expectations import read_expectations

    panel_root = _resolve_root(root)
    path = panel_root / EXPECTATIONS_FILE
    if not path.exists():
        raise PanelNotFoundError(
            f"no {EXPECTATIONS_FILE} in {panel_root}. Run 'bankpanel expectations build' "
            f"first -- without it a NaN cannot be told apart from an item that was never "
            f"collected."
        )
    return read_expectations(path)


def expected_mask(
    df: pd.DataFrame, column: str, root: str | Path | None = None
) -> pd.Series:
    """Was each cell of ``column`` supposed to be reported?

    Separates "not collected" from "reported as missing" -- the distinction that makes a
    NaN interpretable. Needs ``form_type`` and ``REPORTING_PERIOD`` in ``df``, both of
    which :func:`read_panel` always returns.
    """
    from ..reference.expectations import expected_mask as _mask

    return _mask(df, column, expectations(root))


def info(root: str | Path | None = None) -> dict:
    panel_root = _resolve_root(root)
    return BuildManifest.read(panel_root).__dict__


def _verify(panel_root: Path) -> None:
    """Warn if the configs on disk no longer match the ones that built this panel."""
    try:
        manifest = BuildManifest.read(panel_root)
    except FileNotFoundError:
        warnings.warn(f"no build manifest in {panel_root}; cannot verify provenance.", stacklevel=3)
        return
    config_dir = Path("configs")
    if not config_dir.is_dir():
        return
    try:
        from ..config import ConfigSet

        current = ConfigSet.load(config_dir).config_hash()
    except Exception:
        return
    if current != manifest.config_hash:
        warnings.warn(
            f"configs in {config_dir.resolve()} have changed since this panel was built "
            f"({manifest.config_hash} -> {current}). Rebuild, or pass verify=False.",
            stacklevel=3,
        )
