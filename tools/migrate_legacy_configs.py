"""One-shot import of the legacy bec_migration configs into bankpanel format.

Deliberately conservative: variable names and formulas are copied **verbatim**. The only
things added are the metadata the new format requires (schedule, flow_type) and the
zero-fill rules that were previously hardcoded in Python.

Names are not modernized here even though several are ugly (a quarterized flow still
called ``ytd_int_inc``). Renaming and proving equivalence at the same time would mean any
parity failure has two candidate causes. Prove parity first; rename after.

One transform is unavoidable. The legacy configs use a self-overwriting idiom, where a
derived variable carries the same name as a base variable and references itself::

    base     RCFD2011 -> ln_othcons_2
    derived  ln_othcons_2 = ln_othcons_2.fillna(ln_othcons_2a + ln_othcons_2b)

That works only because the legacy engine evaluated formulas in file order and assigned
each result back over the column. Under a dependency graph it is ambiguous, and it breaks
the invariant that one name has one definition. We resolve it by renaming the *base*
variable to ``<name>_src`` and pointing the formula at the new name; the output column
keeps its original name, so the panel is unchanged.

Checked before relying on this: no earlier formula reads the pre-redefinition value of
any affected variable, so the rewrite is exactly semantics-preserving.

Usage:
    python tools/migrate_legacy_configs.py --legacy-dir ... --out-dir configs_legacy
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
from pathlib import Path

import pandas as pd

LEGACY_FILES = ("assets.csv", "liabilities.csv", "income_statement.csv")

#: Schedule RI-A structural-event items. The legacy pipeline special-cased these in
#: ``prepare_structflags``: within each item's reporting era a blank means "no event" and
#: is filled with zero, but before the era began a blank means "not collected" and must
#: stay NaN. That behaviour is now expressed as a [ZERO_FILL] rule.
STRUCTFLAG_CODES = {
    "RIAD4356": "business combinations",
    "RIADB507": "restatements",
    "RIADFT28": "discontinued operations",
}

#: Gross additive income items, which cannot be negative over a quarter. Net items --
#: gains on sales, trading revenue, taxes -- legitimately can be, and stay "any".
#:
#: Matched as a PREFIX on the quarterized name, never as a substring, because
#: "nonint_inc" CONTAINS "int_inc": non-interest income subcategories are net items and
#: would otherwise be marked non-negative, which floods the audit with false positives.
#: (Measured: substring matching flagged 16.4% of bank-quarters, 95.7% "unexplained".)
NONNEG_PREFIXES = ("qint_inc", "qint_exp", "qnonint_exp", "qfiduc_inc")


def _quarterized_name(name: str) -> str:
    """The name the legacy pipeline gave this column after quarterization."""
    if name.startswith("ytd_"):
        return "q" + name[4:]
    if name.startswith("ytd"):
        return "q" + name[3:]
    return name


def _sections(text: str) -> dict[str, list[list[str]]]:
    """Split a legacy sectioned CSV into raw rows per section."""
    out: dict[str, list[list[str]]] = {}
    current: str | None = None
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        head = row[0].strip()
        if head.startswith("[") and head.endswith("]"):
            current = head[1:-1].upper()
            out[current] = []
            continue
        if current is None or head.lstrip('"').lstrip().startswith("#"):
            continue
        if not any(c.strip() for c in row):
            continue
        out[current].append(row)
    return out


def _records(rows: list[list[str]]) -> list[dict[str, str]]:
    if not rows:
        return []
    header = [c.strip().lower() for c in rows[0]]
    out = []
    for row in rows[1:]:
        padded = list(row) + [""] * (len(header) - len(row))
        out.append({k: v.strip() for k, v in zip(header, padded, strict=False)})
    return out


def _rename_identifier(formula: str, old: str, new: str) -> str:
    """Replace whole-word occurrences of ``old``.

    Word boundaries are essential: without them, renaming ``ln_othcons_2`` would also
    rewrite ``ln_othcons_2a`` and ``ln_othcons_2b``, which are different variables.
    """
    return re.sub(rf"\b{re.escape(old)}\b", new, formula)


def _resolve_self_overwrites(
    base: list[dict[str, str]], derived: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
    """Rename self-overwriting base variables and rewrite the formulas that read them."""
    base_names = {r.get("variable_name", "") for r in base}
    renames = {
        r["variable_name"]: f"{r['variable_name']}_src"
        for r in derived
        if r.get("variable_name") in base_names
        and re.search(rf"\b{re.escape(r.get('variable_name', ''))}\b", r.get("formula", ""))
    }
    for old, new in renames.items():
        if new in base_names:
            raise SystemExit(f"cannot rename {old} -> {new}: name already in use")

    new_base = [
        {**r, "variable_name": renames.get(r.get("variable_name", ""), r.get("variable_name", ""))}
        for r in base
    ]
    new_derived = []
    for r in derived:
        name = r.get("variable_name", "")
        formula = r.get("formula", "")
        if name in renames:
            formula = _rename_identifier(formula, name, renames[name])
        new_derived.append({**r, "formula": formula})
    return new_base, new_derived, renames


def _schedule_for(code: str, schedule_map: dict[str, str]) -> str:
    if code in schedule_map:
        return schedule_map[code]
    # Fall back on the prefix: RIAD is the income statement, everything else is a
    # balance-sheet item. Coarse, but schedule is descriptive metadata, so a wrong guess
    # costs grouping quality rather than correctness.
    return "RI" if code.startswith("RIAD") else "RC"


def _flow_type(name: str) -> str:
    return "ytd" if name.lower().startswith("ytd") else "stock"


def _cell(value: str) -> str:
    value = (value or "").replace("\n", " ").strip()
    if any(ch in value for ch in ',"'):
        return '"' + value.replace('"', '""') + '"'
    return value


def migrate(legacy_dir: Path, out_dir: Path, schedule_map_path: Path) -> None:
    schedule_map: dict[str, str] = {}
    if schedule_map_path.exists():
        smap = pd.read_csv(schedule_map_path)
        schedule_map = dict(zip(smap.mdrm_code, smap.schedule, strict=True))

    out_dir.mkdir(parents=True, exist_ok=True)
    all_names: dict[str, str] = {}
    collisions: list[str] = []
    summary = []
    total_renames = 0

    for fname in LEGACY_FILES:
        secs = _sections((legacy_dir / fname).read_text(encoding="utf-8"))
        base, derived, renames = _resolve_self_overwrites(
            _records(secs.get("BASE_VARIABLES", [])),
            _records(secs.get("DERIVED_VARIABLES", [])),
        )
        zero = _records(secs.get("ZERO_FILL", []))
        total_renames += len(renames)

        lines: list[str] = [
            f"# Migrated from bec_migration/data_preparation/config/{fname}.",
            "# Formulas and output column names are unchanged. Added: schedule, flow_type,",
            "# sign, and the zero-fill rules that were previously hardcoded in Python.",
        ]
        if renames:
            lines += [
                "#",
                "# Self-overwriting base variables renamed to <name>_src so that one name has",
                "# one definition; the derived column of the original name is unchanged:",
                *[f"#   {old} -> {new}" for old, new in sorted(renames.items())],
            ]
        lines += [
            "",
            "[META]",
            "key,value",
            f"panel_name,{fname.replace('.csv', '')}",
            "profile,ffiec_call",
            f"source,bec_migration/{fname}",
            "",
            "[BASE_VARIABLES]",
            "mdrm_code,variable_name,schedule,flow_type,form_scope,era_start,era_end,sign,notes",
        ]

        n_base = 0
        structflags: list[tuple[str, str]] = []
        for rec in base:
            code = (rec.get("mdrm_code") or "").upper()
            name = rec.get("variable_name") or ""
            if not code or not name:
                continue
            if name in all_names:
                collisions.append(f"{name!r}: {all_names[name]} and {fname}")
                continue
            all_names[name] = fname
            flow = _flow_type(name)
            sign = (
                "nonneg"
                if flow == "ytd" and _quarterized_name(name).startswith(NONNEG_PREFIXES)
                else ""
            )
            lines.append(",".join([
                code, name, _schedule_for(code, schedule_map), flow, "all", "", "", sign, "",
            ]))
            n_base += 1
            if code in STRUCTFLAG_CODES:
                structflags.append((name, code))

        lines += [
            "",
            "[DERIVED_VARIABLES]",
            "variable_name,schedule,flow_type,description,formula,unit,sign",
        ]
        n_derived = 0
        for rec in derived:
            name = rec.get("variable_name") or ""
            formula = rec.get("formula") or ""
            if not name or not formula:
                continue
            if name in all_names:
                collisions.append(f"{name!r}: {all_names[name]} and {fname}")
                continue
            all_names[name] = fname
            lines.append(",".join([
                name, "CROSS", _flow_type(name), _cell(rec.get("description", "")),
                _cell(formula), _cell(rec.get("unit", "")), "",
            ]))
            n_derived += 1

        zero_lines = [
            ",".join([rec["column"], "always", _cell(rec.get("reason", "migrated from legacy config"))])
            for rec in zero
            if rec.get("column")
        ]
        zero_lines += [
            ",".join([name, "in_era", _cell(
                f"Schedule RI-A {STRUCTFLAG_CODES[code]}: a blank means no event once "
                f"collection began, but means not collected before it did."
            )])
            for name, code in structflags
        ]
        if zero_lines:
            lines += ["", "[ZERO_FILL]", "column,scope,reason", *zero_lines]

        (out_dir / fname).write_text("\n".join(lines) + "\n", encoding="utf-8")
        summary.append((fname, n_base, n_derived, len(zero_lines), len(renames)))

    print(f"{'config':<24}{'base':>6}{'derived':>9}{'zero_fill':>11}{'renamed':>9}")
    for row in summary:
        print(f"{row[0]:<24}{row[1]:>6}{row[2]:>9}{row[3]:>11}{row[4]:>9}")
    print(f"{'TOTAL':<24}{sum(r[1] for r in summary):>6}{sum(r[2] for r in summary):>9}"
          f"{sum(r[3] for r in summary):>11}{total_renames:>9}")

    if collisions:
        print(f"\n!! {len(collisions)} unresolved name collision(s); the later one was dropped:")
        for c in collisions:
            print(f"   {c}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--legacy-dir",
        default=os.environ.get("BANKPANEL_LEGACY_CONFIGS", "../bec_migration/data_preparation/config"),
    )
    ap.add_argument("--out-dir", default="configs")
    ap.add_argument("--schedule-map", default="reference_data/mdrm_to_schedule.csv")
    args = ap.parse_args()
    migrate(Path(args.legacy_dir), Path(args.out_dir), Path(args.schedule_map))
