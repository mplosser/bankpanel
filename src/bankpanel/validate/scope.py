"""The official consolidated-vs-domestic (RCFD vs RCON) evaluation.

bankpanel publishes a CONSOLIDATED item (RCFD on the Call Report, BHCK on the FR Y-9C)
under its variable name. For a bank without foreign offices the domestic figure (RCON /
BHDM) is the same number, and fills in where the consolidated code is blank. For a bank
WITH foreign offices it is not the same number, so the builder leaves the consolidated
column blank rather than publish a domestic figure under a consolidated name (the rule is
``profiles.ReportProfile.domestic_pairs``).

Every build records, per quarter and column, in ``consolidated_scope.parquet``:

* ``blocked``: international banks whose consolidated cell was left blank because only the
  domestic figure was filed. Informational -- it says where the panel is thinner for large
  banks, and where a replacement (an estimate, or the domestic series under its own name)
  may be wanted.
* ``material_equal`` / ``material_both``: among banks whose foreign offices hold more than
  5% of deposits and that FILED both codes, how many filed exactly the same number. For an
  item such banks book abroad the two differ; a sudden rise in exact matches means one code
  is being copied from the other upstream (the 2011-2026 cross-fill in data_call_report
  produced exactly this). That rise is a finding; a stable level is not.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SCOPE_FILE = "consolidated_scope.parquet"
#: A column-quarter is a finding when the share of material-foreign banks filing identical
#: consolidated and domestic numbers rises by at least JUMP above the column's usual share,
#: with at least MIN_BANKS such banks.
JUMP = 0.5
MIN_BANKS = 5
#: ... and the share itself must be near-total: an upstream copy makes EVERY bank identical
#: (14/14 for total assets under the old cross-fill), while a handful of banks whose item is
#: genuinely all domestic can push a small sample to 5/7 by chance.
EQUAL_MIN = 0.95


def load(root: str | Path) -> pd.DataFrame:
    p = Path(root) / SCOPE_FILE
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def blocked_summary(scope: pd.DataFrame, date_col: str = "REPORTING_PERIOD") -> pd.DataFrame:
    """Per column: how often international banks were left blank rather than given a domestic value."""
    if scope.empty:
        return pd.DataFrame()
    b = scope[scope.blocked > 0]
    if b.empty:
        return pd.DataFrame()
    g = b.groupby(["column", "code"])
    out = g.agg(first=(date_col, "min"), last=(date_col, "max"), quarters=(date_col, "nunique"),
                cells=("blocked", "sum"), max_per_quarter=("blocked", "max")).reset_index()
    return out.sort_values("cells", ascending=False)


def substitution_findings(scope: pd.DataFrame, date_col: str = "REPORTING_PERIOD") -> pd.DataFrame:
    """Column-quarters where filed consolidated values suddenly look like copies of the domestic ones.

    Identical figures alone are not evidence: an item a bank never books abroad (agricultural
    loans, state and municipal securities) is legitimately the same consolidated and domestic,
    in every era. A copy shows up as a JUMP -- total assets went from 0% identical before 2011
    to 100% after under the old upstream cross-fill. So each quarter's identical share is
    compared with the column's median share in all OTHER quarters (leave-one-out), and a rise
    of JUMP or more is a finding. A copy present in every quarter cannot be seen this way.
    """
    if scope.empty:
        return pd.DataFrame()
    s = scope[scope.material_both >= MIN_BANKS].copy()
    if s.empty:
        return pd.DataFrame()
    s["equal_share"] = s.material_equal / s.material_both
    base = []
    for _, g in s.groupby("column"):
        vals = g["equal_share"].to_numpy()
        for i, idx in enumerate(g.index):
            others = [v for j, v in enumerate(vals) if j != i]
            base.append((idx, float(pd.Series(others).median()) if others else float("nan")))
    s["usual_share"] = pd.Series(dict(base))
    f = s[((s.equal_share - s.usual_share) >= JUMP) & (s.equal_share >= EQUAL_MIN)]
    return f[[date_col, "column", "code", "material_both", "material_equal", "equal_share", "usual_share"]].sort_values([date_col, "column"])


def mdrm_summary(scope: pd.DataFrame, date_col: str = "REPORTING_PERIOD") -> pd.DataFrame:
    """Per column: upstream copies discarded (MDRM says the form does not collect the code, and the
    value equals its twin) and values kept although MDRM says the code is not collected (they
    differ from their twin, so they are not copies -- evidence the MDRM window is incomplete)."""
    if scope.empty or "copies_discarded" not in scope:
        return pd.DataFrame()
    g = scope.groupby(["column", "code"])
    out = g.agg(copies_discarded=("copies_discarded", "sum"), kept_outside_window=("kept_outside_window", "sum"),
                first=(date_col, "min"), last=(date_col, "max")).reset_index()
    return out[(out.copies_discarded > 0) | (out.kept_outside_window > 0)].sort_values("copies_discarded", ascending=False)


def format_report(scope: pd.DataFrame, date_col: str = "REPORTING_PERIOD", limit: int = 30) -> str:
    bar = "=" * 78
    lines = [bar, "CONSOLIDATED vs DOMESTIC (RCFD vs RCON) -- the official scope evaluation", bar]
    if scope.empty:
        lines.append("no consolidated_scope.parquet in this build (rebuild with bankpanel >= 1.4)")
        return "\n".join(lines)
    sub = substitution_findings(scope, date_col)
    if sub.empty:
        lines.append("no substitution: no column's share of identical consolidated and domestic figures at "
                     "banks with material foreign business jumps above its usual level")
    else:
        lines.append(f"{len(sub)} column-quarter(s) where the share of material-foreign banks filing identical "
                     f"consolidated and domestic figures jumps {JUMP:.0%}+ above its usual level -- an upstream copy:")
        for r in sub.head(limit).itertuples(index=False):
            lines.append(f"  [CRITICAL] {getattr(r, date_col).date() if hasattr(getattr(r, date_col), 'date') else getattr(r, date_col)}"
                         f"  {r.column:32s} {r.code}  {r.material_equal}/{r.material_both} identical (usually {r.usual_share:.0%})")
    md = mdrm_summary(scope, date_col)
    lines += ["", "Upstream copies discarded (outside the MDRM window for the form, identical to the twin code):"]
    if md.empty or not (md.copies_discarded > 0).any():
        lines.append("  none")
    else:
        for r in md[md.copies_discarded > 0].head(limit).itertuples(index=False):
            lines.append(f"  {r.column:32s} {r.code}  {r.copies_discarded:,} cells")
    odd = md[md.kept_outside_window > 0] if not md.empty else md
    if not odd.empty:
        lines += ["", "[WARNING] Kept although MDRM says the form does not collect the code (differs from its twin, so not a copy;"
                  " the MDRM window may be incomplete -- review reference_data/scope_validity.csv):"]
        for r in odd.head(limit).itertuples(index=False):
            lines.append(f"  {r.column:32s} {r.code}  {r.kept_outside_window:,} cells")
    blk = blocked_summary(scope, date_col)
    lines += ["", "Consolidated columns left blank for international banks (only the domestic figure is filed):"]
    if blk.empty:
        lines.append("  none")
    else:
        for r in blk.head(limit).itertuples(index=False):
            lines.append(f"  {r.column:32s} {r.code}  {pd.Timestamp(r.first).date()} .. {pd.Timestamp(r.last).date()}"
                         f"  {r.quarters} quarters, up to {r.max_per_quarter} banks")
        if len(blk) > limit:
            lines.append(f"  ... {len(blk) - limit} more (saved with --save)")
    return "\n".join(lines)


def gate(scope: pd.DataFrame, date_col: str = "REPORTING_PERIOD") -> int:
    return 1 if not substitution_findings(scope, date_col).empty else 0
