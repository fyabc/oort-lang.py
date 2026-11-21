#! /usr/bin/env python

"""HIR lowering and structural validation for the shared backend."""

import pytest

from oort_lang.diagnostics.syntax_errors import UnsupportedSyntax
from oort_lang.hir import (
    BinOp,
    BuildClass,
    BuildDict,
    BuildEnum,
    BuildList,
    BuildSlice,
    Call,
    DefineFunction,
    FreshLocals,
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
    Match,
    RegisterExtension,
    SetAttr,
    SetItem,
    StoreGlobal,
    StoreLocal,
    StoreOuter,
    SuperProxy,
    Unpack,
    lower_module,
    validate_module,
)
from oort_lang.runtime.call_protocol import ParamKind
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


def test_multiple_loop_variables_lower_to_unpack():
    module = lower(
        """for k, v in [(1, 2)] {
    print(k, v)
}
"""
    )
    unpack = next(i for i in module.main.code if isinstance(i, Unpack))
    assert unpack.count == 2
    assert unpack.source != unpack.base


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


def test_augmented_assignment_lowers_to_read_modify_write():
    module = lower(
        """var x = 1
x += 2
val xs = [1]
xs[0] *= 3
class C { def __init__() { this.n = 1 } }
val c = C()
c.n += 4
print(x, xs, c.n)
"""
    )
    ops = [instruction for instruction in module.main.code if isinstance(instruction, BinOp)]
    assert [(instruction.op) for instruction in ops] == ["+", "*", "+"]
    assert sum(isinstance(instruction, SetItem) for instruction in module.main.code) == 1
    assert sum(isinstance(instruction, SetAttr) for instruction in module.main.code) == 1


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


def test_class_methods_lower_separately_from_instance_methods():
    module = lower(
        """class C {
    def __init__(n) { this.n = n }
    def get() { this.n }
    def class.make(n) { this(n) }
}
print(C.make(1).get())
"""
    )
    build = next(i for i in module.main.code if isinstance(i, BuildClass))
    assert [name for name, _ in build.methods] == ["__init__", "get"]
    assert [name for name, _ in build.class_methods] == ["make"]
    make = module.functions[build.class_methods[0][1]]
    assert make.has_this
    assert make.params == ("this", "n")


def test_classes_lower_operator_methods_separately():
    module = lower(
        """class Num {
    def operator "+"(other) { this }
    def operator "-" { this }
}
"""
    )
    build = next(i for i in module.main.code if isinstance(i, BuildClass))
    assert [(symbol, count) for symbol, count, _ in build.operators] == [("+", 2), ("-", 1)]
    plus = module.functions[build.operators[0][2]]
    negate = module.functions[build.operators[1][2]]
    assert plus.params == ("this", "other")
    assert negate.params == ("this",)


def test_metaclass_and_super_lower():
    module = lower(
        """class M < Type {}
class Base { def name() { "base" } }
class C < Base :: M { def name() { super.name() } }
print(C().name())
"""
    )
    builds = [i for i in module.main.code if isinstance(i, BuildClass)]
    target = next(build for build in builds if build.name == "C")
    assert target.metaclass is not None
    method = module.functions[target.methods[0][1]]
    assert any(isinstance(i, SuperProxy) for i in method.code)


def test_extension_methods_lower_to_registration():
    module = lower(
        """class Counter {
    def __init__(n) { this.n = n }
}
def Counter.bump { this.n = this.n + 1 }
def Int.twice: this * 2
def String.operator "**"(times) { this }
"""
    )
    registrations = [i for i in module.main.code if isinstance(i, RegisterExtension)]
    assert [(item.name, item.symbol, item.operand_count) for item in registrations] == [
        ("bump", None, 0),
        ("twice", None, 0),
        ("operator **", "**", 2),
    ]
    for item in registrations:
        function = module.functions[item.function_index]
        assert function.has_this
        assert function.params[0] == "this"


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


def test_core_class_slots_lower_with_initializer_protos():
    module = lower(
        """#lang oort-core
class Point {
    val x: Int = 1
    var y: Int
    def __init__(y: Int) { this.y = y }
}
val p = Point(2)
print(p.x, p.y)
"""
    )
    build = next(i for i in module.main.code if isinstance(i, BuildClass))
    assert [(name, mutable) for name, mutable, _ in build.slots] == [
        ("x", False),
        ("y", True),
    ]
    x_initializer = build.slots[0][2]
    y_initializer = build.slots[1][2]
    assert x_initializer is not None
    assert y_initializer is None
    initializer = module.functions[x_initializer]
    assert initializer.name == "<slot x>"
    assert initializer.params == ()


