# Oort 路线图

Oort 是用于学习编译原理与编程语言设计的玩具语言。Python 原型优先验证**语义**；
性能与工程化（字节码、LLVM、Rust）在语义稳定后再做。

设计约束（所有阶段适用）：

1. 特性正交，不写“类型特判”；
2. 未实现的语法显式报错，不保留半成品；
3. 元编程（宏、`comptime`）最后做；
4. 每个特性先有规范与测试，再有优化；
5. 方言是语义边界：共享骨架不承载方言策略，后端不为方言复制。

## 开发模型

开发与验收以**方言**为主轴，共享组件保持方言无关：

- **共享骨架**：词法/语法超集、AST、源码位置、诊断、模块加载、CLI/REPL、
  测试与基准设施。不为单个方言加特判。
- **方言切片**：对象模型、语义分析、特性门控、规范与测试。一个方言一个语义
  分析器，差异在语义分析阶段门控，不提前分叉文法。
- **共享后端**：树遍历解释器 → 统一 HIR → 字节码 VM。方言差异在进入 HIR 前
  消化；两个方言都先用树遍历解释器跑通 v1。

**方言 v1 的完成定义**：规范声明的特性全部可端到端运行，并有正向测试、拒绝
测试、示例与文档；不以“所有后端/优化完成”为标准。

## 阶段

### 阶段 0：共享骨架与动态核心（完成）

ANTLR 语法与 Pratt 表达式解析、AST、名称解析、树遍历解释器、函数/闭包/类/
继承/元类、容器、运算符重载、内建函数与 REPL。旧的寄存器字节码原型已移除
（[OP 0004](proposals/0004-bytecode-vm.md)）。

### 阶段 1：`oort-object` v1（P1 已完成，P2 打磨中）

把动态方言做成完整、可演示、可验收的产品。对象模型见
[OP 0007](proposals/0007-oort-object-object-model.md)。

已完成：

- 方言契约与按方言构造的 Pratt 表；
- 动态对象模型：开放字段袋、方法遮蔽检查；用户类默认身份相等/哈希
  （容器值/键协议见 OP 0016）；
- 运算符重载（用户类与内建类型共用方法表）；
- 统一值/键相等协议：容器相等与成员测试递归使用 Oort 值相等，Dict/Set
  使用键协议，宿主投影不再定义语言相等
  （[OP 0016](proposals/0016-equality-protocol.md)）；
- 表达式/表面语法清理（[OP 0009](proposals/0009-expression-and-surface-cleanup.md)）；
- 小型 lambda 匿名参数（[OP 0010](proposals/0010-token-responsibilities-and-anonymous-parameters.md)）；
- 完整参数绑定（[OP 0011](proposals/0011-parameter-binding.md)）；
- 模块与导入加载器、规范路径缓存、循环诊断与 `-I/--module-path`
  （[OP 0006](proposals/0006-modules-and-imports.md)）；
- 最小标准库：集合助手与 `math`/`string` 原生模块，以及宿主边界重构
  （[OP 0012](proposals/0012-standard-library.md)）；
- 用户对象迭代器协议：`__iter__` + `(value, valid)`，内置容器与用户
  迭代器统一分发（[OP 0013](proposals/0013-iterator-protocol.md)）；
- 扩展方法与扩展运算符：类外 `def C.f` / `def C.operator`，词法作用域、
  导入激活、调用点歧义、继承与 `super`
  （[OP 0014](proposals/0014-extension-methods.md)）；
- 文法去宿主化、token 后处理层与 REPL 分层重构
  （[OP 0008](proposals/0008-lexer-postprocessing-and-repl.md)）；
- 最小 I/O、命令行参数、退出码与 `string.ord/chr`
  （[OP 0015](proposals/0015-minimal-io-and-process.md)）。

P1 已完成。后续打磨（P2）：

- 字段初始化器语法糖；
- 覆盖率与基准回归持续维护。
- 已完成下标/缺失属性协议（[OP 0018](proposals/0018-subscript-and-missing-attribute-protocol.md)）。

### 阶段 2：`oort-core` v1（薄探针已完成）

已完成薄探针（[OP 0017](proposals/0017-oort-core-thin-probe.md)）：
`#lang oort-core`、Int/Float/Bool/String/Unit 与函数、独立类型检查器、同一
程序在动态/静态方言下的路由隔离。已完成同方言模块导入与导出接口：core→core 的
`import` / `from`、模块命名空间、再导出与编译期循环检测；跨方言仍拒绝。
已完成单态 ADT 第一切片：`enum`、构造器、`match`、嵌套构造器模式、
`_`/绑定与顶层构造器穷尽性，端到端可执行。已完成函数类型、lambda 与
函数值/高阶函数。规范见 [spec 11](spec/11-core-probe.md)。

已完成 expected-type 分支传播：标注、赋值、返回、函数体与实参的期望类型
下推到 `if`/块/`match` 分支。已完成 Float/String 标量扩展、Int/Float 混合
算术与 `/`（固定返回 Float），以及 `List[T]`/`Set[T]`/`Dict[K, V]`/`Tuple[...]`
集合、下标/`len`、`while`/`for`。已完成静态类与固定槽：槽类型/初始化顺序、
确定赋值、`val` 只读与构造器检查。后续按 [OP 0005](proposals/0005-type-system.md)
实现函数返回类型推断、泛型 ADT（内部单态化 + 边界擦除）、
`Result`/`Option`、字面量/元组/守卫/或模式与嵌套穷尽性、静态对象模型与槽
变量，以及跨方言 FFI 边界。

### 阶段 3：共享后端

前置：两个方言的 v1 对象模型稳定。HIR 与 32 位字节码编码/反汇编第一切片
已落地（线性寄存器指令、动态子集 lowering、集合/下标/切片/属性、`-t bc`/`-t vm`、
寄存器 VM、lambda/闭包与一等函数值）。当前 VM 在 fib/循环宏基准上相对
解释器约 2.3–5.5×；接下来继续扩大 HIR/VM 子集（类/方法、模块）、完善差分
测试，再考虑默认后端切换与 LLVM。

### 阶段 4：`oort-systems` / `oort-meta` 与 DSL 开关（按需）

DSL 作为正交开关叠加在 `oort-object` / `oort-core` 之上；`oort-systems`
依赖内存模型与 ABI；`oort-meta` 依赖稳定的 AST、类型表示与模块边界。

### 阶段 5：静态后端与 Rust 迁移（远期）

LLVM IR、静态模块单态化、GC/ARC 选择，以及关键路径的 Rust 重写。

## 工作如何跟踪

- **语言变更**：先写 `docs/proposals/`，再更新 `docs/spec/` 与测试。
- **公开进度**：本文件保持高层阶段与目标；已完成项记录在
  [CHANGELOG](https://github.com/fyabc/oort-lang.py/blob/main/CHANGELOG.md)。
- **任务级事项**：GitHub issues + milestones。
- **日常决策与未合并工作**：维护在私有工作台账（不随仓库发布）。

当某个阶段全部完成时，其详细执行清单从私有台账归档，本文件只保留结果与
下一阶段的入口。
