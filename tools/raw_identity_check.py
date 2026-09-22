"""Regression guard without a legacy panel: every published BASE column equals its raw code.

For each base variable in a config set, read the raw code (and, for a coalesced pair, the
fallback code) from the quarterly files and compare cell for cell with the panel column,
over a sample of quarters or all of them. A base column may differ from its raw code only
where a config rule says so: the coalesce fallback, a zero-fill rule, or a text->number
coercion. Anything else is a construction defect.

Usage: python tools/raw_identity_check.py --profile fry9c --raw-dir <dir> --panel-root <root>
       [--quarters 1990Q4,2005Q4,2015Q4,2024Q4 | --all]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bankpanel.config import ConfigSet  # noqa: E402
from bankpanel.profiles import get_profile  # noqa: E402

CONFIG_DIRS = {"ffiec_call": "configs/call", "fry9c": "configs/y9c"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="ffiec_call", choices=list(CONFIG_DIRS))
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--panel-root", required=True)
    ap.add_argument("--quarters", default="1990Q4,2000Q4,2010Q4,2018Q4,2024Q4")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    cs = ConfigSet.load(ROOT / CONFIG_DIRS[args.profile])
    profile = get_profile(args.profile)
    zero_filled = {r.column for r in cs.zero_fill}
    withheld = cs.intermediate_columns()
    base = [v for v in cs.base if v.variable_name not in withheld]
    fallback_of = {p: f for p, f in profile.coalesce_rules}

    raw_files = sorted(Path(args.raw_dir).glob("*.parquet"))
    if not args.all:
        want = set(args.quarters.split(","))
        raw_files = [f for f in raw_files if f.stem in want]
    dataset = ds.dataset(Path(args.panel_root) / "panel", partitioning="hive")

    rows = []
    for f in raw_files:
        period = pd.Period(f.stem, freq="Q").end_time.normalize()
        names = set(pq.ParquetFile(f).schema_arrow.names)
        codes = {}
        for v in base:
            c = v.mdrm_code
            fb = fallback_of.get(c[:4])
            codes[v.variable_name] = (c if c in names else None, (fb + c[4:]) if fb and (fb + c[4:]) in names else None)
        need = sorted({c for pair in codes.values() for c in pair if c} | {profile.id_col})
        raw = pq.read_table(f, columns=need).to_pandas()
        raw[profile.id_col] = pd.to_numeric(raw[profile.id_col]).astype("int64")
        panel = dataset.to_table(columns=[profile.id_col] + [v.variable_name for v in base if v.variable_name in dataset.schema.names],
                                 filter=ds.field(profile.date_col) == period).to_pandas()
        m = panel.merge(raw, on=profile.id_col, how="left")
        for v in base:
            n = v.variable_name
            if n not in m.columns:
                continue
            primary, fb = codes[n]
            expected = pd.Series(np.nan, index=m.index)
            if primary:
                expected = pd.to_numeric(m[primary], errors="coerce")
            if fb:
                expected = expected.fillna(pd.to_numeric(m[fb], errors="coerce"))
            got = m[n]
            same = (got == expected) | (got.isna() & expected.isna())
            if n in zero_filled:
                same |= got.eq(0) & expected.isna()
            bad = int((~same).sum())
            if bad:
                rows.append({"quarter": f.stem, "column": n, "code": primary or fb, "n_rows": len(m), "n_diff": bad,
                             "example_got": got[~same].iloc[0], "example_raw": expected[~same].iloc[0]})
    rep = pd.DataFrame(rows)
    n_checked = len(base) * len(raw_files)
    print(f"{args.profile}: {len(base)} base columns x {len(raw_files)} quarters = {n_checked:,} column-quarters checked; "
          f"{len(rep)} differ")
    if len(rep):
        print(rep.sort_values("n_diff", ascending=False).head(25).to_string(index=False))
        rep.to_csv(ROOT / "review" / f"raw_identity_{args.profile}.csv", index=False)
    return 1 if len(rep) else 0


if __name__ == "__main__":
    raise SystemExit(main())
