"""Build reference_data/scope_validity.csv: when each consolidated / domestic code is collected
on the form of a bank WITH foreign offices, according to the Fed's MDRM dictionary.

The official consolidated-vs-domestic rule (profiles.ReportProfile.domestic_pairs) needs to
know when a consolidated code (RCFD / BHCK) or a domestic code (RCON / BHDM) is genuinely
filed by an international bank. The Chicago Fed files (to 2010) fill a missing code with a
copy of its twin in BOTH directions, and did so for items the FFIEC 031 never collects at all
(RCFD3387, consolidated average C&I loans, has no MDRM entry), so the data cannot say which
code a bank actually filed. MDRM can: every item has one row per (reporting form, date range).

    python tools/build_scope_validity.py            # regenerate after a form change or MDRM refresh

Output rows: profile, code, start, end. A code the form never collects gets one row with
empty dates. The engine discards a value as a copy only when it is outside these windows AND
identical to its twin (MDRM dates describe the forms, not the source files, so a value that
differs from its twin is kept and reported instead -- see validate/scope.py). Where the filed
data contradict MDRM, reference_data/scope_validity_overrides.csv records the correction and
its evidence; it replaces MDRM's windows for that code.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
#: The forms whose MDRM windows say when a code is collected from a bank WITH foreign
#: offices -- the only banks the consolidated-vs-domestic rule applies to. From 1984 that is
#: the FFIEC 031; before 1984 it is the FFIEC 014 (condition report of banks with domestic and
#: foreign offices). The FFIEC 010/012 were filed by banks WITHOUT foreign offices, so their
#: windows say nothing about what a foreign-office bank filed and are not used. The 014's
#: windows are clipped at 1983Q4 (the number was reused after 1984 for another report).
FORMS = {"ffiec_call": ("configs/call", ("FFIEC 031", "FFIEC 014"), ("RCFD", "RCON")),
         "fry9c": ("configs/y9c", ("FR Y-9C",), ("BHCK", "BHDM"))}
PRE1984_FORMS = {"FFIEC 014"}
PRE1984_END = pd.Timestamp("1983-12-31").date()


def config_codes(config_dir: Path, prefixes: tuple[str, str]) -> set[str]:
    codes = set()
    for f in sorted(config_dir.glob("*.csv")):
        txt = f.read_text(encoding="utf-8")
        if "[BASE_VARIABLES]" not in txt:
            continue
        block = txt.split("[BASE_VARIABLES]")[1].split("\n[")[0]
        for row in csv.reader(io.StringIO(block)):
            if row and re.match(rf"^({prefixes[0]}|{prefixes[1]})\w{{4}}$", row[0]):
                codes.add(row[0])
    # both halves of every pair
    return codes | {(prefixes[1] if c.startswith(prefixes[0]) else prefixes[0]) + c[4:] for c in codes}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mdrm", default=os.environ.get("BANKPANEL_MDRM", "../data_call_report/data/dictionary/MDRM.csv"))
    ap.add_argument("--out", default=str(ROOT / "reference_data" / "scope_validity.csv"))
    args = ap.parse_args()
    m = pd.read_csv(ROOT / args.mdrm if not Path(args.mdrm).is_absolute() else args.mdrm,
                    skiprows=1, dtype=str, keep_default_na=False)
    m["code"] = m["Mnemonic"] + m["Item Code"]
    rows = []
    for profile, (cfg, form, prefixes) in FORMS.items():
        for code in sorted(config_codes(ROOT / cfg, prefixes)):
            r = m[(m.code == code) & (m["Reporting Form"].str.strip().isin(form))]
            if r.empty:
                rows.append((profile, code, "", ""))
                continue
            spans = set()
            for f, a, b in r[["Reporting Form", "Start Date", "End Date"]].values:
                s, e = pd.to_datetime(a.split()[0]).date(), pd.to_datetime(b.split()[0]).date()
                if f.strip() in PRE1984_FORMS:
                    # the form number was reused after 1984 for another report: pre-1984 only
                    if s > PRE1984_END:
                        continue
                    e = min(e, PRE1984_END)
                spans.add((s, e))
            if not spans:
                rows.append((profile, code, "", ""))
                continue
            for s, e in sorted(spans):
                rows.append((profile, code, str(s), "" if e.year >= 9999 else str(e)))
    out = pd.DataFrame(rows, columns=["profile", "code", "start", "end"])
    # Curated corrections where the filed data contradict MDRM, each with its evidence.
    ov_path = ROOT / "reference_data" / "scope_validity_overrides.csv"
    if ov_path.exists():
        ov = pd.read_csv(ov_path, dtype=str, keep_default_na=False)
        keys = set(zip(ov.profile, ov.code, strict=True))
        out = out[[(p, c) not in keys for p, c in zip(out.profile, out.code, strict=True)]]
        out = pd.concat([out, ov[["profile", "code", "start", "end"]]], ignore_index=True).sort_values(["profile", "code", "start"])
        print(f"applied {len(ov)} override row(s) from {ov_path.name}")
    out.to_csv(args.out, index=False)
    never = out[out.start == ""]
    print(f"wrote {len(out)} rows for {out.code.nunique()} codes -> {args.out}; "
          f"never on the form: {len(never)} ({', '.join(never.code.head(12))}{' ...' if len(never) > 12 else ''})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
