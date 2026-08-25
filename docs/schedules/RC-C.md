# Schedule RC-C — Loans and Lease Financing Receivables

41 base items and 4 derived series, extending the loan detail the balance-sheet configs
already carry. The additions are the parts of RC-C that support lending research rather
than balance-sheet assembly.

## Part II — small business and small farm lending

The largest and most useful block. RC-C Part II reports loan **counts** and **amounts**
in origination-size buckets, which is the only place the Call Report distinguishes small
borrowers.

| Family | Buckets | Variables |
| --- | --- | --- |
| Nonfarm nonresidential CRE | ≤$100k · $100k–250k · $250k–1M | `n_ln_nfnres_*`, `amt_ln_nfnres_*` |
| Commercial & industrial | ≤$100k · $100k–250k · $250k–1M | `n_ln_ci_*`, `amt_ln_ci_*` |
| Farmland | ≤$100k · $100k–250k · $250k–**500k** | `n_ln_farmland_*`, `amt_ln_farmland_*` |
| Agricultural production | ≤$100k · $100k–250k · $250k–**500k** | `n_ln_agprod_*`, `amt_ln_agprod_*` |

**The farm buckets top out at $500,000 and the business buckets at $1,000,000.** They are
not directly comparable, and `amt_ln_smallbiz_tot` and `amt_ln_smallfarm_tot` are
deliberately kept as separate aggregates rather than summed.

### Frequency depends on both era and form, and this is measured

Measured coverage of `amt_ln_ci_lte100k`, by era, form, and quarter:

| Era | Form | Q1 | Q2 | Q3 | Q4 | Pattern |
| --- | --- | --- | --- | --- | --- | --- |
| 1993Q2 – 2009Q4 | 031 | 0.04 | **0.99** | 0.04 | 0.04 | June only |
| | 041 | 0.00 | **0.96** | 0.00 | 0.00 | June only |
| 2010Q1 – | 031 | 0.95 | 0.95 | 0.95 | 0.95 | quarterly |
| | 041 | 0.89 | 0.90 | 0.90 | 0.89 | quarterly |
| 2017Q1 – | 051 | **0.00** | 0.93 | **0.00** | 0.92 | Q2 and Q4 |

Three distinct regimes, and Part II does not exist at all before 1993Q2:

1. **1993–2009 it is genuinely a June-only collection** — the received wisdom is correct
   for this era, and an annual series is the only honest one.
2. **From 2010 it becomes quarterly** for long-form filers.
3. **From 2017 the 051 short form collects it semiannually**, so a pooled quarterly series
   silently becomes long-form-only — a larger-bank sample — in Q1 and Q3.

`expected_mask()` resolves all three per cell. Do not assume a single frequency across the
whole panel; there isn't one.

### What it shows

Aggregate small business lending, June of each year (June is used because it is the only
month reported across all three regimes):

| | 2019 | 2020 | 2021 | 2022 | 2025 |
| --- | --- | --- | --- | --- | --- |
| Small business ($bn) | 640 | **891** | 803 | 646 | 668 |
| Small farm ($bn) | 76 | 74 | 68 | 67 | 71 |

The 2020 jump of roughly $250bn is PPP arriving, and it unwinds over 2021–22 — a useful
sanity check that the buckets are being read correctly.

## Other items

- **Fair-value-option loans** — the carrying amounts are already in the balance-sheet
  config (`ln_fv_ci`, `ln_fv_oth`); what this adds is the **unpaid principal balance**
  (`upb_ln_ci_fv`, `upb_ln_oth_fv`), which is what makes the fair-value mark interpretable.
- **`ln_pledged`** — pledged loans and leases, 2009Q2 onward. Encumbered collateral, so
  directly relevant to liquidity and resolution questions.
- **`ln_famres_in_foreclosure`**, **`ln_closedend_negative_amortization`**,
  **`ln_condev_interest_reserve`**, **`ln_famres_heloc_converted_to_term`** — credit-stress
  and underwriting-quality items, each with its own start date.
- **`ln_nondep_fin_inst`** (2010Q1 onward) — lending to non-bank financial institutions,
  the series behind most bank/NBFI interconnection work.

## Four items are collected but not published

`RCONLG24` / `RCONLG25` (Section 4013 COVID loan modifications) and `RCON6999` /
`RCON6860` (small business / small farm loan indicators) are **confidential**. Every
populated cell is the literal string `"CONF"`.

This matters because such a column looks *perfectly covered* on a non-null test and then
builds to all-NaN. `bankpanel propose` now measures coverage on numeric content and
excludes them explicitly; they are named here so nobody re-adds them.

## Deliberately not covered yet

The purchased-impaired acquisition-date detail (`G092`–`G102`, `GW46`/`GW47`) and the
reverse-mortgage sub-items (`J466`–`J471`, `PR04`/`PR06`). Both are narrow-use, and a
badly chosen public name is harder to undo than a missing column. `bankpanel propose
--schedule RC-C` will draft them when they are wanted.
