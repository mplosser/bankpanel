# Caveats

Read this before using the panel for research. Every number below was measured against
the source data, not inferred from documentation.

---

## 1. `RCFD` and `RCON` are not independent after 2011

The upstream parser (`data_call_report/05_parse_ffiec.py`) cross-fills the consolidated
(`RCFD`) and domestic (`RCON`) versions of an item, creating whichever is missing. But it
matches pairs with the regex `^(RCFD)(\d+)$`, and `\d+` only matches **all-numeric** item
codes. The consequence is not uniform:

| item code | shape | 2020Q1 `RCFD` coverage | 2020Q1 `RCON` coverage | identical? |
| --- | --- | --- | --- | --- |
| `2170` | numeric | 1.000 | 1.000 | **yes, byte-for-byte** |
| `3123` | numeric | 1.000 | 1.000 | **yes, byte-for-byte** |
| `A570` | alphanumeric | 0.016 | 0.984 | no |
| `B528` | alphanumeric | 0.016 | 0.984 | no |

So after 2011:

- For **numeric** codes, `RCFD2170` and `RCON2170` carry the same values. Comparing them
  to measure foreign-office activity yields exactly zero, which is an artifact, not a
  finding.
- For **alphanumeric** codes, the two are genuinely disjoint: `RCFD` holds only the ~1.6%
  of banks filing form 031, `RCON` holds the rest.

`bankpanel` coalesces the pair per row (`RCFD` primary, `RCON` fill), which is a harmless
no-op in the first case and essential in the second. Before 2011 the two are independent
in the usual way.

---

## 2. FFIEC 051 filers report many items only twice a year

This is the single most consequential caveat, and the easiest to miss.

The FFIEC 051 short form began in 2017 and is now filed by the **majority** of banks.
051 filers do not merely omit items — they report hundreds of them **semiannually**.

Measured for `RCON3549` across 2023, among 051 filers:

| quarter | 051 coverage | 041 coverage |
| --- | --- | --- |
| 2023Q1 | 0.003 | 0.619 |
| 2023Q2 | **1.000** | 0.615 |
| 2023Q3 | 0.001 | 0.518 |
| 2023Q4 | **1.000** | 0.417 |

Across the 3,650 numeric columns in 2023, roughly:

- **402 columns** are covered for 041 filers and essentially absent for 051 filers;
- **559 columns** are collected from 051 filers **in Q2 and Q4 only**;
- **33 columns** are collected from them **in Q4 only**.

**What this means for you.** A NaN in Q1 or Q3 for an 051 filer means *not collected*. It
does not mean zero, and it does not mean the bank failed to report. Any quarterly average
computed over 2017-present without accounting for this is silently a form-041-only sample
— which is a sample of larger banks.

Every row of the panel carries `form_type` (31/41/51) so you can condition on it:

```python
df = bp.read_panel(columns=[...], start="2017Q1", form_types=(41,))   # form-consistent
```

---

## 3. The source changes provider at 2010Q4 → 2011Q1

Quarters through 2010Q4 come from the Chicago Fed's SAS transport files; 2011Q1 onward
come from the FFIEC CDR bulk files. The two carry different metadata columns, and some
legacy items simply stop.

`RCON1415` (combined construction and land development lending) is the clean example. It
is reported by **100%** of banks from 1985 through 2010Q4 and is **absent** from 2011Q1.
MDRM gives the item an end date of 2007-12-31. Both statements are true of different
things: MDRM describes when the item left the current *forms*, while the Chicago Fed
extract kept publishing it. The disappearance at exactly the provider boundary means the
observed end date is a property of the **source**, not necessarily of the report.

Config `era_end` values record what is *measurable in this source*. Where that differs
from MDRM, the config says so in a comment.

**Corollary:** treat any level shift at 2010Q4/2011Q1 as suspect until you have checked
whether it is economics or provenance.

---

## 4. `form_type` before 2011 is derived, and pre-2001 it is incomplete

There is no filing-type field before 2011. `bankpanel` derives one from `CALL8786`, the
reporting level code (1 = consolidated including foreign offices, 2 = domestic only).

Validated on the 6,920 banks present in both 2010Q4 and 2011Q1:

```
2011Q1 FILING TYPE     31      41
CALL8786
1.0                   109       4
2.0                     0   6,807
```

