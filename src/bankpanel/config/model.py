"""Typed representation of a bankpanel config file.

A config is a *sectioned CSV*: literal marker lines (``[BASE_VARIABLES]`` etc.) split the
file into sections, each with its own header row. The format is deliberately CSV rather
than YAML/TOML so that configs stay editable in Excel and so that adding N line items is
an N-line reviewable diff. See docs/CONFIG_FORMAT.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --- controlled vocabularies -------------------------------------------------------

#: How a variable behaves through time. Only ``ytd`` is quarterized.
#:
#: This replaces the legacy ``ytd*`` name-prefix convention. Keying quarterization on a
#: name prefix meant the output name could never be chosen freely, forced a rename map
#: (``ytd_x`` -> ``qx``) implemented in two places, and silently collided whenever
#: ``ytd_foo`` and ``ytdfoo`` both existed.
FLOW_TYPES = frozenset({"stock", "ytd", "flag", "count", "rate", "text"})

#: Sign constraint used by the quarterize audit. ``nonneg`` marks gross additive flows
#: that cannot legitimately be negative over a quarter (interest income/expense,
#: non-interest *expense*, fiduciary income). Net items -- trading revenue, gains on
#: sales, taxes -- are ``any`` and are never flagged.
SIGNS = frozenset({"any", "nonneg", "nonpos"})

#: Call Report schedules. ``CROSS`` is valid only for derived variables that combine
#: inputs from more than one schedule.
SCHEDULES = frozenset({
    "RC", "RC-A", "RC-B", "RC-C", "RC-D", "RC-E", "RC-F", "RC-G", "RC-H", "RC-K",
    "RC-L", "RC-M", "RC-N", "RC-O", "RC-P", "RC-Q", "RC-R", "RC-R-I", "RC-R-II",
    "RC-S", "RC-T", "RC-V",
    "RI", "RI-A", "RI-B", "RI-C", "RI-D", "RI-E",
    "CROSS",
})

#: Which FFIEC form(s) collect an item. Used by the validators so that an item absent
#: from the 051 short form is not mistaken for a coverage break.
FORM_SCOPES = frozenset({"031", "041", "051", "031+041", "041+051", "all"})

#: When a ``[ZERO_FILL]`` rule applies. ``in_era`` generalizes the legacy
#: ``prepare_structflags`` special case: never fabricate a zero before the quarter in
#: which collection of the item actually began.
ZERO_FILL_SCOPES = frozenset({"always", "in_era"})

#: How loudly a failed data-quality check speaks.
SEVERITIES = frozenset({"error", "warning", "info"})

#: Names the builder owns. A config may not bind any of these.
RESERVED_NAMES = frozenset({
    "RSSD_ID", "REPORTING_PERIOD", "year", "quarter", "form_type", "form_type_source",
    "np", "log", "log1p", "sqrt", "abs", "exp", "maximum", "minimum", "max", "min",
    "where", "nan",
})


class ConfigError(Exception):
    """Raised for any malformed config. Always carries file:line context."""


@dataclass(frozen=True)
class Origin:
    """Where a row came from, so every error message can point at it."""

    path: Path
    line: int

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.path.name}:{self.line}"


@dataclass(frozen=True)
class BaseVar:
    """One raw MDRM code mapped to one output column."""

    mdrm_code: str
    variable_name: str
    schedule: str
    flow_type: str
    origin: Origin
    form_scope: str = "all"
    era_start: str | None = None
    era_end: str | None = None
    sign: str = "any"
    notes: str = ""


@dataclass(frozen=True)
class DerivedVar:
    """A column computed from other columns by a one-line pandas expression.

    ``formula`` is where era-stitching lives: ``a.fillna(b).fillna(c)`` coalesces the
    successive MDRM codes that carried one economic concept across a definition change.
    """

    variable_name: str
    schedule: str
    flow_type: str
    description: str
    formula: str
    origin: Origin
    unit: str = ""
    sign: str = "any"


@dataclass(frozen=True)
class ZeroFillRule:
    """A vetted column whose NaN verifiably means zero.

    Applied as the *last* construction step -- after coalesce and after era-stitching --
    so it can never interfere with logic that needs the NaN.
    """

    column: str
    scope: str
    reason: str
    origin: Origin
    era_start: str | None = None


@dataclass(frozen=True)
class Check:
    """A data-quality assertion over panel columns.

    ``expression`` is a boolean expression in the same language as a derived formula, and
    must hold for every row where its inputs are all present. Writing checks as ordinary
    boolean expressions -- rather than a bespoke rule grammar -- means bounds, orderings,
    accounting identities and cross-item consistency are all the same kind of thing, and
    all validated by the same AST gate::

        (tier1_rbc_ratio >= 0) & (tier1_rbc_ratio <= 1)
        co_ci <= co_tot
        (assets - liabilities_total - equity_all).abs() <= 0.001 * assets.abs()
    """

    name: str
    expression: str
    severity: str
    description: str
    origin: Origin


@dataclass
class Config:
    """One parsed config file."""

    path: Path
    meta: dict[str, str] = field(default_factory=dict)
    base: list[BaseVar] = field(default_factory=list)
    derived: list[DerivedVar] = field(default_factory=list)
    zero_fill: list[ZeroFillRule] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.meta.get("panel_name", self.path.stem)
