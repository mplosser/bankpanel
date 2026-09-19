"""Build a review packet: the decisions that need a human, with the evidence attached.

Three things in this repo are expensive to get wrong and cannot be machine-checked:
the public variable names, the derived series (which encode judgement rather than just
a code mapping), and a handful of domain calls about how items behave.

This writes them to CSVs with the supporting evidence -- MDRM description, measured
coverage, era, sample values -- and a blank ``verdict`` column, so the review can be done
in Excel and handed back rather than reconstructed from a terminal session.

Usage:
    python tools/make_review_packet.py --panel-root path/to/panel --out review
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bankpanel.config import ConfigSet  # noqa: E402

#: Configs authored in this migration. The three legacy configs are parity-verified
#: against the source pipeline and are not up for review here.
NEW_CONFIGS = {
    "rc_c_loans.csv", "rc_e_deposits.csv", "rc_b_securities.csv", "rc_d_trading.csv",
    "rc_n_past_due.csv", "rc_k_quarterly_avg.csv", "rc_r_capital.csv",
    "rc_o_assessments.csv", "ri_a_equity.csv", "ri_b_chargeoffs.csv",
    "ri_provisions.csv", "quality_checks.csv",
}

#: Items excluded as collected-but-unpublished. Every populated cell is the string "CONF".
CONFIDENTIAL = [
    ("RCONLG24", "Number of outstanding Section 4013 loans", "RC-C"),
    ("RCONLG25", "Outstanding balance of Section 4013 loans", "RC-C"),
    ("RCON6999", "Loans to small businesses indicator", "RC-C"),
    ("RCON6860", "Agricultural loans to small farms indicator", "RC-C"),
]


def _zero_fill_evidence(panel_root: Path, cs) -> dict:
    """Per derived column: how many rows rest on an assumed zero.

    Attached to the review rather than left in a terminal report, because "is this
    construction sound" cannot be answered without it -- a sum whose components are
    sometimes blank inside their collection era is a different object from one whose
    blanks are all era stitches.
    """
    import pyarrow.dataset as ds

    from bankpanel.validate.quality import find_fabricated_values, find_within_era_zerofill

    dataset = ds.dataset(panel_root / "panel", partitioning="hive")
    wanted = {"REPORTING_PERIOD"}
    for var in cs.derived:
        wanted.add(var.variable_name)
        wanted |= set(cs.graph.deps.get(var.variable_name, ()))
    df = dataset.to_table(columns=sorted(wanted & set(dataset.schema.names))).to_pandas()

    out: dict[str, str] = {}
    for _, row in find_within_era_zerofill(df, cs).iterrows():
        out[row["column"]] = (
            f"{row.n_rows:,} rows ({row.share_of_built:.1%} of built) rest on an assumed "
            f"zero; worst component {row.worst_input}"
        )
    for _, row in find_fabricated_values(df, cs).iterrows():
        prefix = out.get(row["column"], "")
        out[row["column"]] = (
            f"FABRICATED: {row.n_fabricated:,} rows have a value with no input at all. "
            + prefix
        ).strip()

    # An assumption inherited from upstream is still an assumption. npl_tot is clean in
    # itself and sits on pdl_tot_non, whose 22-term fallback rests on 64,164 assumed
    # zeros -- reviewing npl_tot without that is reviewing the wrong half of it.
    direct = dict(out)
    for var in cs.derived:
        if var.variable_name in direct:
            continue
        seen, stack, found = set(), list(cs.graph.deps.get(var.variable_name, ())), []
        while stack:
            dep = stack.pop()
            if dep in seen:
                continue
            seen.add(dep)
            if dep in direct:
                found.append(dep)
            stack.extend(cs.graph.deps.get(dep, ()))
        if found:
            out[var.variable_name] = "inherited via " + ", ".join(
                f"{d} ({direct[d].split(';')[0]})" for d in sorted(found)
            )
    return out


def _stats(panel_root: Path, columns: list[str]) -> pd.DataFrame:
    """Measured coverage and level for each column, so review needs no querying."""
    import pyarrow.dataset as ds

    dataset = ds.dataset(panel_root / "panel", partitioning="hive")
    present = [c for c in columns if c in dataset.schema.names]
    table = dataset.to_table(columns=["REPORTING_PERIOD", *present])
    df = table.to_pandas()
    period = pd.DatetimeIndex(df.REPORTING_PERIOD)

    rows = []
    for column in present:
        values = df[column]
        filled = values.notna()
        rows.append({
            "column": column,
            "coverage": round(float(filled.mean()), 4),
            "first_quarter": str(period[filled].min().to_period("Q")) if filled.any() else "",
            "last_quarter": str(period[filled].max().to_period("Q")) if filled.any() else "",
            "median_value": round(float(values.median()), 2) if filled.any() else None,
            "pct_negative": round(float((values < 0).sum() / max(filled.sum(), 1)), 5),
        })
    return pd.DataFrame(rows)


def _decisions(out: Path) -> dict:
    """Verdicts already recorded, keyed (file, item).

    The packet is regenerated whenever the configs move, which would otherwise discard
    every verdict already given and ask for them again. Decisions live in their own file
    for exactly that reason: the questions are derived from the configs, the answers are not.
    """
    path = out / "decisions.csv"
    if not path.exists():
        return {}
    prior = pd.read_csv(path, keep_default_na=False)
    if "kind" not in prior.columns:
        prior["kind"] = ""
    # Keyed on kind as well as item: in 03_domain_calls one item could carry two separate
    # judgements (its flow type AND its sign), and a verdict on one must not answer both.
    return {
        (row.file, row.kind, row.item): (row.verdict, row.note)
        for row in prior.itertuples()
    }


def build(panel_root: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    decided = _decisions(out)
    cs = ConfigSet.load("configs")
    dictionary = pd.read_csv(panel_root / "dictionary.csv", keep_default_na=False)
    desc = dict(zip(dictionary.variable_name, dictionary.description, strict=True))

    new_base = [
        (cfg.path.name, var)
        for cfg in cs.configs if cfg.path.name in NEW_CONFIGS
        for var in cfg.base
    ]
    new_derived = [
        (cfg.path.name, var)
        for cfg in cs.configs if cfg.path.name in NEW_CONFIGS
        for var in cfg.derived
    ]
    stats = _stats(panel_root, [v.variable_name for _, v in (*new_base, *new_derived)])
    stats_by_col = stats.set_index("column")
    zero_fill = _zero_fill_evidence(panel_root, cs)

    def stat(name, field, default=""):
        return stats_by_col.at[name, field] if name in stats_by_col.index else default

    # --- 1. names ---------------------------------------------------------------------
    code_suffixes = {v.mdrm_code[4:].lower() for _, v in new_base}
    # Names are reviewed because they are the published API. A withheld [INTERMEDIATE]
    # column never reaches the panel, so its name -- often a deliberate code suffix on an
    # era piece -- is not up for review and must not be flagged as ambiguous.
    withheld = cs.intermediate_columns()
    rows = []
    for filename, var in new_base:
        if var.variable_name in withheld:
            continue
        tail = var.variable_name.rsplit("_", 1)[-1]
        rows.append({
            "schedule": var.schedule,
            "variable_name": var.variable_name,
            "mdrm_code": var.mdrm_code,
            "mdrm_description": desc.get(var.variable_name, var.notes)[:160],
            "ambiguous_name": "YES" if tail in code_suffixes else "",
            "coverage": stat(var.variable_name, "coverage"),
            "first_quarter": stat(var.variable_name, "first_quarter"),
            "last_quarter": stat(var.variable_name, "last_quarter"),
            "era_start": var.era_start or "",
            "era_end": var.era_end or "",
            "flow_type": var.flow_type,
            "config": filename,
            "verdict": decided.get(("01_names.csv", "", var.variable_name), ("", ""))[0],
            "rename_to": "",
            "note": decided.get(("01_names.csv", "", var.variable_name), ("", ""))[1],
        })
    names = pd.DataFrame(rows).sort_values(
        ["ambiguous_name", "schedule", "variable_name"], ascending=[False, True, True]
    )
    names.to_csv(out / "01_names.csv", index=False)

    # --- 2. derived series -------------------------------------------------------------
    graph = cs.graph
    rows = []
    for filename, var in new_derived:
        inputs = sorted(graph.deps.get(var.variable_name, ()))
        rows.append({
            "schedule": var.schedule,
            "variable_name": var.variable_name,
            "description": var.description,
            "formula": var.formula,
            "inputs": " | ".join(inputs),
            "n_inputs": len(inputs),
            "coverage": stat(var.variable_name, "coverage"),
            "first_quarter": stat(var.variable_name, "first_quarter"),
            "last_quarter": stat(var.variable_name, "last_quarter"),
            "median_value": stat(var.variable_name, "median_value", None),
            "config": filename,
            "risk": _derived_risk(var.variable_name),
            "zero_fill_evidence": zero_fill.get(var.variable_name, ""),
            "verdict": decided.get(("02_derived.csv", "", var.variable_name), ("", ""))[0],
            "note": decided.get(("02_derived.csv", "", var.variable_name), ("", ""))[1],
        })
    pd.DataFrame(rows).sort_values(["risk", "variable_name"]).to_csv(
        out / "02_derived.csv", index=False
    )

    # --- 3. domain calls ---------------------------------------------------------------
    rows = []
    for filename, var in new_base:
        if filename == "ri_a_equity.csv":
            rows.append({
                "kind": "flow_type (balance vs flow)",
                "item": var.variable_name,
                "mdrm_code": var.mdrm_code,
                "my_call": var.flow_type,
                "why": "RIAD prefix normally means year-to-date; typed stock where the item "
                       "is a BALANCE reported on a year-to-date form. Wrong => the column "
                       "silently becomes the CHANGE in equity.",
                "detail": desc.get(var.variable_name, "")[:120],
                "verdict": "", "note": "",
            })
    for _, var in new_base:
        if var.sign == "nonneg":
            rows.append({
                "kind": "sign=nonneg",
                "item": var.variable_name,
                "mdrm_code": var.mdrm_code,
                "my_call": "cannot be negative over a quarter",
                "why": "Gross additive flow. Drives the quarterize audit; a NET item here "
                       "would be falsely flagged.",
                "detail": f"{stat(var.variable_name, 'pct_negative')} of non-null values are negative",
                "verdict": "", "note": "",
            })
    for code, label, schedule in CONFIDENTIAL:
        rows.append({
            "kind": "excluded as confidential",
            "item": code,
            "mdrm_code": code,
            "my_call": "excluded from the panel",
            "why": 'Collected but NOT published: every populated cell is the literal '
                   '"CONF", so the column looks fully covered and builds to all-NaN.',
            "detail": f"{schedule}: {label}",
            "verdict": "", "note": "",
        })
    calls = pd.DataFrame(rows)
    for i, row in calls.iterrows():
        verdict, note = decided.get(("03_domain_calls.csv", row.kind, row["item"]), ("", ""))
        calls.at[i, "verdict"], calls.at[i, "note"] = verdict, note
    calls.to_csv(out / "03_domain_calls.csv", index=False)

    _write_readme(out, len(names), len(new_derived))
    print(f"01_names.csv        {len(names):>4} columns "
          f"({int((names.ambiguous_name == 'YES').sum())} flagged ambiguous)")
    print(f"02_derived.csv      {len(new_derived):>4} series")
    print(f"03_domain_calls.csv {len(rows):>4} calls")
    print(f"-> {out.resolve()}")


def _derived_risk(name: str) -> str:
    """Order the review queue by consequence, not alphabetically."""
    high = {
        "tier1_capital", "tier2_capital", "rwa", "tier1_rbc_ratio", "total_rbc_ratio",
        "cet1_ratio", "brokered_dep_mat_lte1yr", "npl_tot", "pastdue_tot",
    }
    partial = {"ac_afs_tot_toplevel", "amt_ln_smallbiz_tot", "amt_ln_smallfarm_tot",
               "amt_ln_smallbiz_ci", "amt_ln_smallbiz_nfnres"}
    if name in high:
        return "1-high: era stitch or computed replacement for a confidential item"
    if name in partial:
        return "2-partial: sums only the components carried; NOT a reported total"
    return "3-simple: additive over items in the same era"


def _write_readme(out: Path, n_base: int, n_derived: int) -> None:
    (out / "README.md").write_text(f"""# Review packet

