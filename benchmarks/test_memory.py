#! /usr/bin/env python

"""Memory benchmarks with deliberately generous absolute ceilings."""

import tracemalloc

from benchmarks.bench_utils import compile_and_run
from benchmarks.limits import PROGRAM_MEMORY_LIMIT, RUNTIME_MEMORY_LIMIT
from oort_lang.runtime import Runtime


def _peak_bytes(func) -> int:
    tracemalloc.start()
    try:
        func()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak


def test_runtime_peak_memory():
    peak = _peak_bytes(Runtime)
    assert peak < RUNTIME_MEMORY_LIMIT, f"Runtime allocated {peak} bytes"


def test_program_peak_memory():
    source = """\
var total = 0
for i in range(1000) {
    total = total + i
}
total
"""
    peak = _peak_bytes(lambda: compile_and_run(source))
    assert peak < PROGRAM_MEMORY_LIMIT, f"Program allocated {peak} bytes"
