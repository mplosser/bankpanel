# Changelog

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
