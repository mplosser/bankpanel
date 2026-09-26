"""Orchestration: config -> lint -> fan out over years -> manifest.

Note on ``jobs > 1``: Windows and macOS start worker processes with *spawn*, which
re-imports the calling module. Callers must therefore guard their entry point with
``if __name__ == "__main__":`` -- the ``bankpanel build`` CLI does this for you. Calling
:func:`build` with ``jobs > 1`` from an unguarded script or a REPL raises
``BrokenProcessPool``; use ``jobs=1`` there.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from .. import __version__
from ..config import ConfigSet
from ..profiles import FFIEC_CALL, ReportProfile
from .source import QuarterFile, discover_quarters
from .writer import BuildManifest
from .year import YearResult, build_year


def _group_by_year(quarters: list[QuarterFile]) -> dict[int, list[QuarterFile]]:
    grouped: dict[int, list[QuarterFile]] = defaultdict(list)
    for qf in quarters:
        grouped[qf.year].append(qf)
    return dict(sorted(grouped.items()))


def build(
    raw_dir: str | Path,
    out: str | Path,
    *,
    config_dir: str | Path,
    profile: ReportProfile = FFIEC_CALL,
    years: tuple[int, int] | None = None,
    jobs: int = 1,
    gap_policy: str = "nan",
    keep_going: bool = False,
    era_starts: dict[str, pd.Timestamp] | None = None,
    strict_lint: bool = False,
    progress: bool = True,
) -> BuildManifest:
    """Build the panel. Returns the manifest that was written to ``out``."""
    out_root = Path(out)
    cs = ConfigSet.load(config_dir)
    issues = cs.lint(strict=strict_lint)
    if progress and issues:
        print(f"[lint] {len(issues)} warning(s):")
        for issue in issues:
            print(f"  {issue}")

    quarters = discover_quarters(raw_dir, profile, years=years)
    by_year = _group_by_year(quarters)

    # Pre-pass: measure when each in-era zero-fill target began being collected. This is
    # the one whole-panel question the per-year workers cannot answer for themselves, so
    # it is resolved once, up front, and handed to them as data.
    if era_starts is None:
        from ..reference.eras import detect_eras, in_era_columns

        needed = in_era_columns(cs)
        era_starts = detect_eras(quarters, cs, profile, needed) if needed else {}
        if progress and needed:
            print(f"[eras] measured collection start for {len(era_starts)}/{len(needed)} column(s)")
    if progress:
        print(
            f"[build] {len(quarters)} quarters across {len(by_year)} years; "
            f"{len(cs.base)} base + {len(cs.derived)} derived variables; "
            f"gap-policy={gap_policy}; jobs={jobs}"
        )

    results: list[YearResult] = []
    if jobs <= 1:
        for year, files in by_year.items():
            results.append(
                build_year(
                    year, files, cs, profile, out_root,
                    era_starts=era_starts, gap_policy=gap_policy, keep_going=keep_going,
                )
            )
            if progress:
                print(f"  {year}: {results[-1].n_rows:,} rows")
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = {
                pool.submit(
                    build_year, year, files, cs, profile, out_root,
                    era_starts=era_starts, gap_policy=gap_policy, keep_going=keep_going,
                ): year
                for year, files in by_year.items()
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                if progress:
                    print(f"  {result.year}: {result.n_rows:,} rows")

    results.sort(key=lambda r: r.year)

    # The dictionary is part of the deliverable, not an afterthought: descriptions are
    # accumulated across every quarter because a code retired in 1996 has no label in a
    # 2025 file. Footer reads only.
    from ..io.dictionary import build_dictionary, collect_descriptions, write_dictionary

    descriptions = collect_descriptions(quarters, set(cs.mdrm_codes(profile.coalesce_rules)))
    write_dictionary(build_dictionary(cs, descriptions), out_root)

    # The official consolidated-vs-domestic evaluation (profiles.ReportProfile.domestic_pairs):
    # per quarter and column, international banks left blank rather than given a domestic
    # figure, and how often a FILED consolidated value equals the domestic one exactly at a
    # bank with material foreign business. Read by `bankpanel validate scope`.
    scope = [r.scope for r in results if not r.scope.empty]
    if scope:
        pd.concat(scope, ignore_index=True).to_parquet(out_root / "consolidated_scope.parquet", index=False)

    gaps = [r.gaps for r in results if not r.gaps.empty]
    if gaps:
        pd.concat(gaps, ignore_index=True).to_parquet(
            out_root / "quarterize_gaps.parquet", index=False
        )

    manifest = BuildManifest(
        bankpanel_version=__version__,
        profile=profile.name,
        config_hash=cs.config_hash(),
        config_files=[c.path.name for c in cs.configs],
        raw_dir=str(Path(raw_dir)),
        gap_policy=gap_policy,
        years=[r.year for r in results if r.n_rows],
        n_rows=sum(r.n_rows for r in results),
        n_columns=len(cs.output_columns()) + len(cs.flow_columns()) + 3,
        date_min=f"{min(q.year for q in quarters)}Q1",
        date_max=max(quarters, key=lambda q: (q.year, q.quarter)).label,
        built_at=_dt.datetime.now().isoformat(timespec="seconds"),
        failures=[f for r in results for f in r.failures],
    )
    manifest.write(out_root)
    if progress:
        print(f"[build] {manifest.n_rows:,} rows x {manifest.n_columns} columns -> {out_root}")
        if manifest.failures:
            print(f"[build] {len(manifest.failures)} quarter(s) failed and were skipped:")
            for failure in manifest.failures:
                print(f"  {failure}")
    return manifest
