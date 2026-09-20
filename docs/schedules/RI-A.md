# Schedule RI-A — Changes in Bank Equity Capital

9 base items and 1 derived series. The equity reconciliation: beginning balance, the
transactions that moved it, ending balance.

## Mixed flow types, and why that matters

Everything on this schedule carries a `RIAD` prefix, and RIAD normally means year-to-date.
Here it does not always:

| flow_type | Items |
| --- | --- |
| `stock` | `equity_end`, `equity_prev_yearend`, `equity_prev_yearend_restated` |
| `ytd` | `ytd_div_common`, `ytd_div_preferred`, `ytd_capital_stock_net`, `ytd_treasury_stock_net`, `ytd_oth_comprehensive_income`, `ytd_oth_stockholder_transactions` |

The three `stock` items are **balances that happen to be reported on a year-to-date form**.
Marking them `ytd` because of the prefix is an easy and invisible error: differencing a
balance yields the *change* in equity, which is a plausible-looking series that is not what
the column claims to be.

This is the schedule where the `flow_type` field earns its keep. The legacy convention of
inferring year-to-date from a name prefix could not express it at all.

## Also on this schedule

The three structural-event indicators — business combinations, restatements, discontinued
operations — live in RI-A and were already carried. They are the attribution used by the
quarterize audit to explain impossible-negative flows, and they are the reason
`[ZERO_FILL] scope=in_era` exists: a blank means "no event" once collection began, but
"not collected" before it did.

`ytd_div_tot = ytd_div_common + ytd_div_preferred` is provided for convenience.
