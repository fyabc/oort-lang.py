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
print(+5, ~1, -3, not true)
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
    """\
class Counter {
    def __init__(n) { this.n = n }
    def inc() { this.n = this.n + 1; this.n }
    def get() { this.n }
}
val c = Counter(10)
print(c.get())
print(c.inc())
c.n = 20
print(c.get())
val bump = c.inc
bump()
print(c.get())
""",
    """\
class Base {
    def name() { "base" }
    def value() { 1 }
}
class Derived < Base {
    def name() { "derived" }
}
val d = Derived()
print(d.name(), d.value())

class WithInit {
    def __init__(x) { this.x = x }
    def make() { do: this.x }
}
print(WithInit(7).make()())
print(map([1, 2], WithInit)[1].x)

class Sub < WithInit {}
print(Sub(9).x)
""",
    """\
var total = 0
for k, v in [(1, 10), [2, 20], (3, 30)] {
    total = total + k * v
}
print(total)
""",
    """\
#lang oort-core
val base: Int = 10
class Point {
    val x: Int = base + 1
    var y: Int
    def __init__(y: Int) { this.y = y }
    def sum() -> Int { this.x + this.y }
    def bump() -> Int {
        this.y = this.y + 1
        this.sum()
    }
}
val p = Point(2)
print(p.sum(), p.bump(), p.x)
""",
    """\
#lang oort-core
class Box {
    val value: Int
    def __init__(value: Int) { this.value = value }
    def get() -> Int { this.value }
}
print(Box(3).get())
""",
    """\
#lang oort-core
enum Shape {
    Circle(radius: Int),
    Rect(width: Int, height: Int),
    Empty
}
def area(shape: Shape) -> Int {
    match shape {
        Circle(r) => r * r * 3,
        Rect(w, h) => w * h,
        Empty => 0
    }
}
print(area(Circle(2)), area(Rect(3, 4)), area(Empty))
print(Circle(1))
""",
    """\
var total = 0
for i in range(10) {
    if i == 2: continue
    if i == 5: break
    total = total + i
}
print(total)
var j = 0
while j < 10 {
    j = j + 1
    if j == 3: continue
    if j == 6: break
    total = total + j
}
print(total)
var early = while true { break 5 }
print(early)
""",
    """\
def makeCounter {
    var i = 0
    def count {
        i = i + 1
        print(i)
    }
    count
}
var counter = makeCounter()
counter()
counter()

def make(step = 1) {
    var total = 0
    def add(n = 2) {
        total = total + n * step
        total
    }
    add
}
val f = make(3)
print(f(), f(4))

def outer() {
    def fact(n) {
        if n <= 1 { return 1 }
        n * fact(n - 1)
    }
    fact
}
print(outer()(5))
""",
    """\
def f(a, b = a + 1, /, c = 2, *args, d, e = 3, **kwargs) {
    print(a, b, c, args, d, e, kwargs)
}
f(1, d = 4)
f(1, 2, 3, 4, 5, d = 6, e = 7, x = 8)

var count = 0
def next() {
    count = count + 1
    count
}
def defaults(x = next()) { x }
print(defaults(), defaults())

def with_block(&block) {
    if block is null { print("none") } else { print(block()) }
}
with_block() do: 1
with_block(block = do: 2)
with_block()

class C {
    def __init__(a, b = 10) { this.a = a; this.b = b }
    def sum(extra = 0) { this.a + this.b + extra }
}
val c = C(1)
print(c.sum(), c.sum(5), c.sum(extra = 7))
val d1 = C(a = 2, b = 3)
print(d1.sum())
""",
    """\
class Countdown {
    def __init__(n) { this.n = n }
    def __iter__() { do: this.step() }
    def step() {
        val current = this.n
        this.n = this.n - 1
        (current, current > 0)
    }
}
for x in Countdown(3) { print(x) }
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


def test_vm_executes_imported_modules(tmp_path, run_file):
    (tmp_path / "lib.ort").write_text(
        """print("loaded")
var value = 40
def add(a, b) { a + b }
class Box {
    def __init__(n) { this.n = n }
    def get() { this.n + value }
}
""",
        encoding="utf-8",
    )
    (tmp_path / "facade.ort").write_text(
        'from "./lib" import value\n',
        encoding="utf-8",
    )
    main = tmp_path / "main.ort"
    main.write_text(
        """import "./lib"
import "./facade"
from "./lib" import add as plus
print(lib.value, plus(1, 2), lib.Box(2).get())
print(facade.value)
""",
        encoding="utf-8",
    )
    out = run_file(main, target="vm").stdout
    assert out == "loaded\n40 3 42\n40\n"


def test_vm_executes_core_modules_with_static_slots(tmp_path, run_file):
    (tmp_path / "geom.ort").write_text(
        """#lang oort-core
class Point {
    val x: Int = 2
    var y: Int
    def __init__(y: Int) { this.y = y }
    def sum() -> Int { this.x + this.y }
}
""",
        encoding="utf-8",
    )
    main = tmp_path / "main.ort"
    main.write_text(
        """#lang oort-core
