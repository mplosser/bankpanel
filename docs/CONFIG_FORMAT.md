# Config format

A config is a **sectioned CSV**. Marker lines (`[BASE_VARIABLES]`, `[DERIVED_VARIABLES]`,
…) split the file; each section carries its own header row. CSV rather than YAML because
configs must stay editable in Excel and because adding N line items should be an N-line
reviewable diff.

Every error carries `file:line`. `bankpanel lint` reads no data, so config mistakes are
caught before a build starts.

## `[META]`

`key,value`. `panel_name`, `schedule`, `version`, `maintainer`, `source_repo`.

## `[BASE_VARIABLES]`

One MDRM code → one output column.

`mdrm_code, variable_name, schedule, flow_type` are required;
`form_scope, era_start, era_end, sign, notes` optional.

`flow_type` (`stock|ytd|flag|count|rate|text`) is the quarterize discriminator — only
`ytd` is differenced. A `ytd` item is **published twice**: `ytd_<stem>` exactly as filed
(the year-to-date, never altered) and `q_<stem>`, the within-year difference (Q1 = the
year-to-date; NaN wherever the prior quarter is missing or blank, so an annual filer's Q4
total stays in `ytd_<stem>` and its `q_<stem>` is NaN all year). The config
`variable_name` is the as-filed column, so lint requires it to start with `ytd_`; the
companion name is derived, and the `q_` prefix is reserved for it (lint refuses a config
name that starts with `q_`). The legacy pipeline overwrote the year-to-date in place under
a `q` name (`ytdint_inc` → `qint_inc`); the legacy spellings are kept in
`reference_data/legacy_names.csv` for parity and the export shim.

`sign=nonneg` marks a gross-additive flow that cannot be negative over a quarter. It
drives the quarterize audit, so it must not be set on net items — trading revenue, gains
on sales and tax benefits are legitimately negative.

## `[DERIVED_VARIABLES]`

`variable_name, schedule, flow_type, description, formula` required; `unit, sign` optional.

`formula` is a one-line pandas expression evaluated against **only** that formula's
graph-resolved dependencies, behind an AST allowlist. `description` is required: the
dictionary ships with the panel, so an undescribed column is an undocumented one.

Era stitching lives here: `a.fillna(b).fillna(c)` coalesces the successive MDRM codes
that carried one concept across a *code* change.

**A series whose definition changes does not keep one name across the change.** A stitch
is for the same measurement under a new code — verified, where both codes overlap, by the
two agreeing. When the form redefines a line (accrued interest on loans becoming accrued
interest on all assets at 2001Q1; credit cards *and related plans* becoming credit cards
alone), the two halves are published under two names, and the old one carries an era
suffix (`accrued_int_loans_pre01`). If the redefinition split one line into two, their sum
is the old definition and may be published as a consistent series under its own name
(`ln_cc_incl_revolving`). `bankpanel validate stitches` finds the level steps that mark a
definition change hidden inside a stitch; the [VALIDATION.md](VALIDATION.md) table records
which steps were which.

**`form_type` is readable in any formula.** It is supplied by the builder, not a config —
so it can be read but never bound, and it is not a dependency. It exists because some RC-N
lines are reported separately on the FFIEC 031 and folded into a broader line on the
041/051: agricultural nonaccrual (`RCFD1583`) sits inside all other loans on the 041, so a
total that counts each category once must write `na_agprod.where(form_type == 31)`.

**Consolidated vs domestic (RCFD vs RCON): the official rule.** A base row names the
consolidated code (`RCFD` on the Call Report, `BHCK` on the FR Y-9C); the builder fills it
from the domestic twin (`RCON`, `BHDM`) where the consolidated code is blank. That fill is
correct only for a bank WITHOUT foreign offices, where the two are the same number, so:

1. a bank with foreign offices (FFIEC 031 filer; on the Y-9C, any foreign-office deposits)
   never gets a domestic figure under a consolidated name -- the column stays blank;
