# Schedule RC-R Part I — Regulatory Capital

19 base items and 7 derived series. Three things about this schedule will silently break
an analysis, and all three are handled here.

## 1. The Basel I → Basel III change is a *prefix* change

The same MDRM item codes carry the same concepts on either side of 2015Q1, under a
different prefix:

| Concept | Basel I (through 2014Q4) | Basel III (2015Q1 →) |
| --- | --- | --- |
| Tier 1 capital | `RCFD8274` | `RCOA8274` |
| Tier 2 capital | `RCFD5311` | `RCOA5311` |
| Risk-weighted assets | `RCFDA223` | `RCOAA223` |

A variable pointed at either one alone goes blank for half the panel — and blank in a way
that looks like a coverage collapse rather than a regime change. The base items are
era-suffixed (`_baselI`, `_baselIII`) and `tier1_capital`, `tier2_capital` and `rwa`
stitch them. Coverage across the boundary:

| | 2014Q4 | 2015Q1 |
| --- | --- | --- |
| `tier1_capital` | 0.997 | 0.987 |
| `rwa` | 1.000 | 0.987 |

### Only the stitched series is published

`tier1_capital`, `tier2_capital` and `rwa` are published; the six `*_baselI` / `*_baselIII`
era pieces behind them are not. In the 48 bank-quarters that filed under both regimes the
ratio of the two is **1.0000 at the median and at p10 and p90**, so the stitch is not a
compromise between two different measures — it is one measure reported under two code
prefixes. Publishing both would be two names for one series.

This does *not* extend to Basel-I content with no Basel III counterpart. The risk-weight
buckets (`rwa_bucket_0pct_baselI` … `_100pct_baselI`), `assets_for_leverage_baselI`, and the
pre-2015 reported ratios are all still published — the last of these are what the computed
ratios below were validated against, so removing them would remove the audit trail.

## 2. The reported ratios change units three times (and are not confidential)

Until 1.0.1 this section said the reported ratios were confidential from 2015Q1, on the
strength of `RCOA7204` cells reading `"CONF"`. That was measured on a parse of the CDR
bulk files that has since been replaced, and it is wrong on the current files: from
2015Q1 to 2025Q3 `RCOA7204` / `7205` / `7206` and `RCOAP793` are populated for ~98% of
banks every quarter, none are CONF, and every value is a **percent string** such as
`"9.1154%"`. The bulk files write them that way; `data_call_report` (since 2026-09-26)
stores the number in percent units. What made them look absent in `bankpanel` was
numeric coercion turning the strings into NaN.

The unit then depends on which source wrote the quarter (measured on `RCFD7204`, the
tier 1 leverage ratio; the two risk-based ratios behave identically):

| era | source | median | units |
| --- | --- | --- | --- |
| 2001Q1–2008Q3 | Chicago Fed | 0.092 | fraction |
| 2008Q4–2010Q4 | Chicago Fed | 9.39 | percent |
| 2011Q1–2014Q4 | FFIEC CDR | 0.095 | fraction |
| 2015Q1– | FFIEC CDR (`RCFA`/`RCOA`) | 9.12 | percent (as `"9.12%"`) |

Before 1.0.1 the published `*_reported_baselI` columns carried the 2008Q4–2010Q4 quarters
in percent next to fractions on either side, a hundred-fold unit break inside one column.
From 1.0.1 each code is read once per Basel era as filed (`RCFD7204` to 2014Q4,
`RCFA`/`RCOA7204` after, withheld as intermediates), the percent quarters are rescaled by
1/100 in the formula using the builder's `yyyyq` (the reporting quarter as `YYYYQ`; see
[CONFIG_FORMAT](../CONFIG_FORMAT.md)), and two families are published, both in
**fractions**, the unit of the computed ratios. (A first attempt split `RCFD7204` into
era pieces bounded by `era_start`/`era_end`; those bounds do not blank values, so every
piece carried every quarter and the first one won. The rule belongs in the formula.)

* `leverage_ratio_reported`, `tier1_rbc_ratio_reported`, `total_rbc_ratio_reported`,
  `cet1_ratio_reported` — the full span, Basel I to 2014Q4 and Basel III after, as the
  form defines them;
* `*_reported_baselI` — the 2001Q1–2014Q4 span under its 1.0 name, now unit-consistent.

On the FR Y-9C the same items (`BHCK7204` to 2014Q4, `BHCA7204` after) are filed in
percent in every era, so the Y-9C formulas rescale every piece; see
`reference_data/y9c_formula_overrides.csv`.

**The 2014 Basel III early adopters.** About 30 banks a quarter in 2014 (the advanced-
approaches institutions) stop filing `RCFD7204` and file the Basel III code `RCFA7204`
instead, a year before everyone else, and on the Call Report they file it as a *fraction*.
The `RCFA`/`RCOA` codes are therefore fractions before 2015Q1 and percent after, and the
formula rescales by quarter. (1.0.1 assumed percent throughout and published these banks'
2014 ratios at 1/100 of their value; fixed in 1.1.0.) On the FR Y-9C the early adopters'
`BHCA` filings are percent, like every other Y-9C quarter.

