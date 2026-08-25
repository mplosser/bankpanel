# Schedule RC-B — Securities

12 base items and 1 derived series. A deliberately narrow addition, because the
balance-sheet configs already carry securities **fair values** in depth: 205 of the 340
RC-B codes were claimed before this wave.

## What was missing: amortized cost

The gap was coherent and worth closing on its own. Fair value alone does not tell you
anything about gains or losses — **the difference between amortized cost and fair value
is the unrealised gain or loss**, which is the quantity that defined 2023.

Aggregate AFS Treasuries, from the newly paired columns:

| | 2021Q2 | 2021Q4 | 2022Q2 | 2022Q4 | 2023Q2 |
| --- | --- | --- | --- | --- | --- |
| Amortized cost ($bn) | 753 | 983 | 947 | 884 | 701 |
| Fair value ($bn) | 758 | 983 | 914 | 844 | 670 |
| **Unrealised ($bn)** | **+5** | −1 | −33 | **−40** | −31 |

The rate shock, visible directly. `ac_afs_*` names deliberately mirror the existing
`fv_afs_*` names so the pairs line up.

## Coverage and its limits

Included: the top-level categories — Treasury, US agency, US GSE, states and political
subdivisions, other domestic, other foreign, asset-backed, structured notes — plus
pledged securities, HTM securities sold or transferred year-to-date, and debt securities
repricing within one year.

**Not included yet:** the 39-item amortized-cost detail for MBS pass-throughs, CMOs, and
structured financial products by underlying collateral (`G302`–`G374`, `K144`–`K156`,
`HT52`/`HT60`, `PU98`/`PV00`). Naming those well needs the same family treatment RC-N
got, and a bad public name is harder to undo than a missing column.
`bankpanel propose --schedule RC-B` drafts them.

## Caveat

`ac_afs_tot_toplevel` sums only the categories listed here and is therefore **not** the
reported AFS total. Use it for composition, not for footing. Two categories carry era
suffixes (`_9418`) where the agency/GSE split was reported separately before 2018.
