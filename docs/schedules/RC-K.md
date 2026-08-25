# Schedule RC-K — Quarterly Averages

10 base items and 1 derived series. Small, and a prerequisite rather than an end in
itself.

## Why averages matter

An income ratio built on a two-endpoint average of a stock is wrong in exactly the
quarters that move — mergers, divestitures, rapid growth — because the endpoints
straddle the event rather than describing the period. RC-K reports what the bank actually
averaged over the quarter, which is the correct denominator for a flow.

This is the input the cleaning layer's denominator repair needs
(`rescale_denominator_reported_avg`, `implied_rate_floored`), so RC-K lands before v0.6
deliberately.

## Covered

Quarterly averages of: fed funds sold and resells, fed funds purchased and repos, other
borrowed money, interest-bearing balances due from depositories, trading assets, the
three securities categories (`qavg_sec_ust_agency`, `qavg_sec_mbs`, `qavg_sec_oth`, plus
`qavg_sec_tot`), and the two consumer-loan categories.

Average total assets (`RCFD3368`) and average loans (`RCFD3360`) were already carried.

## Caveat for large filers

The reported average total assets runs materially **below** the end-of-quarter balance for
some FFIEC 031 filers — 12–38% below for the largest, measured. That is a reporting
artifact of foreign-office and related treatment, not growth, and it means the reported
average and the endpoint do not measure the same population for those banks. A blanket
rescale of one toward the other inflates large-bank rates; any use of RC-K averages as a
denominator should be do-no-harm and quarter-conditional.
