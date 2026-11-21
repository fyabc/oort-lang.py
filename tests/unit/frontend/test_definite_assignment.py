#! /usr/bin/env python

"""Direct coverage for definite-assignment paths outside core syntax."""

import pytest

from oort_lang.ast import nodes
from oort_lang.semantics.core.definite_assignment import (
    AssignState,
    DefiniteAssignmentAnalyzer,
    SlotFact,
)
from oort_lang.source.input_info import StringInputInfo
from tests.helpers import get_compiler


def _parse_init(source: str) -> nodes.FunctionDef:
    compiler = get_compiler("NOT_EXIST -t ast")
    input_info = StringInputInfo(source)
    compiler.error_handler.register_input(input_info)
    dialect = compiler._resolve_dialect(input_info)
    assert dialect is not None
    parser = compiler._build_parser(input_info)
    ast = compiler.build_ast(
        parser,
        input_info,
        dialect=dialect,
        report_errors=False,
    )
    assert isinstance(ast, nodes.ModuleNode)
    cls = ast.body.statements[0]
    assert isinstance(cls, nodes.ClassDef)
    return next(
        stmt
        for stmt in cls.body.statements
        if isinstance(stmt, nodes.FunctionDef) and stmt.name == "__init__"
    )


def _analyze(source: str, slots: list[tuple[str, bool]]) -> list[str]:
    init = _parse_init(source)
    reports: list[str] = []
    analyzer = DefiniteAssignmentAnalyzer(
        [SlotFact(name, mutable, False, init.position) for name, mutable in slots],
        lambda message, _position: reports.append(message),
    )
    analyzer.check(init)
    return reports


def test_analyzer_handles_local_writes_augmented_and_subscript_assignments():
    reports = _analyze(
        """class C {
    def __init__() {
        var local = 1
        var uninitialized
        local = 2
        local += 1
        xs[0] = 1
        obj.field = 2
        for i in [1] { break 1 }
        while false { continue }
        def nested() { 1 }
        class Nested {}
        this.unknown = 1
        this.x = 1
        return 5
        print(2)
    }
}
""",
        [("x", True)],
    )
    assert reports == []


@pytest.mark.parametrize(
    "body",
    [
        "var s = xs[0:2]",
        "var z = 1 + { return }",
        "return { return }",
        "while true { break { return } }",
        "var y = 1\n        y += { return }",
        "{ return }.field += 1",
        "this.x = { return }",
        "var y = 1\n        y = { return }",
        "{ return }[0] = 1",
        "if { return } { }",
        "match { return } { _ => 1 }",
        "while { return } { }",
        "for i in { return } { }",
    ],
)
def test_analyzer_handles_control_flow_inside_expressions(body: str):
    _analyze(f"class C {{ def __init__() {{ {body} }} }}", [("x", True)])


def test_analyzer_empty_and_merge_edge_states():
    analyzer = DefiniteAssignmentAnalyzer([], lambda _message, _position: None)
    state = AssignState({"x"}, {"x"})
    assert analyzer._expr(None, state) is state
    assert analyzer._merge(None, None) is None
    assert analyzer._merge(None, state) is state
    assert analyzer._merge(state, None) is state
    merged = analyzer._merge(AssignState({"a"}, {"a"}), AssignState({"b"}, {"b"}))
    assert merged is not None
    assert merged.definite == set()
    assert merged.maybe == {"a", "b"}