109 of 113 exact, nothing misassigned into the 41 bucket; the 4 discordant banks genuinely
changed form. Rows carry `form_type_source` (`cdr_field` or `call8786_inferred`) so the
distinction is never hidden.

**Limitation:** before 2001, the `8786 == 2` bucket also contains FFIEC 032/033/034
filers, which that field cannot separate. Those rows are labelled 41. No heuristic is
applied to guess further.

About 95 rows across the whole panel (mostly 1985-1988) have a reporting level that is
neither 1 nor 2; their `form_type` is left null rather than guessed.

**Before 1984 the reporting level code carries no information** (level 1 for 0-6 banks a
quarter, against 140-200 banks reporting foreign-office items; from 1984Q1 the two line up).
There `form_type` is 31 for a bank with foreign offices -- it reports any foreign-office
(RCFN) item, or its consolidated total assets differ from its domestic total assets -- and
41 otherwise (`form_type_source = pre1984_foreign_items`). The forms of the time were the
FFIEC 010-014, not the 031-034, so 31/41 here means "with / without foreign offices", which
is what the consolidated-vs-domestic rule needs (§13).

---

## 5. Year-to-date conversion has two failure modes, and they are reported

Income items are year-to-date and reset each Q1, so quarterly flows are differences within
a bank-year. Two situations have no valid difference:

- **Intra-year gaps.** A bank missing Q2 has no computable Q3 flow; the naive difference
  `ytd(Q3) - ytd(Q1)` spans two quarters.
- **Partial first years.** A bank whose first filing of a year is Q3 has nothing to
  difference against; its year-to-date-through-Q3 is *not* a quarterly flow. This affects
  every de-novo bank's first partial year and every acquired bank's final year.

- **Blank prior quarter.** The row exists but the item is blank — the annual-filer case.
  Through 2000, 60–75% of banks filed the Schedule RI-A items (dividends, other
  stockholder transactions) at Q4 only. The Q4 value is a year's total, not a fourth
  quarter's flow.

Every year-to-date item is published twice, `ytd_<stem>` as filed and `q_<stem>` the
flow, so nothing is lost by refusing to difference: the annual filer's total is in
`ytd_`, its `q_` is NaN for the year. Default policy is `nan` — an uncomputable flow is
unknown. `--gap-policy spread` divides a k-quarter difference by k (an average, and it
does **not** create rows for the missing quarters). `--gap-policy keep` reproduces the
older, buggy behaviour (year-to-date booked as a flow) for migration comparison only.

Measured on the 1985–2025 build, the cells with no clean difference are 578K blank-prior-
quarter (annual filers), 191K row-missing (partial first/last years, five true gaps),
and 1,818 where an earlier in-year anchor would allow an average — too rare to build a
rule for. Structural events are listed in `quarterize_gaps.parquet`.

**The flows that are computed can be extreme.** A difference is only as good as the two
year-to-date figures behind it, and several events move income between quarters:

- **Mergers and acquisitions.** Under purchase accounting the acquirer's year-to-date income
  includes the target only from the merger date; under pooling of interests (until mid-2001) the
  earlier quarters of the year are restated. Either way the merger quarter's difference can be
  far too large or negative, and flows over that quarter no longer match end-of-quarter
  balances.
- **Accounting and reporting.** Restatements, amended reports, reclassifications between
  income lines, and corrections folded into the next year-to-date figure. These roughly
  preserve the year's total, so they arrive in pairs: a negative or collapsed quarter beside
  an inflated one. Repairing only the negative leg leaves the inflated one standing.

Measured on the 1976-2026 build, `validate quarterize` finds 132,440 impossible-negative cells
in 60 flow columns, affecting 82,584 bank-quarters (4.2%). Only 5.4% of those bank-quarters
carry the bank's own business-combination flag and 3.1% its restatement flag; the rest are
unexplained by any filed indicator. The inflated twins are not counted.

bankpanel applies no cleaning to these flows on disk -- no winsorizing, smoothing or repair --
beyond leaving a flow blank where no clean difference exists. The negatives are reported, not
fixed. The opt-in `bankpanel.clean` functions help: `interpolate_negative` blanks an impossible
negative in a raw flow and fills it from the bank's own history (the negative leg only), and
`interpolate_broken_ratio` repairs a rate built on flows with both legs of a pair replaced
together; every changed cell is recorded (docs/CLEANING.md). For analysis,
prefer `ytd_` year totals where the question allows, or screen `q_` values before using them.

