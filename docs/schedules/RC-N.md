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
