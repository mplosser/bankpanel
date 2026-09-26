"""Build one quarter's slice of the panel.

Every operation here is **row-wise**, which is what makes the whole architecture work:
prefix aliasing, the RCFD/RCON coalesce, renaming, all derived formulas, and zero-filling
depend only on values within a row. So a quarter can be built in complete isolation, and
the 163 quarters can be built in parallel.

The two operations that are *not* row-wise are handled elsewhere: quarterization needs a
bank's other quarters in the same year (so it runs in the per-year worker, see
``build/year.py``), and era detection needs the whole panel (so it is hoisted into a
cheap pre-pass, see ``reference/eras.py``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import ConfigSet
from ..expr import evaluate
from ..profiles import ReportProfile
from .source import QuarterFile, read_quarter

#: Boolean-valued items arrive as text. The Call Report has genuine yes/no items --
#: ``RCFDK659`` (is this a custody bank) and ``RCONP752`` (does this bank offer consumer
#: deposit products) -- published as the strings "true"/"false", with inconsistent case.
#: A numeric-only panel would drop them entirely, so they are mapped to 1.0/0.0.
_BOOLEAN_TEXT = {
    "true": 1.0, "false": 0.0, "t": 1.0, "f": 0.0,
    "yes": 1.0, "no": 0.0, "y": 1.0, "n": 0.0,
}


def to_numeric(series: pd.Series) -> pd.Series:
    """Coerce a raw column to float, mapping boolean text before giving up on it."""
    if series.dtype == object or pd.api.types.is_string_dtype(series):
        lowered = series.astype("string").str.strip().str.lower()
        mapped = lowered.map(_BOOLEAN_TEXT)
        if mapped.notna().any():
            # Fall back to numeric parsing for any cell that was not boolean text, so a
            # mixed column does not lose its numeric values.
            return mapped.astype("float64").fillna(
                pd.to_numeric(series, errors="coerce")
            ).astype("float64")
    return pd.to_numeric(series, errors="coerce").astype("float64")


def _coalesce_sources(cs: ConfigSet, profile: ReportProfile) -> dict[str, tuple[str, str | None]]:
    """For each base variable, the ``(primary_code, fallback_code)`` to combine.

    The fallback is the same-suffix code under the profile's paired prefix. For the Call
    Report that is RCFD (consolidated) primary, RCON (domestic) fallback -- see
    :meth:`ConfigSet.mdrm_codes` for why the fallback must be read at all.
    """
    out: dict[str, tuple[str, str | None]] = {}
    for var in cs.base:
        code = var.mdrm_code
        fallback = None
        for primary_prefix, fallback_prefix in profile.coalesce_rules:
            if code.startswith(primary_prefix):
                fallback = fallback_prefix + code[len(primary_prefix):]
                break
        out[var.variable_name] = (code, fallback)
    return out


def build_quarter(
    qf: QuarterFile,
    cs: ConfigSet,
    profile: ReportProfile,
    *,
    era_starts: dict[str, pd.Timestamp] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(panel_slice, header_slice)`` for one quarter."""
    era_starts = era_starts or {}
    raw, resolved = read_quarter(
        qf, cs.mdrm_codes(profile.coalesce_rules), profile, extra_columns=profile.source_columns
    )
    index = raw.index
    n = len(raw)

    # --- base variables ------------------------------------------------------------
    sources = _coalesce_sources(cs, profile)
    columns: dict[str, pd.Series] = {}
    for name, (primary_code, fallback_code) in sources.items():
        primary_col = resolved.get(primary_code)
        fallback_col = resolved.get(fallback_code) if fallback_code else None

        if primary_col is not None and fallback_col is not None:
            series = raw[primary_col].combine_first(raw[fallback_col])
        elif primary_col is not None:
            series = raw[primary_col]
        elif fallback_col is not None:
            series = raw[fallback_col]
        else:
            # The code does not exist in this quarter at all. Materialize it as all-NaN
            # rather than omitting it: every partition must share one Arrow schema, era
            # pieces must still resolve inside formulas, and coverage denominators must
            # be computed against a real column.
            series = pd.Series(np.nan, index=index, dtype="float64")
        columns[name] = to_numeric(series)

    # --- form type, resolved before derivation so formulas can read it ---------------
    form = (
        profile.form_type_resolver(raw)
        if profile.form_type_resolver is not None
        else pd.DataFrame(index=index)
    )
    builtins: dict[str, pd.Series] = {}
    if "form_type" in form.columns:
        builtins["form_type"] = pd.Series(
            form["form_type"].to_numpy(dtype="float64", na_value=np.nan), index=index
        )
    else:
        builtins["form_type"] = pd.Series(np.nan, index=index, dtype="float64")

    # --- derived variables, in dependency order ------------------------------------
    # Values are accumulated in a plain dict and assembled into a DataFrame once.
    # Assigning several hundred columns one at a time fragments the block manager badly
    # enough that pandas warns about it, and the frame then has to be defragmented anyway.
    graph = cs.graph
    formulas = {d.variable_name: d for d in cs.derived}
    values: dict[str, pd.Series] = dict(columns)
    for name in graph.order:
        var = formulas[name]
        namespace = {dep: values[dep] for dep in graph.deps[name]}
        namespace.update(builtins)
        result = evaluate(var.formula, namespace, where=str(var.origin))
        if np.isscalar(result):
            result = pd.Series(result, index=index, dtype="float64")
        series = pd.Series(result, index=index)
        # Guard division by zero, which pandas yields as +/-inf rather than NaN.
        values[name] = series.replace([np.inf, -np.inf], np.nan).astype("float64")

    # Declaration order, not evaluation order: the schema must be stable under formula
    # edits (see ConfigSet.output_columns).
    panel = pd.DataFrame({name: values[name] for name in cs.output_columns()}, index=index)

    # --- zero-fill, always last -----------------------------------------------------
    # Runs after coalesce and after era-stitching so it can never mask a NaN that those
    # steps needed to see.
    for rule in cs.zero_fill:
        if rule.column not in panel.columns:
            continue
        if rule.scope == "always":
            panel[rule.column] = panel[rule.column].fillna(0.0)
            continue
        if rule.scope == "in_era_unless_reported":
            continue  # needs the bank's whole year: applied by the year build
        era_start = pd.Timestamp(rule.era_start) if rule.era_start else era_starts.get(rule.column)
        if era_start is None:
            raise KeyError(
                f"{rule.origin}: [ZERO_FILL] scope=in_era for {rule.column!r} needs an era "
                f"start. Either set era_start in the config or run 'bankpanel eras build'."
            )
        if qf.period >= era_start:
            panel[rule.column] = panel[rule.column].fillna(0.0)

    # --- keys and form type ----------------------------------------------------------
    keys = {
        profile.id_col: raw[profile.id_col].to_numpy(),
        profile.date_col: qf.period,
    }
    if "form_type" in form.columns:
        keys["form_type"] = form["form_type"].to_numpy()
    panel = pd.concat([pd.DataFrame(keys, index=index), panel], axis=1)

    # --- header slice ----------------------------------------------------------------
    header = pd.DataFrame(
        {profile.id_col: raw[profile.id_col].to_numpy(), profile.date_col: qf.period},
        index=index,
    )
    for col in profile.header_columns:
        if col in raw.columns:
            header[profile.header_renames.get(col, col.lower())] = raw[col].astype("string")
    for col in form.columns:
        header[col] = form[col].to_numpy()

    panel = panel.sort_values([profile.id_col]).reset_index(drop=True)
    header = header.sort_values([profile.id_col]).reset_index(drop=True)
    assert n == len(panel), "row count changed while building a quarter"
    return panel, header