---

## 6. Identity, mergers, and restatements

- The panel is keyed by **filer RSSD**. No merger, survivorship, or successor adjustment
  is applied. A bank that acquires another shows a discontinuous jump in balances and a
  reset in year-to-date flows.
- The data reflects the source files **as downloaded**. It is not a point-in-time vintage
  archive, so a restated figure appears at its restated value, not as originally filed.
- RSSD identifiers are not stable across some reorganizations. Linking entities over time
  requires NIC transformation data, which is out of scope here.

---

## 7. Units, types, and precision

- All monetary values are **thousands of USD**.
- The panel is stored as `float64`. `read_panel(dtype="float32")` halves memory, but a
  24-bit mantissa is exact only to 16,777,216 — in thousands of dollars, that is about
  $16.8bn, above which balances lose exactness and accounting identities stop closing
  exactly. Use it for exploration, not for footing statements.
- `assets = liabilities + equity` closes to within 0.1% for **98.3%** of bank-quarters
  using `RCFD3210` alone, and **99.97%** once minority interest / noncontrolling
  interests are included. The gap is the pre-FAS 160 presentation, where minority interest
  sat outside equity. Use an equity measure that spans that change.

---

## 8. Known upstream data defects

These originate in `data_call_report`, not in `bankpanel`, and are passed through:

- *(Fixed upstream 2026-09-24.)* Until then the CDR-era `FINANCIAL INSTITUTION STATE`
  and 41 other text fields (names, ZIP+4, `TEXT*` labels) were nulled by a numeric-coercion
  bug in `05_parse_ffiec.py`. The re-parsed files carry them; the header's `state` column
  is filled for every CDR-era bank. A build from raw files parsed before that date still
  has the gap.
- Confidential items (the literal `CONF` in the CDR files; mostly Schedule RC-O
  assessment lines) are dropped at parse time since 2026-09-26. No panel column used them.

## 9. Three definition changes at 2001Q1, published as separate series

The 2001Q1 form revision changed what three lines measure. The panel does not stitch across
a definition change: each half is a separate column, and the old one carries an era suffix.

| through 2000Q4 | from 2001Q1 | why they differ |
| --- | --- | --- |
| `accrued_int_loans_pre01` (`RCFD2164`) | `accrued_int` (`RCFDB556`) | income earned not collected **on loans** → accrued interest on **all** assets. +38.7% at the boundary over the same banks, more for banks holding more securities. No all-asset code exists before 2001. |
| `ln_cc_incl_revolving_pre01` (`RCFD2008`) | `ln_cc` (`RCFDB538`) + `ln_revolving_oth` (`RCFDB539`) | credit cards **and related plans** → credit cards alone; the plans became their own line. |
| `na_cc_incl_revolving_pre01` (`5385`/`1220`) | `na_cc` (`RCFDB577`) | the same carve-out on the nonaccrual side; the revolving-plan nonaccruals have no code of their own after 2001. |

Where the split turned one line into two, the sum is the old definition and is published as
a consistent series: **`ln_cc_incl_revolving`** = `2008` → `B538 + B539` (−3.4% at the
boundary, inside the ±5–9% seasonal swing on either side). **`ln_consumer_oth`** (other
consumer loans excluding cards and revolving plans; `2011` → `K137 + K207`) is consistent
throughout, +3.3% at 2001Q1 and −0.3% at 2011Q1. The legacy `ln_othcons`, which added the
revolving plans from 2001 only, is retired (`reference_data/legacy_retired.csv`).

A consumer who needs one accrued-interest number across 2001 must coalesce the two columns
knowingly; the panel will not do it silently.

## 10. Some totals rest on an assumed zero

A derived total that sums components has to decide what a blank component means. On a Call
Report a blank overwhelmingly means "nothing to report" — banks leave inapplicable lines
empty rather than typing 0 — so summing with `fillna(0)` is right far more often than not.
But it cannot distinguish *had nothing* from *did not report*, and where it guesses wrong
the total comes out low.

Two cases, and only one is a problem:

- **The component was outside its collection era.** Zero-filling is the era stitch working.
  `brokered_dep_mat_lte1yr` has 846,943 rows with missing components and **zero**
  assumptions.
