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

## Provisions: the flow that builds the allowance

The allowance for loan and lease losses (`ll_res`, RCFD3123) is a balance-sheet **stock**.
The provision is the income-statement **flow** that builds it. RI-B Part II reconciles the
two every year:

```
allowance(end) = allowance(start) + provision − charge-offs + recoveries
                 − write-downs on transfer to held-for-sale + adjustments
```

Tested on the raw filings with `RIAD4230` as the provision, this holds for **99.2–99.5% of
banks** in 2005, 2015, 2019 and 2024 — both sides of CECL — and the RI-B end balance equals
the balance-sheet `ll_res` for 100% of them. So `RIAD4230` is exactly the flow into
`ll_res`, with the same loans-and-leases scope. The remaining ~0.7% are not yet
root-caused; mid-year business combinations are the likely source.

### One series, no stitch

`provision_ll` (`RIAD4230`) runs from 1985 to the present on every form. **CECL did not
retire it**: it is reported by 100% of banks in every quarter through 2025, adopters
included. What CECL added is a *broader* total alongside it:

```
provision_credit_tot (JJ33) = provision_ll (4230)       loans and leases
                            + provision_htm (JH90)      held-to-maturity securities
                            + provision_afs (JH96)      available-for-sale securities
                            + provision_oth_fin (JJ02)  other assets at amortized cost
                            + provision_obs (MG93)      off-balance-sheet exposures, from 2021
```

This holds for 99.9% of banks in 2024Q4, and is asserted by the `provision_cecl_identity`
check. `JJ33` is reported by every bank from 2019Q1; before a bank adopts CECL it simply
equals `4230`. The components follow adoption — about 5% of banks in 2020, 95% by 2023Q1,
all by 2024.

**Do not splice `4230` into `JJ33`.** They are different quantities. `JJ33` adds securities
and off-balance-sheet provisions, so splicing would put a level step at each bank's own
adoption quarter — spread across 2020–2023 rather than at one date, which is harder to see.
Use `provision_ll` for a consistent loan-loss series, and `provision_credit_tot` only when
the broader CECL scope is what you want.

### One definitional change: 2001Q1

Before 2001Q1, `RIAD4230` also **included** provisions for off-balance-sheet credit
exposures and for allocated transfer risk. From 2001Q1 both moved to other noninterest
expense (`RIAD4092`), per the MDRM item note. So `provision_ll` narrows slightly at 2001Q1.
The size of that narrowing has not been measured: provisions are volatile and 2001 was a
recession year, so a naive before/after comparison would mostly measure the cycle.

### Provisions are two-signed

Unlike charge-offs and recoveries, a provision can genuinely be negative — a reserve
release. Banks report a negative year-to-date provision 3.1% of the time before CECL and
7.1% under it, against essentially never (0.000–0.001%) for charge-offs and recoveries. So
the provisions carry `sign=any` and the quarterize audit never treats a negative as an
error.

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
