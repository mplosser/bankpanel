# Data quality

```bash
bankpanel validate quality --panel-root panel_root
```

The coverage, breaks and quarterize validators ask whether an item was **reported** as
expected. These checks ask whether what was reported can be **true**.

## Checks are declarative

A check is a boolean expression in the same language as a derived formula, declared in a
config's `[CHECKS]` section:

```csv
[CHECKS]
name,expression,severity,description
loan_reserve_le_loans,ll_res <= ll_tot,error,Reserves cannot exceed the loans they cover
tier1_ratio_nonneg,tier1_rbc_ratio >= 0,error,A capital ratio cannot be negative
chargeoff_ci_le_total,ytd_co_ci <= ytd_co_tot,warning,Category charge-offs cannot exceed the total
```

Writing them as ordinary boolean expressions — rather than inventing a rule grammar —
means bounds, orderings, accounting identities and cross-item consistency are all the
same kind of object, all validated by the same AST gate, and all lintable. A check that
references a variable no config defines is a **lint error**, caught before any data is read.

`severity=error` fails `--strict`; `warning` and `info` report. A check that cannot be
evaluated counts as a failure, not a pass — an unevaluable assertion must never look
like a satisfied one.

## Applicability is separate from failure

A check runs only on rows where **every input is present**. A row missing an input is out
of scope, not a failure.

This is not a nicety. Most of a Call Report panel is legitimately empty — conditional line
items, items outside their collection era, short-form filers — so conflating "not reported"
with "impossible" would make every check fail nearly everywhere and the output would be
worthless. The report shows `n_applicable` alongside `n_failed` so the denominator is
always visible.

## A worked example: the check was wrong, not the data

The first version of the capital-ratio check asserted:

```
(tier1_rbc_ratio >= 0) & (tier1_rbc_ratio <= 1)
```

which sounds obviously true. It failed on **1.317% of applicable rows — 10,578 of them**,
by far the largest failure in the suite. The temptation is to treat that as a data problem
and start repairing.

Diagnosing it instead:

| | failing rows | whole panel |
| --- | --- | --- |
| median assets | **$15.4M** | $86.1M |
| median RWA / assets | **0.27** | 0.67 |

The failures are tiny banks holding almost entirely zero-risk-weight assets. And
decisively — the **regulator's own reported ratio also exceeds 1** for every one of the
5,699 failing rows that have one, with a median reported value of **2.63**. The most
extreme case has $53.5M of tier 1 capital against $72k of risk-weighted assets, a ratio of
743, and is perfectly legitimate.

A capital ratio is capital over *risk-weighted* assets, and a bank can hold more capital
than risk. The invariant was false.

The check is now split: `tier1_ratio_nonneg` (an actual invariant, `error`) and
`tier1_ratio_plausible` (`ratio <= 10`, severity `info`, flagging the rare rather than the
impossible). Failures fell from 1.317% to 0.020%, and the survivors — 160 genuinely
negative ratios — are worth looking at.

**The lesson is the workflow, not the threshold.** A firing check is a hypothesis about
the data. Confirm it against an independent source before believing it, and be willing to
conclude the assertion was wrong.

## Overlap with the other validators is informative

`recovery_ci_le_total` fails on 0.583% of rows, and 58% of those are cases where
`q_rec_tot` is **negative**. That can be a year-to-date reset artifact or a genuine reversal
of an earlier recovery. Recoveries are two-signed, so the quarterize audit no longer reports
them, and this ordering check is the one place a negative total recovery still surfaces.
It is a `warning` for that reason: a failure here is worth a look, not a repair.

## Current checks

16 checks ship in `configs/quality_checks.csv`, covering component-vs-total orderings
(loans, deposits, nonaccrual, charge-offs, past due, small business lending), sign
constraints (reserves, assets, capital ratios), and capital-structure orderings (CET1 ≤
tier 1 ≤ total capital). All pass or fail at rates below 0.6%, most below 0.1%.

Add your own: they cost one config line and are checked by `bankpanel lint` immediately.

## Two structural checks nobody has to declare

The 16 checks above are assertions somebody wrote down. Two more run over every derived
column automatically, because both catch failures an author would have to anticipate to
write a check for — and both are invisible to every other validator in the repo.

### Fabricated values

A total that carries a value where **none** of its inputs do. Almost always a `.fillna(0)`
chain crossing an era boundary: right inside an era, where it tolerates one missing
component; wrong across one, where every component is absent and "not collected" becomes a
confident zero.

The reason it survives ordinary review is that **a fabricated zero raises coverage**. The
column looks unusually well reported. Coverage, breaks and the quarterize audit are blind
to it by construction. Two series here did this — one for 568,102 rows — and both scored
`coverage 1.0000` on items first collected in 1994 and 1996.

The fix is a guard, not removing the `fillna`:

```
(a.fillna(0) + b.fillna(0)).where(a.notna() | b.notna())
```

### Assumed zeros

The subtler case, and the common one: a component blank **inside** its collection era.
Zero-filling it understates the total, and nothing downstream can tell.

Why a cell is blank is the whole question:

- **outside its collection era** — zero-filling is the era stitch working. This is how a
  four-piece stitch gets written as a sum, and `brokered_dep_mat_lte1yr` has 846,943 rows
  where components are missing and **zero** of them are assumptions.
- **inside its era** — the bank either had nothing to report or did not report, and the
  data cannot distinguish them. The zero is an assumption.

A blank is counted only where the zero it produces actually reaches the output. Formulas
branch: `na_tot` is `reported.fillna(<22-term sum>)`, so the sum -- and every
`fillna(0)` inside it -- is evaluated only on the 11.5% of rows where the reported code is
missing. Counting components on every row overstated the exposure threefold (211,689 vs
64,164). Rather than parse branch structure, each suspect cell is perturbed and the formula
re-evaluated: if the output does not move, the zero never mattered there. Exact for any
formula shape, including ones not yet written.

Only a name written literally as `X.fillna(0)` counts. The *head* of a coalesce -- the `a`
in `a.fillna(b)` -- is blank on purpose whenever the fallback fires, so treating it as an
assumed zero flagged every era stitch in the repo.

Liveness is measured per quarter from the cross-section — what share of the banks
reporting *any* component report this one — rather than from the config's declared era.
What the panel shows beats what the era bounds claim, and it needs no maintenance.

Reported, never gated. On a Call Report a blank overwhelmingly *does* mean zero: banks
leave inapplicable lines empty rather than typing 0. Failing a build on this would fail
every build. The point is that the assumption is counted and visible.

Worked example — `na_tot`, the by-category nonaccrual reconstruction, first showed 64,164
rows resting on an assumed zero, all in `na_agprod` (agricultural nonaccrual). Testing whether
blank meant "nothing to report" split them 50/50 between banks with no agricultural loans and
banks with a small book, and bounded the understatement at 0.4%.

The bound was right and the diagnosis was not. Those banks file the FFIEC 041, on which
agricultural nonaccrual is reported *inside* all other loans rather than on its own line —
the value was not blank, it was already in the total under another name. Once the term reads
`na_agprod.where(form_type == 31)`, the assumed-zero count for `na_tot` falls from 64,164 to
**2**, and the category sum matches the reported total for 100.00% of bank-quarters from
2017 on.

So the check found a real defect, but not the one it named: a blank that looks like an
assumption can be a category counted on the wrong line. The bound told us the cost was
small; the form told us it was zero.

That is the shape of the answer this check is for: not "is the zero right" — unknowable —
but "how wrong can it be", answered from the panel itself.