- **The component was being collected that quarter and this bank left it blank.** The zero
  is an assumption.

`bankpanel validate quality` reports the second case per column, with liveness measured
per quarter from the cross-section. Six columns are affected and none materially: the
largest is `oth_assets` at 6,637 rows (0.5%). `na_tot` once showed 64,164, all agricultural
nonaccrual on the 041 form — which is reported inside all other loans there, not blank.
Counted on the right line it falls to 2 rows. See [schedules/RC-N.md](schedules/RC-N.md).

Because these formulas are pure sums of non-negative quantities with no subtraction, the
bias is one-directional: affected totals are too low, never too high.

---

## 11. Zeros the source stopped writing at 2005Q3

From 2005Q3 the source files no longer write a zero for a conditional item a bank does not
have. On 28 columns -- RC-T custody and fiduciary detail, RC-D trading detail, the
agricultural past-due, charge-off and average-balance lines, and the credit-card fee lines
-- the share of banks with a **non-zero** value is unchanged across 2005Q2 -> 2005Q3
(custody 3.5% -> 3.3%, trading 0.2% -> 0.2%, agricultural nonaccrual 9.3% -> 8.6%) while
the share reporting a zero collapses (86% -> 3%, 89% -> 3%, 86% -> 44%). This is not the
2010Q4/2011Q1 provider change.

Left as filed, those rows drop out of every sum and average after 2005Q3 but not before,
which is a bias of its own. The panel therefore resolves the blank to zero from 2005Q3
(`scope=in_era_unless_reported`, 9.5 million cells, no reported value altered), except
where a zero would be invented: a bank that reports the item in another quarter of the year
(Schedule RC-T is annual for smaller trust banks -- their Q1-Q3 stay blank), a quarter in
which no filer of the bank's form reports the item, and forms outside the item's scope
(the 051 has no credit-card fee lines, though two or three of its filers volunteer one).


**The newest partial year (from 1.4.1).** "Reports the item in another quarter of the year"
can only be judged on the quarters present. Until 1.4.1 a bank that files an item only at Q4
looked, in the newest year, like a quarterly filer that left Q1-Q3 blank, and those cells
were zero-filled (3,176 cells in 2025Q1-Q3 before 2025Q4 arrived, 3,155 of them fiduciary and
custody items). The unfinished year is now built after the finished one before it, and a
bank whose reports last year all fell in quarters not yet arrived keeps its blanks.

**The other side of 2005Q3: annual filers' written zeros (from 1.5).** Before 2005Q3 the
source wrote a zero where it later leaves a blank, including for items a bank was not asked
that quarter. Schedule RC-T is collected at Q4 only from smaller trust departments (median
$13M under administration, against about $1bn for quarterly filers), and until 2005Q2 their
Q1-Q3 values are 0 in the source: in 2003, of 1,773 banks with RC-T dollars at Q4, the June
value is 0 for 1,218, blank for 182 and reported for 370. In 2007 it is 0 for 2 and blank
for 1,248. Those zeros mean "not collected this quarter". Under `[BLANK_ANNUAL_ZEROS]`, up to
2005Q2, a bank-year with no non-zero Q1-Q3 value and a non-zero Q4 value has its Q1-Q3 zeros
published blank: 12,830 bank-quarters at 1,411 banks on each RC-T item. A bank with no trust
business keeps its zeros. A scan of every published column 1985-2007 for items reported far
more often at Q4 (or in June and December) than in the other quarters, with written zeros in
between, found no other case. The candidates it raised were genuine: year-to-date charge-offs
first incurred in Q4, annual dividends, and the one-time 1995Q4 reclassification of
securities into available-for-sale.


---

## 13. Consolidated means consolidated (from 1.4)

