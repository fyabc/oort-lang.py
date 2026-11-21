#! /usr/bin/env python

"""Manual cross-language reference benchmarks.

This is not part of CI. It runs the same small programs under Oort and a few
host languages, reports median wall-clock time, subtracts an empty-program
startup baseline for each runtime, and prints ratios. See README.md for the
methodology and caveats.
"""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = Path(__file__).resolve().parent / "programs"

WORKLOADS = {
    "empty": 0,
    "fib": 6765,
    "loop": 199990000,
    "methods": 5000,
}

EXTENSIONS = {
    "oort": ".ort",
    "python": ".py",
    "node": ".js",
    "ruby": ".rb",
    "lua": ".lua",
}

VERSION_ARGS = {
    "oort": ["--version"],
    "python": ["--version"],
    "node": ["--version"],
    "ruby": ["--version"],
    "lua": ["-v"],
}


def _which(name: str) -> str | None:
    return shutil.which(name)


def runtime_command(name: str, overrides: dict[str, str]) -> list[str] | None:
    """Return the base command for a runtime, or None if unavailable."""
    if name == "oort":
        return [sys.executable, "-m", "oort_lang"]
    if name == "python":
        return [sys.executable]
    if name in overrides:
        return [overrides[name]]
    executable = _which(name)
    return [executable] if executable is not None else None


def runtime_version(name: str, base: list[str]) -> str:
    try:
        proc = subprocess.run(
            base + VERSION_ARGS[name],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
            cwd=ROOT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable ({exc})"
    text = (proc.stdout or proc.stderr).strip().splitlines()
    return text[0] if text else "unknown"


def run_once(
    name: str, base: list[str], workload: str, expected: int, timeout: int
) -> tuple[float, float | None]:
    """Run one program; return (process seconds, in-program milliseconds)."""
    program = PROGRAMS / f"{workload}{EXTENSIONS[name]}"
    command = [*base, str(program)]
    started = time.perf_counter()
    proc = subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
        cwd=ROOT,
        env=os.environ.copy(),
    )
    raw = time.perf_counter() - started
    if proc.returncode != 0:
        raise RuntimeError(f"{name}/{workload} exited {proc.returncode}: {proc.stderr.strip()}")
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if workload == "empty":
        if lines[-1:] != [str(expected)]:
            raise RuntimeError(f"{name}/{workload} printed {proc.stdout!r}, expected {expected}")
        return raw, None
    if len(lines) < 2 or lines[-2] != str(expected):
        raise RuntimeError(
            f"{name}/{workload} printed {proc.stdout!r}, expected {expected} plus timing"
        )
    try:
        elapsed_ms = float(lines[-1])
    except ValueError as exc:
        raise RuntimeError(f"{name}/{workload} printed a non-numeric timing {lines[-1]!r}") from exc
    return raw, elapsed_ms


def measure(
    name: str,
    base: list[str],
    workload: str,
    expected: int,
    *,
    warmup: int,
    repeat: int,
    timeout: int,
) -> tuple[float, float | None]:
    """Return (median process seconds, median in-program milliseconds)."""
    for _ in range(warmup):
        run_once(name, base, workload, expected, timeout)
    samples = [run_once(name, base, workload, expected, timeout) for _ in range(repeat)]
    raw = statistics.median(sample[0] for sample in samples)
    elapsed = [sample[1] for sample in samples if sample[1] is not None]
    return raw, (statistics.median(elapsed) if elapsed else None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime",
        action="append",
        default=[],
        metavar="NAME[=PATH]",
        help="Run only these runtimes; PATH overrides the executable for that runtime.",
    )
    parser.add_argument(
        "--workload",
        action="append",
        default=[],
        metavar="NAME",
        help=f"Run only these workloads (default: all of {', '.join(WORKLOADS)}).",
    )
    parser.add_argument("--warmup", type=int, default=0)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    overrides: dict[str, str] = {}
    requested: list[str] = []
    for item in args.runtime:
        name, sep, path = item.partition("=")
        if name not in EXTENSIONS:
            print(f"Unknown runtime {name!r}.", file=sys.stderr)
            return 2
        requested.append(name)
        if sep:
            overrides[name] = path
    selected = requested or list(EXTENSIONS)

    workload_names = args.workload or list(WORKLOADS)
    for name in workload_names:
        if name not in WORKLOADS:
            print(f"Unknown workload {name!r}.", file=sys.stderr)
            return 2
    if "empty" not in workload_names:
        workload_names = ["empty", *workload_names]

    bases: dict[str, list[str]] = {}
    versions: dict[str, str] = {}
    for name in selected:
        base = runtime_command(name, overrides)
        if base is None:
            if requested:
                print(f"Runtime {name!r} is not available.", file=sys.stderr)
                return 2
            print(f"Skipping unavailable runtime {name!r}.", file=sys.stderr)
            continue
        bases[name] = base
        versions[name] = runtime_version(name, base)

    results: dict[str, dict[str, float | None]] = {}
    startup: dict[str, float] = {}
    for name, base in bases.items():
        results[name] = {}
        for workload in workload_names:
            try:
                raw, elapsed_ms = measure(
                    name,
                    base,
                    workload,
                    WORKLOADS[workload],
                    warmup=args.warmup,
                    repeat=args.repeat,
                    timeout=args.timeout,
                )
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                print(f"Failed {name}/{workload}: {exc}", file=sys.stderr)
                return 1
            if workload == "empty":
                startup[name] = raw
            results[name][workload] = elapsed_ms

    def baseline(name: str, workload: str) -> float | None:
        return results.get(name, {}).get(workload)

    def ratio(numerator: float | None, denominator: float | None) -> float | None:
        if numerator is None or denominator is None or denominator <= 0:
            return None
        return numerator / denominator

    if args.json:
        payload = {
            "versions": versions,
            "startup_ms": {name: value * 1e3 for name, value in startup.items()},
            "exec_ms": {
                name: {
                    workload: (value if value is not None else None)
                    for workload, value in readings.items()
                }
                for name, readings in results.items()
            },
        }
        print(json.dumps(payload, indent=2))
        return 0

    print("Manual cross-language reference benchmarks (not CI).")
    for name, version in versions.items():
        print(f"  {name}: {version}")
    print()
    print("| runtime | workload | exec ms | vs Python | vs Oort |")
    print("|---|---|---:|---:|---:|")
    for name in bases:
        for workload in workload_names:
            value = results[name][workload]
            vs_python = ratio(baseline("python", workload), value)
            vs_oort = ratio(baseline("oort", workload), value)
            value_text = "-" if value is None else f"{value:.3f}"
            python_text = "-" if vs_python is None else f"{vs_python:.2f}x"
            oort_text = "-" if vs_oort is None else f"{vs_oort:.2f}x"
            print(f"| {name} | {workload} | {value_text} | {python_text} | {oort_text} |")
    print()
    print("exec ms is measured inside each program, excluding process startup.")
    print("`vs X` is X's exec time divided by this runtime's exec time; >1 is faster.")
    print("Startup (empty program, process wall clock):")
    for name, raw in startup.items():
        print(f"  {name}: {raw * 1e3:.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
