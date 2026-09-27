"""Zero-fill that needs a bank's whole year: ``scope=in_era_unless_reported``.

From 2005Q3 the source files stop writing a zero for a conditional item a bank does not
have (custody and fiduciary detail, trading detail, agricultural past-due lines, credit-card
fees). The share of banks with a non-zero value does not move across that quarter; only the
written zeros disappear. Left alone, the blank rows drop out of every sum and average taken
after 2005Q3 but not before it, which is a bias of its own. So the blank is resolved to the
zero it stands for -- with two exceptions, both of which the data can see:

* **The bank reports the item in another quarter of the same year.** Schedule RC-T is annual
  for smaller trust banks: a bank with $2bn under custody files it at Q4 and leaves Q1-Q3
  blank. Those blanks mean "collected annually", not "none", and a zero there would turn the
  series into 0, 0, 0, 2bn. They stay blank.
* **The year is not finished and last year the bank reported only later in the year.** In
  the newest year the build may end at Q2, before an annual filer's December report exists,
  so "reports it in another quarter of the same year" cannot be seen yet. The bank's
  prior-year pattern stands in for it: a bank whose reports last year all fell in quarters
  that have not arrived this year keeps its blanks (the year build passes these banks as
  ``keep_blank``). Once the year is complete, its own pattern decides as usual.
* **The bank's form does not collect the item that quarter** -- no filer of that form
  reports any value in that quarter. That covers a form that never carries the item and a
  form that collects it only in some quarters (the 051 takes Schedule RC-T at Q4 only). A
  blank there is "not asked", which is not a zero either.

Scope: this is NOT a general policy. It is applied only to the columns a [ZERO_FILL] rule
names, each with a written reason -- today, the 28 conditional items whose zeros stopped
being written at 2005Q3. A zero is never put where the value is not required or not
regularly reported.

Below a reporting threshold and not discernible from the bank's other items is, for every
practical purpose, zero (maintainer decision, 2026-09-21).
"""

from __future__ import annotations

import pandas as pd


def zero_fill_unless_reported(
    panel: pd.DataFrame,
    column: str,
    *,
    id_col: str,
    date_col: str,
    era_start: pd.Timestamp,
    era_end: pd.Timestamp | None = None,
    forms: frozenset[int] | None = None,
    keep_blank: set | None = None,
) -> int:
    """Fill ``column`` in place over one bank-year panel. Returns the number of cells filled.

    ``panel`` must hold whole years (the builder's year partition does), because "reports
    the item in another quarter" is a statement about the bank's year.
    """
    if column not in panel.columns:
        return 0
    values = panel[column]
    dates = pd.DatetimeIndex(panel[date_col])
    window = pd.Series(dates >= era_start, index=panel.index)
    if era_end is not None:
        window &= pd.Series(dates <= era_end, index=panel.index)

    year = pd.Series(dates.year, index=panel.index)
    bank_reports = values.fillna(0).ne(0).groupby([panel[id_col], year]).transform("any")
    # One key per form; a report with no form types (the FR Y-9C) is a single group.
    form = (panel["form_type"].astype("float64").fillna(-1.0) if "form_type" in panel
            else pd.Series(0.0, index=panel.index))
    # Per QUARTER, not per year: an item a form collects only at Q4 (or only in June and
    # December) is not asked in the other quarters, and a zero there would be invented.
    form_collects = values.notna().groupby([form, pd.Series(dates, index=panel.index)]).transform("any")

    fill = values.isna() & window & form_collects & ~bank_reports
    if keep_blank:
        # unfinished year: last year these banks reported only in quarters not yet arrived
        fill &= ~panel[id_col].isin(keep_blank)
    if forms is not None and "form_type" in panel:
        # The config says which forms carry the item. Two 051 filers volunteering a line the
        # 051 does not have must not turn 3,400 other 051 filers into zeros.
        fill &= panel["form_type"].astype("float64").isin([float(f) for f in forms])
    if fill.any():
        panel.loc[fill, column] = 0.0
    return int(fill.sum())
