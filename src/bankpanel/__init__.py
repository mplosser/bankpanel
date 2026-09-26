"""bankpanel -- time-consistent panels from US bank regulatory reports.

Quick start::

    import bankpanel as bp

    bp.build(raw_dir=..., out='panel_root', config_dir='configs/call')   # or: bankpanel build
    bp.list_variables(schedule='RC-C')
    df = bp.read_panel(columns=['assets', 'ln_condev', 'q_int_inc'], start='2000Q1')

See docs/CAVEATS.md before using the data for research.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

try:
    __version__ = _dist_version("bankpanel")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0+unknown"

from .build.runner import build
from .config import ConfigError, ConfigSet
from .io import (
    PanelNotFoundError,
    PanelTooLargeError,
    columns_for_schedule,
    dictionary,
    expectations,
    expected_mask,
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
    "ReportProfile", "FFIEC_CALL", "get_profile",
    "expected_mask", "expectations", "__version__",
]
