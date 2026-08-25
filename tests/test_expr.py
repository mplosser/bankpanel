"""The formula language: what it allows, what it blocks, and what it depends on."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bankpanel.expr import FormulaError, dependencies, evaluate, parse_formula

BLOCKED = [
    '__import__("os").system("echo hi")',
    "a.__class__.__bases__",
    "().__class__.__mro__",
    "[x for x in a]",
    "(lambda: 1)()",
    "a.to_csv('/tmp/leak.csv')",
    "a.apply(print)",
    "open('secrets')",
    "a[0]",
]


@pytest.mark.parametrize("formula", BLOCKED)
def test_blocks_escapes(formula):
    with pytest.raises(FormulaError):
        parse_formula(formula, where="test")


ALLOWED = [
    "a + b",
    "a - b * 2",
    "a.fillna(b).fillna(0)",
    "a.fillna(0) + b.fillna(0)",
    "(a + b).clip(0, 100)",
    "a.where(a.notna() | b.notna())",
    "log(a) - sqrt(b)",
    "maximum(a, b)",
    "a / b",
    "(a - b).abs()",
]


@pytest.mark.parametrize("formula", ALLOWED)
def test_allows_real_idioms(formula):
    parse_formula(formula, where="test")


def test_dependencies_exclude_methods_and_builtins():
    """AST-based extraction, so method names are never mistaken for variables."""
    assert dependencies("a.fillna(b).clip(0, 1) + log(c)") == {"a", "b", "c"}


def test_elementwise_boolean_ops_work():
    """`|` and `&`, not `or`/`and`: pandas raises on the truth value of a Series."""
    a = pd.Series([1.0, np.nan, 3.0])
    b = pd.Series([np.nan, np.nan, 6.0])
    out = evaluate("(a.fillna(0) + b.fillna(0)).where(a.notna() | b.notna())", {"a": a, "b": b})
    assert out.tolist()[0] == 1.0
    assert pd.isna(out.tolist()[1])
    assert out.tolist()[2] == 9.0


def test_typo_raises_rather_than_binding_something_else():
    with pytest.raises(FormulaError, match="NameError"):
        evaluate("assets_totl + 1", {"assets_total": pd.Series([1.0])}, where="test")


def test_error_message_names_the_source():
    with pytest.raises(FormulaError, match="configs/rc.csv:12"):
        parse_formula("a.__dict__", where="configs/rc.csv:12")


def test_fillna_cascade_coalesces_in_order():
    """The era-stitching idiom, which is why `eval` is kept at all."""
    first = pd.Series([np.nan, np.nan, 3.0])
    second = pd.Series([np.nan, 2.0, 99.0])
    third = pd.Series([1.0, 99.0, 99.0])
    out = evaluate(
        "first.fillna(second).fillna(third)",
        {"first": first, "second": second, "third": third},
    )
    assert out.tolist() == [1.0, 2.0, 3.0]
