#! /usr/bin/env python

"""Generate RESULTS.md from machine-readable benchmark runs.

Inputs:
  - pytest-benchmark JSON from ``pytest benchmarks/ --benchmark-json=...``;
  - reference JSON from ``benchmarks/reference/run.py --json``;
  - curated historical milestones in ``benchmarks/history.json``.

The report is deterministic so ``--check`` can detect stale committed results.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GROUP_ORDER = ["micro", "macro", "stdlib", "iterators", "extensions", "startup"]
GROUP_TITLES = {
    "micro": "微基准",
    "macro": "宏基准",
    "stdlib": "标准库与宿主边界",
    "iterators": "迭代器",
    "extensions": "扩展方法/运算符",
    "startup": "启动与编译",
}
LABELS = {
    "test_micro_arithmetic": "arithmetic",
    "test_micro_variable_lookup": "variable lookup",
    "test_micro_function_call": "function call",
    "test_micro_attribute": "attribute",
    "test_micro_index": "index",
    "test_micro_dict": "dict",
    "test_micro_closure": "closure",
    "test_micro_class_instantiation": "class instantiation",
    "test_macro_loop": "loop (1000)",
    "test_macro_method_dispatch": "method dispatch (1000)",
    "test_macro_fibonacci": "fibonacci (fib 10)",
    "test_recursion[10-55]": "recursion fib(10)",
    "test_recursion[20-6765]": "recursion fib(20)",
    "test_stdlib_map": "map",
    "test_stdlib_filter": "filter",
    "test_stdlib_sorted": "sorted",
    "test_stdlib_zip_enumerate": "zip + enumerate",
    "test_stdlib_string_join": "string join",
    "test_host_list_equality_projection": "host list equality projection",
    "test_host_len_does_not_project": "host `len` without projection",
    "test_iterator_builtin_loop": "builtin loop",
    "test_iterator_user_closure": "user closure",
    "test_iterator_infinite_break": "infinite + break",
    "test_extension_member_call": "member call",
    "test_extension_method_call": "method call",
    "test_extension_operator_call": "operator call",
    "test_compiler_construction": "compiler construction",
    "test_runtime_construction": "runtime construction",
    "test_empty_program": "empty program",
}
VM_LABELS = {"fib": "fib(15)", "loop": "loop 10000"}
REFERENCE_WORKLOADS = {
    "fib": "fib(20)",
    "loop": "loop 20000",
    "methods": "methods 5000",
}


def _fmt_ms(value: float) -> str:
    if value < 1:
        return f"{value:.3f} ms"
    if value < 100:
        return f"{value:.2f} ms"
    return f"{value:.1f} ms"


def _fmt_compact(value: float) -> str:
    if value < 1:
        return f"{value:.3f}"
    if value < 100:
        return f"{value:.2f}"
    return f"{value:.1f}"


def _group_for(name: str) -> str:
    if name.startswith("test_micro_"):
        return "micro"
    if name.startswith(("test_macro_", "test_recursion[")):
        return "macro"
    if name.startswith(("test_stdlib_", "test_host_")):
        return "stdlib"
    if name.startswith("test_iterator_"):
        return "iterators"
    if name.startswith("test_extension_"):
        return "extensions"
    if name.startswith(
        ("test_compiler_construction", "test_runtime_construction", "test_empty_program")
    ):
        return "startup"
    return "other"


def _label(name: str) -> str:
    if name in LABELS:
        return LABELS[name]
    for prefix in (
        "test_micro_",
        "test_macro_",
        "test_stdlib_",
        "test_host_",
        "test_iterator_",
        "test_extension_",
    ):
        if name.startswith(prefix):
            return name[len(prefix) :].replace("_", " ")
    return name.removeprefix("test_").replace("_", " ")


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read {path}: {exc}") from exc


def _machine(payload: dict[str, Any]) -> tuple[str, str, str]:
    info = payload.get("machine_info") or {}
    cpu = info.get("cpu") or {}
    cpu_name = cpu.get("brand_raw") or info.get("processor") or info.get("machine") or "unknown CPU"
    system = info.get("system") or "unknown OS"
    release = info.get("release")
    if release:
        system = f"{system} {release}"
    python_version = info.get("python_version") or "unknown Python"
    return str(cpu_name), str(system), str(python_version)


def _version() -> str:
    try:
        with (ROOT / "pyproject.toml").open("rb") as file:
            return str(tomllib.load(file)["project"]["version"])
    except (KeyError, OSError, tomllib.TOMLDecodeError):
        return "unknown"


def _memory_limits() -> tuple[float, float]:
    from benchmarks.limits import PROGRAM_MEMORY_LIMIT, RUNTIME_MEMORY_LIMIT

    return (
        RUNTIME_MEMORY_LIMIT / (1024 * 1024),
        PROGRAM_MEMORY_LIMIT / (1024 * 1024),
    )


def _pytest_sections(
    payload: dict[str, Any],
) -> tuple[dict[str, list[tuple[str, float]]], dict[str, float], list[str]]:
    groups: dict[str, list[tuple[str, float]]] = {}
    entries: dict[str, float] = {}
    order: list[str] = []
    for benchmark in payload.get("benchmarks", []):
        name = str(benchmark.get("name") or benchmark.get("fullname") or "unknown")
        median = benchmark.get("stats", {}).get("median")
        if median is None:
            continue
        ms = float(median) * 1000.0
        entries[name] = ms
        if name.startswith(("test_interpreter_", "test_vm_")):
            continue
        group = _group_for(name)
        groups.setdefault(group, []).append((_label(name), ms))
        if group not in order:
            order.append(group)
    return groups, entries, order


def _vm_rows(entries: dict[str, float]) -> list[tuple[str, float, float, float]]:
    rows: list[tuple[str, float, float, float]] = []
    for name, interpreter_ms in entries.items():
        if not name.startswith("test_interpreter_"):
            continue
        suffix = name.removeprefix("test_interpreter_")
        vm_ms = entries.get(f"test_vm_{suffix}")
        if vm_ms is None:
            continue
        label = VM_LABELS.get(suffix, suffix.replace("_", " "))
        rows.append((label, interpreter_ms, vm_ms, interpreter_ms / vm_ms))
    return rows


def _reference_section(reference: dict[str, Any]) -> list[str]:
    versions = reference.get("versions") or {}
    runtimes = reference.get("runtimes") or list(versions)
    exec_ms = reference.get("exec_ms") or {}
    startup = reference.get("startup_ms") or {}
    workloads = [
        workload
        for workload in ("fib", "loop", "methods")
        if any(
            isinstance(exec_ms.get(runtime, {}).get(workload), (int, float)) for runtime in runtimes
        )
    ]
    lines = [
        "| 运行时 | "
        + " | ".join(REFERENCE_WORKLOADS.get(workload, workload) for workload in workloads)
        + " | 启动 |",
        "|---|" + "---:|" * (len(workloads) + 1),
    ]
    for runtime in runtimes:
        version = versions.get(runtime, "")
        name = {
            "oort": "Oort 树遍历",
            "oort-vm": "Oort VM",
            "python": "Python",
            "node": "Node",
            "ruby": "Ruby",
            "lua": "Lua",
        }.get(runtime, runtime)
        match = re.search(r"\d+\.\d+(?:\.\d+)?", version)
        if match:
            name = f"{name} {match.group(0)}"
        values = []
        for workload in workloads:
            value = exec_ms.get(runtime, {}).get(workload)
            values.append("-" if value is None else f"{_fmt_compact(float(value))} ms")
        startup_ms = startup.get(runtime)
        values.append("-" if startup_ms is None else f"{_fmt_compact(float(startup_ms))} ms")
        lines.append(f"| {name} | " + " | ".join(values) + " |")

    ratios = []
    for runtime in ("oort", "oort-vm"):
        for workload in workloads:
            oort = exec_ms.get(runtime, {}).get(workload)
            python = exec_ms.get("python", {}).get(workload)
            if isinstance(oort, (int, float)) and isinstance(python, (int, float)) and python > 0:
                ratios.append(float(oort) / float(python))
    lines.append("")
    if ratios:
        low = min(ratios)
        high = max(ratios)
        lines.append(
            f"当前 Oort（解释器及 VM）约为 CPython 的 **{low:.0f}–{high:.0f} 倍**耗时。"
            "Node 的优化 JIT 可能折叠简单循环/字段更新，其数字只作下限；"
            "Ruby/Lua 作语境参考。"
        )
    return lines


def _history_section(history: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| 日期 | 状态 | fib(15) | loop 10000 | 说明 |",
        "|---|---|---:|---:|---|",
    ]
    for item in history:
        fib = item.get("fib_ms")
        loop = item.get("loop_ms")
        fib_text = (
            "-"
            if fib is None
            else f"{_fmt_compact(float(fib))} ms（{float(item['fib_speedup']):.2f}×）"
        )
        loop_text = (
            "-"
            if loop is None
            else f"{_fmt_compact(float(loop))} ms（{float(item['loop_speedup']):.2f}×）"
        )
        lines.append(
            f"| {item.get('date', '')} | {item.get('status', '')} | "
            f"{fib_text} | {loop_text} | {item.get('note', '')} |"
        )
    return lines


def render(
    benchmark: dict[str, Any],
    reference: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    benchmark_path: str,
    reference_path: str,
) -> str:
    groups, entries, order = _pytest_sections(benchmark)
    vm_rows = _vm_rows(entries)
    cpu, system, python_version = _machine(benchmark)
    commit_info = benchmark.get("commit_info") or {}
    commit = str(commit_info.get("id") or "unknown")[:7]
    if commit_info.get("dirty"):
        commit += "+dirty"
    date = str(benchmark.get("datetime") or "")[:10]
    repeat = reference.get("repeat", "?")
    reference_versions = reference.get("versions") or {}
    overrides = reference.get("runtime_overrides") or {}
    runtime_args: list[str] = []
    for name in reference_versions:
        path = overrides.get(name)
        if path:
            runtime_args.append(f"--runtime '{name}={path}'")
        else:
            runtime_args.append(f"--runtime {name}")
    command_runtime = " ".join(runtime_args)
    runtime_limit, program_limit = _memory_limits()

    lines = [
        "# 基准结果（当前快照）",
        "",
        "> 本文件由 `benchmarks/report.py` 从机器可读结果生成，请勿手改数字。",
        "> 手工维护的只有 `benchmarks/history.json` 的历史里程碑元数据。",
        f"> 快照日期：{date}  ",
        f"> 提交：`{commit}`  ",
        f"> 环境：{cpu} / {system} / Python {python_version}  ",
        f"> 版本：Oort {_version()}",
        "",
        "本文件是 Oort **当前结果的唯一人工入口**。运行方式、统计规则与 profiling",
        "见 [README.md](README.md)；跨语言套件的 caveat 见",
        "[reference/README.md](reference/README.md)；长期趋势由 GitHub Actions 的",
        "benchmark 工作流维护。",
        "",
        "生成命令：",
        "",
        "```bash",
        f"uv run --frozen pytest benchmarks/ -q --benchmark-json={benchmark_path}",
        f"uv run --frozen python benchmarks/reference/run.py --repeat {repeat} "
        f"{command_runtime} --json > {reference_path}",
        f"uv run --frozen python benchmarks/report.py --benchmark {benchmark_path} "
        f"--reference {reference_path}",
        "```",
        "",
        "## 1. pytest-benchmark 当前结果",
        "",
        "中位数；微/宏基准只测 `interpreter.run(ast)`，启动与编译构造成本单独测量。",
        "",
    ]

    for group in GROUP_ORDER + [name for name in order if name not in GROUP_ORDER]:
        rows = groups.get(group)
        if not rows:
            continue
        lines.extend(
            [
                f"### {GROUP_TITLES.get(group, group)}",
                "",
                "| 基准 | 中位数 |",
                "|---|---:|",
            ]
        )
        for label, value in rows:
            lines.append(f"| {label} | {_fmt_ms(value)} |")
        lines.append("")

    lines.extend(
        [
            "### 内存上限",
            "",
            f"- `Runtime` 峰值分配 < {runtime_limit:.0f} MiB；",
            f"- 典型 1000 次循环程序峰值分配 < {program_limit:.0f} MiB。",
            "",
            "## 2. VM vs 树遍历解释器",
            "",
            "同一 HIR 支持程序、同机、中位数：",
            "",
            "| 基准 | 树遍历解释器 | 字节码 VM | 加速 |",
            "|---|---:|---:|---:|",
        ]
    )
    for label, interpreter_ms, vm_ms, speedup in vm_rows:
        lines.append(
            f"| {label} | {_fmt_ms(interpreter_ms)} | {_fmt_ms(vm_ms)} | **{speedup:.2f}×** |"
        )
    lines.extend(
        [
            "",
            "完整子集进入 VM 后的当前结论见下方历史表；目标与预算见",
            "`docs/design/08-performance-benchmarking.md`。",
            "",
            "## 3. 跨语言参考（仅手动，不进入 CI）",
            "",
            "`exec` 为单次 workload 内部计时；`startup` 为空程序进程实际耗时：",
            "",
            *_reference_section(reference),
            "",
            "详细运行方式与 Node/JIT、Ruby/Lua 的 caveat 见",
            "[reference/README.md](reference/README.md)。",
            "",
            "## 4. 历史里程碑",
            "",
        ]
    )
    lines.extend(_history_section(history))
    lines.extend(
        [
            "",
            "第一切片数字保留用于对照，不作为当前性能承诺。每次后端/优化改动后，",
            "应重新生成当前快照并在 `benchmarks/history.json` 追加里程碑。",
            "",
            "## 5. 维护规则",
            "",
            "1. 在安静机器上运行上面的三条命令，确认 benchmark 结果校验通过；",
            "2. 只更新 `benchmarks/history.json` 中的历史里程碑元数据；",
            "3. 当前表格由 `report.py` 生成，不要手改 RESULTS 数字；",
            "4. 若结论跨过目标线，只在 design08/roadmap 写一句结论并链接本文件；",
            "5. benchmark JSON、profile 与临时图表不提交仓库；长期趋势交给 CI。",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument(
        "--history",
        type=Path,
        default=Path(__file__).with_name("history.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("RESULTS.md"),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the committed RESULTS.md is stale.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    benchmark = _load(args.benchmark)
    reference = _load(args.reference)
    history = _load(args.history)
    text = render(
        benchmark,
        reference,
        history,
        benchmark_path=args.benchmark.name,
        reference_path=args.reference.name,
    )
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if current == text:
            print(f"{args.output} is up to date.")
            return 0
        diff = difflib.unified_diff(
            current.splitlines(),
            text.splitlines(),
            fromfile=str(args.output),
            tofile="generated",
            lineterm="",
        )
        print("\n".join(diff))
        return 1
    args.output.write_text(text, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