def test_core_enums_and_match_lower():
    module = lower(
        """#lang oort-core
enum Shape {
    Circle(radius: Int),
    Empty
}
def area(shape: Shape) -> Int {
    match shape {
        Circle(r) => r * r * 3,
        Empty => 0
    }
}
print(area(Circle(2)))
"""
    )
    enum = next(i for i in module.main.code if isinstance(i, BuildEnum))
    assert enum.name == "Shape"
    assert enum.constructors == (("Circle", 1), ("Empty", 0))
    match = next(
        i
        for i in next(f for f in module.functions if f.name == "area").code
        if isinstance(i, Match)
    )
    assert [arm.pattern.kind for arm in match.arms] == ["constructor", "name"]
    assert match.arms[0].pattern.args[0].kind == "name"
    assert module.functions[match.arms[0].function_index].params == ("r",)
    assert module.functions[match.arms[1].function_index].params == ("Empty",)


def test_return_inside_match_arm_is_rejected():
    with pytest.raises(UnsupportedSyntax, match="return inside a match arm"):
        lower(
            """#lang oort-core
enum E { A, B }
def f(e: E) -> Int {
    match e {
        A => { return 1 },
        B => 2
    }
    3
}
"""
        )


def test_nested_functions_lower_to_closures():
    module = lower(
        """def outer() {
    var n = 0
    def add(step = 1) {
        n = n + step
        n
    }
    add
}
print(outer()())
"""
    )
    outer = next(function for function in module.functions if function.name == "outer")
    closures = [i for i in outer.code if isinstance(i, MakeClosure)]
    assert len(closures) == 1
    nested = module.functions[closures[0].function_index]
    assert nested.name == "add"
    assert nested.params == ("step",)
    assert nested.signature.params[0].default_index is not None
    assert any(isinstance(i, StoreLocal) for i in outer.code)


def test_nested_functions_inside_loops_lower_with_fresh_locals():
    source = """def outer() {
    for i in [1] {
        def f() { i }
    }
}
"""
    module = lower(source)
    outer = next(function for function in module.functions if function.name == "outer")
    assert any(isinstance(i, FreshLocals) for i in outer.code)
    assert any(isinstance(i, MakeClosure) for i in outer.code)


def test_signatures_and_default_protos_lower():
    module = lower(
        """def f(a, b = a + 1, /, c = 2, *args, d, e = 3, **kwargs, &block) {
    a
}
"""
    )
    function = module.functions[0]
    assert function.params == ("a", "b", "c", "args", "d", "e", "kwargs", "block")
    assert [param.kind for param in function.signature.params] == [
        ParamKind.POS_ONLY,
        ParamKind.POS_ONLY,
        ParamKind.POS_OR_KW,
        ParamKind.VAR_POS,
        ParamKind.KW_ONLY,
        ParamKind.KW_ONLY,
        ParamKind.VAR_KW,
        ParamKind.BLOCK,
    ]
    assert [param.slot for param in function.signature.params] == list(range(8))
    b_default = function.signature.params[1].default_index
    c_default = function.signature.params[2].default_index
    e_default = function.signature.params[5].default_index
    assert b_default is not None and c_default is not None and e_default is not None
    assert module.functions[b_default].params == ("a",)
    assert module.functions[c_default].params == ("a", "b")
    assert module.functions[e_default].params == ("a", "b", "c", "args", "d")


def test_method_signature_starts_after_this():
    module = lower(
        """class C {
    def f(a, b = a + 1) { a + b }
}
"""
    )
    method = next(function for function in module.functions if function.name == "f")
    assert method.signature.has_this
    assert [param.slot for param in method.signature.params] == [1, 2]
    default_index = method.signature.params[1].default_index
    assert default_index is not None
    assert module.functions[default_index].params == ("a",)


def test_call_keywords_and_block_lower():
    module = lower(
        """def f(a) { a }
f(1, c = 2) do: 3
"""
    )
    call = next(instruction for instruction in module.main.code if isinstance(instruction, Call))
    assert call.args
    assert call.keywords == (("c", call.keywords[0][1]),)
    assert call.block is not None


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
        ("...\n", "ellipsis"),
        ("val d = {: **other :}\n", "dict unpacking"),
        ("val p = (1, 2)\na, b = p\n", "attribute/tuple assignment"),
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
        ("class C { def __str__: 1 }\n", "special method"),
    ],
)
def test_unsupported_class_forms_are_rejected(source: str, detail: str):
    with pytest.raises(UnsupportedSyntax, match=detail):
        lower_module(build_ast(source))


def test_lambda_inside_loop_lowers_with_fresh_locals():
    module = lower("var fs = []\nwhile false { val f = do: 1\nfs = fs + [f] }\n")
    assert any(isinstance(i, FreshLocals) for i in module.main.code)
    assert any(isinstance(i, MakeClosure) for i in module.main.code)


def test_lambda_assigning_immutable_outer_is_rejected():
    with pytest.raises(UnsupportedSyntax, match="immutable outer local"):
        lower_module(build_ast("def f() { val x = 1\n do: { x = 2 } }\nf()\n"))
