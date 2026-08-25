"""End-to-end build behaviour, against the synthetic fixture."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from bankpanel.io.reader import PanelTooLargeError, read_header, read_panel

CHANGE = pd.Timestamp("2011-03-31")


@pytest.fixture(scope="module")
def panel(synth_panel):
    return read_panel(
        columns=[
            "assets_total", "loans_3mo", "avg_assets", "late_item", "semiannual_item",
            "int_inc_total", "event_flag", "deposit_accounts", "assets_less_loans",
            "late_or_assets",
        ],
        root=synth_panel,
        verify=False,
    )


# --- coalesce and aliasing ---------------------------------------------------------


def test_alphanumeric_pair_is_coalesced_across_the_provider_change(panel):
    """The failure this prevents: an item filed under RCFD before the change and RCON
    after collapses to ~1.6% coverage at the boundary unless the two are combined."""
    assert panel.loans_3mo.notna().all()


def test_coalesce_prefers_the_primary_code(synth_panel):
    """RCFD is consolidated and wins where present; RCON only fills gaps."""
    df = read_panel(columns=["loans_3mo"], root=synth_panel, verify=False)
    modern_31 = df[(df.REPORTING_PERIOD >= CHANGE) & (df.form_type == 31)]
    assert modern_31.loans_3mo.notna().all()


def test_prefix_alias_resolves(panel):
    """RCFA1234 exists in the source only as RCOA1234."""
    assert panel.avg_assets.notna().all()


def test_numeric_pair_agrees(panel):
    assert panel.assets_total.notna().all()


# --- absence is explicit -----------------------------------------------------------


def test_absent_code_becomes_an_all_nan_column_not_a_missing_one(panel):
    early = panel[panel.REPORTING_PERIOD < CHANGE]
    assert "late_item" in panel.columns
    assert early.late_item.isna().all()
    assert panel[panel.REPORTING_PERIOD >= CHANGE].late_item.notna().all()


def test_every_partition_shares_one_schema(synth_panel):
    """Required by pyarrow.dataset, and the reason absent codes are materialized."""
    parts = sorted((synth_panel / "panel").glob("year=*/part-0.parquet"))
    assert len(parts) > 1
    schemas = {pq.ParquetFile(p).schema_arrow.remove_metadata() for p in parts}
    assert len(schemas) == 1


def test_no_raw_mdrm_codes_survive_into_the_panel(synth_panel):
    names = pq.ParquetFile(
        next((synth_panel / "panel").glob("year=*/part-0.parquet"))
    ).schema_arrow.names
    assert not [n for n in names if n.upper().startswith(("RCFD", "RCON", "RIAD", "RCOA"))]


def test_stitch_falls_back_to_the_older_series(panel):
    """late_or_assets = late_item.fillna(assets_total): the era-stitch idiom."""
    early = panel[panel.REPORTING_PERIOD < CHANGE]
    assert (early.late_or_assets == early.assets_total).all()


# --- zero-fill ---------------------------------------------------------------------


def test_in_era_zero_fill_never_fabricates_a_pre_era_zero(panel):
    """The whole point of scope=in_era: before collection began, NaN means unknown."""
    early = panel[panel.REPORTING_PERIOD < CHANGE]
    assert early.event_flag.isna().all()


def test_in_era_zero_fill_applies_once_collection_starts(panel):
    # Restricted to a bank with no reporting gaps: event_flag is a YTD column, so the
    # gap policy legitimately NaNs it for the bank that skips a quarter and the one that
    # enters mid-year. Those NaNs come from quarterization, not from the zero-fill.
    clean = panel[(panel.REPORTING_PERIOD >= CHANGE) & (panel.RSSD_ID == 1)]
    assert clean.event_flag.notna().all()


# --- form type ---------------------------------------------------------------------


def test_form_type_resolved_in_both_eras(panel):
    """Regression: omitting the CDR filing-type column from the read silently produced a
    null form_type for every post-2011 row."""
    assert panel.form_type.notna().all()
    early = panel[panel.REPORTING_PERIOD < CHANGE]
    modern = panel[panel.REPORTING_PERIOD >= CHANGE]
    assert set(early.form_type.unique()) == {31, 41}
    assert set(modern.form_type.unique()) == {31, 41, 51}


def test_form_type_source_records_which_branch(synth_panel):
    header = read_header(root=synth_panel)
    early = header[header.REPORTING_PERIOD < CHANGE]
    modern = header[header.REPORTING_PERIOD >= CHANGE]
    assert set(early.form_type_source) == {"call8786_inferred"}
    assert set(modern.form_type_source) == {"cdr_field"}


def test_short_form_semiannual_pattern_is_preserved_not_filled(panel):
    """A NaN in Q1/Q3 for a 051 filer means 'not collected'. The builder must not
    invent a value; distinguishing this is the validators' job."""
    modern = panel[(panel.REPORTING_PERIOD >= CHANGE) & (panel.form_type == 51)]
    by_quarter = modern.groupby(modern.REPORTING_PERIOD.dt.quarter).semiannual_item.apply(
        lambda s: s.notna().mean()
    )
    assert by_quarter.loc[1] == 0.0 and by_quarter.loc[3] == 0.0
    assert by_quarter.loc[2] == 1.0 and by_quarter.loc[4] == 1.0


