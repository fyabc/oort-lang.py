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
| `test_startup.py` | 编译器/运行时构造、空程序 |
| `test_memory.py` | Runtime 与程序的峰值内存上限 |
| `test_ast_interpreter.py` | 历史 Fibonacci 基线 |

微/宏基准由 `bench_utils.compile_program` 先完成解析、语义分析和解释器
构造，基准函数只测 `interpreter.run(ast)`；编译开销由启动/空程序基准单独
度量，避免把解析时间混入每次操作。

回归跟踪由 `.github/workflows/benchmark.yml` 在 `main` 上写入历史，并在
较基线回退 150% 时告警。运行方式、基线与 profiling 工具
（py-spy / Scalene / Memray）见
[`benchmarks/README.md`](https://github.com/fyabc/oort-lang.py/blob/main/benchmarks/README.md)。

### 扩展计划

- [x] 添加闭包创建/调用基准
- [x] 添加类实例化基准
- [x] 添加属性查找基准
- [x] 添加控制流基准 (循环、分支)
- [ ] 添加可选的手动跨语言参考套件（Python/Node；Lua/Ruby 视环境）
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

### 6.1 当前树遍历解释器基线

Windows / Ryzen 7 5800H，`pytest benchmarks/`，中位数；程序已预先编译，
只测 `interpreter.run(ast)`：

| 基准 | 当前中位数 |
|------|-----------|
| micro arithmetic | 0.047 ms |
| micro function call | 0.039 ms |
| micro attribute | 0.058 ms |
| micro index | 0.022 ms |
| micro class instantiation | 0.065 ms |
| macro loop (1000) | 17.37 ms |
| macro method dispatch (1000) | 43.95 ms |
| fib(10) | 12.37 ms |
| fib(20) | 1017.44 ms |
| 空程序（含运行入口） | 1.37 ms |

同一算法的 CPython 3.12 参考（同机、同一进程内简单计时，仅作数量级校准）：

| 算法 | CPython |
|------|---------|
| fib(20) | ~1.26 ms |
| 循环 1000 | ~0.044 ms |
| 方法分派 1000 | ~0.097 ms |

当前树遍历解释器约为 CPython 的 **400–800 倍**耗时。

### 6.2 目标

- **正确性**：VM 与解释器在全部测试程序上结果/错误一致（差分测试）。
- **VM v1**：宏基准 ≥ 2× 树遍历解释器；micro 与启动不出现回归。
- **VM v1.1**：宏基准 ≥ 5×；fib(25) < 5 s；100 万次循环 < 5 s；
  100 万次方法分派 < 10 s（本机）。
- **可用级别（stretch）**：宏基准耗时进入 CPython 的 20–30 倍以内。
- 绝对目标随 HIR/VM 落地后重新校准，不在没有实现时承诺更细的数字。

### 6.3 与跨语言对比的关系

- 跨语言对比用于判断“是否值得继续优化”和设定 stretch 目标，不用于 CI。
- 每次性能结论必须同时给出：同机 Oort VM vs 树遍历解释器的倍数，以及
  CPython 参考倍数；否则不能称为“可用”。
- 手动参考套件：`benchmarks/reference/`（内部计时、100ms 自适应重复、
  结果校验、启动单独测量）。运行说明与 caveat 见该目录 README。

### 6.4 首次跨语言参考（2026-11-21）

`--repeat 3`，Ryzen 7 5800H / Windows；exec 为单次 workload 内部计时：

| 运行时 | fib(20) | loop 20000 | methods 5000 | 启动 |
|---|---:|---:|---:|---:|
| Oort tree-walker | 1093 ms | 368 ms | 230 ms | 497 ms |
| Python 3.12 | 1.33 ms | 1.30 ms | 0.58 ms | 42 ms |
| Node 24.15 | 0.066 ms | 0.006 ms | 0.002 ms | 51 ms |
| Ruby 4.0.10 | 0.56 ms | 0.33 ms | 0.27 ms | 143 ms |
| Lua 5.4.8 | 0.37 ms | 0.077 ms | 0.16 ms | 6 ms |

Oort 当前约为 CPython 的 280–825 倍耗时。Node 的数字受 JIT 消除影响，只作
下限；Ruby/Lua 作语境参考。预算与目标见 §6.2。