Three CSVs, each with a blank `verdict` column. Fill it in, save, hand back.

Generated by `python tools/make_review_packet.py`. Regenerate any time; your edits are
NOT preserved, so work on a copy or finish in one pass.

## 01_names.csv — {n_base} new public column names

The expensive one. These names become the API: once published, other people's code and
papers reference them, and everything else here is easier to change than this.

Sorted with the **ambiguous ones first** (`ambiguous_name=YES`) — names carrying an MDRM
code suffix, where two genuinely distinct items coexist under near-identical MDRM
descriptions and the code was the only way to tell them apart. You may know which is which.

`verdict`: `ok` | `rename` (put the new name in `rename_to`) | `drop` | `question`

## 02_derived.csv — {n_derived} derived series

Base columns are a code and a name. Derived columns are a *claim*. Sorted by `risk`:

- **1-high** — era stitches asserting two regimes measure the same thing, and the capital
  ratios computed because the reported ones became confidential in 2015.
- **2-partial** — aggregates that sum only the components carried. They are NOT reported
  totals and will be footed by somebody anyway.
- **3-simple** — additive within one era; low stakes.

`formula` and `inputs` are both shown so a claim can be checked without opening a config.

`zero_fill_evidence` is filled in wherever the construction rests on an assumed zero — a
component blank *inside* its collection era, where `fillna(0)` cannot tell "had nothing to
report" from "did not report". Blank in that column means every zero-filled component was
outside its era, which is the era stitch working rather than an assumption.

`verdict`: `ok` | `fix` | `drop` | `question`

## 03_domain_calls.csv — judgement calls made without a second opinion

- **flow_type** on Schedule RI-A: which items are balances reported on a year-to-date
  form rather than flows. Getting this wrong makes a column silently the *change* in
  equity rather than equity.
- **sign=nonneg**: which flows cannot be negative over a quarter. Drives the quarterize
  audit; `detail` gives the measured share of negatives so an over-broad call is visible.
- **excluded as confidential**: items dropped because every published cell is `"CONF"`.

`verdict`: `ok` | `change` | `question`

## Not in this packet

The engine and the parity result. 688 of 688 columns match the source pipeline bit-for-bit
across 1,415,045 rows; that is machine-checkable and re-runnable with
`python tools/parity_check.py --panel-root <root>`. It does not need a human read.
""", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel-root", required=True)
    ap.add_argument("--out", default="review")
    args = ap.parse_args()
    build(Path(args.panel_root), Path(args.out))
