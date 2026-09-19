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

**How often it runs.** `pdl_tot_non` is the reported `RCFD1403` on 88.5% of rows. Where
`RCFD1403` is missing — 160,902 bank-quarters, almost all 2011Q1–2016Q4 — it is rebuilt from
the RC-N nonaccrual column by category.

**Each category is counted once: as its total or as its breakdown, never both.**

| category | published as | total code, else breakdown |
| --- | --- | --- |
| construction, land development, other land | `na_constr` | `F176 + F177` from 2007; `3492` before; `5426` for 041 filers 1991–2000 |
| nonfarm nonresidential | `na_nfnres` | `F182 + F183` from 2007; `3504` before; `5441` for 041 filers 1991–2000 |
| depository institutions | `na_depinst` | `RCONB836`, else `5379 + 5382` |
| C&I | `pdl_ci_non` | `RCFD1608`, else `1253 + 1256` |
| leases | `na_lease` | `RCON1228`, else `F168 + F171` |
| farmland, 1–4 family revolving, closed-end first and junior liens, multifamily, agricultural, credit cards, auto, other consumer, foreign governments, all other loans, real estate in foreign offices | as reported | single codes: `3495`, `5400`, `C229`, `C230`, `3501`, `1583`, `B577`, `K215`, `K218`, `5391`, `5461`, `B574` |

Each "else" is exact where both sides are reported: `3492 = F176 + F177` and
`3504 = F182 + F183` for 100% of banks in 2007–2010; `B836 = 5379 + 5382` for 99.8–100%;
`1608 = 1253 + 1256` for 100% of 031 filers. A breakdown is used only when *all* of its codes
are present. 144K bank-quarters carry only a zero `5382`, and summing whatever happened to
be present would have published those as a confident zero.

`RCONF663` (modified 1–4 family loans, nonaccrual) is deliberately **not** a term. It is an
RC-N memorandum item, and those loans are already inside the 1–4 family lines.

**Where the construction previously went wrong** — two errors that cancelled at one boundary
and compounded at the other:

- `RCONF663` was counted. As a memorandum item it double-counted modified 1–4 family loans:
  17.7% of the reconstructed total.
- C&I, leases and depository institutions used only the breakdowns reported on the 031 form
  (~1.4% of banks). The 041 totals reported by the other ~98% were never read, so for most
  banks C&I nonaccrual was simply missing.

The double count inflated the total and the missing C&I deflated it. At 2011Q1 they happened
to offset, so the handoff looked smooth (−0.3%). By 2016 the double count had grown, and the
level fell **16.3%** when `RCFD1403` returned in 2017Q1. Found by `bankpanel validate
stitches`; see [../VALIDATION.md](../VALIDATION.md).

**How close it gets now.** Scored against `RCFD1403` where both exist:

| window | bank-quarters | matches exactly (±$1k) | sum ratio |
| --- | --- | --- | --- |
| 2017Q1 on | 176,784 | **89.9%** (was 39–44%) | **1.006** (was 1.053) |
| 2007–2010 | 120,191 | 52.8% | 0.987 |
| 2001–2006 | 198,169 | 47.3% | 0.924 |

The handoffs are now −5.5% at 2011Q1 and −4.4% at 2017Q1 across the same banks. Nonaccruals
were falling steadily through 2011–2017, and the stitch validator scores the 2011Q1 step at
robust z = 0.6 — within the series' own quarterly movement — and does not flag 2017Q1.

The fit is weaker before 2011, where the reconstruction almost never runs. The 2001–2006
shortfall (ratio 0.924) most likely reflects a consumer category that was split differently
before the 2011 auto / other-consumer codes; it is recorded, not yet traced.

**Where it assumes.** On 64,164 rows a component is blank while its line was being collected,
and `fillna(0)` treats the blank as zero. All of it is `na_ag_1583`, agricultural nonaccrual.
Splitting the blanks:

| | rows | reading |
| --- | --- | --- |
| banks holding **no** agricultural loans | 32,545 (49.8%) | blank means zero |
| banks that **do** hold ag loans | 32,841 (50.2%) | the zero is an assumption |

For the second half the ag book is a median $618k, 0.98% of loans, and among ag-holding banks
that *did* report the line, 83.4% reported exactly zero. Imputing at the reporting banks' own
nonaccrual rate bounds the understatement at about 0.4% of `pdl_tot_non` on affected rows.

**Blank, not zero.** Where no category is reported at all, `pdl_tot_non` is now blank. It was
previously a fabricated zero on 1,223 bank-quarters.

**What this means for `npl_tot` and `pastdue_tot`.** Both inherit it. For 88.5% of rows they
rest on a reported total; on the reconstructed rows, expect near-exact agreement for most
banks and a small downward bias from assumed zeros. Read `pdl_tot_non_1403` directly if you
need reported values only.

`pastdue_tot` starts at **2001Q1** rather than 1985 — `pd30_tot` (`RCFD1406`) is not collected
earlier. `npl_tot`, which does not use it, runs the full period.

**Relevance to BEC.** BEC uses this series as `na_loans`, which splits the loan-loss reserve
between loan families and enters the loan-book denominators. BEC reads its own copy of the
formula (`data_preparation/config/assets.csv`), which still carries both errors.

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
