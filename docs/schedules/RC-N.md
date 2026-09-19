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

The nonaccrual column of the main body follows the same scheme, and its 17 published
categories are the terms of the `na_tot` reconstruction below:

| `na_` category | codes | | `na_` category | codes |
| --- | --- | --- | --- | --- |
| `constr` | F176+F177 / 3492 / 5426 | | `agprod` | 1583 (031 only — see below) |
| `nfnres` | F182+F183 / 3504 / 5441 | | `ci` | 1608 / 1253+1256 |
| `farmland` | 3495 | | `cc` | B577 / 5385 / 1220 |
| `heloc` | 5400 | | `auto` | K215 |
| `famres_first` | C229 | | `indiv` | K218 |
| `famres_junior` | C230 | | `forgovt` | 5391 |
| `famres_closed` | 5403 (not a term: = first + junior) | | `othln` | 5461 |
| `multifam` | 3501 | | `lease` | 1228 / F168+F171 |
| `depinst` | B836 / 5379+5382 | | `re_foreign` | B574 |

Where a category has both a total code and a breakdown, only the total is published; the
breakdown pieces are `[INTERMEDIATE]`. `na_tot` is the reported `RCFD1403`, else the sum;
`na_tot_1403` is the reported series alone.

These columns were renamed on 2026-09-19 from the legacy `pdl_*_non` / `na_re_3495`-style
names (`reference_data/legacy_names.csv` has the map). `tools/parity_check.py` reads that
map, so the renamed columns are still compared against the legacy panels under their old
names rather than silently dropping out of the shared set.

## The reported totals disappear for 2011–2016, and are rebuilt

`RCFD1403` (nonaccrual), `RCFD1406` (past due 30–89) and `RCFD1407` (past due 90+) are the
schedule's total lines. All three stop at 2010Q4 and resume at 2017Q1; for 2011–2016 the
totals are not collected and only the by-category lines exist. `na_tot`, `pd30_tot` and
`pd90_tot` are the reported total where it exists and the sum of the categories where it
does not, built the same way for all three: **each category once, as its total or as its
breakdown, never both.**

| category | published as | total code, else breakdown |
| --- | --- | --- |
| construction, land development, other land | `{pd30,pd90,na}_constr` | F172+F173 / F174+F175 / F176+F177 from 2007; 2759 / 2769 / 3492 before (031: 5426 for na) |
| nonfarm nonresidential | `_nfnres` | F178+F179 / F180+F181 / F182+F183 from 2007; 3502 / 3503 / 3504 before |
| C&I | `_ci` | RCON1606 / 1607 / RCFD1608, else the 031 split US + non-US addressees |
| depository institutions | `_depinst` | RCONB834 / B835 / B836, else the 031 split US + foreign banks |
| leases | `_lease` | RCON1226 / 1227 / 1228, else the 031 split individuals + all other |
| consumer other than credit cards | `_consumer_noncc` | auto + other from 2011 (K213/K216, K214/K217, K215/K218); the single line B578 / B579 / B580 for 2001–2010 |
| agricultural | `_agprod` | 1594 / 1597 / 1583 — **031 filers only**; on the 041/051 it is inside all other loans |
| farmland, revolving 1–4 family, closed-end first and junior liens, multifamily, credit cards, foreign governments, all other loans, real estate in foreign offices | as reported | single codes |

Every "else" was tested where both sides are reported: the pre-2007 construction and
nonfarm-nonresidential totals equal the sum of their 2007 splits for **100%** of banks in
2007–2010, and the 041 totals never co-report with the 031 breakdowns. Loans to
nondepository financial institutions (2024Q4 on) are *not* a term: added, the sum overshot the
reported total by exactly that line on every affected bank, so they sit inside all other loans.

**How close it gets.** Category sum against the reported total, where both exist:

| | 2017Q1 on (176,784) | 2007–2010 (120,192) | 2001–2006 (198,170) |
| --- | --- | --- | --- |
| `na_tot` vs 1403 | **100.00%**, ratio 1.0000 | **100.00%** | 91.8% |
| `pd30_tot` vs 1406 | **100.00%**, ratio 1.0000 | 98.9% (041: 100%) | 85.7% |
| `pd90_tot` vs 1407 | **100.00%**, ratio 1.0000 | 99.2% (041: 100%) | 92.6% |

All three match exactly on every form from 2017, which is the test that matters: the
reconstruction runs on 2011–2016 filings of the same shape. Before 2011 the 041 filers match
from 2007; what remains short there is the **031 filers before 2011**, whose own lease
breakdown before the 2007 split (`1257/1271`, `1258/1272`) is not carried. Since the
reported total is used wherever it exists, that affects only the 031 category totals before
2007, not `pd30_tot` / `pd90_tot`.

Handoffs, over the same banks: −5.7% / −6.4% for `pd30_tot` at 2011Q1 / 2017Q1, −2.1% /
−7.1% for `pd90_tot`, −4.3% / −5.2% for `npl_tot`; the stitch validator scores every one
within the series' own quarterly movement (robust z ≤ 1.1). `npl_tot` and `pastdue_tot`
now cover 2011–2016 completely; before this they were blank there.

## The nonaccrual reconstruction in detail: what was wrong and how it was found

**How often it runs.** `na_tot` is the reported `RCFD1403` on 88.5% of rows. Where
`RCFD1403` is missing — 160,902 bank-quarters, almost all 2011Q1–2016Q4 — it is rebuilt from
the RC-N nonaccrual column by category.

**Each category is counted once: as its total or as its breakdown, never both.**

