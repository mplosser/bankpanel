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

## 2. The reported ratios are confidential from 2015Q1

`RCOA7204` / `7205` / `7206` and `RCOAP793` have ~98% coverage — and every populated cell
is the literal string `"CONF"`. The capital *ratios* are not published after the Basel III
transition, though the capital *amounts* and RWA are.

So the ratios are **computed**: `tier1_rbc_ratio = tier1_capital / rwa`, and likewise for
total capital and CET1.

That is only legitimate if computing reproduces reporting, so it was checked against the
pre-2015 reported ratios, which *are* published and are kept here as
`*_reported_baselI`:

| Ratio | n | median(computed / reported) | within 1% |
| --- | --- | --- | --- |
| `tier1_rbc_ratio` | 372,262 | **1.0000** | 97.6% |
| `total_rbc_ratio` | 366,255 | **1.0000** | 99.0% |

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
