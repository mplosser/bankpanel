"""Cross-config checks that gate the build.

Everything here runs before a single parquet file is opened. A build that would produce
a subtly wrong panel should fail in under a second, naming the file and line to fix.

The single most important check is duplicate ``variable_name``. Because all configs merge
into one panel namespace, two schedules that both define ``loans_total`` would silently
collide -- one would win, and which one depends on file iteration order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..expr import FormulaError, dependencies
from .graph import DependencyGraph
from .model import BUILTIN_COLUMNS, RESERVED_NAMES, Config, Origin


@dataclass(frozen=True)
class LintIssue:
    level: str  # "error" | "warning"
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.level.upper()}] {self.message}"


def _valid_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
        return True
    except ValueError:
        return False


def lint_configs(configs: list[Config], graph: DependencyGraph) -> list[LintIssue]:
    """Return every issue found. Callers decide whether warnings are fatal."""
    issues: list[LintIssue] = []

    # --- name uniqueness across the merged namespace -------------------------------
    owners: dict[str, list[tuple[str, Origin]]] = {}
    for cfg in configs:
        for var in cfg.base:
            owners.setdefault(var.variable_name, []).append(("base", var.origin))
        for var in cfg.derived:
            owners.setdefault(var.variable_name, []).append(("derived", var.origin))

    for name, places in sorted(owners.items()):
        if len(places) > 1:
            where = "; ".join(f"{kind} at {origin}" for kind, origin in places)
            issues.append(
                LintIssue(
                    "error",
                    f"variable_name {name!r} is defined {len(places)} times ({where}). "
                    f"All configs share one panel namespace, so names must be globally unique.",
                )
            )
        if not name.isidentifier():
            issues.append(
                LintIssue(
                    "error",
                    f"{places[0][1]}: variable_name {name!r} is not a valid Python "
                    f"identifier, so no formula could reference it.",
                )
            )
        if name in RESERVED_NAMES:
            issues.append(
                LintIssue(
                    "error",
                    f"{places[0][1]}: variable_name {name!r} is reserved by the builder.",
                )
            )

    # --- MDRM codes -----------------------------------------------------------------
    code_owners: dict[str, list[Origin]] = {}
    for cfg in configs:
        for var in cfg.base:
            code_owners.setdefault(var.mdrm_code, []).append(var.origin)
    for code, places in sorted(code_owners.items()):
        if len(places) > 1:
            where = "; ".join(str(o) for o in places)
            issues.append(
                LintIssue(
                    "warning",
                    f"MDRM code {code} is mapped by {len(places)} base variables ({where}). "
                    f"That is legal -- one code can feed two names -- but is often a copy-paste slip.",
                )
            )

    # --- dates ----------------------------------------------------------------------
    for cfg in configs:
        for var in cfg.base:
            for field_name, value in (("era_start", var.era_start), ("era_end", var.era_end)):
                if value and not _valid_date(value):
                    issues.append(
                        LintIssue(
                            "error",
                            f"{var.origin}: {field_name}={value!r} is not an ISO date (YYYY-MM-DD).",
                        )
                    )
            if var.era_start and var.era_end and _valid_date(var.era_start) and _valid_date(var.era_end):
                if date.fromisoformat(var.era_end) < date.fromisoformat(var.era_start):
                    issues.append(
                        LintIssue("error", f"{var.origin}: era_end precedes era_start.")
                    )

    # --- zero-fill ------------------------------------------------------------------
    known = graph.all_names
    for cfg in configs:
        for rule in cfg.zero_fill:
            if rule.column not in known:
                issues.append(
                    LintIssue(
                        "error",
                        f"{rule.origin}: [ZERO_FILL] names {rule.column!r}, which is not a "
                        f"variable in any config.",
                    )
                )
            if rule.era_start and not _valid_date(rule.era_start):
                issues.append(
                    LintIssue(
                        "error",
                        f"{rule.origin}: era_start={rule.era_start!r} is not an ISO date.",
                    )
                )
            if rule.scope == "always" and rule.era_start:
                issues.append(
                    LintIssue(
                        "warning",
                        f"{rule.origin}: era_start is ignored when scope=always. "
                        f"Did you mean scope=in_era?",
                    )
                )

    # --- documentation ----------------------------------------------------------------
    for cfg in configs:
        for var in cfg.derived:
            if not var.description.strip():
                issues.append(
                    LintIssue(
                        "warning",
                        f"{var.origin}: derived variable {var.variable_name!r} has no "
                        f"description. The dictionary ships with the panel, so an "
                        f"undescribed column is an undocumented one.",
                    )
                )

    # --- data-quality checks ----------------------------------------------------------
    seen_checks: dict[str, Origin] = {}
    for cfg in configs:
        for check in cfg.checks:
            if check.name in seen_checks:
                issues.append(LintIssue(
                    "error",
                    f"{check.origin}: check name {check.name!r} is already used at "
                    f"{seen_checks[check.name]}.",
                ))
            seen_checks[check.name] = check.origin
            try:
                deps = dependencies(check.expression, where=str(check.origin))
            except FormulaError as exc:
                issues.append(LintIssue("error", str(exc).splitlines()[0]))
                continue
            unknown = sorted(deps - known - BUILTIN_COLUMNS)
            if unknown:
                issues.append(LintIssue(
                    "error",
                    f"{check.origin}: check {check.name!r} references unknown "
                    f"variable(s) {unknown}.",
                ))
            if not check.description.strip():
                issues.append(LintIssue(
                    "warning",
                    f"{check.origin}: check {check.name!r} has no description. A failing "
                    f"check nobody can interpret gets ignored.",
                ))

    # --- flow-type sanity -----------------------------------------------------------
    for cfg in configs:
        for var in (*cfg.base, *cfg.derived):
            if var.variable_name.startswith("q_"):
                issues.append(
                    LintIssue(
                        "error",
                        f"{var.origin}: {var.variable_name!r} -- the q_ prefix is reserved "
                        f"for the quarterly-flow companions of ytd_ items.",
                    )
                )
            if var.flow_type == "ytd" and not var.variable_name.startswith("ytd_"):
                issues.append(
                    LintIssue(
                        "error",
                        f"{var.origin}: {var.variable_name!r} is flow_type=ytd but is not "
                        f"named ytd_<stem>. A year-to-date item is published as itself "
                        f"(ytd_<stem>, as filed) and as its quarterly flow (q_<stem>).",
                    )
                )
        for var in cfg.base:
            if var.flow_type == "ytd" and not var.schedule.startswith("RI"):
                issues.append(
                    LintIssue(
                        "warning",
                        f"{var.origin}: {var.variable_name!r} is flow_type=ytd but sits on "
                        f"schedule {var.schedule}. Year-to-date accumulation is an income-"
                        f"statement (RI*) property; balance-sheet items are point-in-time.",
                    )
                )
            if var.sign == "nonneg" and var.flow_type not in ("ytd", "count"):
                issues.append(
                    LintIssue(
                        "warning",
                        f"{var.origin}: sign=nonneg on flow_type={var.flow_type} has no "
                        f"effect; the sign check runs on quarterized flows.",
                    )
                )

    # --- intermediate columns -------------------------------------------------------
    # Withholding a built column from the panel is safe only if something else consumes
    # it. An intermediate nothing depends on is not "reduced scope", it is deleted data.
    known = set(graph.deps) | {v.variable_name for cfg in configs for v in cfg.base}
    withheld = {r.column for cfg in configs for r in cfg.intermediate}
    consumed: set[str] = set()
    for name, deps in graph.deps.items():
        if name not in withheld:
            consumed |= set(deps)
    for cfg in configs:
        for rule in cfg.intermediate:
            if rule.column not in known:
                issues.append(LintIssue(
                    "error",
                    f"{rule.origin}: [INTERMEDIATE] names {rule.column!r}, which no config "
                    f"defines.",
                ))
            elif rule.column not in consumed:
                issues.append(LintIssue(
                    "error",
                    f"{rule.origin}: {rule.column!r} is [INTERMEDIATE] but no published "
                    f"column depends on it, so building it has no effect and the data is "
                    f"simply dropped. Publish it, or remove it from the config.",
                ))
        for rule in cfg.zero_fill:
            if rule.column in withheld:
                issues.append(LintIssue(
                    "warning",
                    f"{rule.origin}: [ZERO_FILL] targets {rule.column!r}, which is "
                    f"[INTERMEDIATE] and dropped before zero-fill runs. The rule has no "
                    f"effect -- move it to the published column that consumes it.",
                ))

    return issues


def has_errors(issues: list[LintIssue]) -> bool:
    return any(i.level == "error" for i in issues)
