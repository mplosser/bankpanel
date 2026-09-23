# The FR Y-9C panel (`bankpanel_y9c`)

The FR Y-9C is the consolidated financial statement of a bank holding company (and, since
2012, savings-and-loan holding companies and, since 2015, intermediate holding companies).
`bankpanel` builds it with the same engine and the same variable names as the Call Report
panel, so a holding company and its lead bank can be compared column for column.

```bash
bankpanel lint --profile fry9c
bankpanel build --profile fry9c --raw-dir /path/to/data_fry9/data/processed/y_9c --out y9c_root --jobs 4
bankpanel expectations build --profile fry9c --panel-root y9c_root
bankpanel validate all --profile fry9c --panel-root y9c_root --save
```

`--profile fry9c` selects `configs/y9c/` and the `fry9c` report profile. The raw files come
from [`data_fry9`](https://github.com/mplosser/data_fry9); the parser there must keep every
column a Y-9C filer carries (its 2026-09 version does), not only `BHCK`.

## Coverage and shape

1986Q3–2025Q3, 157 quarters, 187,763 holding-company-quarters, ~850 columns. Filers per
year track the reporting thresholds: ~1,300–1,700 through 2005, ~2,400 in 2006 (the $150m
floor), ~1,100 after the $500m floor, ~660 in 2018 and ~380 from 2019 (the $3bn floor).

## How the configs were made

`configs/y9c/` is **generated** from `configs/call/` by `tools/derive_y9c_configs.py`, not
written by hand, and is regenerated whenever the Call configs change. The Y-9C shares the
Call Report's four-character item codes (`BHCK2170` is `RCFD2170`; Schedule HC mirrors RC,
HI mirrors RI), so most of the translation is a prefix rule:

| Call Report prefix | Y-9C prefix | meaning |
| --- | --- | --- |
| `RCFD`, `RIAD` | `BHCK` | consolidated |
| `RCON` | `BHDM` | domestic offices |
| `RCFA`, `RCOA` | `BHCA` | regulatory capital, standardized |
| `RCFW`, `RCOW` | `BHCW` | regulatory capital, advanced approaches |
| `RCFN` | `BHFN` | foreign offices |

A translated base row is kept only if its code appears in at least one Y-9C quarter; a
derived row only if every input survives. Everything dropped is listed with its reason in
[`review/y9c_dropped.csv`](../review/y9c_dropped.csv). What did not translate falls into
three groups:

* **Domestic-office detail (225 codes).** The BHC form reports these consolidated only;
  the consolidated version is in the panel.
* **Not collected on the Y-9C.** The RC-B/RC-C maturity and repricing schedules, RC-O
  (FDIC assessments), RC-T (fiduciary and custody), and the domestic deposit
  interest-expense split.
* **Filed under a different code.** About sixty items, resolved one at a time from the
  MDRM descriptions and recorded in
  [`reference_data/y9c_code_map.csv`](../reference_data/y9c_code_map.csv) (one-to-one
  recodes), [`reference_data/y9c_extra_base.csv`](../reference_data/y9c_extra_base.csv)
  (codes the Call never used) and
  [`reference_data/y9c_formula_overrides.csv`](../reference_data/y9c_formula_overrides.csv)
  (how the Call name is rebuilt from them). Examples: interest-bearing balances are two
  codes (U.S. and foreign offices); loan interest income is one code through 2000, another
  for 2001–2007 and four lines from 2008; fed funds and repos ran under their own split
  codes from 1988Q2 to 2001Q4; C&I charge-offs are filed by addressee.

Every published base column is checked cell for cell against its raw code over all 157
quarters (`tools/raw_identity_check.py`); the build ships at 0 differences.

## What differs from the Call Report

**No form types; a size tier instead.** The Y-9C is one form, but holding companies under
$5bn in total assets file a set of items at Q2 and Q4 only (the CECL amortized-cost detail,
the HI-B charge-off detail, …). The `form_type` column therefore carries a **size tier**
computed from each quarter's own `BHCK2170`: `1` under $5bn, `2` at or above, with
`form_type_source = "size_tier_5bn"`. The threshold was measured, not assumed: in 2024–25
off-quarters 3% of filers under $5bn report those items and 94–96% of filers above. The
expectations matrix, coverage validator and ledger all work per tier.

**Income of predecessor institutions.** Schedule HI's memorandum (`BHBC` prefix, from
2003Q1) reports, in the quarter of a business combination, the acquired institution's
income for the year-to-date period before the acquisition: 31 items (total interest income
and expense, net income, provisions, charge-offs, quarterly averages, …). They are
published as filed under `pred_<stem>` (`pred_ytd_int_inc`, `pred_net_income_loss`) with
`flow_type = ytd_event`: a single amount, never differenced, no `q_` companion. Nothing is
built on them. A merger-adjusted quarterly flow would need the predecessor's own
year-to-date at the prior quarter, which the memorandum does not give (the amount runs to
the acquisition date, so for a Q3 acquisition it includes the predecessor's Q1 and Q2).
For the first two quarters after the memorandum was introduced (2003Q1–Q2) most filers
wrote zeros; a zero there is not evidence of no acquisition.

**Business-combination flags.** `structflag_business_combo` (`BHCKC251`, 2002–; `BHCK6688`
1990–2001) and `structflag_restatement` (`BHCK6689`) are in `configs/y9c/hi_mergers.csv`,
with the acquisition-date loan items (`BHCKKX60–62`).

**Zero-fill rules are not copied.** Every zero-fill rule is a measured statement about one
report's files. The Y-9C's own rules live in `reference_data/y9c_zero_fill.csv`; today they
cover the three foreign-office items whose zeros stop being written at 2025Q2 (the share of
filers with a non-zero value is unchanged while the written zeros vanish; see
[CAVEATS §11](CAVEATS.md) for the same pattern on the Call Report at 2005Q3).

**Regulatory capital.** `BHCA` (standardized) is primary; CET1 also reads the
advanced-approaches column `BHCW` for the holding companies that file it, as on the Call
Report's 031.

## Coverage ledger

[`configs/y9c/coverage_expected.csv`](../configs/y9c/coverage_expected.csv) explains every
coverage step the validator finds (0 open on the shipped build). Events specific to the
Y-9C, beyond those shared with the Call Report: the 1990Q3 revision (pre-1990 codes for
nonaccrual totals, OREO and foreign interest expense are not mapped), the 2001Q1 extension
of HC-B detail to all filers, the 2003Q1 predecessor memorandum, the 2008Q3 fair-value
option (one quarter earlier than on the Call Report), and the 2019Q4 burden relief that
removed HC-B securities detail and HI-B charge-off detail for holding companies under
$5bn. A one-page view by event is `review/07_y9c_coverage_ledger_by_event.csv`.

## Known limits

* No maturity/repricing schedules, so duration-style analysis cannot be done at the BHC
  level from this panel.
* 1986–1990 is thin for the recoded items listed above.
* The negative-flow audit flags ~6% of BHC-quarters on the `q_` companions (year-to-date
  resets around mergers and restatements), the same order as the Call Report; treatment is
  the analyst's choice (see [CLEANING](CLEANING.md)).
