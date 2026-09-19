"""Dependency graph over config variables.

Two consumers, one graph:

* the **builder** needs a topological evaluation order, and the exact dependency set of
  each formula so it can evaluate against a minimal namespace;
* the **coverage validator** needs each formula's inputs, so it can explain a flagged
  transition in terms of the stitch that was supposed to absorb it.

The legacy code derived the second of those independently, by re-parsing the config CSVs
inside ``coverage_check.py``. Two parsers over one format is how a validator ends up
disagreeing with the thing it validates.
"""

from __future__ import annotations

import graphlib
from dataclasses import dataclass

from ..expr import FormulaError, dependencies
from .model import BUILTIN_COLUMNS, ConfigError, DerivedVar


@dataclass
class DependencyGraph:
    base_names: set[str]
    derived_names: set[str]
    deps: dict[str, set[str]]
    order: list[str]
    referenced: set[str]

    @property
    def all_names(self) -> set[str]:
        return self.base_names | self.derived_names

    def terminal_names(self) -> set[str]:
        """Variables that no derived formula reads.

        Useful for documentation -- these are leaf outputs -- but deliberately **not**
        the rule the coverage validator uses to decide what to skip.

        The legacy validator did skip every base variable feeding a derived formula, on
        the theory that such a variable must be an era piece whose coverage is *supposed*
        to start and stop partway through the panel. That over-skips badly. ``assets_total``
        and ``int_inc_total`` are read by ratio formulas, which would exempt two of the
        most important series in the panel from coverage checking entirely.

        Era membership is declared, not inferred: a base variable carries ``era_start`` /
        ``era_end``, and the validator checks its coverage only inside that window. See
        ``validate/coverage.py``.
        """
        return self.all_names - self.referenced

    def transitive_inputs(self, name: str) -> set[str]:
        """Every base variable that feeds ``name``, directly or through other derived vars."""
        seen: set[str] = set()
        stack = [name]
        while stack:
            current = stack.pop()
            for dep in self.deps.get(current, ()):
                if dep in seen:
                    continue
                seen.add(dep)
                if dep in self.deps:
                    stack.append(dep)
        return seen & self.base_names


def build_graph(base_names: set[str], derived: list[DerivedVar]) -> DependencyGraph:
    """Resolve dependencies, validate every reference, and topologically sort.

    Raises :class:`ConfigError` on an unknown identifier or a dependency cycle.
    """
    derived_names = {d.variable_name for d in derived}
    # A builtin may be referenced but is not a dependency: it is supplied by the builder,
    # not produced by a config, so it must not appear in deps (which drive evaluation
    # order, the intermediate lint, and every validator's notion of "inputs").
    known = base_names | derived_names | BUILTIN_COLUMNS

    deps: dict[str, set[str]] = {}
    referenced: set[str] = set()

    for var in derived:
        where = str(var.origin)
        try:
            raw_deps = dependencies(var.formula, where=where) - BUILTIN_COLUMNS
        except FormulaError as exc:
            raise ConfigError(str(exc)) from None

        unknown = sorted(raw_deps - known)
        if unknown:
            # The legacy engine swallowed this: the NameError was caught, a warning was
            # printed, and the variable was simply absent from the output panel.
            raise ConfigError(
                f"{where}: formula for {var.variable_name!r} references unknown "
                f"variable(s) {unknown}.\n  {var.formula}\n"
                f"  Every name must be a base or derived variable defined in some config."
            )
        if var.variable_name in raw_deps:
            raise ConfigError(
                f"{where}: formula for {var.variable_name!r} references itself.\n  {var.formula}"
            )
        deps[var.variable_name] = raw_deps
        referenced |= raw_deps

    sorter = graphlib.TopologicalSorter(deps)
    try:
        order = [n for n in sorter.static_order() if n in derived_names]
    except graphlib.CycleError as exc:
        cycle = " -> ".join(exc.args[1])
        raise ConfigError(f"dependency cycle among derived variables: {cycle}") from None

    return DependencyGraph(
        base_names=set(base_names),
        derived_names=derived_names,
        deps=deps,
        order=order,
        referenced=referenced,
    )
