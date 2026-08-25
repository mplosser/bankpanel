"""Opt-in cleaning. Never imported by the builder or the reader.

The panel on disk is exactly what the configs produced. Everything here runs in memory,
on a copy, at the consumer's request -- so a user who wants raw time-consistent series
simply never calls it, and one who does gets an audit frame of every changed cell.
"""

from ._helpers import interpolate_within_entity
from .denominators import implied_rate, rescale_denominator
from .floors import apply_valued_balance_floor
from .flows import interpolate_negative
from .plan import (
    AUDIT_COLUMNS,
    STEPS,
    CleaningError,
    CleaningPlan,
    apply_plan,
    summarize_audit,
)
from .rates import interpolate_broken_ratio, repair_local_events
from .units import find_unit_errors, fix_unit_errors

__all__ = [
    "CleaningPlan", "apply_plan", "summarize_audit", "CleaningError", "STEPS",
    "AUDIT_COLUMNS",
    "fix_unit_errors", "find_unit_errors",
    "interpolate_negative", "repair_local_events", "interpolate_broken_ratio",
    "apply_valued_balance_floor", "rescale_denominator", "implied_rate",
    "interpolate_within_entity",
]
