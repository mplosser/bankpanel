"""The approvals ledger: a place to record that a finding has been looked at.

A validator that reports the same known, explained transition every run trains its user to
skip the output. Every finding must therefore be resolvable -- either the config gets
fixed, or a human writes down why the transition is real and expected. The ledger is the
second option, and it is deliberately CSV so that the reasons live in version control and
are reviewable in a diff.

Matching is on all of ``(panel, column, from_date, to_date)``. Anything looser would let
an approval for one break silently absolve a different one in the same column later.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

LEDGER_COLUMNS = ["panel", "column", "from_date", "to_date", "reason", "approved_by", "approved_at"]


def load_ledger(path: str | Path) -> pd.DataFrame:
    """Read the ledger, creating an empty one if it does not exist."""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=LEDGER_COLUMNS).to_csv(path, index=False)
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    df = pd.read_csv(path, keep_default_na=False)
    missing = [c for c in LEDGER_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: approvals ledger is missing column(s) {missing}")
    return df


def partition(findings: pd.DataFrame, ledger: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split findings into ``(new, approved)``."""
    if findings.empty:
        return findings, findings
    if ledger.empty:
        return findings, findings.iloc[0:0]

    def key(df: pd.DataFrame) -> pd.Series:
        return (
            df["panel"].astype(str)
            + "|" + df["column"].astype(str)
            + "|" + pd.to_datetime(df["from_date"]).dt.strftime("%Y-%m-%d")
            + "|" + pd.to_datetime(df["to_date"]).dt.strftime("%Y-%m-%d")
        )

    approved_keys = set(key(ledger))
    is_approved = key(findings).isin(approved_keys)
    return findings[~is_approved].copy(), findings[is_approved].copy()
