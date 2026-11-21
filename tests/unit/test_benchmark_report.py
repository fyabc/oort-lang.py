#! /usr/bin/env python

"""The benchmark report must be derived from machine-readable inputs."""

from benchmarks.report import render


def test_report_renders_pytest_vm_reference_and_history():
    benchmark = {
        "datetime": "2026-11-21T12:00:00+00:00",
        "commit_info": {"id": "abcdef123456", "dirty": False},
        "machine_info": {
            "system": "TestOS",
            "release": "1",
            "python_version": "3.12.0",
            "cpu": {"brand_raw": "Test CPU"},
        },
        "benchmarks": [
            {
                "name": "test_micro_arithmetic",
                "stats": {"median": 0.00005},
            },
            {
                "name": "test_interpreter_fib",
                "stats": {"median": 0.2},
            },
            {
                "name": "test_vm_fib",
                "stats": {"median": 0.1},
            },
            {
                "name": "test_empty_program",
                "stats": {"median": 0.002},
            },
        ],
    }
    reference = {
        "repeat": 3,
        "runtimes": ["oort", "python"],
        "versions": {"oort": "Oort 0.3.1", "python": "Python 3.12.0"},
        "runtime_overrides": {},
        "exec_ms": {
            "oort": {"fib": 100.0, "loop": 50.0, "methods": 25.0},
            "python": {"fib": 1.0, "loop": 1.0, "methods": 1.0},
        },
        "startup_ms": {"oort": 400.0, "python": 40.0},
    }
    history = [
        {
            "date": "2026-11-21",
            "status": "slice",
            "fib_ms": 20.0,
            "fib_speedup": 5.0,
            "loop_ms": 10.0,
            "loop_speedup": 2.0,
            "note": "test",
        }
    ]
    text = render(
        benchmark,
        reference,
        history,
        benchmark_path="benchmark.json",
        reference_path="reference.json",
    )
    assert "0.050 ms" in text
    assert "200.0 ms" in text
    assert "100.0 ms" in text
    assert "**2.00" in text
    assert "Python 3.12.0" in text
    assert "Test CPU" in text
    assert "5.00" in text
    assert "benchmarks/report.py" in text
