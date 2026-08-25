# bankpanel

**Time-consistent panels from US bank regulatory reports.**

Turns raw quarterly FFIEC Call Report files into a single analysis-ready panel keyed
`(RSSD_ID, REPORTING_PERIOD)`, handling the things that make forty years of bank
regulatory data hard to use: MDRM codes that change when a definition changes,
year-to-date income items that must be differenced, and a short form that most banks now
file which omits some items entirely and collects others only twice a year.

> **Status: v0.1, under active development.** The engine works end to end; schedule
> coverage is still being filled in. See [Roadmap](#roadmap).

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
bankpanel info --panel-root panel_root
bankpanel dictionary --schedule RC-C
```

```python
import bankpanel as bp

bp.search_variables("construction")
bp.columns_for_schedule("RC-C")

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
`bankpanel` differences within bank-years, and — unlike the naive version — detects the
two cases where that silently goes wrong: a bank missing an intra-year quarter (whose
next difference spans two quarters), and a bank whose first filing of a year is not Q1
(whose year-to-date would otherwise be recorded as one quarter's flow). Both are reported
and handled by an explicit `--gap-policy`.

**Form awareness.** Every row carries `form_type` (31/41/51) across the whole panel,
including the pre-2011 era where it must be derived. This is what lets you tell
"not collected" apart from "reported as missing".

**Validation.** Coverage discontinuities, latest-quarter series breaks, and impossible
negative flows, each with an approvals ledger so a known, explained transition stops
being reported.

**Cleaning is opt-in and last.** The panel on disk is exactly what the configs produced.
Repair functions are pure, importable, and return an audit frame of every changed cell,
so a cleaning decision is reproducible and reviewable rather than baked in.

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
| 0.1 | Engine: config layer, build, quarterization, reader, dictionary, CLI |
| 0.2 | Form-type bridge, reporting-expectations matrix, the three validators |
| 0.3 | Schedules RC-C, RC-E |
| 0.4 | Schedules RC-B, RC-D, RC-N |
| 0.5 | Schedules RC-K, RC-R Part I, RC-O headline, RI-A, RI-B |
| 0.6 | Cleaning layer |
| 1.0 | Docs, examples, DOI, PyPI |

FR Y-9C support is designed for — the engine takes a `ReportProfile` — but not built.

## License

MIT. The underlying data is public domain, published by the FFIEC and the Federal Reserve.
