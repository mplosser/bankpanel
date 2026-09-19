"""Config parsing, linting, and the dependency graph."""

from __future__ import annotations

import pytest

from bankpanel.config import ConfigError, ConfigSet, parse_config_file

MINIMAL = """[BASE_VARIABLES]
mdrm_code,variable_name,schedule,flow_type
RCFD2170,assets_total,RC,stock
RCFD2948,liabilities_total,RC,stock

[DERIVED_VARIABLES]
variable_name,schedule,flow_type,description,formula
equity,CROSS,stock,Residual equity,assets_total - liabilities_total
"""


def test_parses_minimal(write_config):
    cfg = parse_config_file(write_config(MINIMAL) / "test.csv")
    assert [v.variable_name for v in cfg.base] == ["assets_total", "liabilities_total"]
    assert cfg.derived[0].formula == "assets_total - liabilities_total"


def test_tolerates_excel_trailing_commas(write_config):
    """Excel pads every row to the widest row; that padding is not content."""
    padded = "\n".join(line + ",,," for line in MINIMAL.splitlines())
    cfg = parse_config_file(write_config(padded) / "test.csv")
    assert len(cfg.base) == 2


def test_rejects_content_before_first_section(write_config):
    """The legacy parser silently absorbed a stray first line."""
    with pytest.raises(ConfigError, match="before the first section marker"):
        parse_config_file(write_config("stray_value,,,\n" + MINIMAL) / "test.csv")


def test_rejects_row_wider_than_header(write_config):
    text = MINIMAL.replace(
        "RCFD2170,assets_total,RC,stock", "RCFD2170,assets_total,RC,stock,extra"
    )
    with pytest.raises(ConfigError, match="fields but section"):
        parse_config_file(write_config(text) / "test.csv")


def test_rejects_bad_enum(write_config):
    text = MINIMAL.replace("RCFD2170,assets_total,RC,stock", "RCFD2170,assets_total,RC,flowtype")
    with pytest.raises(ConfigError, match="flow_type"):
        parse_config_file(write_config(text) / "test.csv")


def test_rejects_missing_header(write_config):
    text = "[BASE_VARIABLES]\nRCFD2170,assets_total,RC,stock\n\n[DERIVED_VARIABLES]\nx\n"
    with pytest.raises(ConfigError):
        parse_config_file(write_config(text) / "test.csv")


def test_zero_fill_requires_a_reason(write_config):
    text = MINIMAL + "\n[ZERO_FILL]\ncolumn,scope,reason\nassets_total,always,\n"
    with pytest.raises(ConfigError, match="no reason"):
        parse_config_file(write_config(text) / "test.csv")


def test_comment_lines_ignored_even_when_quoted(write_config):
    text = '# plain comment\n"# quoted, with a comma"\n' + MINIMAL
    assert len(parse_config_file(write_config(text) / "test.csv").base) == 2


# --- graph -------------------------------------------------------------------------


def test_unknown_identifier_is_an_error(write_config):
    """The legacy engine swallowed this and silently omitted the column."""
    text = MINIMAL.replace("assets_total - liabilities_total", "assets_total - typo_name")
    with pytest.raises(ConfigError, match="unknown variable"):
        _ = ConfigSet.load(write_config(text)).graph


def test_cycle_detected(write_config):
    text = MINIMAL + "a,CROSS,stock,A,b\nb,CROSS,stock,B,a\n"
    with pytest.raises(ConfigError, match="cycle"):
        _ = ConfigSet.load(write_config(text)).graph


def test_topological_order_ignores_file_order(write_config):
    """A derived variable may be declared before the one it depends on."""
    text = MINIMAL + (
        "final,CROSS,stock,Depends on mid,mid * 2\n"
        "mid,CROSS,stock,Depends on equity,equity + 1\n"
    )
    order = ConfigSet.load(write_config(text)).graph.order
    assert order.index("equity") < order.index("mid") < order.index("final")


def test_output_order_is_declaration_order(write_config):
    """Schema order must be stable under formula edits, so it is not the eval order."""
    text = MINIMAL + (
        "final,CROSS,stock,Depends on mid,mid * 2\n"
        "mid,CROSS,stock,Depends on equity,equity + 1\n"
    )
    cs = ConfigSet.load(write_config(text))
    assert cs.output_columns()[-3:] == ["equity", "final", "mid"]


def test_self_reference_rejected(write_config):
    text = MINIMAL + "loop,CROSS,stock,Self,loop + 1\n"
    with pytest.raises(ConfigError, match="references itself"):
        _ = ConfigSet.load(write_config(text)).graph


# --- lint --------------------------------------------------------------------------


