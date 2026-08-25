# Schedule RC-D — Trading Assets and Liabilities

16 base items and 1 derived series. Small, and about large banks.

## Most cells are empty, and that is correct

RC-D is reported only by banks with material trading books. Coverage peaks at roughly
2–6% of filers, which is why these items are proposed at a much lower density threshold
than any other schedule — the default 50% rule would have excluded the entire schedule.

**A NaN here overwhelmingly means "this bank does not trade", not "missing data."** Most
items are `031+041` and several are `031`-only, since trading concentrates in the banks
filing the consolidated form. Check `expected_mask()` before treating a blank as a
non-report.

## What is covered

- **Trading assets by type** — Treasury, US agency, states and political subdivisions,
  other domestic offices, asset-backed securities, and loans (C&I, other, real estate,
  individuals).
- **Trading liabilities** — short positions and other trading liabilities.
- **Revaluation gains and losses** on interest-rate and foreign-exchange positions, plus
  `trad_revaluation_net` for the difference.
- **Unpaid principal balance** of loans measured at fair value, which is what makes the
  trading loan marks interpretable.

## Era notes

Several items carry an `_0818` suffix: they were introduced with the 2008 fair-value
expansion and retired in 2018Q1. `trad_abs_0810` is narrower still (2008Q1–2010Q4). Era
bounds are measured from the data, not taken from MDRM.

The 63 remaining RC-D codes are mostly finer breakdowns of the same categories.
`bankpanel propose --schedule RC-D --min-coverage 0.02` drafts them.
