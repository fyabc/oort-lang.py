#! /usr/bin/env python

"""Tests for the `oort-object` dynamic object model (OP 0007)."""

import pytest

from oort_lang.driver.compiler import CompilerError
from tests.helpers import get_compiler


@pytest.mark.parametrize("keyword", ["var", "val"])
def test_class_body_variable_is_rejected(keyword: str, caplog: pytest.LogCaptureFixture):
    source = f"""\
class C {{
    {keyword} x = 1
}}
"""
    compiler = get_compiler("NOT_EXIST -t eval")
    with pytest.raises(SystemExit):
        compiler.run_string(source)
    assert "Class-body variable declarations are not supported" in caplog.text
    assert "assign instance fields in `__init__`" in caplog.text


def test_instance_fields_are_created_in_init(capsys: pytest.CaptureFixture):
    source = """\
class Counter {
    def __init__ {
        this.n = 0
    }

    def increment {
        this.n = this.n + 1
        this
    }
}

val c = Counter()
c.increment()
print(c.n)
"""
    compiler = get_compiler("NOT_EXIST -t eval")
    compiler.run_string(source)
    assert capsys.readouterr().out == "1\n"


@pytest.mark.parametrize("member", ["def f: 1", "def class.f: this"])
def test_instance_field_cannot_shadow_callable_member(
    member: str, caplog: pytest.LogCaptureFixture
):
    source = f"""\
class C {{
    {member}
}}
val c = C()
c.f = 2
"""
    compiler = get_compiler("NOT_EXIST -t eval")
    with pytest.raises(CompilerError):
        compiler.run_string(source)
    assert "Cannot shadow method 'f' with an instance field" in caplog.text


def test_instance_field_cannot_shadow_inherited_method(caplog: pytest.LogCaptureFixture):
    source = """\
class A { def f: 1 }
class B < A {}
val b = B()
b.f = 2
"""
    compiler = get_compiler("NOT_EXIST -t eval")
    with pytest.raises(CompilerError):
        compiler.run_string(source)
    assert "Cannot shadow method 'f' with an instance field" in caplog.text


def test_initializer_cannot_shadow_method(caplog: pytest.LogCaptureFixture):
    source = """\
class C {
    def f: 1
    def __init__ { this.f = 2 }
}
C()
"""
    compiler = get_compiler("NOT_EXIST -t eval")
    with pytest.raises(CompilerError):
        compiler.run_string(source)
    assert "Cannot shadow method 'f' with an instance field" in caplog.text


@pytest.mark.parametrize(
    "definition, name",
    [
        ("class C { def f: 1 }", "C.f"),
        ("class C { def class.f: 1 }", "C.f"),
        ("class A { def f: 1 }\nclass C < A {}", "C.f"),
    ],
)
def test_class_attribute_cannot_shadow_callable_member(
    definition: str, name: str, caplog: pytest.LogCaptureFixture
):
    source = f"{definition}\n{name} = 2\n"
    compiler = get_compiler("NOT_EXIST -t eval")
    with pytest.raises(CompilerError):
        compiler.run_string(source)
    assert "Cannot shadow method 'f' with a class attribute" in caplog.text


def test_new_class_attribute_is_allowed(run_source):
    out = run_source(
        """\
class C {}
C.answer = 42
print(C.answer, C().answer)
"""
    ).stdout
    assert out == "42 42\n"


def test_missing_attribute_is_reported(caplog: pytest.LogCaptureFixture):
    source = """\
class C {}
val c = C()
print(c.missing)
"""
    compiler = get_compiler("NOT_EXIST -t eval")
    with pytest.raises(CompilerError):
        compiler.run_string(source)
    assert "'C' object has no attribute 'missing'" in caplog.text


def test_default_equality_is_identity(capsys: pytest.CaptureFixture):
    source = """\
class C {}
val a = C()
val b = C()
print(a == a)
print(a == b)
print(a != b)
"""
    compiler = get_compiler("NOT_EXIST -t eval")
    compiler.run_string(source)
    assert capsys.readouterr().out == "true\nfalse\ntrue\n"


def test_instances_are_hashable_by_identity(capsys: pytest.CaptureFixture):
    source = """\
class C {}
val a = C()
val b = C()
val d = {: a: 1 :}
d[b] = 2
print(len(d))
print(d[a])
print(d[b])
"""
    compiler = get_compiler("NOT_EXIST -t eval")
    compiler.run_string(source)
    assert capsys.readouterr().out == "2\n1\n2\n"


def test_builtin_objects_reject_attribute_assignment(caplog: pytest.LogCaptureFixture):
    compiler = get_compiler("NOT_EXIST -t eval")
    with pytest.raises(CompilerError):
        compiler.run_string("""\
val xs = [1]
xs.foo = 1
""")
    assert "Cannot set attribute 'foo'" in caplog.text
