"""Derive configs/y9c from configs/call by prefix translation, keeping what the FR Y-9C files carry.

The Y-9C shares the Call Report's four-character item codes: BHCK2170 is RCFD2170, HC is RC,
HI is RI. So the Call configs translate by prefix, and the two panels come out with the same
variable names for the same concepts. What does not translate is measured, not guessed:

* a base row is kept only if its translated code appears in at least one Y-9C quarter
  (a BHCK code also counts if only its BHDM twin appears -- the builder coalesces the pair);
* an explicit exception map (reference_data/y9c_code_map.csv) overrides the prefix rule for
  items that carry a different code on the Y-9C;
* a derived row, check, zero-fill or intermediate is kept only if every name it references
  survives; everything dropped is written to review/y9c_dropped.csv with the reason;
* form_type has no meaning on the Y-9C (one form), so formulas that read it are dropped
  to the review list rather than silently rewritten;
* era_start / era_end and form_scope are cleared: the Y-9C's collection windows differ and
  are measured by the build, not copied from the Call Report.

Usage: python tools/derive_y9c_configs.py [--raw-dir <data_fry9/data/processed/y_9c>]
"""

from __future__ import annotations

import argparse
import csv
import glob
import io
import re
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bankpanel.expr import dependencies  # noqa: E402

PREFIX = {"RCFD": "BHCK", "RIAD": "BHCK", "RCON": "BHDM", "RCFA": "BHCA", "RCOA": "BHCA",
          "RCFW": "BHCW", "RCOW": "BHCW", "RCFN": "BHFN"}
SKIP_FILES = {"coverage_expected.csv", "rc_o_assessments.csv"}  # FDIC assessments: no BHC analogue
HEADER_OF = {
    "BASE_VARIABLES": ["mdrm_code", "variable_name", "schedule", "flow_type", "form_scope", "era_start", "era_end", "sign", "notes"],
    "DERIVED_VARIABLES": ["variable_name", "schedule", "flow_type", "description", "formula", "unit", "sign"],
    "ZERO_FILL": ["column", "scope", "reason", "era_start"],
    "CHECKS": ["name", "expression", "severity", "description"],
    "INTERMEDIATE": ["column", "reason"],
    "META": ["key", "value"],
}


def row(*cells: str) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(cells)
    return buf.getvalue()


def read_sections(path: Path) -> dict[str, list[list[str]]]:
    """Section name -> data rows (header row dropped), trailing empties stripped."""
    out: dict[str, list[list[str]]] = {}
    section = None
    header_seen = False
    for r in csv.reader(open(path, encoding="utf-8")):
        while r and r[-1] == "":
            r = r[:-1]
        if not r or r[0].startswith("#"):
            continue
        if r[0].startswith("[") and r[0].endswith("]"):
            section = r[0][1:-1]
            out.setdefault(section, [])
            header_seen = False
            continue
        if section is None:
            continue
        if not header_seen:
            header_seen = True
            continue
        out[section].append(r)
    return out


