# Changelog

## 1.5.0 — 2026-09-27

- **Annual filers' written zeros before 2005Q3 are published blank** (new config section
  `[BLANK_ANNUAL_ZEROS]`, docs/CONFIG_FORMAT.md). Schedule RC-T is collected at Q4 only from
  smaller trust departments. Until 2005Q2 the source wrote 0 for them in Q1-Q3, and from
  2005Q3 it leaves a blank, so the same "not collected" meant 0 on one side of 2005Q3 and
  blank on the other. Up to 2005Q2, a bank-year with no non-zero Q1-Q3 value and a non-zero Q4
  value has its Q1-Q3 zeros blanked: 12,830 bank-quarters at 1,411 banks on each of the six
  RC-T items (twelve columns). A scan of every published column 1985-2007 found no other item
  with this pattern (docs/CAVEATS.md §11). Raw identity knows the rule: 0 differences.
  Otherwise the build is identical to 1.4.1's; data-quality results unchanged.

## 1.4.1 — 2026-09-27

- **Zero-fill in the unfinished newest year.** The in-era zero-fill leaves a blank alone when
  the bank reports the item in another quarter of the same year (annual RC-T filers file at
  Q4 only). In the newest year, before its Q4 exists, that could not be seen, so annual
  filers' Q1-Q3 blanks became zeros: 488 trust banks with real fiduciary balances in
  2026Q1-Q2, and the same in 2025Q1-Q3 in any build made before 2025Q4 was published. The
  unfinished year is now built last and reads the finished prior year: a bank whose reports
  last year all fell in quarters not yet arrived keeps its blanks. Without the prior year in
  the build, the unfinished year gets no such zero-fill. Finished years are unchanged.

## 1.4.0 — 2026-09-26

- **Consolidated means consolidated: the official RCFD-vs-RCON rule** (both panels; the
  Y-9C pair is BHCK/BHDM). A domestic figure fills a consolidated column only for banks
  without foreign offices. For a bank with foreign offices, a value its form does not collect
  that quarter according to MDRM, and identical to its twin code, is an upstream copy and is
  discarded. A value outside the MDRM window that differs from its twin is kept and counted.
  See docs/VALIDATION.md §5 and docs/CAVEATS.md §13.
- **`reference_data/scope_validity.csv`**, generated from MDRM by
  `tools/build_scope_validity.py`, with evidenced corrections in
  `reference_data/scope_validity_overrides.csv` (`RCONF072`/`F073`, RC-P on the 031
  2006-2018). The quarterly refresh regenerates it and reports any change.
- **`bankpanel validate scope`** (also part of `validate all`). The build writes
  `consolidated_scope.parquet`. The gate flags a jump in the share of banks with material
  foreign offices filing identical consolidated and domestic figures. It is CRITICAL when
  the share rises 50 points above the column's usual level, with at least 5 banks and a
  share of at least 95%. On a build from the unfixed parser it flags exactly total assets,
  total liabilities and average total loans. `raw_identity_check.py` re-derives the rule:
  0 differences on both panels.
- **Average total loans is consolidated for 031 filers**: `qavg_loans_tot` =
  `qavg_loans_tot_dom` (RCON3360) + the foreign-offices average (RCFN3360). It equals the
  reported RCFD3360 exactly before 2011. From 2011 the old column carried the domestic
  average for 60 banks with foreign offices (median 4% low), because of the upstream
  cross-fill.
- **Domestic-only items are named as such**: `na_farmland`, `na_heloc`, `na_multifam`, the
  RC-K category averages (`qavg_loans_ci`, `_ag`, `_famres`, `_othre`,
  `qavg_loans_re_agg_pre08`) and `demand_notes_treas` now read their RCON codes and say
  "domestic offices". The 031 never files a consolidated version of these. The lease past-due
  and nonaccrual totals read RCFD1226-1228.
- **New domestic twins**: `trad_ust_dom`, `trad_usagency_dom`, `trad_states_dom`,
  `trad_oth_dom` (RCON3531-3533, 3541) and `ln_nondep_fin_inst_dom` (RCONJ454). The
  consolidated columns are blank for 031 filers where only the domestic figure was filed.
- **FR Y-9C**: the lease totals (`pd30_lease`, `pd90_lease`, `na_lease`) are published. Loans
  to depository institutions is blank 1991-1995 for holding companies with foreign offices,
  because only the domestic BHDM1489 is filed then. Coverage ledger rows are signed for both,
  and the mis-copied reasons on the lease component rows are corrected.

## 1.3.0 — 2026-09-26

