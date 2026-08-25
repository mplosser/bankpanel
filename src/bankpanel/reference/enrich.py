"""Draft config rows from measured data, so schedule coverage is review rather than typing.

Authoring a schedule by hand means looking up every MDRM code, guessing when it starts and
stops, and discovering the era chains one surprising result at a time. Most of that is
mechanical and can be measured:

* **when an item actually exists** in this source -- first and last quarter carrying data;
* **which forms report it** -- so ``form_scope`` is observed, not assumed;
* **which codes are plausibly the same concept** -- MDRM item names group them, and
  non-overlapping date spans are the signature of a definition change.

What cannot be measured is whether a proposed chain is economically the same series. That
stays a human decision, which is why this module *proposes* and never writes a config
itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ..build.source import QuarterFile, resolve_codes, schema_columns
from ..profiles import ReportProfile
from ..reference.formtype import resolve_form_type

#: A code must reach this share of banks in at least one quarter to be worth proposing.
#: Below it, the item is either genuinely rare or a memo line few banks complete.
DENSE_THRESHOLD = 0.50

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

#: Abbreviations applied to MDRM item names when suggesting a variable name. Keeps the
#: generated slugs readable; the reviewer renames anything that matters.
_ABBREV = {
    "commercial": "com", "industrial": "ind", "residential": "res", "properties": "prop",
    "property": "prop", "institutions": "insts", "institution": "inst",
    "depository": "dep", "deposits": "dep", "deposit": "dep", "accounts": "accts",
    "account": "acct", "including": "incl", "excluding": "excl", "and": "",
    "the": "", "of": "", "to": "", "in": "", "for": "", "with": "", "or": "",
    "total": "tot", "other": "oth", "loans": "ln", "loan": "ln", "secured": "sec",
    "family": "fam", "development": "dev", "construction": "constr", "estate": "est",
    "leases": "lease", "financing": "fin", "receivables": "recv", "domestic": "dom",
    "foreign": "fgn", "offices": "off", "office": "off", "government": "govt",
    "obligations": "oblig", "securities": "sec", "agricultural": "agr",
    "individuals": "indiv", "households": "hh", "personal": "pers", "expenditures": "exp",
}


def _words(text: str, max_words: int) -> list[str]:
    kept: list[str] = []
    for word in _SLUG_STRIP.sub(" ", text.lower()).split():
        short = _ABBREV.get(word, word)
        if short:
            kept.append(short)
        if len(kept) >= max_words:
            break
    return kept


def slugify(item_name: str, max_words: int = 6) -> str:
    """Suggest a variable name from an MDRM item name.

    Two details matter for readability. MDRM writes sub-items as
    ``PARENT CONCEPT: THE DISTINGUISHING PART``, and the part after the colon is what
    tells two siblings apart -- dropping it yields ``all_oth_ln_sec_by_1`` and
    ``all_oth_ln_sec_by_1_2`` for first and junior liens. And truncation is done at word
    boundaries, because cutting mid-word produces names like ``..._accoun``.
    """
    text = str(item_name)
    head, _, tail = text.partition(":")
    if tail.strip():
        parts = _words(head, 4) + _words(tail, 3)
    else:
        parts = _words(head, max_words)

    slug = ""
    for part in parts:
        candidate = f"{slug}_{part}" if slug else part
        if len(candidate) > 44:
            break
        slug = candidate
    slug = slug or "item"
    if slug[0].isdigit():
        slug = "x" + slug
    return slug.rstrip("_")


def measure_codes(
    quarters: list[QuarterFile],
    codes: list[str],
    profile: ReportProfile,
    *,
    progress: bool = True,
) -> pd.DataFrame:
    """Per code: when it carries data, how densely, and for which forms.

    Reads only the requested columns, via projection.
    """
    wanted = {c.upper() for c in codes}
    records: list[dict] = []

    for i, qf in enumerate(sorted(quarters, key=lambda q: (q.year, q.quarter))):
        if progress and i % 20 == 0:
            print(f"  scanning {qf.label} ({i + 1}/{len(quarters)})")
        available = set(schema_columns(qf.path))
        resolved = resolve_codes(sorted(wanted & available), available, profile)
        if not resolved:
            continue
        physical = sorted(set(resolved.values()))
        extra = [c for c in ("FINANCIAL INSTITUTION FILING TYPE", "CALL8786") if c in available]
        table = pq.read_table(qf.path, columns=physical + extra)
        df = table.to_pandas()
        df.columns = [str(c).upper() for c in df.columns]
        forms = resolve_form_type(df)["form_type"]
        n = len(df)
        if not n:
            continue
        for code, column in resolved.items():
            raw_values = df[column]
            # Coverage must be measured on NUMERIC content, not on non-nullness. Some
            # Call Report items are collected but not published: every cell holds the
            # literal string "CONF". Those columns look perfectly dense and would be
            # proposed as prime candidates, then build to an all-NaN column.
            values = pd.to_numeric(raw_values, errors="coerce")
            filled = values.notna()
            populated = raw_values.notna() & (raw_values.astype(str).str.strip() != "")
            record = {
                "mdrm_code": code,
                "quarter": qf.period,
                "coverage": float(filled.mean()),
                "n_reported": int(filled.sum()),
                "n_text": int((populated & ~filled).sum()),
                "n_banks": n,
            }
            for form_type in (31, 41, 51):
                in_form = forms == form_type
                record[f"cov_{form_type}"] = (
                    float(filled[in_form].mean()) if in_form.any() else float("nan")
                )
            records.append(record)

    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


def summarize(measured: pd.DataFrame) -> pd.DataFrame:
    """Collapse the per-quarter scan into one row per code."""
    if measured.empty:
        return measured
    rows = []
    for code, block in measured.groupby("mdrm_code"):
        active = block[block.coverage >= 0.005]
        text_only = int(block.get("n_text", pd.Series(dtype=int)).sum() or 0)
        if active.empty:
            rows.append({
                "mdrm_code": code, "first_quarter": pd.NaT, "last_quarter": pd.NaT,
                "peak_coverage": float(block.coverage.max()), "n_quarters": 0,
                "confidential": text_only > 0,
            })
            continue
        rows.append({
            "mdrm_code": code,
            "first_quarter": active.quarter.min(),
            "last_quarter": active.quarter.max(),
            "peak_coverage": float(active.coverage.max()),
            "n_quarters": int(len(active)),
            "confidential": text_only > 0,
            "cov_31": float(active.cov_31.mean()),
            "cov_41": float(active.cov_41.mean()),
            "cov_51": float(active.cov_51.mean()),
        })
    return pd.DataFrame(rows).sort_values("mdrm_code").reset_index(drop=True)


def infer_form_scope(row: pd.Series, floor: float = 0.05) -> str:
    """Which forms actually report this item, from measured coverage."""
    present = [
        form for form in (31, 41, 51)
        if not pd.isna(row.get(f"cov_{form}")) and row.get(f"cov_{form}", 0) >= floor
    ]
    if not present or len(present) == 3:
        return "all"
    if present == [31, 41]:
        return "031+041"
    if present == [41, 51]:
        return "041+051"
    if len(present) == 1:
        return f"0{present[0]}"
    return "all"


def propose_rows(
    summary: pd.DataFrame,
    schedule: str,
    mdrm: pd.DataFrame,
    *,
    existing_names: set[str],
    dense_threshold: float = DENSE_THRESHOLD,
    panel_end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Build reviewable ``[BASE_VARIABLES]`` rows for uncovered codes."""
    if summary.empty:
        return summary
    dense = summary[summary.peak_coverage >= dense_threshold].copy()
    if dense.empty:
        return dense

    names = pd.Series(dense.mdrm_code).map(
        dict(zip(mdrm.mdrm_code, mdrm.item_name, strict=True))
    )
    used = set(existing_names)
    proposed = []
    for code, item_name in zip(dense.mdrm_code, names.fillna(""), strict=True):
        base = slugify(item_name) if item_name else code.lower()
        name, suffix = base, 2
        while name in used:
            name = f"{base}_{suffix}"
            suffix += 1
        used.add(name)
        proposed.append(name)

    dense["variable_name"] = proposed
    dense["item_name"] = names.fillna("").to_numpy()
    dense["schedule"] = schedule
    dense["flow_type"] = ["ytd" if c.startswith("RIAD") else "stock" for c in dense.mdrm_code]
    dense["form_scope"] = dense.apply(infer_form_scope, axis=1)
    # era_start is only meaningful when the item starts after the panel does; era_end only
    # when it stops before the panel ends. Otherwise leave blank -- an era bound that just
    # restates the panel's own extent is noise in the config.
    first_overall = summary.first_quarter.min()
    last_overall = panel_end or summary.last_quarter.max()
    dense["era_start"] = [
        q.strftime("%Y-%m-%d") if pd.notna(q) and q > first_overall else ""
        for q in dense.first_quarter
    ]
    dense["era_end"] = [
        q.strftime("%Y-%m-%d") if pd.notna(q) and q < last_overall else ""
        for q in dense.last_quarter
    ]
    return dense


