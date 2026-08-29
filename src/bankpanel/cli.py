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

    if args.check in ("quality", "all"):
        from .validate.quality import format_report, gate, run_checks

        cs = ConfigSet.load(args.config_dir)
        results = run_checks(df, cs.checks)
        print()
        print(format_report(results))
        saved["quality_checks"] = results

        from .validate.quality import find_fabricated_values, format_fabricated

        fabricated = find_fabricated_values(df, cs)
        print(format_fabricated(fabricated))
        saved["fabricated_values"] = fabricated
        # Reported, not gated: the remaining cases are legacy columns kept bit-identical
        # for parity with the source pipeline, so failing the build on them would make the
        # gate unusable rather than useful.
        exit_code = max(exit_code, gate(results))

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


def _schedule_codes(schedule: str, map_path: str) -> list[str]:
    import pandas as pd

    smap = pd.read_csv(map_path)
    return smap.loc[smap.schedule.str.upper() == schedule.upper(), "mdrm_code"].tolist()


def cmd_propose(args: argparse.Namespace) -> int:
    """Draft config rows for codes in a schedule that no config currently claims."""
    import pandas as pd

    from .build.source import discover_quarters
    from .config import ConfigSet
    from .profiles import get_profile
    from .reference.enrich import measure_codes, propose_rows, summarize, to_config_csv
    from .reference.mdrm import load_mdrm

    profile = get_profile(args.profile)
    cs = ConfigSet.load(args.config_dir)
    existing_names = {v.variable_name for v in (*cs.base, *cs.derived)}

    # A claimed code also claims its coalesce sibling. RCON1766 is the domestic twin of
    # RCFD1766, and the builder already fills one from the other per row, so proposing
    # the sibling as a separate variable would produce two columns for one concept --
    # nearly identical, and silently different only for banks with foreign offices.
    claimed = {v.mdrm_code for v in cs.base}
    for code in list(claimed):
        for primary, fallback in profile.coalesce_rules:
            if code.startswith(primary):
                claimed.add(fallback + code[len(primary):])
            elif code.startswith(fallback):
                claimed.add(primary + code[len(fallback):])

    in_schedule = _schedule_codes(args.schedule, args.schedule_map)
    codes = [c for c in in_schedule if c not in claimed]
    print(
        f"{args.schedule}: {len(codes)} code(s) unclaimed of {len(in_schedule)} in the "
        f"schedule ({len(in_schedule) - len(codes)} already covered, counting coalesce siblings)"
    )
    if not codes:
        return 0

    quarters = discover_quarters(args.raw_dir, profile, years=_parse_years(args.years))
    measured = measure_codes(quarters, codes, profile)
    summary = summarize(measured)
    if summary.empty:
        print("none of those codes carry data in this source")
        return 0

    # Collapse coalesce pairs within the proposal set too. If neither RCFD1563 nor
    # RCON1563 is claimed, both get proposed -- but one variable pointing at the primary
    # already picks up the other per row, so proposing both would create two columns for
    # one concept.
    measured_codes = set(summary.mdrm_code)
    indexed = summary.set_index("mdrm_code")
    drop = set()
    for code in measured_codes:
        for primary, fallback in profile.coalesce_rules:
            if not code.startswith(primary):
                continue
            sibling = fallback + code[len(primary):]
            if sibling not in measured_codes:
                continue
            # The built column is the union of the pair, so it must be MEASURED as the
            # union too. Otherwise a domestic item whose RCFD twin exists but is filed
            # only by the ~1.6% of banks on form 031 looks sparse, and the density filter
            # discards a variable that would in fact be near-universal.
            a, b = indexed.loc[code], indexed.loc[sibling]
            indexed.loc[code, "peak_coverage"] = max(a.peak_coverage, b.peak_coverage)
            indexed.loc[code, "first_quarter"] = min(
                x for x in (a.first_quarter, b.first_quarter) if pd.notna(x)
            ) if pd.notna(a.first_quarter) or pd.notna(b.first_quarter) else pd.NaT
            indexed.loc[code, "last_quarter"] = max(
                x for x in (a.last_quarter, b.last_quarter) if pd.notna(x)
            ) if pd.notna(a.last_quarter) or pd.notna(b.last_quarter) else pd.NaT
            for form in (31, 41, 51):
                col = f"cov_{form}"
                indexed.loc[code, col] = max(
                    a.get(col, float("nan")) or 0, b.get(col, float("nan")) or 0
                )
            drop.add(sibling)
    summary = indexed.reset_index()
    if drop:
        summary = summary[~summary.mdrm_code.isin(drop)]
        print(f"{len(drop)} coalesce sibling(s) merged into their primary code")

    confidential = summary[summary.get("confidential", False).fillna(False)]
    if not confidential.empty:
        print(
            f"{len(confidential)} code(s) are collected but NOT PUBLISHED (every cell is "
            f'the literal "CONF"); excluded: {sorted(confidential.mdrm_code)[:6]}'
            + (" ..." if len(confidential) > 6 else "")
        )
        summary = summary[~summary.mdrm_code.isin(confidential.mdrm_code)]

    mdrm = load_mdrm(args.mdrm)
    proposed = propose_rows(
        summary, args.schedule, mdrm,
        existing_names=existing_names, dense_threshold=args.min_coverage,
    )
    print(
        f"{len(summary)} measured; {len(proposed)} reach {args.min_coverage:.0%} coverage "
        f"in at least one quarter"
    )
    text = to_config_csv(proposed)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"-> {args.out}   (review, rename, then paste into a config)")
    else:
        print()
        print(text)
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    """Fill blank era/form_scope/notes on an existing config from measured data."""
    from .build.source import discover_quarters
    from .config import parse_config_file
    from .profiles import get_profile
    from .reference.enrich import fill_blanks, measure_codes, summarize
    from .reference.mdrm import load_mdrm

    profile = get_profile(args.profile)
    cfg = parse_config_file(args.config)
    codes = [v.mdrm_code for v in cfg.base]
    print(f"{Path(args.config).name}: measuring {len(codes)} code(s)")

    quarters = discover_quarters(args.raw_dir, profile, years=_parse_years(args.years))
    summary = summarize(measure_codes(quarters, codes, profile))
    if summary.empty:
        print("no data measured; nothing to fill")
        return 0

    text = fill_blanks(args.config, summary, load_mdrm(args.mdrm))
    out = Path(args.out) if args.out else Path(args.config)
    out.write_text(text, encoding="utf-8")
    print(f"-> {out}   (only blank fields were filled; existing values untouched)")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    from .io.reader import info

    for key, value in info(args.panel_root).items():
        if isinstance(value, list) and len(value) > 8:
            value = f"[{value[0]} ... {value[-1]}] ({len(value)} items)"
        print(f"{key:>20}: {value}")
    return 0


