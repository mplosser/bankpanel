"""Quarterly refresh: fetch, parse, rebuild and revalidate both panels, then report.

A new quarter needs no code change -- nothing in bankpanel caps the date -- but the forms
change every year or so (codes retired, split or added), and only revalidation shows it.
This runs the whole sequence against the sibling data repositories and ends with a
one-page report of what needs a decision.

    python tools/quarterly_refresh.py --out-dir ../panels            # everything
    python tools/quarterly_refresh.py --out-dir ../panels --skip-fetch --skip-parse
    python tools/quarterly_refresh.py --out-dir ../panels --only call

Steps (each logged to <out-dir>/logs/):
  1. fetch     data_call_report/01b_download_ffiec_cdr.py (scripted); data_fry9/
               01b_check_ffiec_nic.py (the FR Y-9C from 2021Q2 is a manual download --
               the check prints the exact files needed)
  2. dictionary  MDRM dictionary refresh in both repos (descriptions for new codes)
  3. parse     05_parse_ffiec.py / 04_parse_data.py (new files only)
     scope     tools/build_scope_validity.py -- when each consolidated / domestic code is
               collected, from the refreshed MDRM; a change is reported, never committed
  4. configs   tools/derive_y9c_configs.py -- new Y-9C codes the Call configs already map
               only appear after this; a change is reported for review, never committed
  5. build     bankpanel build + expectations + validate all --save, one panel at a time
               (the previous build is kept as <panel>.prev for comparison)
  6. identity  tools/raw_identity_check.py on the two newest quarters

Exit code: 0 clean (a data-only refresh), 1 something needs a decision (new coverage
finding, stale ledger row, unacknowledged critical break, new error-severity quality
failure, raw-identity difference, generated Y-9C configs changed, consolidated-vs-domestic
substitution, MDRM validity table changed), 2 blocked (raw files
missing or a step failed). The report is <out-dir>/refresh_report.md.

Known breaks can be acknowledged in reference_data/breaks_acknowledged.csv
(profile, column, test, until, reason): the latest-quarter gate compares with a year
earlier, so an explained code retirement is flagged for four quarters; an entry silences
it until its `until` date.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

ROOT = Path(__file__).resolve().parents[1]
PANELS = {
    "call": {"profile_flag": [], "profile": "ffiec_call", "raw_sub": "data/processed/FFIEC_031_041",
             "repo_env": "BANKPANEL_CALL_REPO", "repo_default": "../data_call_report"},
    "y9c": {"profile_flag": ["--profile", "fry9c"], "profile": "fry9c", "raw_sub": "data/processed/y_9c",
            "repo_env": "BANKPANEL_FRY9_REPO", "repo_default": "../data_fry9"},
}
ACK_FILE = ROOT / "reference_data" / "breaks_acknowledged.csv"


class Step:
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.results: list[dict] = []

    def run(self, name: str, cmd: list[str], cwd: Path, *, ok_codes=(0,)) -> int:
        log = self.log_dir / f"{len(self.results) + 1:02d}_{name}.log"
        print(f"[{name}] {' '.join(cmd)}  (cwd {cwd})", flush=True)
        t0 = dt.datetime.now()
        with open(log, "w", encoding="utf-8") as fh:
            proc = subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, text=True,
                                  env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        secs = (dt.datetime.now() - t0).total_seconds()
        self.results.append({"step": name, "exit": proc.returncode, "ok": proc.returncode in ok_codes,
                             "seconds": round(secs), "log": str(log)})
        print(f"[{name}] exit {proc.returncode} in {secs:.0f}s -> {log.name}", flush=True)
        return proc.returncode

    def tail(self, name: str, n: int = 25) -> str:
        for r in self.results:
            if r["step"] == name:
                return "\n".join(Path(r["log"]).read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
        return ""


def _repo(key: str) -> Path:
    spec = PANELS[key]
    return (ROOT / os.environ.get(spec["repo_env"], spec["repo_default"])).resolve()


def _manifest(root: Path) -> dict:
    p = root / "_build_manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _read(root: Path, name: str) -> pd.DataFrame:
    p = root / "validation" / f"{name}.csv"
    return pd.read_csv(p) if p.exists() and p.stat().st_size else pd.DataFrame()


def _quarter_end(label: str) -> pd.Timestamp:
    return pd.Period(label, freq="Q").end_time.normalize()


def acknowledged(profile: str, today: dt.date) -> set[tuple[str, str]]:
    if not ACK_FILE.exists():
        return set()
    a = pd.read_csv(ACK_FILE)
    a = a[(a.profile == profile) & (pd.to_datetime(a["until"]).dt.date >= today)]
    return set(zip(a.column, a.test, strict=True))


def assess(key: str, new_root: Path, prev_root: Path | None, today: dt.date) -> dict:
    """Everything the report says about one panel. Pure reads of the saved validation."""
    spec = PANELS[key]
    man, prev = _manifest(new_root), _manifest(prev_root) if prev_root else {}
    out: dict = {"panel": key, "date_min": man.get("date_min"), "date_max": man.get("date_max"),
                 "rows": man.get("n_rows"), "columns": man.get("n_columns"),
                 "prev_date_max": prev.get("date_max")}
    new_q = []
    if out["date_max"]:
        start = pd.Period(prev["date_max"], freq="Q") + 1 if prev.get("date_max") else pd.Period(out["date_max"], freq="Q")
        new_q = [str(q) for q in pd.period_range(start, pd.Period(out["date_max"], freq="Q"), freq="Q")]
    out["new_quarters"] = new_q

    cov, stale = _read(new_root, "coverage_findings"), _read(new_root, "coverage_ledger_stale")
    out["coverage_findings"] = cov
    out["stale_ledger"] = stale

    brk = _read(new_root, "series_breaks")
    ack = acknowledged(spec["profile"], today)
    if not brk.empty:
        brk["acknowledged"] = [(c, t) in ack for c, t in zip(brk.column, brk.test, strict=True)]
    out["breaks"] = brk

    q = _read(new_root, "quality_checks")
    fails = _read(new_root, "quality_failures")
    if not fails.empty and new_q:
        ends = {str(_quarter_end(x).date()) for x in new_q}
        fails = fails[fails.REPORTING_PERIOD.astype(str).str[:10].isin(ends)]
    elif not new_q:
        fails = fails.iloc[0:0] if not fails.empty else fails
    if not fails.empty and not q.empty:
        fails = fails.merge(q[["name", "severity"]], left_on="check", right_on="name", how="left").drop(columns="name")
    out["quality"] = q
    out["new_quarter_failures"] = fails
    out["scope_substitution"] = _read(new_root, "consolidated_scope_substitution")
    out["scope_mdrm"] = _read(new_root, "consolidated_scope_mdrm")

    # capital-ratio unit corrections applied in the new quarters
    corrected = None
    if new_q:
        try:
            t = ds.dataset(new_root / "panel", partitioning="hive").to_table(
                columns=["REPORTING_PERIOD", "capital_ratio_unit_corrected"]).to_pandas()
            t = t[t.REPORTING_PERIOD >= _quarter_end(new_q[0]) - pd.offsets.QuarterEnd(1) + pd.Timedelta(days=1)]
            corrected = int((t.capital_ratio_unit_corrected > 0).sum())
        except Exception:  # noqa: BLE001 -- column absent in an older config set
            corrected = None
    out["ratio_corrections_new_quarters"] = corrected
    return out


def needs_decision(a: dict) -> list[str]:
    why = []
    if len(a["coverage_findings"]):
        why.append(f"{len(a['coverage_findings'])} new coverage finding(s)")
    if len(a["stale_ledger"]):
        why.append(f"{len(a['stale_ledger'])} stale ledger row(s)")
    b = a["breaks"]
    if not b.empty:
        crit = b[(b.severity == "CRITICAL") & ~b.acknowledged]
        if len(crit):
            why.append(f"{len(crit)} unacknowledged critical break(s): {', '.join(sorted(set(crit.column)))}")
    if len(a.get("scope_substitution", [])):
        why.append(f"{len(a['scope_substitution'])} consolidated-vs-domestic substitution(s): an upstream copy")
    f = a["new_quarter_failures"]
    if not f.empty and "severity" in f:
        err = f[f.severity == "error"]
        if len(err):
            why.append(f"{len(err)} error-severity quality failure(s) in the new quarters")
    return why


def _md_table(df: pd.DataFrame, cols: list[str], limit: int = 25) -> str:
    if df is None or df.empty:
        return "_none_\n"
    d = df[[c for c in cols if c in df.columns]].head(limit)
    head = "| " + " | ".join(d.columns) + " |\n| " + " | ".join("---" for _ in d.columns) + " |\n"
    body = "".join("| " + " | ".join(str(v)[:90] for v in r) + " |\n" for r in d.itertuples(index=False))
    more = f"\n_{len(df) - limit} more in the validation folder._\n" if len(df) > limit else ""
    return head + body + more


def report(path: Path, steps: Step, assessments: list[dict], extra: dict, status: int, reasons: list[str]) -> str:
    word = {0: "CLEAN (data-only refresh)", 1: "NEEDS A DECISION", 2: "BLOCKED"}[status]
    lines = [f"# Quarterly refresh -- {dt.date.today()}", "", f"**Status: {word}**", ""]
    if reasons:
        lines += ["Needs attention:", ""] + [f"- {r}" for r in reasons] + [""]
    st = pd.DataFrame(steps.results)
    if not st.empty:
        st["log"] = st["log"].map(lambda x: Path(x).name)
    lines += ["## Steps", "", f"Logs: `{steps.log_dir}`", "", _md_table(st, ["step", "exit", "ok", "seconds", "log"], 40)]
    if extra.get("y9c_config_diff"):
        lines += ["## Generated FR Y-9C configs changed (review, then commit)", "", "```",
                  extra["y9c_config_diff"][:4000], "```", ""]
    if extra.get("scope_validity_diff"):
        lines += ["## MDRM validity table changed (review, then commit)", "",
                  "A code's collection window moved: the consolidated-vs-domestic rule now treats it differently.", "",
                  "```", extra["scope_validity_diff"][:4000], "```", ""]
    for a in assessments:
        lines += [f"## Panel: {a['panel']}", "",
                  f"- coverage {a['date_min']} .. {a['date_max']} ({a['rows']} rows x {a['columns']} columns); "
                  f"previous build ended {a['prev_date_max'] or 'n/a'}",
                  f"- new quarters: {', '.join(a['new_quarters']) or 'none'}",
                  f"- capital-ratio unit corrections in the new quarters: {a['ratio_corrections_new_quarters'] if a['new_quarters'] else 'n/a (no new quarters)'}",
                  f"- raw identity (newest quarters): {extra.get('identity_' + a['panel'], 'not run')}", "",
                  "### New coverage findings", "", _md_table(a["coverage_findings"], ["column", "from_date", "to_date", "before", "after", "delta"]),
                  "### Stale ledger rows", "", _md_table(a["stale_ledger"], ["column", "from_date", "to_date", "reason"]),
                  "### Latest-quarter breaks", "", _md_table(a["breaks"], ["column", "test", "severity", "acknowledged", "detail"]),
                  "### Consolidated vs domestic (RCFD vs RCON)", "",
                  _md_table(a["scope_substitution"], ["REPORTING_PERIOD", "column", "code", "material_equal", "material_both", "usual_share"]),
                  "MDRM windows: copies discarded / values kept outside the window", "",
                  _md_table(a["scope_mdrm"], ["column", "code", "copies_discarded", "kept_outside_window"]),
                  "### Quality failures in the new quarters", "", _md_table(a["new_quarter_failures"], ["check", "severity", "RSSD_ID", "REPORTING_PERIOD", "inputs"]),
                  ""]
    text = "\n".join(lines)
    path.write_text(text, encoding="utf-8")
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", required=True, help="where the panels are built: <out-dir>/call, <out-dir>/y9c")
    ap.add_argument("--only", choices=list(PANELS), help="one panel only")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--skip-dictionary", action="store_true")
    ap.add_argument("--skip-parse", action="store_true")
    ap.add_argument("--skip-build", action="store_true", help="assess the existing builds only")
    ap.add_argument("--allow-missing", action="store_true", help="build even if raw quarters are missing")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    log_dir = out_dir / "logs" / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)
    steps, py, extra, blocked = Step(log_dir), sys.executable, {}, []
    keys = [args.only] if args.only else list(PANELS)
    call_repo, fry9_repo = _repo("call"), _repo("y9c")

    # 1. fetch
    if not args.skip_fetch:
        if "call" in keys and steps.run("fetch_call", [py, "01b_download_ffiec_cdr.py"], call_repo) != 0:
            blocked.append("Call Report download failed; manual steps are in the fetch_call log:\n" + steps.tail("fetch_call", 20))
        if "y9c" in keys:
            code = steps.run("check_y9c", [py, "01b_check_ffiec_nic.py"], fry9_repo, ok_codes=(0, 1))
            txt = steps.tail("check_y9c", 20)
            if code == 1 and "missing raw: none" not in txt:
                blocked.append("FR Y-9C raw quarters missing (manual NIC download):\n" + txt)
        if blocked and not args.allow_missing:
            return _finish(out_dir, steps, [], extra, 2, blocked)

    # 2. dictionary, 3. parse
    for key, repo, dict_steps, parse in (
        ("call", call_repo, ["02_download_dictionary.py", "03_parse_dictionary.py"], "05_parse_ffiec.py"),
        ("y9c", fry9_repo, ["02_download_dictionary.py", "03_parse_dictionary.py"], "04_parse_data.py"),
    ):
        if key not in keys:
            continue
        if not args.skip_dictionary:
            for s in dict_steps:
                extra_args = ["--force"] if s.startswith("02") else []
                if steps.run(f"dictionary_{key}_{s[:2]}", [py, s, *extra_args], repo) != 0:
                    blocked.append(f"{key}: {s} failed")
        if not args.skip_parse and steps.run(f"parse_{key}", [py, parse], repo) != 0:
            blocked.append(f"{key}: {parse} failed")
    if blocked:
        return _finish(out_dir, steps, [], extra, 2, blocked)

    # 3b. the MDRM validity table behind the consolidated-vs-domestic rule
    if not args.skip_dictionary:
        if steps.run("scope_validity", [py, "tools/build_scope_validity.py"], ROOT) != 0:
            blocked.append("tools/build_scope_validity.py failed")
            return _finish(out_dir, steps, [], extra, 2, blocked)
        diff = subprocess.run(["git", "diff", "--unified=0", "--", "reference_data/scope_validity.csv"],
                              cwd=ROOT, capture_output=True, text=True).stdout
        if diff.strip():
            extra["scope_validity_diff"] = diff

    # 4. regenerate the Y-9C configs from the Call configs and the codes now in the files
    if "y9c" in keys:
        steps.run("derive_y9c_configs", [py, "tools/derive_y9c_configs.py"], ROOT)
        diff = subprocess.run(["git", "diff", "--stat", "--", "configs/y9c"], cwd=ROOT, capture_output=True, text=True).stdout
        if diff.strip():
            extra["y9c_config_diff"] = diff + subprocess.run(
                ["git", "diff", "--unified=0", "--", "configs/y9c"], cwd=ROOT, capture_output=True, text=True).stdout
        if steps.run("lint_y9c", [py, "-m", "bankpanel", "lint", "--profile", "fry9c"], ROOT) != 0:
            blocked.append("generated FR Y-9C configs fail lint")
    if "call" in keys and steps.run("lint_call", [py, "-m", "bankpanel", "lint"], ROOT) != 0:
        blocked.append("Call Report configs fail lint")
    if blocked:
        return _finish(out_dir, steps, [], extra, 2, blocked)

    # 5. build + validate, one panel at a time (memory), 6. raw identity on the newest quarters
    assessments = []
    for key in keys:
        spec, repo = PANELS[key], (call_repo if key == "call" else fry9_repo)
        root, prev = out_dir / key, out_dir / f"{key}.prev"
        if not args.skip_build:
            if root.exists():
                if prev.exists():
                    shutil.rmtree(prev)
                root.rename(prev)
            raw = repo / spec["raw_sub"]
            ok = (steps.run(f"build_{key}", [py, "-m", "bankpanel", "build", *spec["profile_flag"], "--raw-dir", str(raw),
                                             "--out", str(root), "--jobs", str(args.jobs)], ROOT) == 0
                  and steps.run(f"expectations_{key}", [py, "-m", "bankpanel", "expectations", "build", *spec["profile_flag"],
                                                        "--panel-root", str(root)], ROOT) == 0)
            if not ok:
                blocked.append(f"{key}: build failed")
                continue
            steps.run(f"validate_{key}", [py, "-m", "bankpanel", "validate", "all", *spec["profile_flag"],
                                          "--panel-root", str(root), "--save"], ROOT, ok_codes=(0, 1))
        man = _manifest(root)
        if man.get("date_max"):
            last = pd.Period(man["date_max"], freq="Q")
            quarters = f"{last - 1},{last}"
            code = steps.run(f"identity_{key}", [py, "tools/raw_identity_check.py", *spec["profile_flag"], "--panel-root", str(root),
                                                 "--raw-dir", str(repo / spec["raw_sub"]), "--quarters", quarters], ROOT)
            extra[f"identity_{key}"] = steps.tail(f"identity_{key}", 1).strip() + ("" if code == 0 else f" (exit {code})")
        assessments.append(assess(key, root, prev if prev.exists() else None, dt.date.today()))

    reasons = list(blocked)
    for a in assessments:
        reasons += [f"{a['panel']}: {r}" for r in needs_decision(a)]
        if " 0 differ" not in extra.get(f"identity_{a['panel']}", " 0 differ"):
            reasons.append(f"{a['panel']}: raw-identity differences")
    if extra.get("y9c_config_diff"):
        reasons.append("generated FR Y-9C configs changed (review the diff, then commit)")
    if extra.get("scope_validity_diff"):
        reasons.append("MDRM validity table changed (review the diff, then commit reference_data/scope_validity.csv)")
    status = 2 if blocked else (1 if reasons else 0)
    return _finish(out_dir, steps, assessments, extra, status, reasons)


def _finish(out_dir, steps, assessments, extra, status, reasons) -> int:
    path = out_dir / "refresh_report.md"
    report(path, steps, assessments, extra, status, reasons)
    word = {0: "CLEAN", 1: "NEEDS A DECISION", 2: "BLOCKED"}[status]
    print(f"\n{word} -- report: {path}")
    for r in reasons:
        print(f"  - {r.splitlines()[0]}")
    return status


if __name__ == "__main__":
    sys.exit(main())
