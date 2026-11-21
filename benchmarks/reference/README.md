# 跨语言参考基准（仅手动运行）

本目录**不进入 CI**，也不由 pytest 收集。它用相同的几个小算法分别在 Oort
和若干宿主语言中运行，用于校准 P4 性能预算。跨语言数字只作参考，不作门禁：
各运行时的 JIT/GC/整数语义、启动与预热差异都会影响结果。

主对比始终是 **Oort 树遍历解释器 vs Oort VM**（同程序、同结果、同机）。
预算与目标见 `docs/design/08-performance-benchmarking.md`。

## 运行时

runner 会在 `PATH` 中查找 `node`、`ruby`、`lua`；Python 与 Oort 使用当前
虚拟环境。也可以用 `--runtime` 显式指定可执行文件：

```bash
uv run --frozen python benchmarks/reference/run.py \
  --runtime oort --runtime python --runtime node \
  --runtime 'ruby=D:\Softwares\Ruby40-x64\bin\ruby.exe' \
  --runtime 'lua=D:\Softwares\lua-5.4.8\lua.exe'
```

本机参考环境（非 Oort 工具按约定放在 `D:\Softwares`）：

- Ruby 4.0.10：`D:\Softwares\Ruby40-x64\bin\ruby.exe`
- Lua 5.4.8：`D:\Softwares\lua-5.4.8\lua.exe`
- Node 24.15.0：`D:\nodejs\node.exe`
- Python 3.12：仓库虚拟环境

## 工作负载

| 工作负载 | 程序 | 期望结果 |
|---|---|---|
| `empty` | 输出 0 | 0 |
| `fib` | 递归 `fib(20)` | 6765 |
| `loop` | 求和 `0..19999` | 199990000 |
| `methods` | 对同一对象调用 5000 次方法 | 5000 |

每个非空程序先预热一次，然后重复基础工作负载直到累计至少 100 ms，并由
语言内部计时（`clock` / `perf_counter` / `performance.now` /
`CLOCK_MONOTONIC` / `os.clock`）报告**单次重复**的毫秒数。runner 校验结果，
并对 `--repeat` 次运行取中位数。`empty` 单独测量进程启动时间。

Node 的优化 JIT 可能把简单循环或字段更新折叠掉，因此其数字只作下限，
不要据此做优化决策。Lua 的 `os.clock` 精度为毫秒，100 ms 目标保证它可测。

## 首次结果（2026-11-21，Ryzen 7 5800H，Windows）

`--repeat 3`；exec 为单次工作负载内部计时，startup 为空程序的进程实际耗时：

| 运行时 | fib | loop | methods | startup |
|---|---:|---:|---:|---:|
| Oort 树遍历 | 1093 ms | 368 ms | 230 ms | 497 ms |
| Python 3.12 | 1.33 ms | 1.30 ms | 0.58 ms | 42 ms |
| Node 24.15 | 0.066 ms | 0.006 ms | 0.002 ms | 51 ms |
| Ruby 4.0.10 | 0.56 ms | 0.33 ms | 0.27 ms | 143 ms |
| Lua 5.4.8 | 0.37 ms | 0.077 ms | 0.16 ms | 6 ms |

当前 Oort 约为 CPython 的 280–825 倍耗时。VM 预算先在宏基准上做到 2×，
再争取 5×；CPython 比值只用于 sanity check。

## 运行

```bash
# 自动检测可用运行时，全部工作负载，5 次中位数
uv run --frozen python benchmarks/reference/run.py

# 快速检查
uv run --frozen python benchmarks/reference/run.py --repeat 1 --workload fib

# 机器可读输出（结果文件不要提交）
uv run --frozen python benchmarks/reference/run.py --json
```

结果只打印到终端；不提交 JSON 或 profiler 产物。