def cmd_dictionary(args: argparse.Namespace) -> int:
    from .io.dictionary import measure_dictionary
    from .io.reader import _resolve_root, dictionary

    df = dictionary(args.panel_root)
    if args.measure:
        df = measure_dictionary(df, _resolve_root(args.panel_root))
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
    p_val.add_argument("check", choices=("coverage", "breaks", "quarterize", "quality", "all"))
    p_val.add_argument("--panel-root", default=None)
    _add_common(p_val)
    p_val.add_argument("--expectations", default=None)
    p_val.add_argument("--ledger", default="configs/coverage_expected.csv")
    p_val.add_argument("--strict", action="store_true", help="exit non-zero on new findings")
    p_val.add_argument("--save", action="store_true")
    p_val.set_defaults(func=cmd_validate)

    p_prop = sub.add_parser("propose", help="draft config rows for an uncovered schedule")
    _add_common(p_prop)
    p_prop.add_argument("--schedule", required=True, help="e.g. RC-C")
    p_prop.add_argument("--raw-dir", required=True)
    p_prop.add_argument("--profile", default="ffiec_call")
    p_prop.add_argument("--schedule-map", default="reference_data/mdrm_to_schedule.csv")
    p_prop.add_argument("--mdrm", default=None)
    p_prop.add_argument("--years", default=None)
    p_prop.add_argument("--min-coverage", type=float, default=0.50)
    p_prop.add_argument("--out", default=None)
    p_prop.set_defaults(func=cmd_propose)

    p_enr = sub.add_parser("enrich", help="fill blank metadata on a config from measured data")
    p_enr.add_argument("--config", required=True)
    p_enr.add_argument("--raw-dir", required=True)
    p_enr.add_argument("--profile", default="ffiec_call")
    p_enr.add_argument("--mdrm", default=None)
    p_enr.add_argument("--years", default=None)
    p_enr.add_argument("--out", default=None, help="default: edit the config in place")
    p_enr.set_defaults(func=cmd_enrich)

    p_info = sub.add_parser("info", help="show a panel's build manifest")
    p_info.add_argument("--panel-root", default=None)
    p_info.set_defaults(func=cmd_info)

    p_dict = sub.add_parser("dictionary", help="print or export the data dictionary")
    p_dict.add_argument("--panel-root", default=None)
    p_dict.add_argument("--schedule", default=None)
    p_dict.add_argument("--format", default="table", choices=("table", "csv", "json"))
    p_dict.add_argument(
        "--measure",
        action="store_true",
        help="scan the panel and append measured coverage, era and emptiness per column",
    )
    p_dict.add_argument("--out", default=None)
    p_dict.set_defaults(func=cmd_dictionary)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