**Filer unit errors are corrected.** A reported ratio is checked against the ratio the
bank's own amounts imply: tier 1, total and CET1 against `tier1_rbc_ratio`,
`total_rbc_ratio` and `cet1_ratio`; leverage against `tier1_capital / assets`. Across the
panel the two agree within 1% for 99.8-100% of cells, and the disagreements split into
clusters with empty space between them: a genuine definitional spread up to ~30x (the
leverage denominator is average assets net of deductions, not quarter-end assets), and a
cluster at ~100x or ~1/100 -- a filer who typed the ratio in the wrong unit (e.g. RSSD
3485541 on the Y-9C files `998` for 9.98% across 2012Q4-2014Q4). A filed value 30-300x the
implied ratio is divided by 100; 1/300-1/30 of it is multiplied by 100. Nothing else is
changed.

| | bank-quarters corrected | ratio cells | filers |
| --- | --- | --- | --- |
| Call Report | 17 | 18 | 17 |
| FR Y-9C | 40 | 83 | 31 |

Every correction is visible: `capital_ratio_unit_corrected` counts the corrected ratios in
the row (0 where none), and the value as filed, in consistent units but before the
correction, is published alongside as `*_reported_uncorrected`. Where the implied ratio is
missing (for example CBLR banks with no RWA) nothing can be checked and the filed value
stands. What the correction cannot resolve is reported by the quality checks below.

**What remains is reported, not corrected.** `bankpanel validate quality` runs
`leverage_reported_units_agree`, `tier1_reported_units_agree`,
`total_reported_units_agree`, `cet1_reported_units_agree` (a factor of 30, warning),
`tier1_reported_matches_computed` and `cet1_reported_matches_computed` (10%, info) and
`tier1_capital_filed_with_ratio` (tier 1 capital filed as zero next to a positive ratio,
warning). After the correction they fail on 0-14 Call Report cells and 1-37 Y-9C cells;
`--save` writes each failing bank-quarter with its inputs to
`validation/quality_failures.csv`. Roughly 1,100 Call Report leverage ratios above 100%
remain and are genuine: tiny banks (median assets $15M) whose tier 1 is ~93% of assets,
where the leverage denominator nets out deductions.

The computed ratios remain the primary series: `tier1_rbc_ratio = tier1_capital / rwa`,
and likewise for total capital and CET1. The reported ratios exist to validate them and
to cover the CBLR banks that report a leverage ratio but no RWA from 2020Q1 (section 3).
The validation below is against the unit-consistent reported ratios:

| Ratio | n | median(computed / reported) | within 1%, 2001-2014 | within 1%, 2015-2026Q2 |
| --- | --- | --- | --- | --- |
| `tier1_rbc_ratio` | 623,490 | **1.0000** | 100.0% | 100.0% |
| `total_rbc_ratio` | 623,492 | **1.0000** | 99.8% | 100.0% |
| `cet1_ratio` | 194,226 | **1.0000** | 100.0% (2014 early adopters) | 100.0% |

On the FR Y-9C: tier 1 99.8%, total 99.1%, CET1 100.0% within 1% (96,500 / 96,502 /
19,066 holding-company quarters). The 1.0 version of this table read 97.6% for tier 1:
the missing 2.4% was the 2008Q4-2010Q4 percent era being compared with fractions.

## 3. From 2020Q1 a third of banks stop reporting RWA

The Community Bank Leverage Ratio framework lets qualifying banks opt out of risk-based
capital reporting entirely. The effect is abrupt:

| | 2019Q4 | 2020Q1 | 2025Q2 |
| --- | --- | --- | --- |
| `rwa` coverage | 0.986 | **0.652** | 0.600 |
| `tier1_capital` coverage | 0.986 | 0.984 | 0.982 |

**Any risk-based ratio is therefore available for only ~62% of banks from 2020**, and the
missing 38% are not random — they are the smaller, less complex banks that qualified for
CBLR. Tier 1 capital itself is unaffected, so leverage-based measures keep full coverage.
Condition on it explicitly rather than letting `dropna()` do it silently.

## Also carried

Basel I risk-weight buckets (`rwa_bucket_0pct_baselI` … `100pct`), which show the
composition of RWA before the Basel III recalibration; the CET1 build-up components
(`cet1_common_stock_surplus`, `cet1_minority_interest`, `cet1_adjustments_deductions`);
and `assets_for_leverage_baselI`.

CET1 itself is already carried as `cet1` by the liabilities config (`RCOAP859` coalesced
with `RCFWP859`), so it is referenced rather than re-declared.

## Not covered

Part II — the ~740-cell risk-weighted-asset grid by exposure category and risk weight.
24 Part I codes are also confidential and excluded.
