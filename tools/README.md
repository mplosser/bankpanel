# Maintainer tools

Scripts that are not part of the installed package. Each has a docstring with its full
usage; `python tools/<name>.py --help` prints the arguments. Paths are arguments or
environment variables, never hard-coded.

## Need only a built panel and the raw files

| tool | what it does |
| --- | --- |
| `raw_identity_check.py` | Regression guard: every published **base** column equals its raw MDRM code, cell for cell, on a sample of quarters (`--all` for every quarter). Uses the builder's own numeric coercion. `--profile fry9c` for the Y-9C. |
| `derive_y9c_configs.py` | Regenerates `configs/y9c/` from `configs/call/` by prefix translation plus the exception maps in `reference_data/y9c_*.csv`. Run after any change to the Call configs; writes `review/y9c_dropped.csv`. |
| `build_schedule_map.py` | Builds `reference_data/mdrm_to_schedule.csv` (MDRM code → Call Report schedule) from the FFIEC CDR bulk ZIPs, which are the only source that says which schedule an item belongs to. |
| `make_review_packet.py` | Writes `review/01_names.csv`, `02_derived.csv` and `03_domain_calls.csv`: the decisions that need a human, with the evidence attached and a blank `verdict` column. |

## Need the legacy BEC repository (`bec_migration`)

These exist because `bankpanel` was extracted from a research pipeline and had to prove
parity with it. A third party does not need them.

| tool | what it does |
| --- | --- |
| `parity_check.py` | Column-by-column comparison of a bankpanel build against the legacy panels (`BANKPANEL_LEGACY_PANELS`). The acceptance test for the migration: 688/688 columns exact. |
| `migrate_legacy_configs.py` | One-shot import of the legacy configs (`BANKPANEL_LEGACY_CONFIGS`) into bankpanel format. Already run; kept for provenance. |
| `export_legacy_panels.py` | The cutover shim: emits the three legacy-named panel files the BEC pipeline reads from a bankpanel build. Streams in Arrow, so it runs in a few GB. |
| `bhc_bank_crosscheck.py` | FR Y-9C consolidated figures against the sum of each holding company's Call-filing subsidiaries. The parent↔bank link comes from BEC's `entity_classification.parquet` (`--classification`); results are in `docs/FR-Y-9C.md`. |

## Review folder

`review/` holds the human-decision artifacts: the name review, the derived-series review
and domain calls (from `make_review_packet.py`), the one-page coverage ledgers by event
(`06_*`, `07_*`), the raw-identity results, the list of Call columns that did not
translate to the Y-9C (`y9c_dropped.csv`, from `derive_y9c_configs.py`), and two one-off
analyses kept for provenance (`04_pdl_tot_non_components.csv`, `05_definition_splits.csv`).
It documents the decisions baked into `configs/` and is not needed to build or use a panel.
