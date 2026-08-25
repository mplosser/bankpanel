"""The config formula language: one AST allowlist, one evaluator, one dependency extractor.

Formulas are Python expressions over pandas Series. That choice is deliberate and worth
defending, because the obvious alternative -- a restricted expression evaluator such as
``simpleeval``/``asteval``, or ``pandas.eval`` -- cannot express the thing configs
actually do most:

    othbor_liab_01.fillna(othbor_9701).fillna(othbor_97).fillna(othbor_9497)

That is a NaN-coalescing cascade stitching four successive MDRM codes into one
time-consistent series. It has no arithmetic equivalent. ``pandas.eval``/numexpr support
no method calls at all, and the restricted evaluators cannot call pandas methods without
re-enabling general attribute access -- which is the thing one was trying to restrict.

So we keep ``eval`` and gate it, on the honest premise that **a config is the user's own
code**, at the same trust level as a ``.py`` file they wrote. The gate exists to catch
mistakes and to make sandbox escapes take real effort, not to defend against a determined
attacker who already controls the config.

Three properties matter more than the sandbox:

1. Dependencies come from the AST (``ast.Name`` nodes), not a regex. A regex over
   identifier tokens also matches method names, which then have to be filtered out by
   intersecting with the known-variable set -- workable, but it silently mis-scopes any
   formula whose method name collides with a variable name.
2. Each formula is evaluated against **only its own resolved dependencies**, so a typo
   raises ``NameError`` instead of silently binding some unrelated column.
3. Failures are loud. The legacy engine wrapped formula evaluation in
   ``except Exception: print(...); continue``, so a typo produced a panel that was simply
   missing a column, with the warning scrolled off the top of a 163-file progress bar.
"""

from __future__ import annotations

import ast
from typing import Any

import numpy as np

#: Expression node types the language permits.
ALLOWED_NODES: frozenset[type[ast.AST]] = frozenset({
    ast.Expression,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.Call, ast.Attribute, ast.Name, ast.Constant, ast.Load,
    ast.Tuple, ast.List, ast.keyword,
    # binary / unary operators
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod,
    ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or, ast.Invert,
    # Bitwise operators are the *elementwise* boolean operators on pandas Series.
    # `a.notna() | b.notna()` is the idiom for "either component was reported", which
    # config authors need constantly to distinguish a conditional zero from a true
    # absence. Python's `and`/`or`/`not` cannot do this -- they call __bool__ and raise
    # "truth value of a Series is ambiguous" -- so `& | ~` are not optional here.
    ast.BitAnd, ast.BitOr, ast.BitXor,
    # comparisons
    ast.Gt, ast.Lt, ast.GtE, ast.LtE, ast.Eq, ast.NotEq,
})

#: Methods callable on a pandas Series from within a formula.
ALLOWED_METHODS: frozenset[str] = frozenset({
    "fillna", "clip", "abs", "where", "mask", "notna", "isna", "isnull", "notnull",
    "astype", "round", "replace", "combine_first", "sub", "add", "div", "mul",
    "gt", "lt", "ge", "le", "eq", "ne", "pow", "sum", "min", "max", "cumsum",
    "shift", "diff", "rank", "between",
})

#: Names always available to a formula, on top of its resolved dependencies.
SAFE_FUNCTIONS: dict[str, Any] = {
    "np": np,
    "log": np.log,
    "log1p": np.log1p,
    "sqrt": np.sqrt,
    "abs": np.abs,
    "exp": np.exp,
    "maximum": np.maximum,
    "minimum": np.minimum,
    "max": np.maximum,
    "min": np.minimum,
    "where": np.where,
    "nan": np.nan,
}


class FormulaError(Exception):
    """A formula is malformed, uses a forbidden construct, or failed to evaluate."""


def parse_formula(formula: str, *, where: str = "") -> ast.Expression:
    """Parse and validate a formula against the allowlist. Returns the AST."""
    prefix = f"{where}: " if where else ""
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"{prefix}not a valid Python expression: {exc.msg}\n  {formula}") from None

    for node in ast.walk(tree):
        if type(node) not in ALLOWED_NODES:
            raise FormulaError(
                f"{prefix}formula uses {type(node).__name__}, which is not allowed here.\n"
                f"  {formula}\n"
                f"  Allowed: arithmetic, comparisons, conditionals, and calls to "
                f"whitelisted Series methods."
            )
        if isinstance(node, ast.Attribute):
            if node.attr not in ALLOWED_METHODS:
                raise FormulaError(
                    f"{prefix}method .{node.attr}() is not allowed.\n"
                    f"  {formula}\n"
                    f"  Allowed methods: {', '.join(sorted(ALLOWED_METHODS))}"
                )
        if isinstance(node, ast.Name) and "__" in node.id:
            raise FormulaError(f"{prefix}name {node.id!r} is not allowed.\n  {formula}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            # A call on a bare name must be one of the whitelisted functions. Without
            # this, `open(...)` or `eval(...)` parses cleanly and is only stopped later
            # by the empty builtins and the minimal namespace. Those layers do hold, but
            # a formula that can never work should be rejected where it is written, not
            # at the point of use.
            if node.func.id not in SAFE_FUNCTIONS:
                raise FormulaError(
                    f"{prefix}{node.func.id}() is not a function available to formulas.\n"
                    f"  {formula}\n"
                    f"  Available: {', '.join(sorted(SAFE_FUNCTIONS))}"
                )
    return tree


def dependencies(formula: str, *, where: str = "") -> set[str]:
    """Free variable names a formula reads, excluding the always-available functions.

    Uses ``ast.Name`` nodes, so method names (which are ``ast.Attribute.attr``) are
    correctly excluded without needing to be filtered against a known-name set.
    """
    tree = parse_formula(formula, where=where)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    return names - set(SAFE_FUNCTIONS)


def evaluate(formula: str, namespace: dict[str, Any], *, where: str = "") -> Any:
    """Evaluate a validated formula against ``namespace`` plus the safe functions."""
    tree = parse_formula(formula, where=where)
    scope = dict(SAFE_FUNCTIONS)
    scope.update(namespace)
    try:
        return eval(compile(tree, "<formula>", "eval"), {"__builtins__": {}}, scope)
    except FormulaError:
        raise
    except Exception as exc:
        prefix = f"{where}: " if where else ""
        raise FormulaError(
            f"{prefix}{type(exc).__name__} while evaluating\n  {formula}\n  {exc}"
        ) from exc
