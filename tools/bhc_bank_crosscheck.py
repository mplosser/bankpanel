"""Cross-report plausibility check: a holding company against its subsidiary banks.

For each (holding company, quarter) in the FR Y-9C panel, sum the Call Report values of the
banks it owns (the BEC entity classification's ``hh_entity`` link) and compare with the BHC's
consolidated figure. The two are not an identity -- the parent has its own assets and debt,
non-bank subsidiaries exist, intercompany balances net out -- so the check reports the
distribution of bank-sum / BHC ratios, not exact matches. What it guards is the shared
naming: if ``assets`` on one panel were not the same concept as ``assets`` on the other, the
ratio would not sit near 1 for one-bank holding companies.

Usage: python tools/bhc_bank_crosscheck.py --call-root <root> --y9c-root <root> --classification <parquet>
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ITEMS = ["assets", "ll_net_unearned", "dom_deposit_ib", "dom_deposit_nib", "ytd_int_inc", "ytd_net_inc", "cet1", "tier1_capital"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--call-root", required=True)
    ap.add_argument("--y9c-root", required=True)
    ap.add_argument("--classification", required=True, help="BEC entity_classification.parquet (entity, date, hh_entity)")
    ap.add_argument("--start", default="1997-01-01")
    args = ap.parse_args()

    cls = pd.read_parquet(args.classification, columns=["entity", "date", "hh_entity"]).dropna(subset=["hh_entity"])
    cls["hh_entity"] = cls.hh_entity.astype("int64")
    call = ds.dataset(f"{args.call_root}/panel", partitioning="hive")
    items = [c for c in ITEMS if c in call.schema.names]
    bank = call.to_table(columns=["RSSD_ID", "REPORTING_PERIOD"] + items,
                         filter=ds.field("REPORTING_PERIOD") >= pd.Timestamp(args.start)).to_pandas()
    bank = bank.rename(columns={"RSSD_ID": "entity", "REPORTING_PERIOD": "date"}).merge(cls, on=["entity", "date"])
    n_banks = bank.groupby(["hh_entity", "date"]).entity.transform("size")
    bank["one_bank"] = n_banks == 1
    agg = bank.groupby(["hh_entity", "date"]).agg({**dict.fromkeys(items, "sum"), "one_bank": "first", "entity": "size"}).reset_index()

    y9 = ds.dataset(f"{args.y9c_root}/panel", partitioning="hive")
    items_y = [c for c in items if c in y9.schema.names]
    bhc = y9.to_table(columns=["RSSD_ID", "REPORTING_PERIOD"] + items_y,
                      filter=ds.field("REPORTING_PERIOD") >= pd.Timestamp(args.start)).to_pandas()
    bhc = bhc.rename(columns={"RSSD_ID": "hh_entity", "REPORTING_PERIOD": "date"})
    m = agg.merge(bhc, on=["hh_entity", "date"], suffixes=("_banks", "_bhc"))
    print(f"holding-company-quarters with both a Y-9C filing and Call-filing subsidiaries: {len(m):,} "
          f"({m.hh_entity.nunique():,} BHCs); one-bank: {int(m.one_bank.sum()):,}")
    print(f"{'item':18s} {'group':9s} {'n':>8s} {'median':>7s} {'p10':>7s} {'p90':>7s} {'within 5%':>10s} {'within 20%':>11s}")
    for c in items_y:
        for lab, sub in (("one-bank", m[m.one_bank]), ("multi", m[~m.one_bank])):
            r = (sub[c + "_banks"] / sub[c + "_bhc"].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
            r = r[(sub.loc[r.index, c + "_bhc"] > 0)]
            if len(r) < 100:
                continue
            print(f"{c:18s} {lab:9s} {len(r):8,d} {r.median():7.3f} {r.quantile(.1):7.3f} {r.quantile(.9):7.3f} "
                  f"{(r.sub(1).abs() <= .05).mean():10.1%} {(r.sub(1).abs() <= .20).mean():11.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
