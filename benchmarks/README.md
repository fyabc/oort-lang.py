# 基准测试

基准套件使用 [pytest-benchmark](https://pytest-benchmark.readthedocs.io/)，
并走真实的编译流水线，而不是简化过的测试桩。

> 当前基线、VM/解释器对比与跨语言参考统一记录在
> [RESULTS.md](RESULTS.md)。本文件只讲运行方式、统计规则与 profiling。

| 文件 | 层级 | 覆盖内容 |
|------|------|---------|
| `test_micro.py` | 微基准 | 算术、局部变量、调用、属性、下标、字典 |
| `test_macro.py` | 宏基准 | 递归、循环、方法分派 |
| `test_stdlib.py` | 宏/微基准 | map/filter/sorted/zip/enumerate、字符串 join、宿主投影与 `len` |
| `test_iterators.py` | 宏/微基准 | 内置容器循环、用户 `__iter__` 闭包、无限迭代器 + `break` |
| `test_startup.py` | 启动 | 编译器/运行时构造、空程序 |
| `test_memory.py` | 内存 | 运行时与程序的峰值分配上限 |
| `test_ast_interpreter.py` | 宏基准 | 历史 Fibonacci 基线 |
| `test_vm.py` | 宏基准 | 同一 HIR 支持程序在解释器与字节码 VM 上的对比 |

## 运行

```bash
uv run pytest benchmarks/ -q
uv run pytest benchmarks/ --benchmark-json=benchmark.json -q
```

`bench_utils.compile_program` 只做一次解析、解析绑定并构造解释器；
微/宏基准随后只测 `interpreter.run(ast)`。启动测试单独测量构造过程，
编译期开销由启动/空程序基准覆盖，不混入每次微基准数字。

宿主边界有两类成本：每次调用的模式分派，以及 HOST 模式原生函数在
`HostBridge.to_host` 中的深拷贝。集合助手使用 CONTEXT 模式，不做投影；
`len` 使用 VALUE 模式，直接读取 Oort 容器。`test_stdlib.py` 为每条路径保留
基准（大嵌套列表上的 `len`、字符串 join、列表相等），供下一次宿主边界重构
对照。

迭代器协议有两类成本：内置容器会为快照分配一个原生迭代器；用户
`__iter__` 闭包会回调解释器，并在每一步分配一个 `(value, valid)` Tuple。
`test_iterators.py` 分别为内置路径、用户闭包和由 `break` 终止的无限迭代器
保留基准；不要声称树遍历解释器没有每步分配。

## 回归跟踪

`.github/workflows/benchmark.yml` 在推送到 `main` 和手动触发时运行，写出
`benchmark.json`，并用
[github-action-benchmark](https://github.com/benchmark-action/github-action-benchmark)
保存历史。相对历史回退达到 150% 时告警。PR 默认不写历史（fork 的 PR 无法
推送基准结果）。

跨语言数字**不进入** CI 或历史存储：不同运行时、JIT 预热和程序语义会让结果
不稳定且容易误读。它们只作为 P4 性能预算的可选手工校准，结果见
[RESULTS.md](RESULTS.md#3-跨语言参考仅手动不进入-ci)。主对比始终是 Oort
树遍历解释器 vs. Oort VM 上的同一程序。

本地比较时，在安静机器上保存基线后对比：

```bash
uv run pytest benchmarks/ --benchmark-json=baseline.json -q
# 修改后
uv run pytest benchmarks/ --benchmark-json=current.json \
  --benchmark-compare=baseline.json --benchmark-compare-fail=median:10% -q
```

## 结果报告生成

当前结果不手工维护。先产生机器可读输入，再由生成器写出
[RESULTS.md](RESULTS.md)：

```bash
uv run pytest benchmarks/ --benchmark-json=benchmark.json -q
uv run python benchmarks/reference/run.py --repeat 5 --json > reference.json
uv run python benchmarks/report.py --benchmark benchmark.json --reference reference.json
# 验证已提交 RESULTS 是否漂移
uv run python benchmarks/report.py --benchmark benchmark.json --reference reference.json --check
```

make 等价目标：`benchmark-json`、`benchmark-reference-json`、
`benchmark-report`、`benchmark-report-check`。生成器只读取 JSON；只有
`history.json` 的历史里程碑元数据是人工维护的。

## 性能分析

基准告诉我们*是否*回退；profiler 告诉我们*在哪里*回退。

```bash
# 宏基准套件的采样 profile
uvx py-spy record -o profile.svg -- uv run pytest benchmarks/test_macro.py -q

# 行级 CPU + 内存归因
uvx scalene --cli --reduced-profile benchmarks/test_macro.py

# 内存套件的分配追踪
uvx memray run -o memory.bin -m pytest benchmarks/test_memory.py -q
uvx memray flamegraph memory.bin
```

不要提交生成的 profile 或 benchmark JSON 文件。
