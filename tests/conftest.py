from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from fixtures.make_synth import write_synth_config, write_synth_raw  # noqa: E402


@pytest.fixture(scope="session")
def synth_raw(tmp_path_factory) -> Path:
    return write_synth_raw(tmp_path_factory.mktemp("synth_raw"))


@pytest.fixture(scope="session")
def synth_config_dir(tmp_path_factory) -> Path:
    return write_synth_config(tmp_path_factory.mktemp("synth_configs"))


@pytest.fixture(scope="session")
def synth_panel(synth_raw, synth_config_dir, tmp_path_factory) -> Path:
    """A fully built synthetic panel, shared across the suite."""
    from bankpanel.build.runner import build

    out = tmp_path_factory.mktemp("synth_panel")
    build(raw_dir=synth_raw, out=out, config_dir=synth_config_dir, jobs=1, progress=False)
    return out


@pytest.fixture(scope="session")
def real_raw_dir() -> Path:
    """Real quarterly parquets, if the environment points at them."""
    raw = os.environ.get("BANKPANEL_RAW_DIR")
    if not raw or not Path(raw).is_dir():
        pytest.skip("set BANKPANEL_RAW_DIR to run tests against real data")
    return Path(raw)


@pytest.fixture
def write_config(tmp_path):
    """Write an ad-hoc config file and return its directory."""

    def _write(text: str, name: str = "test.csv") -> Path:
        (tmp_path / name).write_text(text, encoding="utf-8")
        return tmp_path

    return _write


@pytest.fixture(scope="session")
def synth_scope_root(synth_raw, synth_config_dir, tmp_path_factory) -> Path:
    """The synthetic panel built with a test MDRM table saying the FFIEC 031 never collects
    RCFD6666 -- the official consolidated/domestic rule's inputs, isolated from the real table."""
    from bankpanel.build.runner import build
    from bankpanel.reference import scope as scope_ref

    real = scope_ref.windows
    scope_ref.windows.cache_clear()
    import pandas as pd

    table = {"RCFD6666": [], "RCON6666": [(pd.Timestamp("1984-03-31"), pd.Timestamp("2262-01-01"))]}
    scope_ref.windows = lambda profile: table
    try:
        out = tmp_path_factory.mktemp("synth_scope_panel")
        build(raw_dir=synth_raw, out=out, config_dir=synth_config_dir, jobs=1, progress=False)
    finally:
        scope_ref.windows = real
    return out


@pytest.fixture(scope="session")
def panel_scope(synth_scope_root):
    from bankpanel.io.reader import read_panel

    return read_panel(columns=["consol_item"], root=synth_scope_root, verify=False)
