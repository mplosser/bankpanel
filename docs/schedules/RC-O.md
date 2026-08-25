# Schedule RC-O — Other Data for Deposit Insurance Assessments

9 base items and 1 derived series, out of 433 codes in the schedule.

## Most of this schedule is not published

**165 of the 433 codes are collected but confidential** — every populated cell is the
literal string `"CONF"`. The assessment-scorecard detail the FDIC uses to price deposit
insurance is not public, so RC-O reduces to its headline items whether or not one intends
to scope it that way.

This matters mechanically as well as substantively: a confidential column is *fully
populated* on a non-null test, so it looks like prime coverage and then builds to an
all-NaN column. `bankpanel propose` measures coverage on numeric content and excludes
them.

## What survives

- **The assessment base** — `assessable_dep_liabilities` (total deposit liabilities as
  defined in section 3(l) of the FDI Act) less `assessable_allowable_exclusions`.
- **Unsecured other borrowings by maturity** — four buckets from ≤1 year to >5 years,
  plus `unsecured_othbor_tot`. Introduced 2009Q2, in the wake of the crisis.
- **`qavg_consolidated_assets`** and **`qavg_tangible_equity`** (2011Q2 onward), the
  quarterly averages the assessment rate is actually applied to. Note these are a
  *different* average from RC-K's, computed on the FDIC's definition.

`RCFDK653` (averaging method used) and `RCONA545` (legal title of parent institution) are
excluded as identifiers rather than measures.
