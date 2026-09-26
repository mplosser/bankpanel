"""The quarterly-refresh report logic, on synthetic validation output (no data needed)."""

import datetime as dt
import importlib.util
import json
from pathlib import Path

import pandas as pd

TOOL = Path(__file__).resolve().parents[1] / "tools" / "quarterly_refresh.py"
spec = importlib.util.spec_from_file_location("quarterly_refresh", TOOL)
qr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qr)


def _root(tmp: Path, name: str, date_max: str, **frames) -> Path:
    root = tmp / name
    (root / "validation").mkdir(parents=True)
    (root / "_build_manifest.json").write_text(json.dumps(
        {"date_min": "1985Q1", "date_max": date_max, "n_rows": 10, "n_columns": 5}))
    for fname, df in frames.items():
        df.to_csv(root / "validation" / f"{fname}.csv", index=False)
    return root


def test_clean_refresh_needs_no_decision(tmp_path):
    prev = _root(tmp_path, "prev", "2025Q4")
    new = _root(tmp_path, "new", "2026Q2")
    a = qr.assess("call", new, prev, dt.date(2026, 9, 26))
    assert a["new_quarters"] == ["2026Q1", "2026Q2"]
    assert qr.needs_decision(a) == []


def test_findings_breaks_and_new_quarter_failures(tmp_path, monkeypatch):
    ack = tmp_path / "ack.csv"
    pd.DataFrame([{"profile": "ffiec_call", "column": "old_code", "test": "coverage_collapse",
                   "until": "2027-03-31", "reason": "retired"}]).to_csv(ack, index=False)
    monkeypatch.setattr(qr, "ACK_FILE", ack)
    prev = _root(tmp_path, "prev", "2026Q1")
    new = _root(
        tmp_path, "new", "2026Q2",
        coverage_findings=pd.DataFrame([{"column": "x", "from_date": "2026-03-31", "to_date": "2026-06-30"}]),
        series_breaks=pd.DataFrame([
            {"quarter": "2026-06-30", "column": "old_code", "test": "coverage_collapse", "severity": "CRITICAL", "detail": ""},
            {"quarter": "2026-06-30", "column": "new_break", "test": "zero_flip", "severity": "CRITICAL", "detail": ""},
        ]),
        quality_checks=pd.DataFrame([{"name": "loans_le_assets", "severity": "error"},
                                     {"name": "soft", "severity": "warning"}]),
        quality_failures=pd.DataFrame([
            {"check": "loans_le_assets", "RSSD_ID": 1, "REPORTING_PERIOD": "2026-06-30", "inputs": ""},
            {"check": "loans_le_assets", "RSSD_ID": 2, "REPORTING_PERIOD": "2001-03-31", "inputs": ""},  # old: not new
            {"check": "soft", "RSSD_ID": 3, "REPORTING_PERIOD": "2026-06-30", "inputs": ""},
        ]),
    )
    a = qr.assess("call", new, prev, dt.date(2026, 9, 26))
    why = " | ".join(qr.needs_decision(a))
    assert "1 new coverage finding" in why
    assert "new_break" in why and "old_code" not in why          # acknowledged break is silent
    assert "1 error-severity quality failure" in why              # old-quarter and warning ones excluded
    assert len(a["new_quarter_failures"]) == 2


def test_acknowledgement_expires(tmp_path, monkeypatch):
    ack = tmp_path / "ack.csv"
    pd.DataFrame([{"profile": "fry9c", "column": "c", "test": "zero_flip", "until": "2027-03-31",
                   "reason": ""}]).to_csv(ack, index=False)
    monkeypatch.setattr(qr, "ACK_FILE", ack)
    assert qr.acknowledged("fry9c", dt.date(2027, 3, 31)) == {("c", "zero_flip")}
    assert qr.acknowledged("fry9c", dt.date(2027, 4, 1)) == set()
    assert qr.acknowledged("ffiec_call", dt.date(2026, 9, 26)) == set()