def to_config_csv(proposed: pd.DataFrame) -> str:
    """Render proposals as pasteable [BASE_VARIABLES] lines."""
    lines = [
        "mdrm_code,variable_name,schedule,flow_type,form_scope,era_start,era_end,sign,notes"
    ]
    for _, row in proposed.iterrows():
        note = str(row.get("item_name", "")).replace(",", ";").replace('"', "")
        lines.append(
            ",".join([
                row.mdrm_code, row.variable_name, row.schedule, row.flow_type,
                row.form_scope, row.era_start, row.era_end, "", note,
            ])
        )
    return "\n".join(lines)


def fill_blanks(config_path: str | Path, summary: pd.DataFrame, mdrm: pd.DataFrame) -> str:
    """Return the config text with blank era/form_scope/notes filled from measurement.

    Only ever fills blanks. An existing value is a human decision and is never overwritten.
    """
    path = Path(config_path)
    text = path.read_text(encoding="utf-8")
    stats = summary.set_index("mdrm_code")
    names = dict(zip(mdrm.mdrm_code, mdrm.item_name, strict=True))
    first_overall, last_overall = summary.first_quarter.min(), summary.last_quarter.max()

    out_lines = []
    in_base = False
    header: list[str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_base = stripped.upper() == "[BASE_VARIABLES]"
            header = None
            out_lines.append(line)
            continue
        if not in_base or not stripped or stripped.lstrip('"').startswith("#"):
            out_lines.append(line)
            continue
        cells = line.split(",")
        if header is None:
            header = [c.strip().lower() for c in cells]
            out_lines.append(line)
            continue

        code = cells[0].strip().upper()
        if code not in stats.index:
            out_lines.append(line)
            continue
        row = stats.loc[code]
        cells = cells + [""] * (len(header) - len(cells))
        index = {name: i for i, name in enumerate(header)}

        fills = {"form_scope": infer_form_scope(row), "notes": str(names.get(code, "")).replace(",", ";")}
        if pd.notna(row.first_quarter) and row.first_quarter > first_overall:
            fills["era_start"] = row.first_quarter.strftime("%Y-%m-%d")
        if pd.notna(row.last_quarter) and row.last_quarter < last_overall:
            fills["era_end"] = row.last_quarter.strftime("%Y-%m-%d")

        for field, value in fills.items():
            i = index.get(field)
            # Only ever fill a blank: an existing value is a human decision.
            if i is not None and value and not cells[i].strip():
                cells[i] = value
        out_lines.append(",".join(cells))

    return "\n".join(out_lines) + "\n"
