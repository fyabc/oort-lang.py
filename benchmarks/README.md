# Benchmarks

The benchmark suite uses [pytest-benchmark](https://pytest-benchmark.readthedocs.io/)
and exercises the real compiler pipeline, not a stripped-down harness.

| File | Level | Covers |
|------|-------|--------|
| `test_micro.py` | micro | arithmetic, locals, calls, attributes, indexing, dicts |
| `test_macro.py` | macro | recursion, loops, method dispatch |
| `test_stdlib.py` | macro/micro | map/filter/sorted/zip/enumerate, string join, host projection and `len` |
| `test_iterators.py` | macro/micro | builtin loop, user `__iter__` closure, infinite iterator + break |
| `test_startup.py` | startup | compiler/runtime construction, empty program |
| `test_memory.py` | memory | peak allocation ceilings for a runtime and a program |
| `test_ast_interpreter.py` | macro | historical Fibonacci baseline |

## Running

```bash
uv run pytest benchmarks/ -q
uv run pytest benchmarks/ --benchmark-json=benchmark.json -q
```

`bench_utils.compile_program` parses, resolves and builds an interpreter once;
micro/macro tests then measure only `interpreter.run(ast)`. Startup tests
measure construction, and compile-time work is covered by startup/empty
program rather than mixed into every micro number.

Host-boundary work has two kinds of cost: the constant per-call mode dispatch,
and the deep copy performed by `HostBridge.to_host` for HOST-mode natives.
Collection helpers use CONTEXT mode and do not project; `len` is VALUE-mode and
reads the Oort container directly. `test_stdlib.py` keeps a benchmark for each
path (`len` on a large nested list, string join, list equality) so the next
host refactor has a baseline.

The iterator protocol has two costs: builtin containers allocate one native
iterator over a snapshot, while user `__iter__` closures call into the
interpreter and allocate one `(value, valid)` Tuple per step. `test_iterators.py`
keeps a benchmark for the builtin path, a user closure and an infinite iterator
stopped by `break`; do not claim zero per-step allocation for the tree-walker.

## Regression tracking

`.github/workflows/benchmark.yml` runs on pushes to `main` and on manual
dispatch, writes `benchmark.json`, and stores results with
[github-action-benchmark](https://github.com/benchmark-action/github-action-benchmark).
An alert is raised at a 150% regression against the stored history. PRs do not
write history by default (forked PRs cannot push benchmark results).

Cross-language numbers are **not** part of CI or the stored history: different
runtimes, JIT warmup and program semantics make them unstable and easy to
misread. They are an optional manual calibration for the P4 performance budget
(see `docs/design/08-performance-benchmarking.md`). The primary comparison is
always Oort's tree-walking interpreter vs. the Oort VM on identical programs.

For local comparisons, save a baseline on a quiet machine and compare:

```bash
uv run pytest benchmarks/ --benchmark-json=baseline.json -q
# after a change
uv run pytest benchmarks/ --benchmark-json=current.json \
  --benchmark-compare=baseline.json --benchmark-compare-fail=median:10% -q
```

## Profiling

Benchmarks tell us *that* something regressed; profilers tell us *where*.

```bash
# Sampling profile of the macro suite
uvx py-spy record -o profile.svg -- uv run pytest benchmarks/test_macro.py -q

# Line-level CPU + memory attribution
uvx scalene --cli --reduced-profile benchmarks/test_macro.py

# Allocation tracing for the memory suite
uvx memray run -o memory.bin -m pytest benchmarks/test_memory.py -q
uvx memray flamegraph memory.bin
```

Do not commit generated profiles or benchmark JSON files.