- **Core totals from Kashyap and Stein's consistent-time-series notes** (cited in the README;
  `configs/call/core_series.csv`), on both panels, each validated against the reported totals:
  `liabilities`, `deposits` (consolidated), `liabilities_ex_subdebt`, `ln_gross`,
  `ln_consumer`, `securities` (investment securities 1985-, stitched across 1994),
  `trad_ass_pre94` (not stitched: the 1994 definition adds derivative revaluation gains),
  `ytd_net_inc`, `ytd_int_exp_dep`, `ytd_op_inc`, `ytd_op_exp`, `ytd_int_inc_ffrepo`,
  `ytd_int_exp_ffrepo` (each `ytd_` with its `q_` flow). Where a reported total exists
  (the Chicago Fed files, to 2010) it is used as filed and the component sum takes over,
  identical over 1985-2010.
- **`deposits` is not read from `RCFD2200`**: after 2011 that code carries the domestic figure
  for banks with foreign offices (the upstream cross-fill), which would drop their foreign
  deposits. Domestic + foreign equals the reported consolidated total exactly before 2011.
- **Quality checks**: `balance_sheet_foots` (assets = liabilities + equity, + minority
  interest from 2001), `deposits_le_liabilities`, `ln_gross_ge_net` (info). Checks can now
  read the `yyyyq` builtin. **`deposits_le_assets` corrected**: as `dep_tot_dom <= assets` it
  failed on 1,066 bank-quarters in every build, all insolvent banks with negative equity; it
  is now `(deposits <= assets) | (equity < 0)` and passes. 27 checks in total.
- **Published names are kept**: the Y-9C generator reuses an existing predecessor-item name
  (`pred_net_income_loss`) rather than re-deriving one when the Call configs gain a stem for
  the same code.

## 1.2.0 — 2026-09-26

- **`tools/quarterly_refresh.py`**: one command for each new quarter -- fetch (Call Report
  scripted; FR Y-9C stops at the manual NIC download with the exact files), MDRM
  dictionary, parse, regenerate the Y-9C configs, rebuild and validate both panels,
  raw-identity check on the newest quarters, and a one-page `refresh_report.md` with an
  exit code (0 clean, 1 decision needed, 2 blocked).
- **`reference_data/breaks_acknowledged.csv`**: explained latest-quarter breaks signed off
  with an expiry date (first entry: the FR Y-9C `J458` retirement, until 2027Q1).
- The data repositories' READMEs now point to bankpanel for building panels.

## 1.1.1 — 2026-09-26

- **FR Y-9C through 2026Q2** (2025Q4, 2026Q1, 2026Q2 added from the NIC files).
- **FR Y-9C 2026Q1 form change handled.** The Y-9C retired `BHCKJ458` (unused commitments
  to financial institutions) in 2026Q1 for `BHCKPV10 + PV11`, a year after the Call Report
  (2024Q4). With the new codes now in the Y-9C files, the regenerated configs publish the
  stitched `uc_other_2` and, for the first time on this panel, `uc_other` (total other
  unused commitments), plus the new nondepository-financial past-due and nonaccrual lines
  (`pd30_nondep_fin`, `pd90_nondep_fin`, `na_nondep_fin`). 9 items added, none removed.
- Docs: the Call Report `J458` retirement is 2024Q4 (was given as 2025Q3); why the
  latest-quarter gate keeps flagging a retired era piece for four quarters.

## 1.1.0 — 2026-09-26

- **Filer unit errors in the reported capital ratios are corrected** (RC-R-I §2). A filed
  ratio 30-300x (or 1/300-1/30 of) the ratio implied by the bank's own amounts is rescaled
  by 100: 18 cells on the Call Report, 83 on the FR Y-9C. New columns:
  `capital_ratio_unit_corrected` (count of corrections in the row) and
  `leverage_ratio_reported_uncorrected`, `tier1_rbc_ratio_reported_uncorrected`,
  `total_rbc_ratio_reported_uncorrected`, `cet1_ratio_reported_uncorrected` (as filed, in
  consistent units, before correction).
- **Fixed (1.0.1 bug): the 2014 Basel III early adopters.** ~30 banks a quarter file
  `RCFA7204`/`7205`/`7206` in 2014 as fractions; 1.0.1 treated them as percent and
  published their 2014 reported ratios at 1/100. `*_reported_baselI` is now blank for these
  banks in 2014 (they filed the Basel III code).
- **Seven new quality checks** on the reported ratios (unit agreement, identity with the
  computed ratio, tier 1 filed as zero next to a ratio). `validate quality --save` now also
  writes `quality_failures.csv`, the failing bank-quarters with their inputs.

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