| category | published as | total code, else breakdown |
| --- | --- | --- |
| construction, land development, other land | `na_constr` | `F176 + F177` from 2007; `3492` before; `5426` for 041 filers 1991–2000 |
| nonfarm nonresidential | `na_nfnres` | `F182 + F183` from 2007; `3504` before; `5441` for 041 filers 1991–2000 |
| depository institutions | `na_depinst` | `RCONB836`, else `5379 + 5382` |
| C&I | `na_ci` | `RCFD1608`, else `1253 + 1256` |
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

**Agricultural loans are counted once, and which line depends on the form.** On the FFIEC
031, agricultural nonaccrual (`1583`) is its own line. On the 041 and 051 it is reported
*inside* all other loans (`5461`) — the MDRM note on `1583` reads "beginning 3/31/01,
reported in Schedule RC-N Past Due for the FFIEC 041 report; not applicable to banks filing
the FFIEC 031", and the data agrees: where both are reported, all other loans ≥ agricultural
for 100% of 041/051 filers and only 66% of 031 filers. So the term is
`na_agprod.where(form_type == 31)`. Counting it for everyone had overstated 11,732
bank-quarters in 2011–2016 by exactly their agricultural line — $4.6bn, 0.16% of the
reconstructed total, 3.3% for the banks affected. `form_type` is readable in formulas for
exactly this reason; see [../CONFIG_FORMAT.md](../CONFIG_FORMAT.md).

**How close it gets now.** Scored against `RCFD1403` where both exist:

| window | bank-quarters | matches exactly (±$1k) | sum ratio |
| --- | --- | --- | --- |
| 2017Q1 on | 176,784 | **100.00%** on every form (was 39–44%) | **1.0000** (was 1.053) |
| 2007–2010 | 120,191 | 55.0% | 0.985 |
| 2001–2006 | 198,169 | 50.0% | 0.918 |

From 2017 the construction reproduces the reported total exactly, so where the
reconstruction actually runs (2011–2016, the same form) it can be trusted to the same
degree. The handoffs are −5.6% at 2011Q1 and −3.9% at 2017Q1 over the same banks;
nonaccruals were falling steadily through that period and the stitch validator scores the
2011Q1 step at robust z = 0.7, inside the series' own quarterly movement.

The pre-2011 shortfall is one code: `RCFDB580`, other loans to individuals, which the 2011
`K215`/`K218` split replaced. Every remaining mismatch there equals `B580` exactly. It touches
3 reconstructed rows and is not carried; the pre-2011 category totals are affected, `na_tot`
is not.

**Blank inside the window means zero — and after the fix there is almost nothing left to
assume.** A category that is blank while its line is being collected enters the sum as zero.
`bankpanel validate quality` counts those assumptions per column; `na_tot` had 64,164 of them,
all agricultural — and every one was a 041 bank whose agricultural nonaccrual was inside all
other loans, not blank. Counted correctly, `na_tot` rests on an assumed zero for **2**
bank-quarters. Where no category is reported at all the total is blank, not a fabricated
zero (1,223 rows before).

**The credit-card stitch was blank before 2001.** `na_cc` is `B577` from 2001; the fallback
*summed* the two pre-2001 codes (`RCFD5385` on the 031, `RCON1220` elsewhere), and since no
bank reports both, the sum was blank for the entire pre-2001 era — 717,918 bank-quarters.
Coalesced, coverage is 0.72 in 1985 and 1.00 from 1995. The balanced-panel step at 2001Q1 is
−10.0%: the pre-2001 items are "credit cards **and related plans**", and `B577` is credit
cards alone, so the series narrows slightly at the definition change. Recorded, not repaired.

**What this means for `npl_tot` and `pastdue_tot`.** Both inherit it. For 88.5% of rows they
rest on a reported total; on the reconstructed rows, expect near-exact agreement for most
banks and a small downward bias from assumed zeros. Read `na_tot_1403` directly if you
need reported values only.

`pastdue_tot` starts at **2001Q1** rather than 1985 — `pd30_tot` (`RCFD1406`) is not collected
earlier. `npl_tot`, which does not use it, runs the full period.

**Effect on BEC, measured.** BEC uses this series as `na_loans`, which splits the loan-loss
reserve between loan families, enters the loan-book totals, and feeds a footing gate. Two full
pipeline runs on identical code — one on the production panels, one on these panels emitted
through `tools/export_legacy_panels.py` — differ only through the three fixed columns:

| | |
| --- | --- |
| bank-quarters whose `na_loans` changed | 101,664, all 2011–2016 (plus a handful of pre-2011 rows from the credit-card stitch) |
| `na_loans`, aggregate on those rows | **−15.0%**; median bank **+4.0%** |
| EC (industry spread, 5y horizon), mean over affected bank-quarters | **+6.0 bps of assets**, median +2.4 |
| EC, aggregate | **−$476bn** summed over affected bank-quarters, of which 89% is four banks with assets above $1tn |
| aggregate EC / assets, 2011–2016 | **−8 to −19 bps** each year; zero outside the window |
| bank-quarters restored to the panel | **+1,382** (2011–2016): previously dropped by `flag_matlow` because missing C&I nonaccrual made the loan book foot 2.5%+ short |

The two halves pull opposite ways. The 041 filers — nearly every bank — gain the C&I
nonaccrual total that was missing, so `na_loans` rises (+2.3% for banks under $10bn) and
their EC rises a few basis points. The largest mortgage banks lose the double-counted
modified 1–4 family memo item (`RCONF663`), so their `na_loans` falls (−19.7% for banks over
$10bn) and, because nonaccrual loans enter the "other" loan-book total that the reserve
deduction scales, their loan fair value and EC fall. Both are corrections of the same
construction error, in opposite directions for different banks.

BEC's own config still carries the old formula; the shim is how the corrected panel reaches
it.

## What the data shows

Aggregate nonperforming loans (`npl_tot` = `pd90_tot` + `na_tot`) against loans:

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
