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
            "ytd_int_inc_total", "q_int_inc_total", "ytd_event_flag", "deposit_accounts", "assets_less_loans",
            "late_or_assets", "assets_031_only", "assets_rescaled_2010",
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
    assert early.ytd_event_flag.isna().all()


def test_in_era_zero_fill_applies_once_collection_starts(panel):
    # Restricted to a bank with no reporting gaps: ytd_event_flag is a YTD column, so the
    # gap policy legitimately NaNs it for the bank that skips a quarter and the one that
    # enters mid-year. Those NaNs come from quarterization, not from the zero-fill.
    clean = panel[(panel.REPORTING_PERIOD >= CHANGE) & (panel.RSSD_ID == 1)]
    assert clean.ytd_event_flag.notna().all()


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
    """Source accumulates 100/quarter: the flow companion is ~100 and the as-filed
    year-to-date column is kept, so its Q4 value is ~400."""
    clean = panel[(panel.RSSD_ID == 1)]
    assert clean.q_int_inc_total.dropna().between(100, 102).all()
    q4 = clean[pd.DatetimeIndex(clean.REPORTING_PERIOD).quarter == 4]
    assert q4.ytd_int_inc_total.dropna().between(400, 408).all()


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


def test_percent_strings_become_numbers_in_percent_units():
    """The CDR bulk files write the reported capital ratios as "9.1154%" from 2015Q1. The
    number written is kept (percent units); rescaling to a fraction is the config's job."""
    from bankpanel.build.quarter import to_numeric

    out = to_numeric(pd.Series(["9.1154%", " 12.5% ", "CONF", None, "0.0948"]))
    assert out.tolist()[:2] == [9.1154, 12.5]
    assert pd.isna(out.iloc[2]) and pd.isna(out.iloc[3])
    assert out.iloc[4] == 0.0948


# --- form type is readable inside a formula ------------------------------------------------


def test_formula_can_read_form_type(panel):
    """A category reported separately on one form and inside a broader line on another
    can only be counted once if the formula knows which form the row came from."""
    is_031 = panel["form_type"] == 31
    assert is_031.any() and (~is_031).any(), "fixture must carry both forms"
    on = panel.loc[is_031, "assets_031_only"]
    off = panel.loc[~is_031, "assets_031_only"]
    assert on.notna().all() and (on == panel.loc[is_031, "assets_total"]).all()
    assert off.isna().all()


def test_formula_can_read_the_quarter(panel):
    """yyyyq (the reporting quarter as YYYYQ) lets a formula apply a rule to a span of
    quarters, e.g. a unit change at a source boundary."""
    q = panel["REPORTING_PERIOD"].dt.year * 10 + panel["REPORTING_PERIOD"].dt.quarter
    inside = (q >= 20102) & (q <= 20103)
    assert inside.any() and (~inside).any(), "fixture must span the rule's quarters"
    a, r = panel["assets_total"], panel["assets_rescaled_2010"]
    assert (r[inside] == a[inside] / 100).all()
    assert (r[~inside] == a[~inside]).all()


# --- form type before 2011 ----------------------------------------------------------


def test_level_one_without_a_foreign_office_schedule_is_not_a_031_filer():
    """1985-1988: CALL8786 == 1 also marks small domestic filers. A true 031 filer always
    carries the foreign-office schedule (RCFN2200)."""
    from bankpanel.reference.formtype import resolve_form_type

    raw = pd.DataFrame({"CALL8786": [1.0, 1.0, 2.0, np.nan], "RCFN2200": [500.0, np.nan, np.nan, np.nan]})
    out = resolve_form_type(raw)
    assert out.form_type.tolist()[:3] == [31, 41, 41]
    assert pd.isna(out.form_type.iloc[3])
    # Without the column at all (a synthetic or trimmed file) the level code decides.
    assert resolve_form_type(raw[["CALL8786"]]).form_type.tolist()[:3] == [31, 31, 41]


# --- zero-fill that needs the bank's year --------------------------------------------


def test_blank_is_zero_unless_the_bank_reports_that_year_or_the_form_never_does():
    from bankpanel.build.zerofill import zero_fill_unless_reported

    q = [pd.Timestamp(d) for d in ("2010-03-31", "2010-06-30", "2010-09-30", "2010-12-31")]
    rows = []
    for bank, form, vals in [
        (1, 41, [np.nan] * 4),                      # has none: every blank is a zero
        (2, 41, [np.nan, np.nan, np.nan, 2000.0]),  # annual filer: Q1-Q3 stay blank
        (3, 41, [5.0, 6.0, np.nan, 7.0]),           # reports it: a blank is unknown
        (6, 41, [1.0, 1.0, 1.0, 1.0]),              # a quarterly filer: the 041 collects it every quarter
        (4, 51, [np.nan] * 4),                      # 051 collects it at Q4 only ...
        (5, 51, [np.nan, np.nan, np.nan, 9.0]),     # ... so bank 4 is zero at Q4, blank before
    ]:
        rows += [{"RSSD_ID": bank, "REPORTING_PERIOD": d, "form_type": form, "x": v} for d, v in zip(q, vals, strict=True)]
    df = pd.DataFrame(rows)
    n = zero_fill_unless_reported(df, "x", id_col="RSSD_ID", date_col="REPORTING_PERIOD",
                                  era_start=pd.Timestamp("2010-06-30"))
    got = {b: g.x.tolist() for b, g in df.groupby("RSSD_ID")}
    assert np.isnan(got[1][0]) and got[1][1:] == [0.0, 0.0, 0.0]      # before the era: untouched
    assert all(np.isnan(v) for v in got[2][:3]) and got[2][3] == 2000.0
    assert np.isnan(got[3][2])
    assert all(np.isnan(v) for v in got[4][:3]) and got[4][3] == 0.0
    assert all(np.isnan(v) for v in got[5][:3])
    assert n == 4


def test_zero_fill_respects_the_forms_an_item_is_collected_on():
    from bankpanel.build.zerofill import zero_fill_unless_reported

    d = pd.Timestamp("2010-12-31")
    df = pd.DataFrame({"RSSD_ID": [1, 2, 3, 4], "REPORTING_PERIOD": d, "form_type": [41, 41, 51, 51],
                       "x": [3.0, np.nan, 8.0, np.nan]})
    zero_fill_unless_reported(df, "x", id_col="RSSD_ID", date_col="REPORTING_PERIOD",
                              era_start=pd.Timestamp("2005-09-30"), forms=frozenset({31, 41}))
    assert df.x.tolist()[:3] == [3.0, 0.0, 8.0] and np.isnan(df.x.iloc[3])


def test_fry9c_size_tier():
    from bankpanel.profiles import resolve_size_tier

    out = resolve_size_tier(pd.DataFrame({"BHCK2170": [4_999_999.0, 5_000_000.0, np.nan]}))
    assert out.form_type.tolist()[:2] == [1, 2] and pd.isna(out.form_type.iloc[2])
    assert out.form_type_source.tolist() == ["size_tier_5bn", "size_tier_5bn", "unknown"]
