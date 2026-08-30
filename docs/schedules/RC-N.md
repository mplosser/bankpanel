# Schedule RC-N — Past Due and Nonaccrual Loans, Leases and Other Assets

166 base items and 2 derived series. The credit-quality schedule, and the largest single
addition in this repo.

## The naming scheme

RC-N is a grid repeated several times over. Names encode that structure:

```
{bucket}_{category}[_{family}]
```

| Part | Values |
| --- | --- |
| `bucket` | `pd30` past due 30–89 days and still accruing · `pd90` past due 90+ days and still accruing · `na` nonaccrual |
| `category` | the loan category — `ci`, `cc`, `auto`, `famres_first`, `nfnres_owner`, `multifam`, `agprod`, `lease`, … |
| `family` | which grid the item belongs to — **absent for the schedule's main body** |

Families:

| Family | Meaning |
| --- | --- |
| *(none)* | the main body of the schedule |
| `lossshare` | loans covered by FDIC loss-sharing agreements (crisis-era assisted deals) |
| `modified` | loan modifications to borrowers experiencing financial difficulty (TDRs) |
| `itemized` | memo itemisation of amounts already inside "all other loans and leases" |
| `usgtd`, `usgtd_portion`, `gnma_rebooked` | government-guaranteed cuts |
| `fv`, `upb` | fair value and unpaid principal balance of held-for-sale loans |

**The family is not decoration.** RC-N repeats the same bucket-by-category grid for each
family, so naming on bucket and category alone collapses them onto one another — 112 of
184 names collided before the family was added.

A handful of names carry a trailing MDRM item code (`pd30_forgovt_itemized_k095` vs
`..._k283`). Those are genuinely distinct items that coexist in the same period under
near-identical MDRM descriptions — checked, and their eras are identical, so they are not
an era chain. The suffix is ugly and unambiguous, which is the right trade; the full item
name is in the `notes` column.

## Known gap: the reported totals disappear for 2011–2016

Measured coverage of `pd30_tot` / `pd90_tot` (`RCFD1406` / `RCFD1407`):

| 2010Q4 | 2011Q1 | 2016Q4 | 2017Q1 |
| --- | --- | --- | --- |
| 1.00 | **0.00** | **0.00** | 1.00 |

The same six-year hole as `RCFD1403`, total nonaccrual. So `npl_tot` and `pastdue_tot`
are **NaN for 2011Q1–2016Q4**. That is honest rather than convenient: the value is not
known from the reported totals in that window.

A reconstruction is possible in principle — the balance-sheet config already does it for
nonaccrual, where `pdl_tot_non` fills the gap by summing 22 by-category RC-N items — and
that is why `npl_tot` and `pastdue_tot` reference `pdl_tot_non` rather than a local total.

**It is not done here for past-due, because it does not yet validate.** Summing the
by-category `pd30_*` / `pd90_*` items and comparing to the reported total in the periods
where both exist reproduces it for only ~23% of bank-quarters, with a median error of
about 21%. The cause is identified: this repo does not yet carry the *main-body*
nonfarm-nonresidential past-due items — only their `lossshare` and `modified` variants —
and nonfarm nonresidential is the largest CRE category. Adding them is the prerequisite,
and the reconstruction should be shipped only once it reproduces the reported total in the
overlap periods.

## How good is the reconstruction, and should you use it

Accepted with the caveat below. The numbers, measured rather than asserted:

**How often it runs.** `pdl_tot_non` is the reported `RCFD1403` on **88.5%** of rows. The
22-term reconstruction fills the other 11.5% (162,125 rows), and 99% of those sit in
2010–2019 — the window where `RCFD1403` was discontinued. It is used where it is needed and
almost nowhere else.

**How close it gets.** Scored against `RCFD1403` on the 465,519 rows where both exist:

| era | within 1% | median abs error |
| --- | --- | --- |
| 1985–1999 | 3% | 70–82% |
| 2000–2009 | 7–18% | 29–81% |
| 2010–2025 | 23–38% | **6–8%** |

Pooled across all eras the median error is 35%, which is the wrong number to quote: it
averages the method over forty years in which it never runs. Conditional on the rows where
it *is* used, the error is the 6–8% figure.

**Where it assumes.** On 64,164 of those rows a component is blank while its line was being
collected, and `fillna(0)` treats the blank as zero. All of it is `na_ag_1583`, agricultural
nonaccrual. Splitting the blanks:

| | rows | reading |
| --- | --- | --- |
| banks holding **no** agricultural loans | 32,545 (49.8%) | blank means zero |
| banks that **do** hold ag loans | 32,841 (50.2%) | the zero is an assumption |

For the second half the ag book is a median $618k, 0.98% of loans, and among ag-holding
banks that *did* report the line, 83.4% reported exactly zero. Imputing at the reporting
banks' own nonaccrual rate bounds the understatement at **0.41%** of `pdl_tot_non` on
affected rows. The bias is one-directional — the formula is a pure sum of non-negative
quantities, so a missing term can only push the total down.

**It is also biased, not just noisy.** `bankpanel validate stitches` measures the level
step at the quarter the source changes back, over a panel balanced across that quarter:
at 2017Q1, across 5,906 banks, `pdl_tot_non` falls **13.8%** (robust z = 11.7 against the
series' own 1.3% quarterly volatility) as `RCFD1403` resumes. So the reconstruction runs
roughly **16% above** the reported total in aggregate, not merely scattered around it.
Dispersion and level bias are separate defects; the 6–8% figure above measures only the
first. The likely cause is double counting among the 22 terms -- several RC-N nonaccrual
items nest inside one another -- and it is not yet root-caused.

**What this means for `npl_tot` and `pastdue_tot`.** Both inherit it. For 88.5% of rows they
rest on a reported total; on the rest, expect ~6–8% dispersion and a ≤0.41% downward bias.
That is fine for cross-sectional and time-series work and not fine for reconciling a single
bank-quarter to its filing. Read `pdl_tot_non_1403` directly if you need only reported values.

Separately, `pastdue_tot` starts at **2001Q1** rather than 1985 — `pd30_tot` (`RCFD1406`) is
simply not collected earlier. `npl_tot`, which does not use it, runs the full period.

## What the data shows

Aggregate nonperforming loans (`npl_tot` = `pd90_tot` + `pdl_tot_non`) against loans:

| | 2007Q2 | 2008Q1 | 2008Q4 | 2009Q3 | 2010Q2 |
| --- | --- | --- | --- | --- | --- |
| NPL ($bn) | 55 | 111 | 205 | 334 | 360 |
| NPL ratio (%) | **0.9** | 1.6 | 2.9 | 5.0 | **5.3** |

A clean crisis path, which is the check that the buckets are being read correctly.

## Era notes

- The **`lossshare`** family begins **2011Q1**, not 2009 — the items were added after the
  assisted-deal wave, so early loss-share portfolios are not captured.
- The **`modified`** family reflects the accounting change from "troubled debt
  restructuring" to "loan modifications to borrowers experiencing financial difficulty";
  MDRM descriptions use both, and the family regex matches either.
- `na_forgovt_itemized` and its siblings run 2011Q1–2016Q2 only.

## Deliberately not covered

18 of 184 proposals were not named systematically and are excluded rather than given a
poor name: `additions to nonaccrual assets` / `nonaccrual assets sold during the quarter`
(`C410`/`C411` — these are *flows*, not stock buckets, and do not fit the scheme) and a
handful of items whose MDRM description carries no recognisable category.
