"""Command line interface.

Also the supported way to run a parallel build: ``main()`` is reached through a console
script, so the ``__main__`` module is importable and process spawning works on Windows
and macOS.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config-dir", default="configs", help="directory of config CSVs (default: configs)"
    )


def _parse_years(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    if ":" in text:
        lo, hi = text.split(":", 1)
        return int(lo), int(hi)
    year = int(text)
    return year, year


def cmd_lint(args: argparse.Namespace) -> int:
    from .config import ConfigError, ConfigSet

    try:
        cs = ConfigSet.load(args.config_dir)
        issues = cs.lint(strict=args.strict)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"{len(cs.configs)} config(s): {len(cs.base)} base + {len(cs.derived)} derived "
        f"variables, {len(cs.mdrm_codes())} MDRM codes to read."
    )
    for issue in issues:
        print(f"  {issue}")
    print("OK" if not issues else f"OK with {len(issues)} warning(s)")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from .build.runner import build
    from .config import ConfigError
    from .profiles import get_profile

    try:
        build(
            raw_dir=args.raw_dir,
            out=args.out,
            config_dir=args.config_dir,
            profile=get_profile(args.profile),
            years=_parse_years(args.years),
            jobs=args.jobs,
            gap_policy=args.gap_policy,
            keep_going=args.keep_going,
            strict_lint=args.strict_lint,
        )
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def _load_for_validation(panel_root, columns=None):
    """Load the panel plus form_type, for a validator."""
    import pyarrow.dataset as ds

    from .io.reader import _resolve_root

    root = _resolve_root(panel_root)
    dataset = ds.dataset(root / "panel", partitioning="hive")
    reserved = {"RSSD_ID", "REPORTING_PERIOD", "form_type", "year"}
    cols = columns or [c for c in dataset.schema.names if c not in reserved]
    frame = dataset.to_table(
        columns=["RSSD_ID", "REPORTING_PERIOD", "form_type", *cols]
    ).to_pandas()
    return root, frame, cols


def cmd_expectations(args: argparse.Namespace) -> int:
    from .reference.expectations import build_expectations, read_expectations, write_expectations

    root, df, cols = _load_for_validation(args.panel_root)
    # The matrix describes THIS panel, so it lives beside it rather than in a shared
    # directory that could drift out of step with the data it describes.
    out = Path(args.out) if args.out else root / "reporting_expectations.parquet"
    if args.action == "build":
        exp = build_expectations(df, cols)
        write_expectations(exp, out)
        print(f"{len(exp):,} expectation rows for {exp.column.nunique():,} columns -> {out}")
        print(exp.frequency.value_counts().to_string())
    else:
        exp = read_expectations(out)
        non_quarterly = exp[~exp.frequency.isin(["quarterly", "absent"])]
        print(f"{len(exp):,} rows; {non_quarterly.column.nunique():,} columns are collected")
        print("less often than quarterly for at least one form type:")
        print()
        print(
            non_quarterly[["column", "form_type", "era_start", "era_end", "frequency"]]
            .sort_values(["form_type", "column"]).to_string(index=False)
        )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    import pandas as pd

    from .config import ConfigSet
    from .reference.expectations import read_expectations

    root, df, cols = _load_for_validation(args.panel_root)
    exit_code = 0
    saved: dict[str, pd.DataFrame] = {}

    if args.check in ("coverage", "all"):
        from .validate.coverage import coverage_scan, format_report

        expectations = None
        exp_path = Path(args.expectations) if args.expectations else root / "reporting_expectations.parquet"
        if exp_path.exists():
            expectations = read_expectations(exp_path)
        else:
            print(f"[warn] no expectations at {exp_path}; run 'bankpanel expectations build'.")
            print("[warn] without it, FFIEC 051 semiannual items will dominate the output.")
        new, approved = coverage_scan(
            df, cols, panel="panel", expectations=expectations, ledger_path=args.ledger
        )
        print(format_report(new, approved))
        saved["coverage_findings"] = new
        if args.strict and not new.empty:
            exit_code = 1

    if args.check in ("breaks", "all"):
        from .validate.breaks import check_latest_quarter, format_report, gate

        findings = check_latest_quarter(df, cols)
        latest = str(pd.DatetimeIndex(df.REPORTING_PERIOD).max().date())
        print()
        print(format_report(findings, latest))
        saved["series_breaks"] = findings
        exit_code = max(exit_code, gate(findings))

    if args.check in ("quarterize", "all"):
        from .validate.quarterize_audit import attribute, audit, format_report

        cs = ConfigSet.load(args.config_dir)
        nonneg = [
            v.variable_name for v in (*cs.base, *cs.derived)
            if v.sign == "nonneg" and v.flow_type == "ytd"
        ]
        flags = [v.variable_name for v in cs.base if "structflag" in v.variable_name]
        summary, flagged = audit(df, nonneg, flag_columns=flags)
        causes = attribute(flagged, flags)
        print()
        print(format_report(summary, flagged, causes, len(df)))
        saved["quarterize_summary"] = summary
        saved["quarterize_flagged"] = flagged

    if args.save:
        out = root / "validation"
        out.mkdir(parents=True, exist_ok=True)
        for name, frame in saved.items():
            if frame is not None and not frame.empty:
                frame.to_csv(out / f"{name}.csv", index=False)
        print()
        print(f"[saved] {out}")

    return exit_code


def cmd_info(args: argparse.Namespace) -> int:
    from .io.reader import info

    for key, value in info(args.panel_root).items():
        if isinstance(value, list) and len(value) > 8:
            value = f"[{value[0]} ... {value[-1]}] ({len(value)} items)"
        print(f"{key:>20}: {value}")
    return 0


def cmd_dictionary(args: argparse.Namespace) -> int:
    from .io.reader import dictionary

    df = dictionary(args.panel_root)
    if args.schedule:
        df = df[df.schedule.str.upper() == args.schedule.upper()]
    out = Path(args.out) if args.out else None
    if args.format == "csv":
        text = df.to_csv(index=False)
    elif args.format == "json":
        text = df.to_json(orient="records", indent=2)
    else:
        text = df.to_string(index=False)
    if out:
        out.write_text(text, encoding="utf-8")
        print(f"wrote {len(df)} rows to {out}")
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bankpanel",
        description="Time-consistent panels from US bank regulatory reports.",
    )
    parser.add_argument("--version", action="version", version=f"bankpanel {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_lint = sub.add_parser("lint", help="validate configs without reading any data")
    _add_common(p_lint)
    p_lint.add_argument("--strict", action="store_true", help="treat warnings as errors")
    p_lint.set_defaults(func=cmd_lint)

    p_build = sub.add_parser("build", help="build the panel")
    _add_common(p_build)
    p_build.add_argument("--raw-dir", required=True, help="directory of raw quarterly parquets")
    p_build.add_argument("--out", required=True, help="panel root to write")
    p_build.add_argument("--profile", default="ffiec_call")
    p_build.add_argument("--years", default=None, help="YYYY or YYYY:YYYY")
    p_build.add_argument("--jobs", type=int, default=1, help="parallel year workers")
    p_build.add_argument(
        "--gap-policy", default="nan", choices=("nan", "spread", "keep"),
        help="how to quarterize across missing quarters (default: nan)",
    )
    p_build.add_argument(
        "--keep-going", action="store_true",
        help="skip and record unreadable quarters instead of failing",
    )
    p_build.add_argument("--strict-lint", action="store_true")
    p_build.set_defaults(func=cmd_build)

    p_exp = sub.add_parser("expectations", help="build or report the reporting-expectations matrix")
    p_exp.add_argument("action", choices=("build", "report"))
    p_exp.add_argument("--panel-root", default=None)
    p_exp.add_argument("--out", default=None, help="default: <panel-root>/reporting_expectations.parquet")
    p_exp.set_defaults(func=cmd_expectations)

    p_val = sub.add_parser("validate", help="run a validator against a built panel")
    p_val.add_argument("check", choices=("coverage", "breaks", "quarterize", "all"))
    p_val.add_argument("--panel-root", default=None)
    _add_common(p_val)
    p_val.add_argument("--expectations", default=None)
    p_val.add_argument("--ledger", default="configs/coverage_expected.csv")
    p_val.add_argument("--strict", action="store_true", help="exit non-zero on new findings")
    p_val.add_argument("--save", action="store_true")
    p_val.set_defaults(func=cmd_validate)

    p_info = sub.add_parser("info", help="show a panel's build manifest")
    p_info.add_argument("--panel-root", default=None)
    p_info.set_defaults(func=cmd_info)

    p_dict = sub.add_parser("dictionary", help="print or export the data dictionary")
    p_dict.add_argument("--panel-root", default=None)
    p_dict.add_argument("--schedule", default=None)
    p_dict.add_argument("--format", default="table", choices=("table", "csv", "json"))
    p_dict.add_argument("--out", default=None)
    p_dict.set_defaults(func=cmd_dictionary)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
