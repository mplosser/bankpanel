# Schedule RC-E — Deposit Liabilities

23 base items and 4 derived series covering deposit *composition*: who the depositor is,
how the deposit is sourced, and when it matures. The headline deposit totals live in the
balance-sheet config; this schedule is what lets you say something about the franchise.

## The two threshold changes

Brokered and time deposits are reported in maturity/size tiers, and the tiers have been
redefined twice. This is the single thing to understand before using them.

| Era | Tiers reported | Codes |
| --- | --- | --- |
| 1996Q1 – 2010Q4 | under $100,000 | `A241`, `A243` |
| 2011Q1 – 2016Q4 | under $100k · $100k–$250k · over $250k | `A241`, `K219`/`K221`, `K220`/`K222` |
| 2017Q1 – | $250,000 or less · over $250,000 | `HK06`/`HK11`, `K220`/`K222` |

The $100,000 line moved to $250,000 because deposit insurance did, permanently, in 2010.
Base variables therefore carry era suffixes recording where they are valid:

- `*_9716` — the sub-$100k tier, 1996Q1–2016Q4
- `*_1116` — the $100k–$250k tier, 2011Q1–2016Q4
- no suffix — currently reported

`brokered_dep_mat_lte1yr` stitches these into one series. **It is only comparable from
2011Q1.** Before then the sub-$250k concept does not exist in the data: everything at or
above $100,000 was reported in a single bucket with no $250k split, so the pre-2011 values
are a *narrower* quantity wearing the same name. Use `era_start` when you need a series
you can regress on.

## Sweep deposits

`sweep_dep_*` begin **2021Q3** and split four ways: affiliate vs non-affiliate, fully
insured vs not. `sweep_dep_tot` sums them; `sweep_dep_insured` / `sweep_dep_uninsured`
give the insurance cut, which is the one that matters for run risk.

Aggregate sweep deposits ran about **$1.76tn at 2021Q3** and roughly $1.47tn by 2025Q3.
Note `sweep_dep_not_brokered_tot` (`MT95`) is reported separately by the bank and is not
the sum of the four components — sweep deposits can also be brokered, and the overlap is
what `MT95` is designed to isolate.

## Reciprocal deposits

`reciprocal_dep_jun2018` (`JH84`) exists for **one quarter only**, 2018Q3, as a one-time
as-of-June-2018 collection tied to the 2018 reciprocal-deposit statutory change. It is
not a time series. The era bounds record this.

## Depositor type

`dep_usgovt_*`, `dep_statelocal_*`, `dep_forgovt_*` split deposits by depositor across
transaction and non-transaction accounts, and `preferred_dep` (collateralised public
deposits) runs 1993Q1–2024Q4. These are the items to use when asking which deposits are
contractually or politically sticky rather than merely small.

## Caveats

- `offers_consumer_dep_products` (`P752`) is a **yes/no** item published as the text
  `"true"`/`"false"`. bankpanel maps it to 1.0/0.0; it is `flow_type=flag`, not a dollar
  amount.
- Everything here is **domestic-office** (`RCON`). There is no consolidated twin, so the
  RCFD/RCON coalesce does not apply and no foreign-office deposits are included.
- Several items are collected only from some forms. Check `form_scope` in the config, or
  `expected_mask()`, before treating a NaN as a missing report.
