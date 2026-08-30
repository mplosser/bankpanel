"""Era-stitch continuity: does the quantity step when its source changes?

The other validators watch *reporting*. This one watches the **handoff**. An era stitch --
``rwa_baselIII.fillna(rwa_baselI)``, ``ln_oth_consol.fillna(ln_oth_dom)``, a reported total
falling back to a sum of its subcomponents -- swaps which MDRM code supplies a column at
some quarter. On both sides of that quarter every source reports perfectly, so coverage
sees nothing, breaks sees nothing, and quality sees nothing. What can go wrong is the
*level*: the two codes may not measure quite the same thing, and the series steps.

That is the failure this catches, and nothing else in the repo would.

Three things make the test trustworthy:

**Balanced panel.** The jump is measured only over banks reporting the column in BOTH the
quarter before and the quarter after. Otherwise an era boundary that also changes who files
-- and they usually do -- shows a level shift that is pure composition.

**Level-free threshold.** The jump is scored against the column's *own* quarter-to-quarter
volatility in the surrounding window, not against a fixed percentage. A 20% move is nothing
in trading revenue and enormous in total assets, and a single threshold would either miss
the second or drown in the first.

**Handoffs are found from the data.** The dominant source is whichever input actually
supplies the column that quarter, so the check needs no declared era bounds and cannot
drift out of step with the configs.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

#: Minimum banks reporting on both sides before a handoff is scored at all.
MIN_BALANCED = 100

#: Window of quarters either side used to establish normal volatility.
BASELINE_WINDOW = 8

#: Robust z above which the step is reported. MAD-based, so a couple of genuinely
#: turbulent quarters in the baseline cannot mask a stitch break.
Z_WARN = 4.0
Z_CRIT = 8.0

#: A jump this small is not worth reporting however quiet the series is -- below it the
#: difference is rounding and reclassification, not a definitional break.
MIN_JUMP = 0.02


#: Label for the branch that has no single source column -- a reported total falling back
#: to a sum of its subcomponents. Naming it rather than picking one of the 22 terms is the
#: point: "reported" -> "constructed" is the transition worth watching.
CONSTRUCTED = "<constructed>"


def _chain(formula: str) -> list[str]:
    """Named links of a coalesce chain, in the order the formula resolves them.

    ``a.fillna(b).fillna(c)`` gives ``[a, b, c]``. A fallback that is an *expression*
    rather than a column -- ``reported.fillna(x + y + z)`` -- contributes no name; those
    rows are labelled :data:`CONSTRUCTED` instead, which is the distinction that matters.
    """
    if ".fillna(" not in formula:
        return []
    head = re.findall(r"[A-Za-z_]\w*", formula.split(".fillna(")[0])
    tail = re.findall(r"\.fillna\(\s*([A-Za-z_]\w*)\s*\)", formula)
    return head + tail


def find_stitch_steps(df: pd.DataFrame, configset, *, date_col: str = "REPORTING_PERIOD",
                      id_col: str = "RSSD_ID") -> pd.DataFrame:
    """Level discontinuities at the quarter a column changes source."""
    period = pd.PeriodIndex(df[date_col], freq="Q")
    quarters = period.unique().sort_values()
    rows: list[dict] = []

    for var in configset.derived:
        name = var.variable_name
        chain = [c for c in _chain(var.formula) if c in df.columns]
        # One named link plus an expression fallback still stitches two eras together.
        if name not in df.columns or not chain or ".fillna(" not in var.formula:
            continue

        # Which source supplied each row: the first link of the chain that is present,
        # else the unnamed fallback branch. Then the modal source per quarter. Read from
        # the data, so it cannot drift out of step with declared era bounds.
        built = df[name].notna()
        source = pd.Series(CONSTRUCTED, index=df.index, dtype=object)
        assigned = pd.Series(False, index=df.index)
        for link in chain:
            take = df[link].notna() & ~assigned
            source[take] = link
            assigned |= take
        source = source.where(built)
        modal = source.groupby(period).agg(lambda s: s.mode().iat[0] if len(s.mode()) else None)
        dominant = {q: v for q, v in modal.items() if v is not None}

        # Per-quarter aggregate over a panel balanced against the previous quarter, so a
        # change in who files cannot masquerade as a change in level.
        frame = pd.DataFrame({"q": period, "id": df[id_col], "v": df[name]}).dropna()
        growth: dict[pd.Period, float] = {}
        counts: dict[pd.Period, int] = {}
        by_quarter = {q: g.set_index("id")["v"] for q, g in frame.groupby("q")}
        for previous, current in zip(quarters[:-1], quarters[1:], strict=False):
            a, b = by_quarter.get(previous), by_quarter.get(current)
            if a is None or b is None:
                continue
            shared = a.index.intersection(b.index)
            counts[current] = len(shared)
            total_a, total_b = a[shared].sum(), b[shared].sum()
            if len(shared) >= MIN_BALANCED and total_a > 0 and total_b > 0:
                growth[current] = float(np.log(total_b / total_a))

        series = pd.Series(growth).sort_index()
        for previous, current in zip(quarters[:-1], quarters[1:], strict=False):
            before, after = dominant.get(previous), dominant.get(current)
            if not before or not after or before == after or current not in series:
                continue
            window = series[
                (series.index >= current - BASELINE_WINDOW)
                & (series.index <= current + BASELINE_WINDOW)
                & (series.index != current)
            ]
            if len(window) < 4:
                continue
            centre = float(window.median())
            # MAD, scaled to be comparable with a standard deviation on normal data.
            spread = float(1.4826 * (window - centre).abs().median())
            step = series[current] - centre
            z = abs(step) / spread if spread > 0 else np.inf
            if abs(step) < MIN_JUMP:
                continue
            rows.append({
                "column": name,
                "quarter": str(current),
                "from_source": before,
                "to_source": after,
                "n_balanced": counts.get(current, 0),
                "jump": round(float(np.expm1(step)), 4),
                "baseline_sd": round(spread, 4),
                "z": round(float(z), 1) if np.isfinite(z) else np.inf,
                "severity": "critical" if z >= Z_CRIT else ("warning" if z >= Z_WARN else "info"),
            })

    columns = ["column", "quarter", "from_source", "to_source", "n_balanced", "jump",
               "baseline_sd", "z", "severity"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows).sort_values("z", ascending=False).reset_index(drop=True)


def format_report(found: pd.DataFrame) -> str:
    lines = ["=" * 78, "ERA-STITCH CONTINUITY", "=" * 78]
    if found.empty:
        lines.append("no handoff moves the level more than its own surrounding volatility.")
        return "\n".join(lines)
    flagged = found[found.severity != "info"]
    lines.append(
        f"{len(found)} handoff(s) with a step above {MIN_JUMP:.0%}; "
        f"{len(flagged)} beyond {Z_WARN} robust sd of the column's own volatility."
    )
    lines.append("")
    lines.append(f"{'column':<28}{'quarter':>8}{'jump':>9}{'z':>7}{'banks':>8}  source change")
    for _, row in found.iterrows():
        z = "inf" if not np.isfinite(row.z) else f"{row.z:.1f}"
        lines.append(
            f"{row['column'][:27]:<28}{row.quarter:>8}{row.jump:>9.1%}{z:>7}"
            f"{row.n_balanced:>8,}  {row.from_source} -> {row.to_source}"
        )
    return "\n".join(lines)


def gate(found: pd.DataFrame) -> int:
    if found.empty:
        return 0
    return 1 if (found.severity == "critical").any() else 0
