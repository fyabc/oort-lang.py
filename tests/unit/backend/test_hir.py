#! /usr/bin/env python

"""HIR lowering and structural validation for the shared backend."""

import pytest

from oort_lang.diagnostics.syntax_errors import UnsupportedSyntax
from oort_lang.hir import (
    BuildClass,
    BuildDict,
    BuildList,
    BuildSlice,
    Call,
    DefineFunction,
    GetAttr,
    GetItem,
    ImportFrom,
    ImportModule,
    JumpIfFalse,
    JumpIfTrue,
    Label,
    LoadGlobal,
    LoadLocal,
    LoadOuter,
    MakeClosure,
    SetAttr,
    StoreGlobal,
    StoreLocal,
    StoreOuter,
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
print(xs[1], {: "a": 1 :}["a"], xs[0:1])
"""
    )
    code = module.main.code
    assert any(isinstance(i, BuildList) for i in code)
    assert any(isinstance(i, BuildDict) for i in code)
    assert any(isinstance(i, GetItem) for i in code)
    assert any(isinstance(i, BuildSlice) for i in code)


def test_attributes_lower_to_get_and_set():
    module = lower(
        """val xs = [1, 2]
print(xs.length)
xs.foo = 1
"""
    )
    code = module.main.code
    assert any(isinstance(i, GetAttr) for i in code)
    assert any(isinstance(i, SetAttr) for i in code)


def test_lambdas_lower_to_function_values():
    module = lower(
        """val double = do: $0 * 2
val inc = do(x): x + 1
print(double(3), inc(4))
"""
    )
    closures = [i for i in module.main.code if isinstance(i, MakeClosure)]
    assert len(closures) == 2
    lambdas = [function for function in module.functions if function.is_lambda]
    assert len(lambdas) == 2
    assert lambdas[0].params == ("$0",)
    assert lambdas[1].params == ("x",)


def test_closures_read_and_write_outer_locals():
    module = lower(
        """def make(n) {
    var total = n
    do(v): {
        total = total + v
        total
    }
}
val f = make(1)
print(f(2))
"""
    )
    closure = next(function for function in module.functions if function.is_lambda)
    assert any(isinstance(i, LoadOuter) and i.depth == 1 for i in closure.code)
    assert any(isinstance(i, StoreOuter) for i in closure.code)


def test_classes_lower_methods_with_this():
    module = lower(
        """class C {
    def __init__(n) { this.n = n }
    def get() { this.n }
}
val c = C(1)
print(c.get())
"""
    )
    build = next(i for i in module.main.code if isinstance(i, BuildClass))
    assert build.name == "C"
    assert [name for name, _ in build.methods] == ["__init__", "get"]
    methods = [module.functions[index] for _, index in build.methods]
    assert [method.name for method in methods] == ["__init__", "get"]
    assert all(method.has_this for method in methods)
    assert methods[0].params == ("this", "n")
    assert methods[1].params == ("this",)


def test_class_bases_lower_to_registers():
    module = lower(
        """class Base { def value() { 1 } }
class Derived < Base { def value() { 2 } }
print(Derived().value())
"""
    )
    builds = [i for i in module.main.code if isinstance(i, BuildClass)]
    assert builds[0].bases == ()
    assert len(builds[1].bases) == 1


def test_calls_accept_function_values_and_subscripts():
    module = lower(
        """val f = do(x): x
print(f(1), [f][0](2))
"""
    )
    assert sum(isinstance(i, Call) for i in module.main.code) >= 3


def test_imports_lower_and_hoist_before_other_statements():
    module = lower(
        """print("before")
import "./lib"
from "./lib" import add as plus
print("after")
"""
    )
    code = module.main.code
    imports = [i for i in code if isinstance(i, (ImportModule, ImportFrom))]
    assert len(imports) == 2
    assert isinstance(imports[0], ImportModule)
    assert imports[0].module_path == "./lib"
    assert isinstance(imports[1], ImportFrom)
    assert imports[1].names == (("add", "plus"),)
    first_load = next(index for index, i in enumerate(code) if isinstance(i, LoadGlobal))
    assert code.index(imports[1]) < first_load


def test_import_bindings_are_immutable():
    with pytest.raises(UnsupportedSyntax, match="immutable global"):
        lower_module(build_ast('import "./lib"\nlib = 1\n'))
    with pytest.raises(UnsupportedSyntax, match="immutable global"):
        lower_module(build_ast('from "./lib" import add\nadd = 1\n'))


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


@pytest.mark.parametrize(
    ("source", "detail"),
    [
        ("class C { print(1) }\n", "class-body"),
        ("def f() { class C {} }\nf()\n", "nested class"),
        ("class C { def class.f: 1 }\n", "class methods"),
        ("class C { def __str__: 1 }\n", "special method"),
        ("class A { def f: 1 }\nclass C < A { def f: super.f() }\n", "ImplicitSuperExpr"),
    ],
)
def test_unsupported_class_forms_are_rejected(source: str, detail: str):
    with pytest.raises(UnsupportedSyntax, match=detail):
        lower_module(build_ast(source))


def test_lambda_inside_loop_is_rejected():
    with pytest.raises(UnsupportedSyntax, match="lambdas created inside loops"):
        lower_module(build_ast("while false { val f = do: 1 }\n"))


def test_lambda_assigning_immutable_outer_is_rejected():
    with pytest.raises(UnsupportedSyntax, match="immutable outer local"):
        lower_module(build_ast("def f() { val x = 1\n do: { x = 2 } }\nf()\n"))
