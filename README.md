# bankpanel

**Time-consistent panels from US bank regulatory reports.**

Turns raw quarterly FFIEC Call Report and FR Y-9C files into analysis-ready panels keyed
`(RSSD_ID, REPORTING_PERIOD)`, with the same variable names on both, handling the things that make forty years of bank
regulatory data hard to use: MDRM codes that change when a definition changes,
year-to-date income items that must be differenced, and a short form that most banks now
file which omits some items entirely and collects others only twice a year.

> **Status: v1.1.0.** Two panels: **`bankpanel_call`** (FFIEC 031/041/051, 1985Q1–2026Q2,
> 1.43 million bank-quarters, ~1,180 columns) and **`bankpanel_y9c`** (FR Y-9C, 1986Q3–2025Q3,
> 188 thousand holding-company-quarters, ~850 columns). Every published base column is
> verified cell for cell against its raw MDRM code over every quarter, every coverage
> discontinuity is explained in a signed ledger, and no derived value rests on nothing.
> Column names are stable from 1.0: a rename gets a deprecation entry in the
> [changelog](CHANGELOG.md). See [Reproduce from scratch](#reproduce-from-scratch),
> [Examples](#examples) and [docs/FR-Y-9C.md](docs/FR-Y-9C.md).

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
pip install -e .                 # add ".[examples]" for examples/ (matplotlib, notebook tooling)
```

You supply the raw data. `bankpanel` reads the quarterly parquet files produced by
[`data_call_report`](https://github.com/mplosser/data_call_report) (Call Report: Chicago
Fed and FFIEC CDR bulk files) and [`data_fry9`](https://github.com/mplosser/data_fry9)
(FR Y-9C: Chicago Fed and FFIEC files). Both are sibling repositories: the tools default
to `../data_call_report` and `../data_fry9`, overridable with `BANKPANEL_MDRM`,
`BANKPANEL_Y9C_RAW`, `BANKPANEL_CALL_RAW_FFIEC` and `BANKPANEL_LEGACY_PANELS`.

## Use

```bash
bankpanel lint                              # validate configs; reads no data
bankpanel build --raw-dir /path/to/FFIEC_031_041 --out panel_root --jobs 8
bankpanel build --profile fry9c --raw-dir /path/to/y_9c --out y9c_root --jobs 4   # the FR Y-9C panel
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
current build is [`docs/variables_call.csv`](docs/variables_call.csv) and [`docs/variables_y9c.csv`](docs/variables_y9c.csv).

`pct_zero` is there because coverage alone cannot tell a well-reported column from an
analytically empty one. Several Schedule RC-N itemisations are reported by every 031
filer for six years and are zero in 99.9% of those cells.

```python
import bankpanel as bp

bp.search_variables("sweep_dep")
bp.columns_for_schedule("RC-C")
bp.expected_mask(df, "custody_assets")     # was this cell supposed to be reported?

df = bp.read_panel(
    columns=["assets", "ln_condev", "q_int_inc", "q_int_exp"],
    start="2000Q1",
    form_types=(31, 41, 51),
)
```

`columns` is required — the finished panel is far too wide to load whole, and parquet
column projection means asking for what you need is cheap. The reader finds the panel
through `root=`, else `BANKPANEL_PANEL_ROOT`, else `./panel_root`.

## Examples

[`examples/quickstart.py`](examples/quickstart.py) reads both panels and walks through the
three things a first-time user has to know: every row carries a form type, year-to-date
income is published both as filed (`ytd_`) and as a quarterly flow (`q_`), and a NaN is
only interpretable with `expected_mask`, which separates "not collected on this form this
quarter" from "left blank". It ends with one figure (aggregate loans-to-assets and net
interest margin, banks against holding companies).

```bash
python examples/quickstart.py --call-root panel_root --y9c-root y9c_root
# or: BANKPANEL_CALL_ROOT=... BANKPANEL_Y9C_ROOT=... python examples/quickstart.py
```

[`examples/quickstart.ipynb`](examples/quickstart.ipynb) is the same walk as an executed
notebook, generated from the script by `examples/make_notebook.py` so the two cannot drift.
[`examples/annotated_config_example.csv`](examples/annotated_config_example.csv) is a
commented config showing every section and column.

## Reproduce from scratch

Everything below runs on a machine that has never seen this data. Nothing is downloaded by
`bankpanel` itself; the two data repositories do that, and their READMEs are the reference
for their own steps. Every Call Report file is fetched by script, the FFIEC CDR bulk files
for 2011 onward by `data_call_report/01b_download_ffiec_cdr.py`. The one manual step is
the FR Y-9C from 2021Q2, which the FFIEC NIC site serves only to a browser. The Call
Report build is the one long step; the rest take minutes.

```bash
# 1. raw data (public FFIEC / Chicago Fed / Federal Reserve files -> quarterly parquet)
git clone https://github.com/mplosser/data_call_report && cd data_call_report
pip install -r requirements.txt
python 01_download_data.py && python 01b_download_ffiec_cdr.py   # Chicago Fed to 2010; FFIEC CDR 2011Q1-present
python 02_download_dictionary.py && python 03_parse_dictionary.py
python 04_parse_chicago.py && python 05_parse_ffiec.py
cd ..
git clone https://github.com/mplosser/data_fry9 && cd data_fry9
pip install -r requirements.txt
python 01_download_data.py                  # Chicago Fed, 1986Q3-2021Q1
# 2021Q2 onward: download the BHCF*.ZIP files by hand from the FFIEC NIC site into data/raw/
# (the site blocks scripts); python 01b_check_ffiec_nic.py lists any that are missing
python 04_parse_data.py
cd ..

# 2. bankpanel
git clone https://github.com/mplosser/bankpanel && cd bankpanel
pip install -e ".[dev,examples]"
bankpanel lint && pytest -q                       # configs and engine, no data needed

# 3. the Call Report panel (1.4 million rows x ~1,180 columns; ~1.1 GB on disk)
bankpanel build --raw-dir ../data_call_report/data/processed/FFIEC_031_041 --out panel_root --jobs 8
bankpanel expectations build --panel-root panel_root
bankpanel validate all --panel-root panel_root --save

# 4. the FR Y-9C panel (188 thousand rows x ~850 columns; ~150 MB)
bankpanel build --profile fry9c --raw-dir ../data_fry9/data/processed/y_9c --out y9c_root --jobs 4
bankpanel expectations build --profile fry9c --panel-root y9c_root
bankpanel validate all --profile fry9c --panel-root y9c_root --save

# 5. check what you built against what was published
python tools/raw_identity_check.py --panel-root panel_root --raw-dir ../data_call_report/data/processed/FFIEC_031_041
python tools/raw_identity_check.py --profile fry9c --panel-root y9c_root --raw-dir ../data_fry9/data/processed/y_9c
python examples/quickstart.py --call-root panel_root --y9c-root y9c_root
```

`validate all` compares the panel to the signed coverage ledger in `configs/*/coverage_expected.csv`;
a build from the same raw vintage reports zero open findings. A newer raw vintage adds
quarters and may add findings at the new end, which is the intended signal.

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
| 0.7 | Year-to-date items published as `ytd_` + `q_`; the `in_era_unless_reported` zero-fill; raw-identity check; **[FR Y-9C panel](docs/FR-Y-9C.md)** with the size tier and predecessor items — **done** |
| 1.0 | [Examples](#examples); reproducible from a fresh clone; column names stable — **done** |
| 1.1 | Reported capital ratios: unit harmonization across eras, filer unit-error correction with a flag, value checks with failing-row output — **done** |
| 1.2 | FR Y-9C items before 1990 whose codes differ from the Call Report's; Schedule HC/HI notes (see [docs/CAVEATS.md §12](docs/CAVEATS.md)) |

## License

MIT. The underlying data is public domain, published by the FFIEC and the Federal Reserve.
