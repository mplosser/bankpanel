"""When a consolidated or domestic code is collected on the form of a bank WITH foreign offices.

Loaded from ``reference_data/scope_validity.csv`` (built from the Fed's MDRM dictionary by
``tools/build_scope_validity.py``): one row per (profile, code, start, end); a code the form
never collects has one row with empty dates. Used by the builder to recognise a value an
upstream file copied from its twin (see ``profiles.ReportProfile.domestic_pairs``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

FILE = "scope_validity.csv"


def _candidates() -> list[Path]:
    here = Path(__file__).resolve()
    return [here.parents[1] / "_bundled" / "reference_data" / FILE,   # installed wheel
            here.parents[3] / "reference_data" / FILE]                # source tree


@lru_cache(maxsize=4)
def windows(profile: str) -> dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]]:
    """``{code: [(start, end), ...]}``; an empty list means the form never collects the code.
    Codes not in the table are unknown and treated as collected."""
    path = next((p for p in _candidates() if p.exists()), None)
    if path is None:
        return {}
    t = pd.read_csv(path, dtype=str, keep_default_na=False)
    t = t[t.profile == profile]
    out: dict[str, list] = {}
    for code, g in t.groupby("code"):
        spans = []
        for s, e in zip(g.start, g.end, strict=True):
            if not s:
                continue
            spans.append((pd.Timestamp(s), pd.Timestamp(e) if e else pd.Timestamp("2262-01-01")))
        out[code] = spans
    return out


def collected(profile: str, code: str, period: pd.Timestamp) -> bool:
    w = windows(profile)
    if code not in w:
        return True
    return any(s <= period <= e for s, e in w[code])