import "./geom"
print(geom.Point(3).sum())
""",
        encoding="utf-8",
    )
    out = run_file(main, target="vm").stdout
    assert out == "5\n"


def test_vm_shares_module_state_and_imports_native_modules(tmp_path, run_file):
    (tmp_path / "counter.ort").write_text(
        """var count = 0
def next() {
    count = count + 1
    count
}
""",
        encoding="utf-8",
    )
    main = tmp_path / "main.ort"
    main.write_text(
        """import "./counter" as c
from "./counter" import next
import "math"
print(c.next(), next(), c.count)
print(math.sqrt(9))
""",
        encoding="utf-8",
    )
    out = run_file(main, target="vm").stdout
    assert out == "1 2 2\n3.0\n"


def test_vm_hoists_imports(tmp_path, run_file):
    (tmp_path / "dep.ort").write_text('print("dep")\n', encoding="utf-8")
    main = tmp_path / "main.ort"
    main.write_text(
        'print("before")\nimport "./dep"\nprint("after")\n',
        encoding="utf-8",
    )
    out = run_file(main, target="vm").stdout
    assert out == "dep\nbefore\nafter\n"


def test_vm_reports_import_errors(tmp_path, run_file, caplog: pytest.LogCaptureFixture):
    missing = tmp_path / "missing.ort"
    missing.write_text('import "./nope"\n', encoding="utf-8")
    with pytest.raises(CompilerError):
        run_file(missing, target="vm")
    assert "Cannot find module './nope'" in caplog.text

    (tmp_path / "a.ort").write_text('import "./b"\nvar a = 1\n', encoding="utf-8")
    (tmp_path / "b.ort").write_text('import "./a"\nvar b = 2\n', encoding="utf-8")
    cycle = tmp_path / "cycle.ort"
    cycle.write_text('import "./a"\n', encoding="utf-8")
    with pytest.raises(CompilerError):
        run_file(cycle, target="vm")
    assert "Circular import detected" in caplog.text


def test_vm_reports_match_limitations(caplog: pytest.LogCaptureFixture):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string(
            """#lang oort-core
enum E { A, B }
def f(e: E) -> Int {
    match e {
        A => { return 1 },
        B => 2
    }
    3
}
f(A)
"""
        )
    assert "return inside a match arm" in caplog.text


@pytest.mark.parametrize(
    ("source", "detail"),
    [
        ("def f(a, b) { a }\nf(1)\n", "missing required argument 'b'"),
        ("def f(a) { a }\nf(1, a = 2)\n", "got multiple values"),
        ("def f(a, /) { a }\nf(a = 1)\n", "positional-only"),
        ("def f(*, a) { a }\nf()\n", "missing required argument 'a'"),
        ("def f(a) { a }\nf(b = 1)\n", "unexpected keyword argument 'b'"),
        ("print(value = 1)\n", "does not accept keyword arguments"),
    ],
)
def test_vm_reports_binding_errors(
    source: str,
    detail: str,
    caplog: pytest.LogCaptureFixture,
):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string(source)
    assert detail in caplog.text


def test_vm_reports_loop_unpack_errors(caplog: pytest.LogCaptureFixture):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("for a, b in [(1, 2, 3)] { print(a) }\n")
    assert "Cannot unpack 3 value(s) into 2 loop variable(s)" in caplog.text

    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("for a, b in [1] { print(a) }\n")
    assert "Cannot unpack a non-tuple value in for loop" in caplog.text


def test_vm_reports_duplicate_block(caplog: pytest.LogCaptureFixture):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("def f(&block) { 1 }\nf(block = do: 1) do: 2\n")
    assert "got multiple values" in caplog.text


def test_vm_reports_closure_errors(caplog: pytest.LogCaptureFixture):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("while false { val f = do: 1 }\n")
    assert "lambdas created inside loops" in caplog.text

    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("val f = do(x): x\nf()\n")
    assert "missing required argument 'x'" in caplog.text


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
    assert "missing required argument 'a'" in caplog.text


@pytest.mark.parametrize(
    ("source", "detail"),
    [
        ("print(1 / 0)\n", "division by zero"),
        ("print(1 // 0)\n", "division or modulo by zero"),
        ("print(1 % 0)\n", "modulo by zero"),
    ],
)
def test_vm_reports_division_by_zero(
    source: str,
    detail: str,
    caplog: pytest.LogCaptureFixture,
):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string(source)
    assert detail in caplog.text


def test_vm_reports_class_errors(caplog: pytest.LogCaptureFixture):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("class C < 1 {}\nC()\n")
    assert "object is not a class" in caplog.text

    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("class C { def __init__(x) { this.x = x } }\nC()\n")
    assert "missing required argument 'x'" in caplog.text

    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("class C {}\nprint(C().missing)\n")
    assert "has no attribute 'missing'" in caplog.text


def test_vm_rejects_unsupported_constructs(caplog: pytest.LogCaptureFixture):
    compiler = get_compiler(["NOT_EXIST", "-t", "vm"])
    with pytest.raises(CompilerError):
        compiler.run_string("var x = 1\nx += 1\n")
    assert "HIR backend does not support augmented assignment" in caplog.text
