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

- **`FINANCIAL INSTITUTION STATE` is unusable.** In the CDR-era files it is typed as
  `float64` and is **99.98% null** (2-letter state codes fail numeric coercion). Other
  identity fields — name, city, FDIC certificate number — are intact. Do not use the
  header dataset's `state` column until this is fixed upstream.

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

