# Schedule RI-B — Charge-offs and Recoveries

46 base items and 1 derived series. The realised-loss counterpart to RC-N: RC-N says what
is not performing, RI-B says what was written off and what came back.

## Naming

```
{co|rec}_{category}
```

`co_` charge-offs, `rec_` recoveries, over the same category vocabulary RC-N uses
(`ci`, `cc`, `auto`, `famres_first`, `nfnres_owner`, `agprod`, `lease`, …). The schedule
totals are pinned to `ytd_co_tot` (`RIAD4635`) and `ytd_rec_tot` (`RIAD4605`) — several other
items mention "allowance for loan and lease losses" and would otherwise have claimed the
name. Remaining collisions take an MDRM item-code suffix.

`ytd_net_chargeoffs_tot = ytd_co_tot - ytd_rec_tot` is the series most work actually uses.

## Flow types matter here

Charge-offs and recoveries are **year-to-date** and are quarterized.

**Charge-offs are one-signed** (`sign=nonneg`): a charge-off cannot be negative over a
quarter, and the quarterize audit reports any that are.

**Recoveries are not** (`sign=any`). A recovery can be reversed, so a negative quarterly
recovery can be real. Banks almost never *report* a negative year-to-date recovery —
0.001% of 1.4 million filings — but a reversal within the year shows up as a fall in the
year-to-date figure and so as a negative quarter. Treating those as errors would repair
real data away.

Recoveries can also exceed charge-offs, which is a separate point: in 14% of bank-years a
bank recovers more than it charges off (26% for C&I), mostly on losses written off in
earlier years. It is strongly countercyclical — 4–5% of bank-years in 2009–10, 35–37% in
2021–22. So net charge-offs are negative in those years, and `ytd_net_chargeoffs_tot` carries
no sign constraint.

The Part II reconciliation items are *not* charge-off flows and are typed accordingly:
`alll_end` and `acl_oth_fin_assets` are balances (`stock`), while `ytd_alll_adjustments` and
`ytd_writedowns_transfer_to_hfs` are flows.

## Consumer loans across the 2001 and 2011 splits

RI-B's consumer lines were redrawn twice, the same way RC-C's and RC-N's were:

| era | charge-off codes | who reports |
| --- | --- | --- |
| through 2000Q4 | `4262` credit cards **and related plans**; the 031 also `4656` + `4657` (other) and the total `4639` | most forms: the card line only |
| 2001–2010 | `B514` credit cards + `B516` other | everyone; `B514 + B516 = 4639` for 100% of banks |
| 2011 on | `B514` + `K129` automobile + `K205` other | everyone |

`K205` (and `K206` for recoveries) is **all** other consumer lending — "single payment,
installment, all student loans, and revolving credit plans other than credit cards" — so it
cannot be paired with `B514` to recover the pre-2001 "credit cards and related plans" line;
that sum is consumer ex-automobile. The related plans have no code of their own after 2001.

So, following the rule that a series whose definition changes does not keep one name:

- **`ytd_co_consumer_tot` / `ytd_rec_consumer_tot`** — total consumer, the consistent series:
  `B514 + K129 + K205` from 2011, `B514 + B516` for 2001–2010, the reported `4639` for 031
  filers before 2001. Blank before 2001 for the other forms, which reported only the card
  line.
- **`ytd_co_consumer_oth` / `ytd_rec_consumer_oth`** — consumer other than credit cards:
  `K129 + K205` from 2011, `B516` for 2001–2010, `4657` (031) before.
- **`ytd_co_cc` / `ytd_rec_cc`** — credit cards alone, from 2001 (`B514` / `B515`).
- **`ytd_co_cc_incl_revolving_pre01` / `ytd_rec_cc_incl_revolving_pre01`** — cards and related
  plans, through 2000Q4 only.
- **`ytd_co_auto`, `ytd_co_consumer_oth_ex_auto`** (and `rec_`) — the 2011 halves, from 2011 only.

The stitch validator scores every handoff inside the series' own volatility (the largest,
`ytd_co_consumer_tot` at 2001Q1, is robust z 2.6 at the start of the 2001 recession). The same
construction gives `na_consumer_tot` on RC-N.

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

`ytd_provision_ll` (`RIAD4230`) runs from 1985 to the present on every form. **CECL did not
retire it**: it is reported by 100% of banks in every quarter through 2025, adopters
included. What CECL added is a *broader* total alongside it:

```
ytd_provision_credit_tot (JJ33) = ytd_provision_ll (4230)       loans and leases
                            + ytd_provision_htm (JH90)      held-to-maturity securities
                            + ytd_provision_afs (JH96)      available-for-sale securities
                            + ytd_provision_oth_fin (JJ02)  other assets at amortized cost
                            + ytd_provision_obs (MG93)      off-balance-sheet exposures, from 2021
```

This holds for 99.9% of banks in 2024Q4, and is asserted by the `provision_cecl_identity`
check. `JJ33` is reported by every bank from 2019Q1; before a bank adopts CECL it simply
equals `4230`. The components follow adoption — about 5% of banks in 2020, 95% by 2023Q1,
all by 2024.

**Do not splice `4230` into `JJ33`.** They are different quantities. `JJ33` adds securities
and off-balance-sheet provisions, so splicing would put a level step at each bank's own
adoption quarter — spread across 2020–2023 rather than at one date, which is harder to see.
Use `ytd_provision_ll` for a consistent loan-loss series, and `ytd_provision_credit_tot` only when
the broader CECL scope is what you want.

### One definitional change: 2001Q1

Before 2001Q1, `RIAD4230` also **included** provisions for off-balance-sheet credit
exposures and for allocated transfer risk. From 2001Q1 both moved to other noninterest
expense (`RIAD4092`), per the MDRM item note. So `ytd_provision_ll` narrows slightly at 2001Q1.
The size of that narrowing has not been measured: provisions are volatile and 2001 was a
recession year, so a naive before/after comparison would mostly measure the cycle.

### Provisions are two-signed

A provision can genuinely be negative — a reserve release. Banks report a negative
year-to-date provision 3.1% of the time before CECL and 7.1% under it, against essentially
never (0.000–0.001%) for charge-offs and recoveries. So the provisions carry `sign=any` and
the quarterize audit never treats a negative as an error.

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
