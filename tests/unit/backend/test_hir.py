#! /usr/bin/env python

"""HIR lowering and structural validation for the shared backend."""

import pytest

from oort_lang.diagnostics.syntax_errors import UnsupportedSyntax
from oort_lang.hir import (
    BuildDict,
    BuildList,
    Call,
    DefineFunction,
    GetItem,
    JumpIfFalse,
    JumpIfTrue,
    Label,
    LoadLocal,
    StoreGlobal,
    StoreLocal,
    lower_module,
    validate_module,
)
from tests.helpers import build_ast


def lower(source: str):
    module = lower_module(build_ast(source))
    validate_module(module)
    return module


def test_fib_lowers_to_functions_and_calls():
    module = lower(
        """\
def fib(n) {
    if n <= 1: return n
    fib(n - 1) + fib(n - 2)
}
print(fib(10))
"""
    )
    assert [function.name for function in module.functions] == ["fib"]
    assert any(isinstance(instruction, DefineFunction) for instruction in module.main.code)
    fib = module.functions[0]
    assert fib.params == ("n",)
    assert any(isinstance(instruction, Call) for instruction in fib.code)
    assert fib.local_count > 0


def test_globals_and_block_locals_are_separate():
    module = lower(
        """\
var g = 1
{
    var x = 2
    print(x)
}
print(g)
"""
    )
    code = module.main.code
    assert any(isinstance(i, StoreGlobal) and i.name == "g" for i in code)
    assert not any(isinstance(i, StoreGlobal) and i.name == "x" for i in code)
    assert any(isinstance(i, StoreLocal) for i in code)
    assert any(isinstance(i, LoadLocal) for i in code)


def test_branches_and_loops_have_matching_labels():
    module = lower(
        """\
var total = 0
if true {
    total = total + 1
} else {
    total = total - 1
}
while total < 3 {
    total = total + 1
}
for i in range(2) {
    total = total + i
}
print(total)
"""
    )
    labels = {
        instruction.name for instruction in module.main.code if isinstance(instruction, Label)
    }
    assert labels


def test_collection_literals_and_subscripts_lower():
    module = lower(
        """var xs = [1, 2]
xs[0] = 3
print(xs[1], {: "a": 1 :}["a"])
"""
    )
    code = module.main.code
    assert any(isinstance(i, BuildList) for i in code)
    assert any(isinstance(i, BuildDict) for i in code)
    assert any(isinstance(i, GetItem) for i in code)


def test_logical_operators_short_circuit_with_jumps():
    module = lower(
        """\
print(true and false)
print(true or false)
"""
    )
    assert any(isinstance(i, JumpIfFalse) for i in module.main.code)
    assert any(isinstance(i, JumpIfTrue) for i in module.main.code)


@pytest.mark.parametrize(
    ("source", "detail"),
    [
        ("class C {}\n", "ClassDef"),
        ("val f = do: 1\n", "FunctionDef"),
        ("print([1][0:1])\n", "slices"),
        ("var x = 1\nprint(x.foo)\n", "Attribute"),
        ("def f(a) { a }\nf(a = 1)\n", "keyword"),
        ("for a, b in [1] { print(a) }\n", "multiple loop"),
        (
            "def f() {\n    def g() { 1 }\n    g()\n}\nf()\n",
            "nested function",
        ),
        ("while true { break }\n", "break/continue"),
        ("var x = 1\nx += 1\n", "augmented assignment"),
    ],
)
def test_unsupported_nodes_are_rejected(source: str, detail: str):
    with pytest.raises(UnsupportedSyntax, match=detail):
        lower_module(build_ast(source))
