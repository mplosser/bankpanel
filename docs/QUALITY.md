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
chargeoff_ci_le_total,co_ci <= co_tot,warning,Category charge-offs cannot exceed the total
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
`rec_tot` is **negative** — the year-to-date reset artifact the quarterize audit already
reports. The same defect surfacing through an ordering violation is not duplication; it
shows how far the artifact propagates.

## Current checks

16 checks ship in `configs/quality_checks.csv`, covering component-vs-total orderings
(loans, deposits, nonaccrual, charge-offs, past due, small business lending), sign
constraints (reserves, assets, capital ratios), and capital-structure orderings (CET1 ≤
tier 1 ≤ total capital). All pass or fail at rates below 0.6%, most below 0.1%.

Add your own: they cost one config line and are checked by `bankpanel lint` immediately.
