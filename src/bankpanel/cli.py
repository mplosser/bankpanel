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
