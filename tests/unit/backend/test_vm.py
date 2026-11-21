#! /usr/bin/env python

"""Bytecode VM correctness and interpreter differential tests."""

import pytest

from oort_lang.driver.compiler import CompilerError
from tests.helpers import get_compiler


def run_target(source: str, target: str):
    compiler = get_compiler(["NOT_EXIST", "-t", target])
    return compiler.run_string(source)


CASES = [
    """\
def fib(n) {
    if n <= 1: return n
    fib(n - 1) + fib(n - 2)
}
print(fib(10))
""",
    """\
var total = 0
for i in range(100) {
    total = total + i
}
print(total)
""",
    """\
var g = 1
def f(a, b) {
    var x = a + b
    if x > 2 { return x * 2 }
    x
}
print(f(1, 2), f(2, 2))
while g < 4 { g = g + 1 }
print(g)
{
    var g = 9
    print(g)
}
print(g)
""",
    """\
print(1 + 2 * 3, 7 / 2, 7 // 2, 7 % 2)
print(1 < 2, 1 == 1.0, true and false, 0 or 3)
print("a" + "b")
print(1 is 1, null is null, not false)
""",
    """\
var xs = [1, 2, 3]
print(xs[0], len(xs))
xs[1] = 9
print(xs)
for x in xs {
    print(x)
}
""",
    """\
val pair = (1, "a")
val d = {: "a": 1, "b": 2 :}
val s = {. 1, 2 .}
print(pair[1], d["a"], len(d), len(s), 2 in s)
for key in d {
    print(key)
}
print([[1], [2]][0][0], "abc"[1])
""",
    """print([0, 1, 2, 3][1:3], [0, 1, 2, 3][::2], [0, 1, 2, 3][::-1])
print("hello"[1:], (1, 2, 3)[1:])
var xs = [0, 1, 2, 3]
xs[1:3] = [9, 8]
print(xs)
""",
    """val xs = [1, 2]
print(xs.length)
val d = {: "a": 1 :}
print(d.length)
""",
    """\
for c in "abc" {
    print(c)
}
""",
    """\
def sign(n) {
    if n < 0 { return -1 }
    if n > 0 { return 1 }
    0
}
print(sign(-2), sign(0), sign(3))
""",
    """\
val double = do: $0 * 2
val inc = do(x): x + 1
print(double(3), inc(4))
print(map([1, 2, 3], do(v): v + 1))
""",
    """\
def counter(start) {
    var n = start
    do: {
        n = n + 1
        n
    }
}
val c = counter(10)
print(c(), c())
""",
    """\
def nested(a) {
    do(x): do(y): a + x + y
}
val g = nested(100)
print(g(5)(1))

def apply(f, x) { f(x) }
print(apply(do(v): v * 3, 7))
val fs = [do: $0 + 1, do: $0 + 2]
print(fs[0](10), fs[1](10))
""",
]


@pytest.mark.parametrize("source", CASES)
def test_vm_matches_interpreter(source: str, capsys: pytest.CaptureFixture):
    eval_value = run_target(source, "eval")
    eval_out = capsys.readouterr().out
    vm_value = run_target(source, "vm")
    vm_out = capsys.readouterr().out
    assert vm_out == eval_out
    assert vm_value == eval_value


def test_vm_reports_collection_errors(caplog: pytest.LogCaptureFixture):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("""\
val t = (1, 2)
t[0] = 3
""")
    assert "does not support item assignment" in caplog.text

    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("""\
val d = {: "a": 1 :}
print(d["b"])
""")
    assert "'b'" in caplog.text


def test_vm_reports_attribute_errors(caplog: pytest.LogCaptureFixture):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("print([1].missing)\n")
    assert "has no attribute 'missing'" in caplog.text

    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("""\
val xs = [1]
xs.foo = 1
""")
    assert "Cannot set attribute 'foo'" in caplog.text


def test_vm_reports_closure_errors(caplog: pytest.LogCaptureFixture):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("while false { val f = do: 1 }\n")
    assert "lambdas created inside loops" in caplog.text

    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("val f = do(x): x\nf()\n")
    assert "expects 1 arguments" in caplog.text


def test_vm_returns_last_value():
    assert run_target("def f(a) { a + 1 }\nf(41)\n", "vm") == 42


def test_vm_reports_unbound_global(caplog: pytest.LogCaptureFixture):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("print(missing)\n")
    assert "is not defined in bytecode" in caplog.text


def test_vm_reports_function_arity(caplog: pytest.LogCaptureFixture):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("def f(a) { a }\nf()\n")
    assert "expects 1 arguments" in caplog.text


def test_vm_reports_division_by_zero(caplog: pytest.LogCaptureFixture):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("print(1 / 0)\n")
    assert "division by zero" in caplog.text


def test_vm_rejects_unsupported_constructs(caplog: pytest.LogCaptureFixture):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("class C {}\n")
    assert "HIR backend does not support ClassDef" in caplog.text