def test_duplicate_name_across_configs_is_fatal(tmp_path):
    """All configs share one namespace; a collision would silently pick a winner."""
    (tmp_path / "a.csv").write_text(MINIMAL, encoding="utf-8")
    (tmp_path / "b.csv").write_text(
        MINIMAL.replace("RCFD2948,liabilities_total", "RCFD3210,liabilities_total")
        .replace("equity,CROSS", "equity2,CROSS"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="defined 2 times"):
        ConfigSet.load(tmp_path).lint()


def test_reserved_name_rejected(write_config):
    text = MINIMAL.replace("assets_total,RC,stock", "form_type,RC,stock").replace(
        "assets_total - liabilities_total", "form_type - liabilities_total"
    )
    with pytest.raises(ConfigError, match="reserved"):
        ConfigSet.load(write_config(text)).lint()


def test_zero_fill_unknown_column_rejected(write_config):
    text = MINIMAL + "\n[ZERO_FILL]\ncolumn,scope,reason\nnope,always,because\n"
    with pytest.raises(ConfigError, match="not a variable"):
        ConfigSet.load(write_config(text)).lint()


def test_bad_era_date_rejected(write_config):
    text = MINIMAL.replace(
        "mdrm_code,variable_name,schedule,flow_type",
        "mdrm_code,variable_name,schedule,flow_type,era_start",
    ).replace("RCFD2170,assets_total,RC,stock", "RCFD2170,assets_total,RC,stock,1997-13-01")
    with pytest.raises(ConfigError, match="ISO date"):
        ConfigSet.load(write_config(text)).lint()


def test_rcon_siblings_added_for_rcfd_codes(write_config):
    codes = ConfigSet.load(write_config(MINIMAL)).mdrm_codes()
    assert "RCON2170" in codes and "RCON2948" in codes


def test_ytd_on_balance_sheet_schedule_warns(write_config):
    text = MINIMAL.replace("RCFD2170,assets_total,RC,stock", "RCFD2170,assets_total,RC,ytd")
    issues = ConfigSet.load(write_config(text)).lint()
    assert any("year-to-date" in i.message.lower() for i in issues)


# --- [INTERMEDIATE]: built, used, then withheld ---------------------------------------

WITHHOLDING = MINIMAL + """
[INTERMEDIATE]
column,reason
liabilities_total,Only wanted as an input to equity
"""


def test_intermediate_column_is_built_but_not_published(write_config):
    """A withheld column stays in the namespace and leaves the output schema."""
    cs = ConfigSet.load(write_config(WITHHOLDING))
    cs.lint()
    assert "liabilities_total" not in cs.output_columns()
    assert "assets_total" in cs.output_columns()
    # Still a variable: the formula that consumes it must still resolve.
    assert cs.variable("liabilities_total").mdrm_code == "RCFD2948"
    assert "RCFD2948" in cs.mdrm_codes()


def test_intermediate_nothing_consumes_is_fatal(write_config):
    """Withholding an unconsumed column is not reduced scope, it is deleted data."""
    text = MINIMAL + """
[INTERMEDIATE]
column,reason
equity,Nobody needs it
"""
    with pytest.raises(ConfigError, match="no published column depends on it"):
        ConfigSet.load(write_config(text)).lint()


def test_intermediate_unknown_column_is_fatal(write_config):
    text = MINIMAL + """
[INTERMEDIATE]
column,reason
typo_here,Withhold it
"""
    with pytest.raises(ConfigError, match="which no config defines"):
        ConfigSet.load(write_config(text)).lint()


def test_intermediate_requires_a_reason(write_config):
    text = MINIMAL + """
[INTERMEDIATE]
column,reason
liabilities_total,
"""
    with pytest.raises(ConfigError, match="has no reason"):
        ConfigSet.load(write_config(text))


def test_zero_fill_on_withheld_column_warns(write_config):
    text = WITHHOLDING + """
[ZERO_FILL]
column,scope,reason
liabilities_total,always,Verified absent means zero
"""
    issues = ConfigSet.load(write_config(text)).lint()
    assert any("dropped before zero-fill runs" in str(i) for i in issues)


# --- builtins: readable, never bindable, never a dependency ----------------------------------


def test_form_type_is_readable_but_not_a_dependency(write_config):
    text = MINIMAL + "big_bank_assets,RC,stock,Assets on the 031 form,assets_total.where(form_type == 31)\n"
    cs = ConfigSet.load(write_config(text))
    cs.lint()
    assert cs.graph.deps["big_bank_assets"] == {"assets_total"}
    assert "form_type" not in cs.output_columns()


def test_form_type_cannot_be_bound(write_config):
    # Rename the base variable AND its reference, so the only fault is the reserved name.
    text = MINIMAL.replace("liabilities_total", "form_type")
    with pytest.raises(ConfigError, match="reserved"):
        ConfigSet.load(write_config(text)).lint()
