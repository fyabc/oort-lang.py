# 基准结果（当前快照）

> 本文件由 `benchmarks/report.py` 从机器可读结果生成，请勿手改数字。
> 手工维护的只有 `benchmarks/history.json` 的历史里程碑元数据。
> 快照日期：2026-11-21  
> 提交：`36f2ea5+dirty`  
> 环境：AMD Ryzen 7 5800H with Radeon Graphics / Windows 11 / Python 3.12.12  
> 版本：Oort 0.3.1

本文件是 Oort **当前结果的唯一人工入口**。运行方式、统计规则与 profiling
见 [README.md](README.md)；跨语言套件的 caveat 见
[reference/README.md](reference/README.md)；长期趋势由 GitHub Actions 的
benchmark 工作流维护。

生成命令：

```bash
uv run --frozen pytest benchmarks/ -q --benchmark-json=benchmark.json
uv run --frozen python benchmarks/reference/run.py --repeat 3 --runtime oort --runtime oort-vm --runtime python --runtime node --runtime 'ruby=D:\Softwares\Ruby40-x64\bin\ruby.exe' --runtime 'lua=D:\Softwares\lua-5.4.8\lua.exe' --json > refvm.json
uv run --frozen python benchmarks/report.py --benchmark benchmark.json --reference refvm.json
```

## 1. pytest-benchmark 当前结果

中位数；微/宏基准只测 `interpreter.run(ast)`，启动与编译构造成本单独测量。

### 微基准

| 基准 | 中位数 |
|---|---:|
| arithmetic | 0.048 ms |
| variable lookup | 0.056 ms |
| function call | 0.038 ms |
| attribute | 0.060 ms |
| index | 0.024 ms |
| dict | 0.025 ms |
| closure | 0.057 ms |
| class instantiation | 0.067 ms |

### 宏基准

| 基准 | 中位数 |
|---|---:|
| recursion fib(10) | 54.22 ms |
| recursion fib(20) | 1152.8 ms |
| fibonacci (fib 10) | 12.19 ms |
| loop (1000) | 17.58 ms |
| method dispatch (1000) | 45.59 ms |

### 标准库与宿主边界

| 基准 | 中位数 |
|---|---:|
| map | 22.56 ms |
| filter | 31.00 ms |
| sorted | 2.74 ms |
| zip + enumerate | 5.50 ms |
| string join | 19.82 ms |
| host list equality projection | 2.29 ms |
| host `len` without projection | 1.30 ms |

### 迭代器

| 基准 | 中位数 |
|---|---:|
| builtin loop | 18.26 ms |
| user closure | 65.89 ms |
| infinite + break | 41.43 ms |

### 扩展方法/运算符

| 基准 | 中位数 |
|---|---:|
| member call | 74.70 ms |
| method call | 79.40 ms |
| operator call | 83.11 ms |

### 启动与编译

| 基准 | 中位数 |
|---|---:|
| compiler construction | 0.528 ms |
| empty program | 1.37 ms |
| runtime construction | 0.142 ms |

### 内存上限

- `Runtime` 峰值分配 < 32 MiB；
- 典型 1000 次循环程序峰值分配 < 16 MiB。

## 2. VM vs 树遍历解释器

同一 HIR 支持程序、同机、中位数：

| 基准 | 树遍历解释器 | 字节码 VM | 加速 |
|---|---:|---:|---:|
| fib(15) | 103.1 ms | 35.86 ms | **2.88×** |
| loop 10000 | 187.8 ms | 92.26 ms | **2.04×** |

完整子集进入 VM 后的当前结论见下方历史表；目标与预算见
`docs/design/08-performance-benchmarking.md`。

## 3. 跨语言参考（仅手动，不进入 CI）

`exec` 为单次 workload 内部计时；`startup` 为空程序进程实际耗时：

| 运行时 | fib(20) | loop 20000 | methods 5000 | 启动 |
|---|---:|---:|---:|---:|
| Oort 树遍历 0.3.1 | 1077.1 ms | 370.4 ms | 235.4 ms | 460.7 ms |
| Oort VM 0.3.1 | 415.5 ms | 134.1 ms | 155.1 ms | 505.9 ms |
| Python 3.12.12 | 1.30 ms | 1.31 ms | 0.574 ms | 42.01 ms |
| Node 24.15.0 | 0.064 ms | 0.006 ms | 0.002 ms | 45.72 ms |
| Ruby 4.0.10 | 0.548 ms | 0.329 ms | 0.262 ms | 141.7 ms |
| Lua 5.4.8 | 0.373 ms | 0.075 ms | 0.162 ms | 6.50 ms |

当前 Oort（解释器及 VM）约为 CPython 的 **102–832 倍**耗时。Node 的优化 JIT 可能折叠简单循环/字段更新，其数字只作下限；Ruby/Lua 作语境参考。

详细运行方式与 Node/JIT、Ruby/Lua 的 caveat 见
[reference/README.md](reference/README.md)。

## 4. 历史里程碑

| 日期 | 状态 | fib(15) | loop 10000 | 说明 |
|---|---|---:|---:|---|
| 2026-11-21 | VM 第一切片 | 18.74 ms（5.47×） | 76.23 ms（2.34×） | 仅标量/函数/分支/循环 |
| 2026-11-21 | 完整子集复测 | 37.83 ms（2.72×） | 95.04 ms（1.96×） | 加入集合、类、模块、ADT、参数绑定后 |

第一切片数字保留用于对照，不作为当前性能承诺。每次后端/优化改动后，
应重新生成当前快照并在 `benchmarks/history.json` 追加里程碑。

## 5. 维护规则

1. 在安静机器上运行上面的三条命令，确认 benchmark 结果校验通过；
2. 只更新 `benchmarks/history.json` 中的历史里程碑元数据；
3. 当前表格由 `report.py` 生成，不要手改 RESULTS 数字；
4. 若结论跨过目标线，只在 design08/roadmap 写一句结论并链接本文件；
5. benchmark JSON、profile 与临时图表不提交仓库；长期趋势交给 CI。
