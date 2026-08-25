# Schedule RI-B — Charge-offs and Recoveries

46 base items and 1 derived series. The realised-loss counterpart to RC-N: RC-N says what
is not performing, RI-B says what was written off and what came back.

## Naming

```
{co|rec}_{category}
```

`co_` charge-offs, `rec_` recoveries, over the same category vocabulary RC-N uses
(`ci`, `cc`, `auto`, `famres_first`, `nfnres_owner`, `agprod`, `lease`, …). The schedule
totals are pinned to `co_tot` (`RIAD4635`) and `rec_tot` (`RIAD4605`) — several other
items mention "allowance for loan and lease losses" and would otherwise have claimed the
name. Remaining collisions take an MDRM item-code suffix.

`net_chargeoffs_tot = co_tot - rec_tot` is the series most work actually uses.

## Flow types matter here

Charge-offs and recoveries are **year-to-date** and are quarterized. They are gross
additive quantities — neither can be negative over a quarter — so they carry
`sign=nonneg` and the quarterize audit will report any that are.

The Part II reconciliation items are *not* charge-off flows and are typed accordingly:
`alll_end` and `acl_oth_fin_assets` are balances (`stock`), while `alll_adjustments` and
`writedowns_transfer_to_hfs` are flows.

## What it shows

Net charge-offs, Q4 of each year ($bn):

| 2006 | 2008 | 2009 | 2010 | 2012 | 2019 | 2020 | 2023 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10.1 | 28.5 | **53.2** | 40.1 | 18.4 | 14.0 | 11.3 | 20.2 |

The 2009 peak, the slow normalisation, and the striking fact that 2020 charge-offs came in
*below* 2019 — fiscal support and forbearance kept realised losses down through the
pandemic even as provisions spiked.

## Not covered

24 of 66 proposals are RI-B Part II reconciliation lines that do not fit the
charge-off/recovery scheme (separate valuation allowances, allocated transfer risk
reserve, various adjustments). `bankpanel propose --schedule RI-B` lists them.
