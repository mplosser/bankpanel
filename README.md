# bankpanel

**Time-consistent panels from US bank regulatory reports.**

Turns raw quarterly FFIEC Call Report files into a single analysis-ready panel keyed
`(RSSD_ID, REPORTING_PERIOD)`, handling the things that make forty years of bank
regulatory data hard to use: MDRM codes that change when a definition changes,
year-to-date income items that must be differenced, and a short form that most banks now
file which omits some items entirely and collects others only twice a year.

> **Status: v0.1.** The engine is complete and verified: the shipped configs reproduce
> the panels of the research pipeline this was extracted from — **688 of 688 columns
> match exactly** across 1,415,045 bank-quarters. The panel now carries **1,071 columns**
> across fourteen schedules. See [Roadmap](#roadmap).

---

## Why this exists

A single economic concept is rarely a single MDRM code. Construction and land development
lending is `RCON1415` for twenty years, then splits into `RCONF158 + RCONF159`, with a
two-year overlap in which both are reported and only some banks file the split. Other
borrowed money runs through five codes since 1984. Total nonaccrual loans has a five-year
hole that can only be filled by summing twenty-two Schedule RC-N line items.

Every researcher who uses this data rediscovers these breaks by hand, usually one at a
time, usually after a result looks strange. `bankpanel` puts that knowledge in **config
files** — one line per variable, editable in Excel, reviewable in a diff — and keeps the
engine generic.

```csv
[BASE_VARIABLES]
mdrm_code,variable_name,schedule,flow_type,form_scope,era_start,era_end,sign,notes
RCON1415,ln_condev_pre07,RC-C,stock,all,,2010-12-31,,Combined item; in source through 2010Q4
RCONF158,ln_condev_res_1_4,RC-C,stock,all,2007-03-31,,,1-4 family residential construction
RCONF159,ln_condev_other,RC-C,stock,all,2007-03-31,,,Other construction and land development

[DERIVED_VARIABLES]
variable_name,schedule,flow_type,description,formula,unit,sign
ln_condev_post07,RC-C,stock,Rebuilt from the 2007 split,ln_condev_res_1_4 + ln_condev_other,thousands_usd,
ln_condev,RC-C,stock,Consistent basis 1985-present,ln_condev_post07.fillna(ln_condev_pre07),thousands_usd,
```

That yields one `ln_condev` column at 100% coverage from 1985 to today.

---

## Install

```bash
git clone https://github.com/mplosser/bankpanel
cd bankpanel
pip install -e .
```

You supply the raw data. `bankpanel` reads the quarterly parquet files produced by
[`data_call_report`](https://github.com/mplosser/data_call_report), which downloads and
parses the Chicago Fed and FFIEC CDR bulk files.

## Use

```bash
bankpanel lint                              # validate configs; reads no data
bankpanel build --raw-dir /path/to/FFIEC_031_041 --out panel_root --jobs 8
bankpanel expectations build --panel-root panel_root
bankpanel validate all --panel-root panel_root --save   # coverage, breaks, quarterize, quality, stitches
bankpanel info --panel-root panel_root
bankpanel dictionary --schedule RC-C
bankpanel dictionary --measure --format csv --out variables.csv   # + measured coverage
```

`dictionary --measure` scans the built panel and appends, per column, `n_obs`,
`coverage`, `first_quarter`, `last_quarter`, `pct_zero` (share of *reported* values that
are exactly zero) and `total`, next to the construction: MDRM code or formula, resolved
`inputs`, schedule, era bounds, form scope and description. A committed snapshot for the
current build is [`docs/variables.csv`](docs/variables.csv).

`pct_zero` is there because coverage alone cannot tell a well-reported column from an
analytically empty one. Several Schedule RC-N itemisations are reported by every 031
filer for six years and are zero in 99.9% of those cells.

```python
import bankpanel as bp

bp.search_variables("sweep_dep")
bp.columns_for_schedule("RC-C")
bp.expected_mask(df, "custody_assets")     # was this cell supposed to be reported?

df = bp.read_panel(
    columns=["assets_total", "ln_condev", "net_interest_income"],
    start="2000Q1",
    form_types=(31, 41, 51),
)
```

`columns` is required — the finished panel is far too wide to load whole, and parquet
column projection means asking for what you need is cheap.

---

## What it does

**Era stitching.** Three layers, kept separate on purpose. Column-level prefix aliasing
(`RCFA`→`RCOA`) and row-level `RCFD`/`RCON` coalescing are *mechanical* and live in the
engine. Genuine definition changes are *knowledge* and live in config formulas.

**Year-to-date conversion.** Every RIAD income item is year-to-date and resets each Q1.
`bankpanel` differences within bank-years, and — unlike the naive version — catches the
three cases where that silently goes wrong: a bank missing an intra-year quarter (whose
next difference spans two quarters), a bank whose first filing of a year is not Q1 (whose
year-to-date would otherwise be booked as one quarter's flow), and a bank whose previous
quarter was filed but left the item blank (same effect, and invisible to any check based
on the reporting calendar). Handled by an explicit `--gap-policy` and reported rather than
absorbed. Both representations are published: `ytd_<stem>` as filed and `q_<stem>` the
flow, so a bank that files an item only at Q4 keeps its annual total in `ytd_` and shows
no invented quarters in `q_`. On a full 1985–2025 build the uncomputable flows are about
1 in 100 bank-quarters for the core income items, almost all partial first or last years.

**Form awareness.** Every row carries `form_type` (31/41/51) across the whole panel,
including the pre-2011 era where it must be derived. This is what lets you tell
"not collected" apart from "reported as missing".

**Validation.** Three checks — coverage discontinuities across all history, a
latest-quarter break gate, and impossible negative flows — all driven by a measured
**reporting-expectations matrix** so that FFIEC 051 semiannual items are not mistaken for
breaks. On the full panel that suppresses 73% of findings while still catching genuine
ones, including a code retirement in 2025Q3. See [`docs/VALIDATION.md`](docs/VALIDATION.md).

**Data-quality checks.** Declarative boolean assertions about *values* — component ≤
total, ratios non-negative, accounting identities — declared in config and validated by
the same AST gate as formulas. See [`docs/QUALITY.md`](docs/QUALITY.md), including a
worked case where the check turned out to be wrong and the data right.

**Cleaning is opt-in and last.** The panel on disk is exactly what the configs produced —
enforced by a test that `build/` and `io/` cannot import `clean/`. Repair functions are
pure and importable, and `apply_plan` returns an audit frame of every changed cell, so a
cleaning decision is reproducible and reviewable rather than baked in. See
[`docs/CLEANING.md`](docs/CLEANING.md).

---

## Read this before using the data

[`docs/CAVEATS.md`](docs/CAVEATS.md) is not boilerplate. In particular:

- Post-2011, `RCFD` and `RCON` are **byte-identical for all-numeric item codes** and
  genuinely different for alphanumeric ones — an artifact of upstream cross-filling.
- FFIEC 051 filers, the majority of banks since 2017, report hundreds of items only in
  Q2 and Q4. A quarterly average over 2017+ that ignores this is a 041-only sample.
- The upstream source changes provider at 2010Q4→2011Q1, and some legacy items disappear
  there for reasons that are about the source, not about the form.
- Values are thousands of USD. The panel is by filer RSSD, with no merger or
  survivorship adjustment.

---

## Roadmap

| Version | Contents |
| --- | --- |
| 0.1 | Engine: config layer, build, quarterization, reader, dictionary, CLI. Parity verified against the source pipeline (688/688 columns exact) |
| 0.2 | Form-type bridge, reporting-expectations matrix, the three validators — **done** |
| 0.3 | Schedules [RC-C](docs/schedules/RC-C.md), [RC-E](docs/schedules/RC-E.md) — **done** |
| 0.4 | Schedules [RC-B](docs/schedules/RC-B.md), [RC-D](docs/schedules/RC-D.md), [RC-N](docs/schedules/RC-N.md) — **done** |
| 0.5 | Schedules [RC-K](docs/schedules/RC-K.md), [RC-R Part I](docs/schedules/RC-R-I.md), [RC-O](docs/schedules/RC-O.md), [RI-A](docs/schedules/RI-A.md), [RI-B](docs/schedules/RI-B.md) — **done** |
| 0.6 | [Cleaning layer](docs/CLEANING.md) + [data-quality checks](docs/QUALITY.md) — **done** |
| 1.0 | Docs, examples, DOI, PyPI |

FR Y-9C support is designed for — the engine takes a `ReportProfile` — but not built.

## License

MIT. The underlying data is public domain, published by the FFIEC and the Federal Reserve.
