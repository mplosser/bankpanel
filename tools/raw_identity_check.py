"""Regression guard without a legacy panel: every published BASE column equals its raw code.

For each base variable in a config set, read the raw code (and, for a coalesced pair, the
fallback code) from the quarterly files and compare cell for cell with the panel column,
over a sample of quarters or all of them. A base column may differ from its raw code only
where a config rule says so: the coalesce fallback, a zero-fill rule, a [BLANK_ANNUAL_ZEROS]
rule, the consolidated-vs-domestic rule, or a text->number
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
from bankpanel.build.quarter import to_numeric  # noqa: E402
from bankpanel.config import ConfigSet  # noqa: E402
from bankpanel.profiles import get_profile  # noqa: E402
from bankpanel.reference import scope as scope_ref  # noqa: E402

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
    blank_until = {r.column: pd.Timestamp(r.era_end) for r in cs.blank_annual_zeros}
    withheld = cs.intermediate_columns()
    base = [v for v in cs.base if v.variable_name not in withheld]
    fallback_of = dict(profile.coalesce_rules)

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
        twin_of = dict(profile.domestic_pairs) | {b: a for a, b in profile.domestic_pairs}
        twins = {n: (twin_of[v.mdrm_code[:4]] + v.mdrm_code[4:]) for v in base
                 if v.mdrm_code[:4] in twin_of and (twin_of[v.mdrm_code[:4]] + v.mdrm_code[4:]) in names
                 for n in [v.variable_name]}
        extra = [c for c in profile.source_columns if c in names]
        need = sorted({c for pair in codes.values() for c in pair if c} | set(twins.values()) | set(extra) | {profile.id_col})
        raw = pq.read_table(f, columns=need).to_pandas()
        # the official consolidated-vs-domestic rule, re-derived here from the raw file so the check
        # stays independent of the builder: international banks get no domestic fill, and a code
        # outside its MDRM window that equals its twin is an upstream copy (blank)
        form = profile.form_type_resolver(raw) if profile.form_type_resolver else pd.DataFrame(index=raw.index)
        intl = profile.foreign_offices(raw, form)[0] if profile.foreign_offices else pd.Series(False, index=raw.index)
        raw["_intl"] = intl.to_numpy()
        raw[profile.id_col] = pd.to_numeric(raw[profile.id_col]).astype("int64")
        panel = dataset.to_table(columns=[profile.id_col] + [v.variable_name for v in base if v.variable_name in dataset.schema.names],
                                 filter=ds.field(profile.date_col) == period).to_pandas()
        m = panel.merge(raw, on=profile.id_col, how="left")
        # [BLANK_ANNUAL_ZEROS]: a Q1-Q3 zero may be published blank when the bank's Q4 value
        # that year is non-zero (read from the panel's own Q4, which that rule never touches)
        q4 = None
        if period.quarter < 4 and any(period <= e for e in blank_until.values()):
            cols = [c for c in blank_until if c in dataset.schema.names]
            q4 = dataset.to_table(columns=[profile.id_col, *cols], filter=ds.field(profile.date_col) == pd.Timestamp(f"{period.year}-12-31")).to_pandas()
            q4 = m[[profile.id_col]].merge(q4, on=profile.id_col, how="left")
        for v in base:
            n = v.variable_name
            if n not in m.columns:
                continue
            primary, fb = codes[n]
            expected = pd.Series(np.nan, index=m.index)
            intl_m = m["_intl"].fillna(False).astype(bool)
            if primary:
                expected = to_numeric(m[primary])
                tw = twins.get(n)
                if tw and not scope_ref.collected(profile.name, v.mdrm_code, period):
                    t = to_numeric(m[tw])
                    expected = expected.mask(intl_m & expected.notna() & t.notna() & expected.eq(t))
            if fb:
                fill = to_numeric(m[fb])
                if (v.mdrm_code[:4], fb[:4]) in set(profile.domestic_pairs):
                    fill = fill.where(~intl_m)
                expected = expected.fillna(fill)
            got = m[n]
            same = (got == expected) | (got.isna() & expected.isna())
            if n in zero_filled:
                same |= got.eq(0) & expected.isna()
            if q4 is not None and n in blank_until and period <= blank_until[n]:
                same |= got.isna() & expected.eq(0) & q4[n].fillna(0).ne(0).to_numpy()
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