Until 1.4 a consolidated column fell back to the domestic figure whenever the consolidated
code was blank, for every bank. For the ~80-110 banks with foreign offices (the FFIEC 031
filers, which hold most of the system's assets) that put a DOMESTIC number under a
consolidated name wherever the form collects only the domestic item -- quarterly average
loans by category, nonaccrual by real-estate type, the real-estate loan pieces before 2013Q2.
The upstream parser did the same from 2011, and the Chicago Fed files did it before 2011
under the consolidated code itself. Citi's "average total loans" read 0.62 of its loan book:
that was its domestic share.

The official rule now leaves such cells blank (docs/CONFIG_FORMAT.md). Items that are
domestic by construction carry their domestic code and say so. Average total loans is the
exact sum of the domestic and foreign pieces (`RCON3360 + RCFN3360`), identical to the
reported consolidated average wherever that is filed. Every build's `validate scope` shows
where international banks are left blank.

---

## 12. Known gaps (deferred to 1.4)

Two things are documented rather than done. Neither affects a column after 1990 on either
panel, and neither is hidden: the ledger rows are signed and the dictionary shows the eras.

**FR Y-9C items before the 1990Q3 revision.** `configs/y9c` is generated from
`configs/call` by prefix translation, which is exact where the two forms share item codes.
Before 1990Q3 a handful of Y-9C items carried codes that the Call Report never used, so the
translated column starts at 1990Q3 and the 1986Q3–1990Q2 quarters are blank. The coverage
ledger (`configs/y9c/coverage_expected.csv`) records five columns at the 1990Q3 revision:
`na_tot_1403` and `pd90_tot_1407` (nonaccrual and 90-day past-due totals), `oreo`,
`ytd_int_exp_for` (foreign-office interest expense) and `ytd_int_inc_ln_foreign`. (The
two 1988Q2 rows, `ffrepo_ass_1350` / `ffrepo_liab_2800`, are a retirement of combined
fed-funds/repo codes that *is* handled by the split codes from 1988Q2.) Recoding the
1990Q3 five means a per-item era map in `reference_data/y9c_code_map.csv`, a rebuild, and
a re-signed ledger. Until then, treat 1986Q3–1990Q2 on those columns as not collected,
which is what `expected_mask` reports.

**Schedule HC / HI notes.** `docs/schedules/` documents the Call Report schedules whose
construction needed judgment (RC-B, RC-C, RC-D, RC-E, RC-K, RC-N, RC-O, RC-R Part I, RI-A,
RI-B). The Y-9C schedules HC-B, HC-C, … , HI-B are the same constructions under `BHCK` /
`BHDM` codes, so those notes apply to the Y-9C by construction; what is missing is a page
per Y-9C schedule recording the exceptions listed in [FR-Y-9C.md](FR-Y-9C.md) (the size
tier, the 2019Q4 burden relief, the predecessor memorandum) next to the corresponding
Call Report note.


---

## 14. 1976-1984: a different reporting regime (from 1.6)

The Call panel starts in 1976Q1 from 1.6. The Chicago Fed files for 1976-1984 are the same
source as 1985-2010, but the reports behind them differ, and the first pass publishes only
the item codes the later forms use. Read the period with these in mind; each point is
measured and signed in the coverage ledger (`configs/call/coverage_expected.csv`).

- **Income is semiannual through 1982.** Most banks filed the income report only in June and
  December: the March and September files carry income for 1-3% of domestic banks, against
  95-99% in June and December. From 1983 income is quarterly. Year-to-date values are
  published as filed; the quarterly `q_` flows follow the general rule (§5) and are blank
  wherever no clean one-quarter difference exists, which before 1983 is most banks. Nothing
  is interpolated or spread across quarters.
- **Dividends at mid-year** are carried for only 14-16% of domestic banks in 1980, 1981 and
  1984Q1-Q3, against 95-97% in the other years; year-end values are complete.
- **A family of forms, not the 031-034.** Before 1984 the Call Report was the FFIEC 010/012
  (domestic condition), 014 (condition of banks with foreign offices) and 011/013 (income).
  From 1978Q4 many items -- interest-bearing balances, other assets and liabilities,
  acceptances, other borrowed money, total securities -- are collected on the 012 and 014 but
  not the 010, so about 27% of domestic banks report them (reporters' median assets $83M
  against $22M, with no clean size cutoff). Minority interest is not collected at all from
  1978Q4 to 1983Q4. Everything returns for every bank with the 031-034 in 1984Q1; some items
  then move to the larger banks' forms only (fiduciary income, the past-due lines, other
  loans).
- **Source-file gaps.** The 1976Q4 file has a smaller layout (about 1,000 columns, no
  entity-type field, no foreign-office items): foreign deposits, total securities and large
  time deposits are missing that quarter. The 1983Q2-Q4 files omit the same items and
  deposits in foreign offices. Intangible assets are missing for most banks with foreign
  offices in 1983Q4. Entity types for 1976Q4 are borrowed from 1977Q1 and 1976Q3 by RSSD ID
  (see the data_call_report README).
