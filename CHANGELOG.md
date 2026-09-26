# Changelog

## 1.0.1 — 2026-09-26

- **Reported capital ratios corrected and extended to 2025** (Schedule RC-R Part I,
  [docs/schedules/RC-R-I.md](docs/schedules/RC-R-I.md) §2). The 1.0 claim that
  `RCOA7204`/`7205`/`7206`/`P793` are confidential from 2015Q1 was wrong: they are ~98%
  populated and written as percent strings (`"9.1154%"`) in the CDR bulk files, which
  numeric coercion had turned into NaN. `data_call_report` now stores them as numbers.
  The reported ratio also changes units with the source (fractions 2001Q1–2008Q3 and
  2011Q1–2014Q4, percent 2008Q4–2010Q4 and 2015Q1–), so the three published
  `*_reported_baselI` columns carried a 100× unit break in 2008Q4–2010Q4.
  - **Changed values**: `leverage_ratio_reported_baselI`, `total_rbc_ratio_reported_baselI`,
    `tier1_rbc_ratio_reported_baselI` are now fractions in every quarter (the 2008Q4–2010Q4
    quarters were percent). Names unchanged.
  - **New columns** (fractions, full span): `leverage_ratio_reported`,
    `tier1_rbc_ratio_reported`, `total_rbc_ratio_reported` (2001Q1–), `cet1_ratio_reported`
    (2015Q1–). On the Y-9C the same names, from `BHCK`/`BHCA` codes.
  - The computed ratios (`tier1_rbc_ratio`, `total_rbc_ratio`, `cet1_ratio`) are unchanged.
- **New formula builtin `yyyyq`**: the reporting quarter as an integer `YYYYQ`, for rules
  that depend on the period (the ratio unit change above). Documented in
  [docs/CONFIG_FORMAT.md](docs/CONFIG_FORMAT.md), which now also states that
  `era_start`/`era_end` on a base row do not blank values outside the era.
- **Percent strings** (`"9.1154%"`) are read as numbers in percent units by the builder's
  coercion, in case a raw parse leaves them as text.
- **Coverage through 2026Q2** on the Call Report (2025Q4–2026Q2 added; `data_call_report`
  now downloads the CDR bulk files itself). The FR Y-9C stays at 2025Q3 until the three
  NIC files are downloaded by hand (the NIC site blocks scripts).
- Raw input change (`data_call_report` 2026-09-26): the 325–327 all-`CONF` confidential
  columns per CDR quarter (Schedule RC-O assessment items and a few others) are no longer
  written to the raw parquets. No `bankpanel` column read any of them.

## 1.0.0 — 2026-09-26

First stable release. Column names on both panels are now an API: they will not be renamed
without a deprecation entry here.

- **Examples**: `examples/quickstart.py` and the executed `examples/quickstart.ipynb`
  (generated from the script by `examples/make_notebook.py`). Reads both panels; shows
  `form_type`, `ytd_` vs `q_`, `expected_mask`, and one figure.
- **Third-party reproducibility**: no path in the package or tools refers to a particular
  machine; every location is an argument or an environment variable
  (`BANKPANEL_PANEL_ROOT`, `BANKPANEL_CALL_ROOT`, `BANKPANEL_Y9C_ROOT`, `BANKPANEL_MDRM`,
  `BANKPANEL_Y9C_RAW`, `BANKPANEL_CALL_RAW_FFIEC`, `BANKPANEL_LEGACY_PANELS`,
  `BANKPANEL_LEGACY_CONFIGS`). A fresh clone installs with `pip install -e .`, passes
  `bankpanel lint` and the test suite with no data present, and builds both panels from
  the public `data_call_report` and `data_fry9` repositories.
- **Fixed: the engine's `src/bankpanel/build/` package was never committed.** The
  `.gitignore` rule `build/` (meant for packaging output) matched it, so every clone of
  0.1–0.7 failed at `import bankpanel`. Found by the fresh-clone test above; the rule is
  now anchored to the repository root.
- `bankpanel.__version__` reads the installed distribution's version.
- CI keyed to the repository's `master` branch (it was keyed to `main` and never ran).
- Wheels no longer bundle a stale local `reporting_expectations.parquet`; the matrix is
  built per panel with `bankpanel expectations build`.
- Lint clean under the shipped ruff configuration; `tools/README.md` describes the
  maintainer tools and which of them need the legacy BEC repository.
- Known gaps deferred to 1.1 and listed in `docs/CAVEATS.md` §12: FR Y-9C items before
  1990 whose codes differ from the Call Report's are not yet recoded; Schedule HC/HI notes
  in `docs/schedules/` are not yet written (the RC/RI notes apply by construction, since
  `configs/y9c` is generated from `configs/call`).

## 0.7.0 — 2026-09-22

- **FR Y-9C panel** (`--profile fry9c`, `configs/y9c/`): generated from the Call Report configs
  by prefix translation plus a measured exception map; same variable names on both panels.
  Size tier ($5bn) as the population key; Schedule HI predecessor-institution items published
  as filed (`pred_*`, never differenced); business-combination flags.
- **Year-to-date items published twice**: `ytd_<stem>` as filed and `q_<stem>` the quarterly
  flow, NaN wherever no clean one-quarter difference exists (annual filers keep their total).
- **Zero-fill scope `in_era_unless_reported`**: blank -> 0 only where the bank was expected to
  report; per item, with a measured reason (Call Report 2005Q3, Y-9C 2025Q2).
- **Raw-identity check** (`tools/raw_identity_check.py`): every base column against its raw
  code, every quarter. Coalesce fallback codes now come from the profile (the Y-9C's `BHDM`
  twins were not being read).
- Call Report construction fixes: `ln_re` built from components where line 1 is not filed;
  `ln_dep` for 031 filers from 2011; Basel III capital read from `RCFA`/`RCFW` for the 031;
  1985–88 form type requires the foreign-office schedule; `ffrepo_*` blank on empty filings.
- Coverage ledgers signed for both panels; validators read the panel in column chunks.

## 0.6.0 — 2026-09

- Cleaning layer, data-quality checks, `[INTERMEDIATE]`, structural validators (fabricated
  values, assumed zeros, stitch continuity), review packet.

## 0.1–0.5 — 2026-08

- Engine, form-type bridge, expectations matrix, schedules RC-B/C/D/E/K/N/O/R-I, RI-A/B;
  parity 688/688 against the source pipeline.
