# 性能基准测试方法论

> 整理自项目早期的设计讨论（原始记录未纳入仓库）。

---

## 1. 测试层级

七层测试框架，从微基准到真实工作负载：

| 层级 | 名称 | 测试内容 | 示例 |
|------|------|---------|------|
| L1 | 指令级 | 单条指令执行速度 | LOAD_CONST, ADD |
| L2 | 操作级 | 基本操作序列 | 函数调用开销、属性查找 |
| L3 | 结构级 | 控制流结构 | 循环、递归、闭包 |
| L4 | 数据结构 | 容器操作 | 列表追加、字典查找 |
| L5 | 算法级 | 经典算法 | Fibonacci、排序、矩阵乘法 |
| L6 | 程序级 | 小型完整程序 | 解释器、编译器片段 |
| L7 | 工作负载 | 真实应用 | Richards、DeltaBlue |

## 2. 跨语言基准

> **定位**：跨语言数字只用于人工参考与性能预算校准，**不进入 CI 门禁**。
> 不同运行时（JIT/GC/整数模型）、程序语义和机器负载会让比较失真；CI 只对
> Oort 自身的历史结果告警。主对比始终是 **Oort 树遍历解释器 vs Oort VM**。

推荐用于跨语言对比的标准测试：

| 基准 | 来源 | 测试重点 |
|------|------|---------|
| Richards | Google | 面向对象调度 |
| DeltaBlue | 约束求解器 | 方法调度 + 内联缓存 |
| spectral-norm | Shootout | 数值计算 |
| binary-trees | Shootout | 内存分配 + GC |
| fannkuch | Shootout | 数组操作 |
| n-body | Shootout | 浮点运算 |

## 3. 统计方法

### 3.1 运行要求

- **最少 30 次运行**（中心极限定理）
- 报告中位数（而非平均值，减少离群值影响）
- 几何平均用于跨基准汇总

### 3.2 环境控制

- 预热运行（前 5 次不计入）
- 关闭 CPU 频率调节
- 固定 CPU 核心
- 关闭无关进程

## 4. 当前基准测试

`benchmarks/` 使用 pytest-benchmark 覆盖微基准、宏基准、启动与内存：

| 文件 | 覆盖 |
|------|------|
| `test_micro.py` | 算术、局部变量、函数调用、属性、下标、字典 |
| `test_macro.py` | 递归、循环、方法分派 |
| `test_stdlib.py` | map/filter/sorted/zip/enumerate、字符串 join、宿主投影与 `len` |
| `test_iterators.py` | 内置循环、用户 `__iter__` 闭包、无限迭代器 + `break` |
| `test_startup.py` | 编译器/运行时构造、空程序 |
| `test_memory.py` | Runtime 与程序的峰值内存上限 |
| `test_ast_interpreter.py` | 历史 Fibonacci 基线 |
| `test_vm.py` | 同一 HIR 程序在解释器与字节码 VM 上的对比 |

微/宏基准由 `bench_utils.compile_program` 先完成解析、语义分析和解释器
构造，基准函数只测 `interpreter.run(ast)`；编译开销由启动/空程序基准单独
度量，避免把解析时间混入每次操作。

回归跟踪由 `.github/workflows/benchmark.yml` 在 `main` 上写入历史，并在
较基线回退 150% 时告警。运行方式、基线与 profiling 工具
（py-spy / Scalene / Memray）见
[`benchmarks/README.md`](https://github.com/fyabc/oort-lang/blob/main/benchmarks/README.md)。

### 扩展计划

- [x] 添加闭包创建/调用基准
- [x] 添加类实例化基准
- [x] 添加属性查找基准
- [x] 添加控制流基准 (循环、分支)
- [x] 添加可选的手动跨语言参考套件（Python/Node/Ruby/Lua）
- [ ] 增加 CI 中的机器可读阈值（当前为历史告警）

### 手动参考套件规则

- 程序按**算法**对齐（fib、循环求和、方法分派），不做单条指令对比；
- 固定语言版本与机器，预热后取中位数，记录 30 次运行；
- Python 是最有意义的基线：Oort 运行在 Python 宿主上，CPython 提供现实下限；
  Node/Lua/Ruby 只作语境参考；
- 结果 JSON/图表不提交仓库，只记录结论与预算。

## 5. 实现语言选择

| 语言 | 适合度 | 说明 |
|------|--------|------|
| **Rust** | ⭐⭐⭐⭐⭐ | 首选，内存安全 + 性能 |
| C | ⭐⭐⭐⭐ | 传统选择，手动内存管理 |
| C++ | ⭐⭐⭐ | 强大但复杂 |
| Zig | ⭐⭐⭐⭐ | 新兴选择，简洁高效 |

---

## 6. P4 性能预算（2026-11-21 基线）

### 6.1 当前结果

当前树遍历基线、VM 对比、跨语言参考和内存上限统一记录在
[`benchmarks/RESULTS.md`](https://github.com/fyabc/oort-lang/blob/main/benchmarks/RESULTS.md)。
本文只保留测量方法、预算与结论，不复制整张结果表，避免多处数字漂移。

**最近结论（详细数字见 RESULTS）**：

- 树遍历解释器仍以预编译程序的 pytest-benchmark 中位数为基线；
- VM fib 稳定超过 2× 目标，loop 在约 1.8–2.0× 之间波动，尚未稳定达标；
- 跨语言参考显示 Oort 仍比 CPython 慢数百倍，Node 数字仅作下限。

### 6.2 目标

- **正确性**：VM 与解释器在全部测试程序上结果/错误一致（差分测试）。
- **VM v1**：宏基准 ≥ 2× 树遍历解释器；micro 与启动不出现回归。
  （当前 fib 已达标，loop 仍需优化。）
- **VM v1.1**：宏基准 ≥ 5×；fib(25) < 5 s；100 万次循环 < 5 s；
  100 万次方法分派 < 10 s（本机）。
- **可用级别（stretch）**：宏基准耗时进入 CPython 的 20–30 倍以内。
- 绝对目标随 HIR/VM 落地后重新校准，不在没有实现时承诺更细的数字。

### 6.3 与跨语言对比的关系

- 跨语言对比用于判断“是否值得继续优化”和设定 stretch 目标，不用于 CI。
- 每次性能结论必须同时给出：同机 Oort VM vs 树遍历解释器的倍数，以及
  CPython 参考倍数；否则不能称为“可用”。
- 手动参考套件：`benchmarks/reference/`（内部计时、100ms 自适应重复、
  结果校验、启动单独测量）。运行说明与 caveat 见该目录 README；结果统一
  记录在 [`benchmarks/RESULTS.md`](https://github.com/fyabc/oort-lang/blob/main/benchmarks/RESULTS.md)。

### 6.4 更新流程

1. 运行 `pytest benchmarks/ --benchmark-json=benchmark.json` 和
   `benchmarks/reference/run.py --json > reference.json`；
2. 运行 `python benchmarks/report.py --benchmark benchmark.json --reference reference.json`
   重新生成 RESULTS；需要时用 `--check` 验证已提交版本未漂移；
3. 只手工更新 `benchmarks/history.json` 的历史里程碑元数据；
4. 只有当结论跨过目标线时，才在本文/roadmap 更新一句结论并链接结果页；
5. 不提交 benchmark JSON、profile 或临时图表；长期趋势由 CI benchmark
   工作流维护。
