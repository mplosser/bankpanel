"""Build the MDRM code -> Call Report schedule map from the CDR bulk ZIPs.

Nothing in the published data says which schedule an item belongs to. MDRM gives a
reporting *form* (`FFIEC 041`) but not a schedule, and the parsed quarterly parquets have
merged every schedule into one wide table.

The information does survive in the raw CDR bulk downloads, which ship one tab-delimited
file per schedule:

    FFIEC CDR Call Schedule RCCI 12312024.txt
    FFIEC CDR Call Schedule RCE  12312024.txt

Reading only the header line of each gives an authoritative code -> schedule mapping.
Scanning several vintages picks up items that have since been retired.

Usage:
    python tools/build_schedule_map.py --zip-dir /path/to/data_call_report/data/raw/ffiec
"""

from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path

import pandas as pd

MDRM_RE = re.compile(r"^(RC|RI)[A-Z]{2}[A-Z0-9]{4}$")
SCHEDULE_RE = re.compile(r"Call Schedule ([A-Z0-9]+) \d{8}")

#: CDR file tags -> the schedule names used in configs and docs.
TAG_TO_SCHEDULE = {
    "RC": "RC", "RCA": "RC-A", "RCB": "RC-B", "RCCI": "RC-C", "RCCII": "RC-C",
    "RCD": "RC-D", "RCE": "RC-E", "RCEI": "RC-E", "RCEII": "RC-E", "RCF": "RC-F",
    "RCG": "RC-G", "RCH": "RC-H", "RCK": "RC-K", "RCL": "RC-L", "RCM": "RC-M",
    "RCN": "RC-N", "RCO": "RC-O", "RCP": "RC-P", "RCQ": "RC-Q", "RCR": "RC-R",
    "RCRI": "RC-R", "RCRIA": "RC-R", "RCRIB": "RC-R", "RCRII": "RC-R",
    "RCS": "RC-S", "RCT": "RC-T", "RCV": "RC-V",
    "RI": "RI", "RIA": "RI-A", "RIB": "RI-B", "RIBI": "RI-B", "RIBII": "RI-B",
    "RIC": "RI-C", "RID": "RI-D", "RIE": "RI-E",
}


def build(zip_dir: Path, out: Path) -> pd.DataFrame:
    zips = sorted(zip_dir.glob("*.zip"))
    if not zips:
        raise SystemExit(f"no CDR bulk zips in {zip_dir}")

    mapping: dict[str, str] = {}
    seen_tags: set[str] = set()
    # Oldest first, so the earliest vintage that carries a code wins and retired items
    # are not overwritten by a later schedule reorganization.
    for path in zips:
        with zipfile.ZipFile(path) as zf:
            for member in zf.namelist():
                match = SCHEDULE_RE.search(member)
                if not match:
                    continue
                tag = match.group(1).upper()
                seen_tags.add(tag)
                schedule = TAG_TO_SCHEDULE.get(tag)
                if schedule is None:
                    continue
                with zf.open(member) as fh:
                    header = fh.readline().decode("utf-8", "replace").rstrip("\r\n")
                for cell in header.split("\t"):
                    code = cell.strip().strip('"').upper()
                    if MDRM_RE.match(code) and code not in mapping:
                        mapping[code] = schedule

    unmapped = sorted(seen_tags - set(TAG_TO_SCHEDULE))
    if unmapped:
        print(f"[warn] schedule tags with no mapping (ignored): {unmapped}")

    df = pd.DataFrame(
        sorted(mapping.items()), columns=["mdrm_code", "schedule"]
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"{len(df):,} codes across {df.schedule.nunique()} schedules -> {out}")
    print(df.schedule.value_counts().to_string())
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--zip-dir",
        default="c:/Users/Matthew/OneDrive/GitHub/data_call_report/data/raw/ffiec",
    )
    ap.add_argument("--out", default="reference_data/mdrm_to_schedule.csv")
    args = ap.parse_args()
    build(Path(args.zip_dir), Path(args.out))
