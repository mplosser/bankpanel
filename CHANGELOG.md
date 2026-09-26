# Changelog

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
