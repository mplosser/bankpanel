"""bankpanel quickstart: read both panels, and the three things a first-time user must know.

    python examples/quickstart.py --call-root <panel_root> --y9c-root <y9c_root>

or set BANKPANEL_CALL_ROOT / BANKPANEL_Y9C_ROOT. Each root is the ``--out`` of a
``bankpanel build`` (plus ``bankpanel expectations build``, which step 4 needs).

What it shows
  1. what is in a panel: the build manifest and the dictionary
  2. reading columns, with the form type every row carries
  3. year-to-date income items: ``ytd_`` as filed and ``q_`` as a quarterly flow
  4. NaN is not one thing: ``expected_mask`` separates "not collected" from "left blank"
  5. the holding-company panel uses the same names, so the two line up column for column
  6. one figure: aggregate loans-to-assets and net interest margin, banks vs holding companies

Values are thousands of US dollars. Nothing here is cleaned, winsorized or merger-adjusted;
see docs/CAVEATS.md before using the data for research.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

import bankpanel as bp

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)

COLS = ["assets", "ll_tot", "ll_res", "equity", "dom_deposit_nib", "dom_deposit_ib", "foreign_dep",
        "ytd_int_inc", "ytd_int_exp", "q_int_inc", "q_int_exp"]


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--call-root", default=os.environ.get("BANKPANEL_CALL_ROOT"), help="Call Report panel root")
    ap.add_argument("--y9c-root", default=os.environ.get("BANKPANEL_Y9C_ROOT"), help="FR Y-9C panel root")
    ap.add_argument("--out", default=Path(__file__).with_name("output"), help="where the figure goes")
    args = ap.parse_args()
    if not args.call_root or not args.y9c_root:
        ap.error("give --call-root and --y9c-root, or set BANKPANEL_CALL_ROOT / BANKPANEL_Y9C_ROOT")
    call, y9c = Path(args.call_root), Path(args.y9c_root)

    # ---- 1. what is in a panel -----------------------------------------------------------
    section("1. What is in the panel")
    manifest = bp.info(root=call)
    print(f"built {manifest['built_at']} with bankpanel {manifest['bankpanel_version']} | profile {manifest['profile']} | "
          f"{int(manifest['n_rows']):,} rows x {manifest['n_columns']} columns | {manifest['date_min']} .. {manifest['date_max']}")
    d = bp.dictionary(root=call)
    print(f"{len(d):,} columns: {d.variable_type.value_counts().to_dict()}")
    print("schedules:", ", ".join(sorted(d.schedule.dropna().unique())))
    print("\nsearch_variables('nonaccrual') ->")
    print(bp.search_variables("nonaccrual", root=call)[["variable_name", "schedule", "mdrm_code", "description"]].head(6).to_string(index=False))

    # ---- 2. reading columns ----------------------------------------------------------------
    section("2. Reading columns (columns= is required; the panel is ~1,200 columns wide)")
    df = bp.read_panel(COLS, start="1997Q1", root=call)
    df["date"] = df["REPORTING_PERIOD"]
    print(f"{len(df):,} bank-quarters x {df.shape[1]} columns, {df.date.min().date()} .. {df.date.max().date()}")
    print(df.head(4).to_string(index=False))
    print("\nEvery row carries form_type (31 = with foreign offices, 41 = domestic, 51 = the short form since 2017):")
    ft = df.groupby([df.date.dt.year, "form_type"]).size().unstack(fill_value=0)
    print(ft.loc[[1997, 2005, 2011, 2017, 2020, 2024]].to_string())

    # ---- 3. ytd_ and q_ ----------------------------------------------------------------------
    section("3. Year-to-date income: ytd_ as filed, q_ as the quarterly flow")
    bank = df[df.RSSD_ID == df.loc[df.date == df.date.max(), "RSSD_ID"].iloc[0]].sort_values("date")
    bank = bank[bank.date.dt.year == bank.date.dt.year.max() - 1]
    print(f"one bank (RSSD {int(bank.RSSD_ID.iloc[0])}), one calendar year -- ytd_int_inc accumulates, q_int_inc is the difference:")
    print(bank[["date", "form_type", "ytd_int_inc", "q_int_inc"]].to_string(index=False))
    q = df.date.dt.quarter
    missing_q = df.q_int_inc.isna().groupby(q).mean()
    print("\nshare of bank-quarters with NO q_int_inc, by calendar quarter (Q1 = the YTD value itself):")
    print((missing_q * 100).round(2).rename("% missing").to_string())
    print("A q_ is NaN wherever no clean one-quarter difference exists (a bank missing the prior quarter,\n"
          "an annual filer, a first filing mid-year). It is never fabricated; the ytd_ column keeps what was filed.")

    # ---- 4. expected_mask -----------------------------------------------------------------
    section("4. NaN is not one thing: expected_mask")
    col = "ln_famres_first_adjrate"          # RC-C memoranda: adjustable-rate closed-end first liens
    c = bp.read_panel([col], start="2018Q1", root=call)
    exp = bp.expected_mask(c, col, root=call)
    tab = pd.DataFrame({"reported": c[col].notna(), "expected": exp})
    summary = tab.groupby([c.form_type, c.REPORTING_PERIOD.dt.quarter]).agg(
        n=("reported", "size"), reported=("reported", "mean"), expected=("expected", "mean"))
    print(f"{col} (Schedule RC-C memoranda) since 2018, by form and calendar quarter:")
    print((summary.assign(reported=lambda s: (100 * s.reported).round(1), expected=lambda s: (100 * s.expected).round(1))
           .rename(columns={"reported": "% reported", "expected": "% expected"})).to_string())
    print("\nThe 041 collects this item every quarter; the 051 short form collects it only in Q2 and Q4.\n"
          "So a NaN in a 051 filer's Q1 or Q3 is 'not collected' (expected = False), while a NaN where\n"
          "expected = True is a bank that left the line blank. Averaging the raw column over 2018+\n"
          "without this distinction silently turns Q1/Q3 into a 041-only sample.")
    blank = tab[tab.expected & ~tab.reported]
    print(f"cells expected but blank: {len(blank):,} of {int(tab.expected.sum()):,} expected ({100 * len(blank) / max(1, tab.expected.sum()):.2f}%)")

    # ---- 5. the FR Y-9C panel, same names ------------------------------------------------------
    section("5. The FR Y-9C panel uses the same variable names")
    hh = bp.read_panel(COLS, start="1997Q1", root=y9c)
    hh["date"] = hh["REPORTING_PERIOD"]
    print(f"{len(hh):,} holding-company-quarters | form_type here is the $5bn size tier (1 = under $5bn, 2 = $5bn and over)")
    print(hh.head(3).to_string(index=False))
    both = pd.concat([df.assign(panel="banks (Call)"), hh.assign(panel="holding companies (Y-9C)")])
    agg = both.groupby(["panel", "date"]).agg(assets=("assets", "sum"), loans=("ll_tot", "sum"),
                                              ii=("q_int_inc", "sum"), ie=("q_int_exp", "sum"), n=("RSSD_ID", "size"))
    agg["loans_to_assets"] = agg.loans / agg.assets
    agg["nim_annualized_pct"] = 400 * (agg.ii - agg.ie) / agg.assets
    latest = agg.reset_index().sort_values("date").groupby("panel").tail(1)
    print("\nlatest quarter, aggregated:")
    print(latest[["panel", "date", "n", "assets", "loans_to_assets", "nim_annualized_pct"]].to_string(index=False))

    # ---- 6. figure --------------------------------------------------------------------------
    section("6. Figure")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    for panel, g in agg.groupby(level="panel"):
        g = g.droplevel("panel")
        axes[0].plot(g.index, g.loans_to_assets, label=panel)
        axes[1].plot(g.index, g.nim_annualized_pct.rolling(4).mean(), label=panel)
    axes[0].set_title("Loans / assets, aggregate")
    axes[0].set_ylim(0.35, 0.75)
    axes[1].set_title("Net interest margin, % of assets, annualized (4-qtr average)")
    for ax in axes:
        ax.grid(alpha=.3)
        ax.legend()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out / "quickstart.png", dpi=120)
    print("wrote", out / "quickstart.png")


if __name__ == "__main__":
    main()