def schedule_name(s: str) -> str:
    """RC-C -> HC-C, RI-B -> HI-B, RC -> HC, RI -> HI."""
    return re.sub(r"^R([CI])", r"H\1", s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default="c:/Users/Matthew/OneDrive/GitHub/data_fry9/data/processed/y_9c")
    ap.add_argument("--mdrm", default="c:/Users/Matthew/OneDrive/GitHub/bec_migration/data_preparation/MDRM.csv")
    args = ap.parse_args()

    files = sorted(glob.glob(str(Path(args.raw_dir) / "*.parquet")))
    present: dict[str, int] = {}
    for f in files:
        for c in pq.ParquetFile(f).schema_arrow.names:
            present[c] = present.get(c, 0) + 1
    override = {}
    p = ROOT / "reference_data" / "y9c_code_map.csv"
    if p.exists():
        t = pd.read_csv(p, dtype=str, keep_default_na=False)
        override = dict(zip(t.call_code, t.y9c_code, strict=True))

    out_dir = ROOT / "configs" / "y9c"
    out_dir.mkdir(exist_ok=True)
    dropped: list[dict] = []
    kept_names: set[str] = set()
    kept_codes: dict[str, str] = {}   # variable_name -> y9c code
    all_sections: dict[str, dict[str, list[list[str]]]] = {}

    # ---- pass 1: base rows -----------------------------------------------------------
    for src in sorted((ROOT / "configs" / "call").glob("*.csv")):
        if src.name in SKIP_FILES:
            continue
        sec = read_sections(src)
        base_keep = []
        for r in sec.get("BASE_VARIABLES", []):
            r = r + [""] * (9 - len(r))
            code, name = r[0], r[1]
            y = override.get(code) or ((PREFIX[code[:4]] + code[4:]) if code[:4] in PREFIX else "")
            twin = ("BHDM" + y[4:]) if y.startswith("BHCK") else ""
            if not y or not (present.get(y) or present.get(twin)):
                dropped.append({"config": src.name, "kind": "base", "name": name, "call_code": code, "y9c_code": y,
                                "reason": "translated code absent from every Y-9C quarter"})
                continue
            base_keep.append([y, name, schedule_name(r[2]), r[3], "all", "", "", r[7], r[8]])
            kept_names.add(name)
            kept_codes[name] = y
        all_sections[src.name] = {"BASE_VARIABLES": base_keep, **{k: v for k, v in sec.items() if k != "BASE_VARIABLES"}}

    # ---- pass 2: derived rows, iterated until stable (a derived may feed another) -------
    derived_keep: dict[str, list[list[str]]] = {n: [] for n in all_sections}
    pending = {n: list(s.get("DERIVED_VARIABLES", [])) for n, s in all_sections.items()}
    changed = True
    while changed:
        changed = False
        for cfg, rows_ in pending.items():
            rest = []
            for r in rows_:
                r = r + [""] * (7 - len(r))
                name, formula = r[0], r[4]
                deps = dependencies(formula)
                if "form_type" in deps:
                    dropped.append({"config": cfg, "kind": "derived", "name": name, "call_code": "", "y9c_code": "",
                                    "reason": "formula reads form_type (no form types on the Y-9C); needs its own Y-9C formula"})
                    continue
                if deps <= kept_names:
                    derived_keep[cfg].append([r[0], schedule_name(r[1]), r[2], r[3], r[4], r[5], r[6]])
                    kept_names.add(name)
                    changed = True
                else:
                    rest.append(r)
            pending[cfg] = rest
    for cfg, rows_ in pending.items():
        for r in rows_:
            missing = sorted(dependencies(r[4]) - kept_names)
            dropped.append({"config": cfg, "kind": "derived", "name": r[0], "call_code": "", "y9c_code": "",
                            "reason": f"input(s) not on the Y-9C: {', '.join(missing)}"})

    # ---- pass 3: zero-fill, intermediate, checks; write ---------------------------------
    for cfg, sec in all_sections.items():
        lines = [f"# Derived from configs/call/{cfg} by tools/derive_y9c_configs.py -- FR Y-9C (BHCK/BHDM).",
                 "# Base rows kept only where the translated code exists in the Y-9C files; see review/y9c_dropped.csv.", ""]
        if sec.get("META"):
            lines += ["[META]", "key,value", *[row(*r) for r in sec["META"]], ""]
        lines += ["[BASE_VARIABLES]", ",".join(HEADER_OF["BASE_VARIABLES"]), *[row(*r) for r in sec["BASE_VARIABLES"]], ""]
        lines += ["[DERIVED_VARIABLES]", ",".join(HEADER_OF["DERIVED_VARIABLES"]), *[row(*r) for r in derived_keep[cfg]], ""]
        zf = []
        for r in sec.get("ZERO_FILL", []):
            r = r + [""] * (4 - len(r))
            if r[1] == "in_era_unless_reported":
                # Explains a Call Report source change (zeros stop being written at 2005Q3);
                # whether the Y-9 files do the same is a separate measurement, not a copy.
                dropped.append({"config": cfg, "kind": "zero_fill", "name": r[0], "call_code": "", "y9c_code": "",
                                "reason": "Call Report 2005Q3 zero-representation rule; measure separately on the Y-9C"})
            elif r[0] in kept_names:
                zf.append([r[0], r[1], r[2], ""])   # era_start measured by the build, not copied
            else:
                dropped.append({"config": cfg, "kind": "zero_fill", "name": r[0], "call_code": "", "y9c_code": "", "reason": "column not kept"})
        if zf:
            lines += ["[ZERO_FILL]", ",".join(HEADER_OF["ZERO_FILL"]), *[row(*r) for r in zf], ""]
        ck = []
        for r in sec.get("CHECKS", []):
            if dependencies(r[1]) <= kept_names:
                ck.append(r)
            else:
                dropped.append({"config": cfg, "kind": "check", "name": r[0], "call_code": "", "y9c_code": "", "reason": "input(s) not kept"})
        if ck:
            lines += ["[CHECKS]", ",".join(HEADER_OF["CHECKS"]), *[row(*r) for r in ck], ""]
        # an intermediate must still have a published consumer
        consumers = {d for rows_ in derived_keep.values() for r in rows_ for d in dependencies(r[4])}
        im = []
        for r in sec.get("INTERMEDIATE", []):
            if r[0] in kept_names and r[0] in consumers:
                im.append(r)
            elif r[0] in kept_names:
                dropped.append({"config": cfg, "kind": "intermediate", "name": r[0], "call_code": "", "y9c_code": "",
                                "reason": "withheld on the Call Report but its consumer was dropped here; published instead"})
        if im:
            lines += ["[INTERMEDIATE]", ",".join(HEADER_OF["INTERMEDIATE"]), *[row(*r) for r in im], ""]
        (out_dir / cfg).write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- predecessor institutions (Schedule HI memorandum, BHBC) -----------------------
    mdrm = pd.read_csv(args.mdrm, skiprows=1, dtype=str, keep_default_na=False)
    mdrm["code"] = mdrm.Mnemonic + mdrm["Item Code"]
    names = mdrm.drop_duplicates("code").set_index("code")["Item Name"]
    stem_of = {code[4:]: name for name, code in kept_codes.items() if code.startswith("BHCK")}
    lines = ["# Schedule HI memorandum: income of predecessor institutions (BHBC), filed in the quarter of a",
             "# business combination for the year-to-date period BEFORE the acquisition. Never quarterized:",
             "# each is a single amount, not a running total. Generated by tools/derive_y9c_configs.py.", "",
             "[BASE_VARIABLES]", ",".join(HEADER_OF["BASE_VARIABLES"])]
    pred_rows = []
    for code in sorted(c for c in present if c.startswith("BHBC")):
        item = code[4:]
        stem = stem_of.get(item)
        if stem:
            name = "pred_" + stem
        else:
            name = "pred_" + re.sub(r"[^a-z0-9]+", "_", names.get(code, item).lower()).strip("_")[:48]
        pred_rows.append(row(code, name, "HI", "ytd_event", "all", "", "", "", names.get(code, "")))
    lines += pred_rows + ["", "[DERIVED_VARIABLES]", ",".join(HEADER_OF["DERIVED_VARIABLES"]), ""]
    (out_dir / "hi_predecessor.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- the merger flags and acquisition-date items ------------------------------------
    extra = [("BHCKC251", "structflag_business_combo", "HI", "flag", "", "HAS THE BHC ENTERED INTO A BUSINESS COMBINATION DURING THE CALENDAR YEAR (2002-)"),
             ("BHCK6688", "structflag_business_combo_pre02", "HI", "flag", "", "CONSOLIDATED STATEMENT REFLECTS A BUSINESS COMBINATION (1990-2001)"),
             ("BHCK6689", "structflag_restatement", "HI", "flag", "", "RESTATED FINANCIAL STATEMENTS DURING THE LAST QUARTER"),
             ("BHCK4356", "ytd_equity_chg_business_combo", "HI-A", "ytd", "any", "CHANGES INCIDENT TO BUSINESS COMBINATIONS, NET"),
             ("BHCK4776", "ytd_allowance_chg_mergers", "HI-B", "ytd", "any", "CHANGES INCIDENT TO MERGERS AND ABSORPTIONS, NET, ALLOWANCE (to 2000)"),
             ("BHCKKX60", "acq_loans_fv_at_acquisition", "HC-C", "stock", "", "FAIR VALUE OF ACQUIRED LOANS AND LEASES AT ACQUISITION DATE (2019-)"),
             ("BHCKKX61", "acq_loans_gross_contractual", "HC-C", "stock", "", "GROSS CONTRACTUAL AMOUNTS RECEIVABLE AT ACQUISITION (2019-)"),
             ("BHCKKX62", "acq_loans_expected_shortfall", "HC-C", "stock", "", "BEST ESTIMATE OF CONTRACTUAL CASH FLOWS NOT EXPECTED TO BE COLLECTED (2019-)")]
    lines = ["# Business-combination flags and acquisition-date items on the FR Y-9C. Generated by", "# tools/derive_y9c_configs.py.", "",
             "[BASE_VARIABLES]", ",".join(HEADER_OF["BASE_VARIABLES"])]
    taken = set(kept_codes.values())
    for code, name, sched, ft, sign, note in extra:
        if present.get(code) and name not in kept_names and code not in taken:
            lines.append(row(code, name, sched, ft, "all", "", "", sign, note))
    lines += ["", "[DERIVED_VARIABLES]", ",".join(HEADER_OF["DERIVED_VARIABLES"]), ""]
    (out_dir / "hi_mergers.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    rev = ROOT / "review" / "y9c_dropped.csv"
    pd.DataFrame(dropped).to_csv(rev, index=False)
    n_base = sum(len(s["BASE_VARIABLES"]) for s in all_sections.values())
    n_der = sum(len(v) for v in derived_keep.values())
    print(f"configs/y9c: {len(all_sections) + 2} files | base rows kept {n_base} | derived kept {n_der} | "
          f"predecessor items {len(pred_rows)} | dropped {len(dropped)} -> {rev}")
    d = pd.DataFrame(dropped)
    print(d.groupby(["kind"]).size().to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
