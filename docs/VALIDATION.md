# Validation

Three checks, each answering a different question. All are report-first; only `breaks` is
intended to fail a build.

```bash
bankpanel expectations build --panel-root panel_root   # once, after a build
bankpanel validate all --panel-root panel_root --save
```

---

## The reporting-expectations matrix

Everything else depends on this, so build it first.

It records, for each `(column, form_type, era)`, how often the item is actually collected:
`quarterly`, `semiannual_q2q4`, `annual_q4`, `annual_q2`, `sparse`, or `absent`. It is
measured from the data per form type, not read from documentation, then cross-checked
against MDRM.

**Why it exists.** FFIEC 051 filers — most banks since 2017 — report hundreds of items
only in Q2 and Q4. Measured on the full panel, **38 columns are collected non-quarterly
from 051 filers**, including the whole Schedule RC-T fiduciary and custody block
(`custody_assets`, `fidu_managed_assets`, …), which goes Q4-only from 2017.

Without the matrix, those columns swing ~100 percentage points every quarter forever. That
is not just noise: the checker becomes **saturated**, and a real break can no longer be
seen among the artifacts.

Two granularities are used deliberately. Era boundaries are found at **quarter**
granularity, so an item retired mid-year is recognised as having stopped; the frequency
pattern is classified per **year**, because that is the shortest window in which a
quarterly-vs-semiannual shape is visible. A label must persist three years before it
displaces the incumbent, so one odd year does not split an era in three.

Use it directly:

```python
mask = bp.expected_mask(df, "custody_assets")   # was this cell supposed to be reported?
```

---

## 1. `coverage` — reporting discontinuities across all history

Catches the archetype: an MDRM code moves, the config keeps pointing at the old one, and a
column reported by 99% of banks becomes one reported by 1% — with nothing raised anywhere,
because every surviving value is still valid.

Flags a transition when the reporting share moves ≥ 20pp, at least one side has ≥ 10%
reporting mass, and the form's own bank count did not itself swing > 20%.

Two design choices do the real work:

- **Compare within a form type, not across the pooled panel.** Different forms ask
  different questions, so a pooled share moves whenever the filer *mix* moves — which it
  does violently at 2017Q1. Splitting by form removes the confound and makes each finding
  actionable ("this broke for 051 filers").
- **Compare consecutive *collection events*, not calendar quarters.** For a Q2/Q4 item the
  meaningful comparison is Q2 → Q4 → Q2. Comparing Q1 to Q2 asks whether a quarter in which
  nobody was asked differs from one in which everyone was; the answer is always yes.
  Events more than four quarters apart are an era boundary, not a break, and are skipped.

Measured effect on the full 1985–2025 panel: **1,038 findings naive → 278
expectation-aware, a 73% reduction**, with the survivors being genuine transitions
(`time_cod_gt100k_dom` retiring at 1997Q1, the fair-value-option loan block at 2008Q4).

Every finding must be resolved: fix the config, declare an `era_start`/`era_end`, or record
it in the approvals ledger with a reason. Matching is on all of
`(panel, column, from_date, to_date)`, so one approval cannot silently absolve a different
break in the same column later.

## 2. `breaks` — did the newest quarter move?

The check you want to fail a scheduled rebuild. Every test is **year-over-year, same
quarter**, which is what makes seasonality safe: comparing 2025Q3 to 2024Q3 asks whether
this quarter differs from what this quarter normally looks like.

| Test | Trigger | Severity |
| --- | --- | --- |
| coverage collapse | coverage < 50% of its year-ago level (from ≥ 5%) | CRITICAL |
| zero flip | non-zero share < 10% of year-ago | CRITICAL |
| level break | per-quarter **median** of non-zero values moves ≥ 3× / ≥ 10× | WARNING / CRITICAL |

The level test uses the **median**, not the mean: a unit or definition change rescales
every bank and moves the median, while one large bank's one-off does not. It needs ≥ 30
non-zero reporters on both sides.

This is not hypothetical — on the current panel it flags `uc_other_2_src` (`RCFDJ458`)
collapsing 100% → 0% in **2025Q3**, a genuine code retirement that the config's stitch
handles but which nothing else would have surfaced.

## 3. `quarterize` — impossible negative flows

A gross additive flow — interest income, interest expense, non-interest *expense*,
fiduciary income — cannot be negative over a quarter. When one is, the year-to-date series
was reset mid-year, usually by a merger, divestiture, or restatement.

Which columns this applies to is a **semantic** property, so it is declared in the config
as `sign=nonneg` rather than guessed from the name. This matters more than it sounds:
`"nonint_inc"` contains `"int_inc"`, so substring matching silently marks non-interest
*income* subcategories — which are net items and legitimately negative — as non-negative.
Measured, that mistake flags 16.4% of bank-quarters at 95.7% "unexplained"; the correct
rule flags **2.38%**, matching the figure independently documented for this data.

Findings are attributed against the Schedule RI-A structural-event indicators. A quarter
can carry more than one, so the shares need not sum to 100%, and `unexplained` is computed
from rows carrying *no* indicator rather than as one minus the rest.

Report-and-flag, never a hard gate. The right treatment is to NaN the artifact rather than
pass a negative — or a fabricated zero — into a rate calculation, and that decision belongs
to the analysis, not to ingest.

## What parity does and does not prove

`tools/parity_check.py` compares this panel against the legacy `bec_migration` panels and
reports **688/688 columns matching exactly across 1,415,045 rows**. That number has held
through every release, which is the point: it is a regression guard.

It is not a correctness check on the panel, and the distinction matters because the two are
easy to conflate:

```
PARITY: 688/688 columns match exactly (100.00%)
SCOPE:  688 of 1043 panel columns (66%). 355 have no legacy
        counterpart and are NOT checked here.
```

Parity can only compare columns that exist on both sides. Every column defined by a config
with no legacy counterpart — all of RC-B, RC-C, RC-D, RC-E, RC-K, RC-N, RC-O, RC-R-I, RI-A,
RI-B — is outside its scope. A release could rename, restructure or break any of those 355
columns and parity would still print 100%.

That is exactly what happened while consolidating Schedule RC-N: six mislabelled columns
were renamed, twenty-one were replaced by three bucket totals, and two fabricated-zero bugs
were fixed. Parity did not move by a single cell, because none of those columns are in the
comparison.

The corollary is the uncomfortable one. The three legacy columns with known fabricated
zeros — `pdl_tot_non`, `ffrepo_ass`, `ffrepo_liab` — are *inside* the parity set, which is
precisely why they have not been fixed: correcting them would change values the legacy
pipeline depends on. Parity protects them from being changed, including from being
corrected.

So parity answers "did I break what I inherited". Coverage, breaks, quarterize and quality
answer "is what I built sound". Neither substitutes for the other, and the scope line is
printed so the first is never read as the second.

