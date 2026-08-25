"""The merged view of every config file: one namespace, one graph, one output schema."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from .graph import DependencyGraph, build_graph
from .lint import LintIssue, has_errors, lint_configs
from .model import BaseVar, Config, ConfigError, DerivedVar, ZeroFillRule
from .parser import parse_config_file

#: Files that live in ``configs/`` but are ledgers, not variable definitions.
LEDGER_FILES = frozenset({
    "coverage_expected.csv",
    "reporting_expectations_overrides.csv",
})


@dataclass
class ConfigSet:
    configs: list[Config] = field(default_factory=list)
    _graph: DependencyGraph | None = None

    # --- construction ---------------------------------------------------------------

    @classmethod
    def load(cls, config_dir: str | Path) -> ConfigSet:
        """Parse every variable-definition config in ``config_dir``."""
        config_dir = Path(config_dir)
        if not config_dir.is_dir():
            raise ConfigError(f"config directory not found: {config_dir}")
        paths = sorted(
            p for p in config_dir.glob("*.csv")
            if p.name not in LEDGER_FILES and not p.name.startswith("_")
        )
        if not paths:
            raise ConfigError(f"no config files found in {config_dir}")
        return cls(configs=[parse_config_file(p) for p in paths])

    # --- merged views ---------------------------------------------------------------

    @property
    def base(self) -> list[BaseVar]:
        return [v for cfg in self.configs for v in cfg.base]

    @property
    def derived(self) -> list[DerivedVar]:
        return [v for cfg in self.configs for v in cfg.derived]

    @property
    def zero_fill(self) -> list[ZeroFillRule]:
        return [r for cfg in self.configs for r in cfg.zero_fill]

    @property
    def graph(self) -> DependencyGraph:
        if self._graph is None:
            self._graph = build_graph({v.variable_name for v in self.base}, self.derived)
        return self._graph

    def variable(self, name: str) -> BaseVar | DerivedVar:
        for var in self.base:
            if var.variable_name == name:
                return var
        for var in self.derived:
            if var.variable_name == name:
                return var
        raise KeyError(name)

    # --- derived products -----------------------------------------------------------

    def mdrm_codes(self) -> list[str]:
        """Every raw code to read, including auto-synthesized RCON siblings.

        For each configured ``RCFD`` code we also read the same-suffix ``RCON`` code so
        the builder can coalesce them per row. This matters because the 2011Q1 move to
        the FFIEC CDR source left many alphanumeric items reported under RCON by the
        ~98% of banks filing form 041, while RCFD kept only the ~1.6% filing form 031.
        Without the sibling, those series collapse to near-zero coverage at 2011Q1.

        (For all-numeric item codes the upstream parser already cross-fills the pair, so
        the coalesce is a harmless no-op there. See docs/CAVEATS.md.)
        """
        codes = [v.mdrm_code for v in self.base]
        siblings = ["RCON" + c[4:] for c in codes if c.startswith("RCFD")]
        return list(dict.fromkeys(codes + siblings))

    def output_columns(self) -> list[str]:
        """Panel column order: declaration order, not evaluation order.

        Deliberately distinct from :attr:`graph.order`. Evaluation must follow the
        dependency DAG, but the *schema* should be stable under formula edits, so that
        rewriting one formula does not reshuffle every partition's column order.
        """
        return [v.variable_name for v in self.base] + [v.variable_name for v in self.derived]

    def flow_types(self) -> dict[str, str]:
        return {v.variable_name: v.flow_type for v in (*self.base, *self.derived)}

    def ytd_columns(self) -> list[str]:
        return [n for n, ft in self.flow_types().items() if ft == "ytd"]

    def schedules(self) -> dict[str, str]:
        return {v.variable_name: v.schedule for v in (*self.base, *self.derived)}

    def config_hash(self) -> str:
        """Content hash of every config file, recorded in the build manifest."""
        digest = hashlib.sha256()
        for cfg in sorted(self.configs, key=lambda c: c.path.name):
            digest.update(cfg.path.name.encode())
            digest.update(cfg.path.read_bytes())
        return digest.hexdigest()[:16]

    # --- validation -----------------------------------------------------------------

    def lint(self, *, strict: bool = False) -> list[LintIssue]:
        """Run every cross-config check. Raises :class:`ConfigError` on any error.

        ``strict=True`` promotes warnings to errors (used in CI).
        """
        issues = lint_configs(self.configs, self.graph)
        fatal = has_errors(issues) or (strict and issues)
        if fatal:
            lines = "\n".join(f"  {i}" for i in issues)
            raise ConfigError(f"config validation failed ({len(issues)} issue(s)):\n{lines}")
        return issues
