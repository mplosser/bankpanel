# Cleaning

Opt-in, in memory, and last.

```python
from bankpanel.clean import CleaningPlan, apply_plan, summarize_audit

plan = (CleaningPlan()
        .add("interpolate_negative", column="co_tot")
        .add("interpolate_negative", column="rec_tot"))

cleaned, audit = apply_plan(df, plan)
summarize_audit(audit)
```

## The panel on disk is never cleaned

`bankpanel build` writes exactly what the configs produced. Nothing in `clean/` runs
during a build, and a test walks the module ASTs to prove `build/` and `io/` cannot import
`clean/` — enforced structurally rather than by convention, so a future edit cannot
quietly make cleaning part of the pipeline.

That matters because cleaning is a *modelling* decision. Two researchers can reasonably
disagree about whether to repair a merger-quarter artifact or drop the bank-quarter, and
neither should have the other's choice baked into the data they downloaded.

## Every changed cell is recorded

`apply_plan` returns `(cleaned, audit)`. The audit is one row per changed cell:

| RSSD_ID | REPORTING_PERIOD | column | rule | old | new |
| --- | --- | --- | --- | --- | --- |
| 46 | 1986-09-30 | co_tot | interpolate_negative | −1.0 | 7.0 |
| 354 | 2016-12-31 | co_tot | interpolate_negative | −1.0 | 5.5 |

Steps are not asked to report their own changes — the runner diffs the frame around each
step, so the audit cannot drift out of step with what actually happened. On the current
panel, repairing negative charge-offs and recoveries touches **18,565 cells**, and every
one is in the frame.

This is what turns "we cleaned the data" into a claim somebody else can check, quantify,
and disagree with.

## What the steps do

| Step | Purpose |
| --- | --- |
| `fix_unit_errors` | A bank reports a stretch of quarters in units instead of thousands. Splits the series at ~1000× jumps, clusters segments about the geometric mean of their medians, and only acts if the two clusters really differ by the factor — so a series that merely grew is untouched. |
| `interpolate_negative` | A gross-additive flow came out negative, which is impossible. Blanks it and interpolates from the bank's own history. |
| `interpolate_broken_ratio` | Local-event repair for a rate or ratio surface. See below. |
| `apply_valued_balance_floor` | A rate needs a balance to be earned on. Zero balance → NaN; immaterial balance → per-date median; real balance → untouched. |
| `rescale_denominator` | Swaps a two-endpoint average for the reported RC-K within-quarter average, in suspect quarters only. |

Also importable but not plan steps, because they take arrays rather than frames:
`repair_local_events`, `implied_rate`.

## The doctrine behind local-event repair

Worth stating, because it replaced something that looked reasonable and was subtly wrong.

A year-to-date reset — from a merger, divestiture or restatement — is approximately
**sum-preserving**. Income belonging to one quarter is allocated to another, so the
artifact arrives in **pairs**: a negative or collapsed quarter beside an inflated one.

Repairing only the impossible-looking leg leaves the inflated twin standing — and worse,
lets the repaired value interpolate *from* it. A one-sided repair therefore does not just
miss half the problem, it imports the corruption into its own fix.

So:

- **Detection is by discontinuity against the bank's own local neighbourhood** (the median
  of its t±2 quarters), not against a level threshold. That is level-free, so a genuine
  rate cycle never triggers however high rates go, while a one-quarter dislocation does.
- **The repair window widens** over any adjacent quarter that is itself loosely anomalous,
  so both legs are replaced together and interpolation can only anchor on clean quarters.
- **A structural-event flag alone is not enough** to trigger a repair — most mergers do not
  corrupt the series — but it does lower the bar, since the flag is independent evidence.

Use `interpolate_negative` for a raw flow *before* any ratio is built on it, where there is
no correlated twin yet. Use `interpolate_broken_ratio` for a rate or ratio surface.

## Own history, not the cross-section

Where a repair needs a replacement value, it comes from the bank's **own neighbouring
quarters** wherever possible. A bank with a real balance and a broken numerator still has a
well-defined own level, and its own history estimates it far better than a peer median.
The cross-section is the fallback for banks with no usable history, and for balances too
small to support a rate at all.

## Order matters

`apply_plan` sorts by `(RSSD_ID, REPORTING_PERIOD)` first — every repair reads a bank's
neighbouring quarters, and an unsorted frame would silently interpolate against the wrong
rows.

Apply floors *after* repairs, so a real balance keeps its repaired own rate and only the
tiny tail is overridden.

## When not to use this

Do not pass a **net** quantity to `interpolate_negative` or to a repair with
`negative_impossible=True`. Trading revenue, gains and losses on sales, and tax benefits
are all legitimately negative, and repairing them destroys real variation. The panel
declares which columns are gross-additive via `sign=nonneg`; `bankpanel validate
quarterize` reports exactly those.