# --- quarterization in the build ---------------------------------------------------


def test_ytd_columns_are_quarterized(panel):
    """Source accumulates 100/quarter, so every quarterized flow is ~100."""
    clean = panel[(panel.RSSD_ID == 1)]
    assert clean.int_inc_total.dropna().between(100, 102).all()


def test_stock_columns_are_not_quarterized(panel):
    """Balance-sheet items are point-in-time and must survive untouched."""
    assert (panel.assets_total > 1000).all()


# --- the builder does not clean ----------------------------------------------------


def test_unit_errors_are_left_in_place(panel):
    """Cleaning is opt-in and downstream; the panel on disk is what the configs produced."""
    bank9 = panel[(panel.RSSD_ID == 9) & (panel.REPORTING_PERIOD < CHANGE)]
    assert (bank9.deposit_accounts > 100_000).all()


# --- reader guards -----------------------------------------------------------------


def test_columns_argument_is_required(synth_panel):
    with pytest.raises(ValueError, match="required"):
        read_panel(root=synth_panel, verify=False)


def test_unknown_column_raises(synth_panel):
    with pytest.raises(KeyError):
        read_panel(columns=["not_a_variable"], root=synth_panel, verify=False)


def test_memory_guard_trips_and_force_overrides(synth_panel):
    with pytest.raises(PanelTooLargeError):
        read_panel(columns=["assets_total"], root=synth_panel, max_memory_gb=1e-12, verify=False)
    df = read_panel(
        columns=["assets_total"], root=synth_panel, max_memory_gb=1e-12, force=True, verify=False
    )
    assert len(df) > 0


def test_form_type_filter_selects_banks(synth_panel):
    df = read_panel(columns=["assets_total"], form_types=(51,), root=synth_panel, verify=False)
    assert set(df.form_type.unique()) == {51}


def test_date_window_filter(synth_panel):
    df = read_panel(columns=["assets_total"], start="2011Q1", end="2011Q4", root=synth_panel, verify=False)
    assert df.REPORTING_PERIOD.dt.year.unique().tolist() == [2011]


def test_float32_downcast_is_available(synth_panel):
    df = read_panel(columns=["assets_total"], root=synth_panel, dtype="float32", verify=False)
    assert df.assets_total.dtype == np.dtype("float32")


# --- dictionary ---------------------------------------------------------------------


def test_dictionary_carries_mdrm_labels(synth_panel):
    from bankpanel.io.reader import dictionary

    d = dictionary(synth_panel)
    row = d[d.variable_name == "assets_total"].iloc[0]
    assert row.description == "TOTAL ASSETS"
    assert row.mdrm_code == "RCFD2170"
    assert row.variable_type == "base"


def test_dictionary_covers_every_panel_column(synth_panel):
    from bankpanel.io.reader import dictionary

    d = dictionary(synth_panel)
    names = pq.ParquetFile(
        next((synth_panel / "panel").glob("year=*/part-0.parquet"))
    ).schema_arrow.names
    documented = set(d.variable_name)
    undocumented = [
        n for n in names if n not in documented
        and n not in {"RSSD_ID", "REPORTING_PERIOD", "form_type", "year"}
    ]
    assert not undocumented


# --- boolean-valued items ------------------------------------------------------------


def test_boolean_text_is_coerced_to_one_and_zero():
    """The Call Report publishes genuine yes/no items as "true"/"false" text.

    A numeric-only panel would silently drop them: to_numeric turns the whole column to
    NaN, and a parity check comparing two all-NaN columns then calls them identical.
    That is how a missing column hid here until an all-NaN audit found it.
    """
    from bankpanel.build.quarter import to_numeric

    series = pd.Series(["true", "false", "FALSE", "True", None, "yes", "no"])
    assert to_numeric(series).tolist()[:4] == [1.0, 0.0, 0.0, 1.0]
    assert np.isnan(to_numeric(series).tolist()[4])
    assert to_numeric(series).tolist()[5:] == [1.0, 0.0]


def test_mixed_boolean_and_numeric_keeps_the_numbers():
    from bankpanel.build.quarter import to_numeric

    out = to_numeric(pd.Series(["true", "1234", "false", "0"]))
    assert out.tolist() == [1.0, 1234.0, 0.0, 0.0]


def test_non_boolean_text_still_becomes_nan():
    """Confidential items are published as the literal string "CONF"."""
    from bankpanel.build.quarter import to_numeric

    assert to_numeric(pd.Series(["CONF", "CONF"])).isna().all()
