"""bankpanel -- time-consistent panels from US bank regulatory reports.

Quick start::

    import bankpanel as bp

    bp.build(raw_dir=..., out='panel_root', config_dir='configs')   # or: bankpanel build
    bp.list_variables(schedule='RC-C')
    df = bp.read_panel(columns=['assets_total', 'ln_condev'], start='2000Q1')

See docs/CAVEATS.md before using the data for research.
"""

__version__ = "0.1.0.dev0"

from .build.runner import build
from .config import ConfigError, ConfigSet
from .io import (
    PanelNotFoundError,
    PanelTooLargeError,
    columns_for_schedule,
    dictionary,
    info,
    list_variables,
    read_header,
    read_panel,
    search_variables,
)
from .profiles import FFIEC_CALL, ReportProfile, get_profile

__all__ = [
    "build", "read_panel", "read_header", "dictionary", "list_variables",
    "columns_for_schedule", "search_variables", "info",
    "ConfigSet", "ConfigError", "PanelTooLargeError", "PanelNotFoundError",
    "ReportProfile", "FFIEC_CALL", "get_profile", "__version__",
]
