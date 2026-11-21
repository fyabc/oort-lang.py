#! /usr/bin/env python

"""Historical AST-interpreter Fibonacci baseline.

Broader interpreter coverage lives in test_micro.py, test_macro.py,
test_stdlib.py, test_iterators.py and test_extensions.py. Keep this file small
so its benchmark history stays comparable across backend changes.
"""

import pytest

from .utils import get_compiler


def run_string(compiler, string):
    return compiler.run_string(string)


@pytest.mark.parametrize(
    "n, expected",
    [
        (10, 55),
        (20, 6765),
    ],
)
def test_recursion(benchmark, n: int, expected: int):
    compiler = get_compiler("NOT_EXIST -t eval")
    test_string = (
        """\
def fib(n) {
    if n <= 1: return n
    fib(n - 1) + fib(n - 2)
}
fib(%d)
"""
        % n
    )
    result = benchmark(run_string, compiler, test_string)
    assert result == expected
