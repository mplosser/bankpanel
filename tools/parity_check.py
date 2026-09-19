"""Compare a bankpanel build against the legacy bec_migration panels, column by column.

This is the acceptance test for the migration. A column passes when every cell matches,
treating NaN as equal to NaN. Anything else is either a bug or a deliberate, explained
difference -- and the point of the exercise is to force each one into one of those boxes.

Column names differ in one systematic way. The legacy pipeline encoded "this is a
year-to-date item" in the *name* and renamed it during quarterization (``ytd_int_inc`` ->
``qint_inc``). bankpanel encodes it in ``flow_type`` and leaves the name alone, so the
comparison applies the legacy rename map to line the two up.

Usage:
    python tools/parity_check.py --panel-root ... --legacy-dir ...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bankpanel.build.quarter import to_numeric  # noqa: E402

KEYS = ["RSSD_ID", "REPORTING_PERIOD"]

LEGACY_PANELS = {
    "assets": "assets.parquet",
    "liabilities": "liabilities.parquet",
    "income_statement": "income_statement.parquet",
}


def _renamed() -> dict[str, str]:
    """Our name -> legacy name, from reference_data/legacy_names.csv.

    A column renamed for the public API is still the same series, and parity must keep
    comparing it. Without this map a rename silently drops the column out of the shared
    set and parity reports fewer columns, all green -- a regression guard that forgets
    what it was guarding.
    """
    path = Path(__file__).resolve().parents[1] / "reference_data" / "legacy_names.csv"
    if not path.exists():
        return {}
    table = pd.read_csv(path, keep_default_na=False)
    return dict(zip(table["name"], table["legacy_name"], strict=True))


RENAMED = _renamed()


def legacy_name(name: str) -> str:
    """Our column name as the legacy panels spelled it.

    Two transforms: the legacy quarterize rename (ytd_X -> qX, ytdX -> qX) and the
    explicit public-API renames recorded in reference_data/legacy_names.csv.
    """
    if name in RENAMED:
        return RENAMED[name]
    if name.startswith("ytd_"):
        return "q" + name[4:]
    if name.startswith("ytd"):
        return "q" + name[3:]
    return name


def compare_column(ours: pd.Series, theirs: pd.Series) -> dict:
    """Cell-by-cell comparison treating NaN as equal to NaN.

    Both sides go through the builder's own coercion, which maps boolean text to 1/0.
    Plain ``to_numeric`` would turn a "true"/"false" column into all-NaN on both sides
    and then declare the two identical -- a false pass that hid a genuinely missing
    column here until an all-NaN audit caught it. ``lost_to_coercion`` records any cell
    that had a value before coercion and none after, so the failure mode cannot recur
    silently.
    """
    a_series, b_series = to_numeric(ours), to_numeric(theirs)
    lost = int(
        ((ours.notna() & a_series.isna()).sum())
        + ((theirs.notna() & b_series.isna()).sum())
    )
    a = a_series.to_numpy(dtype="float64")
    b = b_series.to_numpy(dtype="float64")
    both_nan = np.isnan(a) & np.isnan(b)
    equal = (a == b) | both_nan
    n_diff = int((~equal).sum())
    out = {
        "n": len(a),
        "n_diff": n_diff,
        "lost_to_coercion": lost,
        "ours_nonnull": int((~np.isnan(a)).sum()),
        "theirs_nonnull": int((~np.isnan(b)).sum()),
    }
    if n_diff:
        d = np.abs(a[~equal] - b[~equal])
        finite = d[np.isfinite(d)]
        out["max_abs_diff"] = float(finite.max()) if finite.size else float("nan")
        out["n_nan_mismatch"] = int((np.isnan(a[~equal]) | np.isnan(b[~equal])).sum())
    return out


def run(panel_root: Path, legacy_dir: Path, limit: int | None = None) -> pd.DataFrame:
    dataset = ds.dataset(panel_root / "panel", partitioning="hive")
    ours_cols = set(dataset.schema.names)
    rows = []

    for label, fname in LEGACY_PANELS.items():
        path = legacy_dir / fname
        if not path.exists():
            print(f"[skip] {path} not found")
            continue

        legacy = pd.read_parquet(path)
        legacy["REPORTING_PERIOD"] = pd.to_datetime(legacy["REPORTING_PERIOD"])
        legacy["RSSD_ID"] = pd.to_numeric(legacy["RSSD_ID"]).astype("int64")

        # Map legacy column -> our column name.
        pairs = {}
        for ours in ours_cols:
            theirs = legacy_name(ours)
            if theirs in legacy.columns and ours not in KEYS:
                pairs[ours] = theirs
        if not pairs:
            print(f"[skip] no shared columns with {label}")
            continue
        if limit:
            pairs = dict(list(pairs.items())[:limit])

        ours_df = dataset.to_table(columns=KEYS + list(pairs)).to_pandas()
        merged = ours_df.merge(
            legacy[KEYS + list(pairs.values())], on=KEYS, how="inner", suffixes=("", "__legacy")
        )
        print(
            f"\n{label}: legacy {len(legacy):,} rows x {legacy.shape[1]} cols | "
            f"ours {len(ours_df):,} rows | joined {len(merged):,} | {len(pairs)} shared columns"
        )

        for ours_col, theirs_col in pairs.items():
            right = theirs_col if theirs_col != ours_col else f"{ours_col}__legacy"
            if right not in merged.columns:
                right = theirs_col
            res = compare_column(merged[ours_col], merged[right])
            res.update(panel=label, column=ours_col, legacy_column=theirs_col)
            rows.append(res)

    return pd.DataFrame(rows)


def report(df: pd.DataFrame, *, n_unchecked: int = 0) -> None:
    """Print the comparison, and say plainly what it does NOT cover.

    Parity compares only the columns this panel shares with the legacy panels. Every
    column defined by a config with no legacy counterpart -- which is where new schedule
    work happens -- is outside its scope, so "688/688, 100%" holds no matter what that
    work does. Reporting a match rate without its denominator invites reading a
    regression guard on inherited columns as a correctness proof for the whole panel.
    """
    if df.empty:
        print("nothing compared")
        return
    total = len(df)
    exact = int((df.n_diff == 0).sum())
    print("\n" + "=" * 78)
    print(f"PARITY: {exact}/{total} columns match exactly ({exact / total:.2%})")
    if n_unchecked:
        covered = total / (total + n_unchecked)
        print(f"SCOPE:  {total} of {total + n_unchecked} panel columns ({covered:.0%}). "
              f"{n_unchecked} have no legacy")
        print("        counterpart and are NOT checked here. Parity is a regression guard")
        print("        on inherited columns, not a correctness check on new ones.")
    print("=" * 78)
    lost = df[df.get("lost_to_coercion", 0) > 0]
    if not lost.empty:
        print(f"\n{len(lost)} column(s) lost values to numeric coercion on one side:")
        print(lost[["panel", "column", "lost_to_coercion"]].to_string(index=False))

    bad = df[df.n_diff > 0].sort_values("n_diff", ascending=False)
    if bad.empty:
        print("no differences")
        return
    print(f"\n{len(bad)} column(s) differ:\n")
    show = bad[[
        "panel", "column", "n", "n_diff", "ours_nonnull", "theirs_nonnull",
        "n_nan_mismatch", "max_abs_diff",
    ]].head(40)
    print(show.to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel-root", required=True)
    ap.add_argument(
        "--legacy-dir",
        default="c:/Users/Matthew/OneDrive/GitHub/bec_migration/data/call_reports/panels",
    )
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    result = run(Path(args.panel_root), Path(args.legacy_dir), args.limit)

    import pyarrow.dataset as _ds

    panel_cols = set(_ds.dataset(Path(args.panel_root) / "panel", partitioning="hive").schema.names)
    panel_cols -= {"RSSD_ID", "REPORTING_PERIOD", "form_type", "year"}
    report(result, n_unchecked=len(panel_cols - set(result.column)))
    if args.out:
        result.to_csv(args.out, index=False)
        print(f"\nfull results -> {args.out}")
