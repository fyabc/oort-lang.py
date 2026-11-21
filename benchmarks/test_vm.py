#! /usr/bin/env python

"""Interpreter vs bytecode VM benchmarks on identical HIR-supported programs."""

from benchmarks.bench_utils import compile_program, run_compiled
from oort_lang.bytecode import compile_module
from oort_lang.hir import lower_module
from oort_lang.runtime.bytecode_vm import BytecodeVM

_FIB = """\
def fib(n) {
    if n <= 1: return n
    fib(n - 1) + fib(n - 2)
}
fib(15)
"""
_LOOP = """\
var total = 0
for i in range(10000) {
    total = total + i
}
total
"""


def _setup(source: str):
    interpreter, ast = compile_program(source)
    program = compile_module(lower_module(ast))
    return interpreter, ast, BytecodeVM(interpreter), program


def test_interpreter_fib(benchmark):
    interpreter, ast, _, _ = _setup(_FIB)
    benchmark(run_compiled, interpreter, ast)


def test_vm_fib(benchmark):
    _, _, vm, program = _setup(_FIB)
    benchmark(vm.run, program)


def test_interpreter_loop(benchmark):
    interpreter, ast, _, _ = _setup(_LOOP)
    benchmark(run_compiled, interpreter, ast)


def test_vm_loop(benchmark):
    _, _, vm, program = _setup(_LOOP)
    benchmark(vm.run, program)