- **Consolidated means consolidated here too.** For the 140-200 banks with foreign offices,
  a consolidated code the forms did not collect (MDRM: FFIEC 014 windows, e.g. consolidated
  loans and interest-bearing balances only from 1978Q4) carries a copy of the domestic figure
  in the source; it is discarded (about 39,700 cells), so those consolidated series are blank
  for these banks where the item was not collected. The MDRM validity table includes the
  pre-1984 forms, clipped at 1983Q4 because the FFIEC 014 number was later reused.
- **Written zeros in 1984.** In the first year of the 031-034 forms the source writes 0 for
  the end-of-period loan-loss allowance (RIAD3123) in quarters a bank did not report it,
  while the balance-sheet reserve (RCFD3123) is non-zero; 684 such zeros are published blank
  (`[BLANK_ANNUAL_ZEROS]`, annual and semiannual patterns). A scan of every column 1976-1985
  for other not-collected zeros found none.
- **The 1984 revision changed concepts, not just codes (from 1.7).** 67 published series are
  filed from 1984 but not before. Each was tested for a same-concept predecessor: every
  pre-1984 line (and every sum of two) that tracks it, scored bank by bank across the switch
  against a same-code benchmark, and, where old and new coexist in 1984, in the same quarter.
  Only two qualify, both as exact two-line links:
  - **Total liabilities** = liabilities excluding subordinated debt (RCFD2950) + subordinated
    debt (RCFD3200): 100% of banks in every 1984 quarter where both are filed. For banks with
    foreign offices, whose report did not collect consolidated subordinated debt in 1976-1983,
    it is total assets minus equity (both collected from them throughout; the identity holds
    for 98-100% of them on the 031 in 1984-2000). The same two-line link also fills the ~2% of
    banks with no filed total in 1984-85, so the series runs at ~94% of assets straight through.
  - **Income taxes** = taxes before securities gains (RIAD4260) + taxes on securities gains
    (RIAD4285), validated through the total-applicable-income-taxes line (RIAD4770): equal to
    their sum for 94.5% of banks in 1983 and to the new code for 97-99% after 1984 (the rest by
    $1 thousand, rounding).
  The other 65 are genuinely new in 1984 (interest income and expense replace operating income
  and expense, transaction/nontransaction deposits replace demand/time-and-savings, charge-offs
  by loan type start), as Kashyap and Stein also found.
- **Pre-1984 concepts published under their own names (from 1.7, `configs/call/pre1984.csv`).**
  `time_savings_dep_dom` (1976-2010, domestic offices; equal to total domestic deposits minus
  demand deposits for 99.3-99.8% of banks in every era; in 1984Q1-Q2, when the new forms
  moved NOW/ATS and Super NOW accounts out of the item, it is that difference),
  `ln_ci_incl_accept` (1976-2000), `othbor_incl_demand_notes` (1978-2000), and, to 1983,
  `deferred_inc_taxes_pre84`, `sec_oth_bonds_stocks_pre84`, `trad_acct_sec_pre84`. Each was
  checked for continuity across 1984 against its own quarter-to-quarter movement.
- **Banks with foreign offices, as a class.** Their pre-1984 report (the FFIEC 014) collected
  consolidated figures for about 22 of bankpanel's 501 consolidated items in 1976-78 and 39 by
  1983 (56 on the 031 in 1985): the core totals throughout, most loan detail only from 1978Q4,
  and subordinated debt, several loan types and accrued interest not at all. Where it did not,
  the consolidated column is blank; the domestic figure is not a consolidated one (where the
  031 later collected both, they differ for 10-70% of these banks). The domestic detail is
  published beside it under `_dom` names (`configs/call/domestic_twins.csv`: `ibb_dom`,
  `ln_gross_dom`, `ln_agr_dom`, `ln_ci_incl_accept_dom`, `ln_consumer_dom`, `subdebt_dom`,
  ...). The MDRM validity table uses the FFIEC 014's windows alone for these years -- the
  010/012 were filed by banks without foreign offices -- so a domestic figure the 014 did not
  collect (most domestic detail before 1978Q4) is also recognised as a copy and discarded.
