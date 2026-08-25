"""Parse a sectioned-CSV config into a :class:`Config`.

Deliberately strict. The legacy parser this replaces split the file on literal marker
strings and re-joined the surviving lines into ``pd.read_csv``, which meant a stray line
at the top of the file was silently absorbed, a missing header row produced a garbled
frame, and no error ever named a line number. Here every failure raises
:class:`ConfigError` with ``file:line``.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .model import (
    FLOW_TYPES,
    FORM_SCOPES,
    SCHEDULES,
    SIGNS,
    ZERO_FILL_SCOPES,
    BaseVar,
    Config,
    ConfigError,
    DerivedVar,
    Origin,
    ZeroFillRule,
)

# section -> (required columns, optional columns)
_SECTION_SPEC: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "META": (("key", "value"), ()),
    "BASE_VARIABLES": (
        ("mdrm_code", "variable_name", "schedule", "flow_type"),
        ("form_scope", "era_start", "era_end", "sign", "notes"),
    ),
    "DERIVED_VARIABLES": (
        ("variable_name", "schedule", "flow_type", "description", "formula"),
        ("unit", "sign"),
    ),
    "ZERO_FILL": (("column", "scope", "reason"), ("era_start",)),
}


def _strip_trailing_empty(row: list[str]) -> list[str]:
    """Drop trailing empty cells.

    Excel pads every row out to the widest row in the sheet, so a 2-column data line
    arrives as ``[RCFD2170, assets_total, '', '', '']``. That padding is an artifact of
    the editor, not content, and must not count toward column-count validation.
    """
    end = len(row)
    while end > 0 and not row[end - 1].strip():
        end -= 1
    return [c.strip() for c in row[:end]]


def _is_comment(row: list[str]) -> bool:
    if not row:
        return False
    # Strip a leading quote first: Excel writes a comment containing a comma as a quoted
    # field, so the raw cell can begin with a double-quote before the hash.
    first = row[0].lstrip('"').lstrip()
    return first.startswith("#")


def _section_marker(row: list[str]) -> str | None:
    if not row:
        return None
    cell = row[0].strip()
    if len(cell) > 2 and cell.startswith("[") and cell.endswith("]"):
        return cell[1:-1].strip().upper()
    return None


def _rows(path: Path) -> list[tuple[int, list[str]]]:
    out: list[tuple[int, list[str]]] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        for row in reader:
            out.append((reader.line_num, row))
    return out


class _SectionReader:
    """Accumulates the header row and data rows of one section."""

    def __init__(self, name: str, path: Path, start_line: int) -> None:
        self.name = name
        self.path = path
        self.start_line = start_line
        self.header: list[str] | None = None
        self.records: list[tuple[Origin, dict[str, str]]] = []

    def add(self, line: int, row: list[str]) -> None:
        row = _strip_trailing_empty(row)
        if not row:
            return
        origin = Origin(self.path, line)
        if self.header is None:
            self._set_header(origin, row)
            return
        header = self.header
        if len(row) > len(header):
            raise ConfigError(
                f"{origin}: row has {len(row)} fields but section [{self.name}] header "
                f"declares {len(header)} ({', '.join(header)}). "
                f"Extra: {row[len(header):]!r}"
            )
        # Short rows are tolerated (Excel omits trailing blanks); pad with empty strings.
        padded = row + [""] * (len(header) - len(row))
        self.records.append((origin, dict(zip(header, padded, strict=True))))

    def _set_header(self, origin: Origin, row: list[str]) -> None:
        try:
            required, optional = _SECTION_SPEC[self.name]
        except KeyError:
            known = ", ".join("[" + s + "]" for s in _SECTION_SPEC)
            raise ConfigError(
                f"{origin}: unknown section [{self.name}]. Known sections: {known}"
            ) from None
        header = [c.lower() for c in row]
        missing = [c for c in required if c not in header]
        if missing:
            raise ConfigError(
                f"{origin}: section [{self.name}] header is missing required column(s) "
                f"{missing}. Got: {header}"
            )
        unknown = [c for c in header if c not in required + optional]
        if unknown:
            raise ConfigError(
                f"{origin}: section [{self.name}] header has unknown column(s) {unknown}. "
                f"Allowed: {list(required + optional)}"
            )
        dupes = sorted({c for c in header if header.count(c) > 1})
        if dupes:
            raise ConfigError(
                f"{origin}: section [{self.name}] header repeats column(s) {dupes}"
            )
        self.header = header

    def finish(self) -> None:
        if self.header is None:
            raise ConfigError(
                f"{self.path.name}:{self.start_line}: section [{self.name}] has no header "
                f"row. The first non-comment line after the marker must name its columns."
            )


def _check_enum(origin: Origin, field: str, value: str, allowed: frozenset[str]) -> str:
    if value not in allowed:
        raise ConfigError(
            f"{origin}: {field}={value!r} is not valid. Allowed: {sorted(allowed)}"
        )
    return value


def _opt(rec: dict[str, str], key: str) -> str | None:
    value = rec.get(key, "").strip()
    return value or None


def parse_config_file(path: str | Path) -> Config:
    """Parse one config file. Raises :class:`ConfigError` on any malformation."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")

    sections: dict[str, _SectionReader] = {}
    current: _SectionReader | None = None

    for line, raw in _rows(path):
        if _is_comment(raw):
            continue
        marker = _section_marker(raw)
        if marker is not None:
            if marker in sections:
                raise ConfigError(f"{path.name}:{line}: section [{marker}] appears twice")
            current = _SectionReader(marker, path, line)
            sections[marker] = current
            continue
        if not _strip_trailing_empty(raw):
            continue
        if current is None:
            # The failure the legacy parser swallowed: a stray value sitting above the
            # first section marker was simply never seen.
            raise ConfigError(
                f"{path.name}:{line}: content before the first section marker: "
                f"{_strip_trailing_empty(raw)!r}. Every row must sit under a [SECTION]."
            )
        current.add(line, raw)

    for section in sections.values():
        section.finish()

    for required_section in ("BASE_VARIABLES", "DERIVED_VARIABLES"):
        if required_section not in sections:
            raise ConfigError(f"{path.name}: missing required section [{required_section}]")

    cfg = Config(path=path)

    if "META" in sections:
        for _origin, rec in sections["META"].records:
            cfg.meta[rec["key"]] = rec["value"]

    for origin, rec in sections["BASE_VARIABLES"].records:
        if not rec["mdrm_code"] or not rec["variable_name"]:
            raise ConfigError(
                f"{origin}: base variable needs both mdrm_code and variable_name"
            )
        cfg.base.append(
            BaseVar(
                mdrm_code=rec["mdrm_code"].upper(),
                variable_name=rec["variable_name"],
                schedule=_check_enum(origin, "schedule", rec["schedule"], SCHEDULES),
                flow_type=_check_enum(origin, "flow_type", rec["flow_type"], FLOW_TYPES),
                form_scope=_check_enum(
                    origin, "form_scope", rec.get("form_scope") or "all", FORM_SCOPES
                ),
                era_start=_opt(rec, "era_start"),
                era_end=_opt(rec, "era_end"),
                sign=_check_enum(origin, "sign", rec.get("sign") or "any", SIGNS),
                notes=rec.get("notes", ""),
                origin=origin,
            )
        )

    for origin, rec in sections["DERIVED_VARIABLES"].records:
        # description is checked by lint, not here: the parser validates structure, and
        # a missing description is a documentation gap rather than a malformed file. It
        # must not block importing an otherwise-valid legacy config.
        for req in ("variable_name", "formula"):
            if not rec[req]:
                raise ConfigError(f"{origin}: derived variable is missing {req!r}")
        cfg.derived.append(
            DerivedVar(
                variable_name=rec["variable_name"],
                schedule=_check_enum(origin, "schedule", rec["schedule"], SCHEDULES),
                flow_type=_check_enum(origin, "flow_type", rec["flow_type"], FLOW_TYPES),
                description=rec["description"],
                formula=rec["formula"],
                unit=rec.get("unit", ""),
                sign=_check_enum(origin, "sign", rec.get("sign") or "any", SIGNS),
                origin=origin,
            )
        )

    if "ZERO_FILL" in sections:
        for origin, rec in sections["ZERO_FILL"].records:
            if not rec["reason"]:
                raise ConfigError(
                    f"{origin}: [ZERO_FILL] entry for {rec['column']!r} has no reason. "
                    f"Zero-filling a measured value is a data-integrity decision and "
                    f"must be justified."
                )
            cfg.zero_fill.append(
                ZeroFillRule(
                    column=rec["column"],
                    scope=_check_enum(origin, "scope", rec["scope"], ZERO_FILL_SCOPES),
                    reason=rec["reason"],
                    era_start=_opt(rec, "era_start"),
                    origin=origin,
                )
            )

    return cfg