2. for such a bank, a consolidated (or domestic) value in a quarter the form does not collect
   that code, according to MDRM (`reference_data/scope_validity.csv`, built by
   `tools/build_scope_validity.py`), and identical to its twin, is an upstream copy and is
   discarded. The Chicago Fed files (to 2010) copy in both directions, including codes the
   031 never collects at all (`RCFD3387`, consolidated average C&I loans).

An item the 031 collects only for domestic offices is therefore configured under its `RCON`
code and described as domestic (`qavg_loans_ci`, `na_heloc`, ...). `bankpanel validate scope`
reports, from every build's `consolidated_scope.parquet`: columns left blank for international
banks, copies discarded, values kept although MDRM says the code is not collected (they
differ from their twin, so MDRM may be incomplete), and -- as a gate -- a sudden jump in the
share of identical consolidated and domestic figures at banks with material foreign
business, the signature of an upstream copy.

**`yyyyq` is readable in any formula.** Also supplied by the builder: the reporting quarter as
an integer `YYYYQ` (2008Q4 is `20084`). It is for rules that depend on the period, such as a
unit change at a source boundary: the reported capital ratios are filed in percent for
2008Q4-2010Q4 and in fractions on either side, so `configs/call/rc_r_capital.csv` writes
`x.where(~((yyyyq >= 20084) & (yyyyq <= 20104)), x / 100)`. Note that `era_start` / `era_end`
on a base row feed the expectations matrix, ledger and zero-fill; they do **not** blank
values outside the era, so an era rule that must change values belongs in a formula.

**Guard every `fillna(0)` chain.** Tolerating one missing component inside an era is
right; doing it across an era boundary, where every component is absent, fabricates a
confident zero — and *raises* coverage while doing it, so no reporting-side validator can
see it. Write:

```
(a.fillna(0) + b.fillna(0)).where(a.notna() | b.notna())
```

`bankpanel validate quality` checks this structurally over every derived column.

## `[ZERO_FILL]`

`column, scope, reason` (+ optional `era_start`). `scope` is `always`, `in_era` or
`in_era_unless_reported`.

`in_era_unless_reported` is for an item a bank is *expected* to file when it has any, and
whose zeros the source stopped writing: a blank becomes 0 unless (a) the bank reports the
item in another quarter of the same year -- annual or semiannual collection, where the
quarterly value is unknown, not zero; (b) no filer of the bank's form reports it that
quarter -- not collected then; or (c) the bank's form is outside the item's `form_scope`.
It is never a general policy: each column needs its own rule and a measured reason. A zero
is not put where the value is not required or not regularly reported.

`reason` is required and enforced: zero-filling a measured value is a data-integrity
decision. `in_era` never fabricates a zero before the quarter collection actually began.
Applied last, after coalesce and era-stitching, so it cannot mask a NaN those steps needed.

## `[INTERMEDIATE]`

`column, reason`. A column that is **built and used, then withheld** from the panel.

Some reported items are only worth having as inputs. Schedule RC-N itemises past-due and
nonaccrual amounts for four small loan categories across three ageing buckets — a grid
whose fullest cell has 214 non-zero values in 148,899 bank-quarters. The analytically
meaningful object is the bucket total.

Declaring the grid `[INTERMEDIATE]` keeps the construction auditable — the formula still
names every input, and the dictionary still documents them with `published=false` — while
keeping two dozen near-empty columns out of the published panel. That is different from
deleting the rows, which would leave the bucket total as an unexplained number.

Lint refuses an `[INTERMEDIATE]` column that no published column depends on: withholding
something nothing consumes is not reduced scope, it is deleted data.

## `[CHECKS]`

`name, expression, severity, description`. A boolean expression in the same language as a
formula, asserted on every row where all its inputs are present. See
[QUALITY.md](QUALITY.md).
