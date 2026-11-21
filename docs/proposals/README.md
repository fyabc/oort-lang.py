# Oort 提案（Oort Proposals）

本目录采用类似 Python PEP / Rust RFC 的流程，管理语言、语义与工具链的
**非平凡变更**。目标是避免 C++ 式“特性层层打补丁”：

- 每个特性在实现前先写清楚动机、边界与替代方案；
- 特性之间保持正交，不允许“特例 + 隐式例外”；
- 元编程类特性（宏、编译期计算）排在使用期语义稳定之后。

## 状态

| 状态 | 含义 |
|------|------|
| Draft | 讨论中，尚未定稿 |
| Proposed | 已提交，等待实现/评审 |
| Accepted | 已接受，正在或等待实现 |
| Implemented | 已实现，并由 [语言规范](../spec/index.md) 与测试覆盖 |
| Rejected | 不采纳（保留记录，避免重复讨论） |
| Withdrawn | 作者撤回 |

## 提案列表

| 编号 | 标题 | 状态 |
|------|------|------|
| [0001](0001-feature-layers-and-dialects.md) | 特性分层与语言方言（防止 C++ 化） | Accepted |
| [0002](0002-dsl-support.md) | 嵌入式 DSL 支持 | Proposed |
| [0003](0003-grammar-cleanup.md) | 文法清理与语义收紧 | Implemented |
| [0004](0004-bytecode-vm.md) | 字节码虚拟机（重新实现） | Accepted（第一切片实现中） |
| [0005](0005-type-system.md) | 类型系统、泛型、ADT 与模式匹配 | Draft |
| [0006](0006-modules-and-imports.md) | 模块与导入系统 | Implemented |
| [0007](0007-oort-object-object-model.md) | `oort-object` 动态对象模型 | Implemented |
| [0008](0008-lexer-postprocessing-and-repl.md) | 词法后处理层与 REPL 重构 | Implemented |
| [0009](0009-expression-and-surface-cleanup.md) | 表达式语义与语法表面积清理 | Implemented |
| [0010](0010-token-responsibilities-and-anonymous-parameters.md) | Token 职责与匿名 lambda 参数 | Implemented |
| [0011](0011-parameter-binding.md) | 参数绑定：默认值、关键字实参与变长参数 | Implemented |
| [0012](0012-standard-library.md) | 最小标准库与宿主边界 | Implemented |
| [0013](0013-iterator-protocol.md) | 迭代器协议（`__iter__` + `(value, valid)`） | Implemented |
| [0014](0014-extension-methods.md) | 扩展方法与扩展运算符（`def C.f`） | Implemented |
| [0015](0015-minimal-io-and-process.md) | 最小 I/O、命令行参数与退出码 | Implemented |
| [0016](0016-equality-protocol.md) | 统一相等性协议（值相等 / 键相等） | Implemented |
| [0017](0017-oort-core-thin-probe.md) | `oort-core` 薄探针（Int/Float/Bool/String/Unit/函数） | Implemented |
| [0018](0018-subscript-and-missing-attribute-protocol.md) | 下标与缺失属性协议（`operator "[]"`/`"[]="`、`on_missing`） | Implemented |
| [0019](0019-hir-vm-parameter-binding.md) | 参数绑定进入 HIR/VM（默认值、关键字、变长、块参数） | Implemented |

## 流程

1. 复制 [0000-template.md](0000-template.md)，分配下一个编号。
2. 在提案中写清：动机、设计、语义边界、与现有特性的正交性、替代方案、
   向后兼容与测试计划。
3. 更新本页的提案列表与状态。
4. 实现时：
   - 同步更新 `docs/spec/`；
   - 增加或修改 `tests/`；
   - 若提案改变了未实现特性的拒绝清单，更新
     [06-conformance.md](../spec/06-conformance.md)。
5. 实现完成后把状态改为 `Implemented`。

## 决策记录

| 日期 | 决策 | 提案 |
|------|------|------|
| 2026-11-18 | 文法清理：`USER_OP` 去掉 `.`/`:`/`@`，删除死 token，`elif`/`else` 对称化 | [OP 0003](0003-grammar-cleanup.md)（Implemented） |
| 2026-11-18 | 移除不成熟的寄存器字节码原型；重新实现需满足显式失败与端到端测试等前置条件 | [OP 0004](0004-bytecode-vm.md) |
| 2026-11-18 | 类型参数采用声明处变型：`[out T: Bound]` / `[in T: Bound]`，上界用 `T: Bound` | [OP 0005 §3.1](0005-type-system.md#31-类型参数语法与变型已接受) |
| 2026-11-18 | 运算符方法统一用 `def operator "<sym>"` 字符串命名；内建类型与用户类共用 `OortType.operators` 调度；`!=`/`!in` 默认取反 | [OP 0002 §3](0002-dsl-support.md#3-运算符声明) |
| 2026-11-18 | 采用“共享骨架 + 方言垂直切片 + 共享后端”的开发模型；先完成 `oort-object` v1，再以薄 `oort-core` 探针验证隔离 | [OP 0001 §5](0001-feature-layers-and-dialects.md#5-开发模型共享骨架--方言垂直切片2026-11-18-已接受) |
| 2026-11-18 | `oort-object` 使用开放字段袋、拒绝类体 `var`/`val`、禁止实例字段遮蔽类方法；槽归入 `oort-core` 静态对象模型 | [OP 0007](0007-oort-object-object-model.md)（Implemented） |
| 2026-11-18 | `oort-object` v1 对象模型实现完成：方法遮蔽检查覆盖类方法、缺失属性诊断、身份相等/哈希 | [OP 0007](0007-oort-object-object-model.md)（Implemented） |
| 2026-11-18 | `Oort.g4` 去除宿主语言动作，换行/括号交给 token 后处理层；REPL 重构为 `ReplSession` 并补分层测试 | [OP 0008](0008-lexer-postprocessing-and-repl.md)（Implemented） |
| 2026-11-18 | `#lang` 按首行预处理识别（该行对词法器仍是注释），非首行/未知/未实现方言显式报错；`DialectConfig` 提供特性门控与 Pratt 表工厂 | [OP 0001 §3](0001-feature-layers-and-dialects.md#3-模块级方言控制) |
| 2026-11-18 | 位运算高于比较；比较非结合；`Bool` 不再 `<: Int` | [OP 0009](0009-expression-and-surface-cleanup.md)（Implemented） |
| 2026-11-18 | 移除标识符 `!` 后缀；所有形参列表必须带括号；关闭隐式中缀；拒绝 `def C.f` / `class A.B` / 显式 `super(...)` | [OP 0009](0009-expression-and-surface-cleanup.md)（Implemented） |
| 2026-11-18 | 支持 `break expr`、行首 `.` 续行、`//=`；Dict/Set 使用 Oort 字面量显示 | [OP 0009](0009-expression-and-surface-cleanup.md)（Implemented） |
| 2026-11-18 | 固定 token 职责：`:` 标签/体、`=` 绑定/命名实参、`->` 返回类型、`=>` 延迟/映射 | [OP 0010](0010-token-responsibilities-and-anonymous-parameters.md)（Implemented） |
| 2026-11-18 | 实现匿名 lambda 参数 `$0` / `$1`；仅允许无显式参数列表的 lambda | [OP 0010](0010-token-responsibilities-and-anonymous-parameters.md)（Implemented） |
| 2026-11-19 | 参数绑定：默认值调用时求值；`*args` 用 Tuple；`**kwargs` 用 Dict；尾随块与 `block = ...`；位置限定名可被 `**kwargs` 捕获 | [OP 0011](0011-parameter-binding.md)（Implemented） |
| 2026-11-19 | 模块系统：顶层-only import（提升执行）、规范路径缓存、首版禁止循环、默认全公开；只导入 `.ort`，宿主模块留待 FFI；新增 `-I/--module-path` | [OP 0006](0006-modules-and-imports.md)（Implemented） |
| 2026-11-20 | 标准库：集合助手为全局内建、急切返回 List、集合优先回调顺序；`sorted` 稳定并使用 Oort `<`；`math`/`string` 为封闭原生模块；`HostBridge`/HOST-VALUE-CONTEXT 宿主边界 | [OP 0012](0012-standard-library.md)（Implemented） |
| 2026-11-20 | 迭代器：`__iter__()` 返回可调用迭代器，步进返回 `(value, valid)`；valid 为严格 Bool；内置容器实现同一协议，`for` 流式拉取 | [OP 0013](0013-iterator-protocol.md)（Implemented） |
| 2026-11-20 | 扩展：`def C.f` / `def C.operator` 按词法作用域生效，成员/字段/类内运算符优先；作用域分层后按 MRO 具体度；导入直接激活、调用点歧义；扩展内允许 `super`（只查类成员） | [OP 0014](0014-extension-methods.md)（Implemented） |
| 2026-11-20 | 真实程序支持：`io.read_file/write_file`（UTF-8 整文件，失败为运行时错误）；`os.args`（仅用户参数）、`os.script`、`os.exit`；`string.ord/chr` | [OP 0015](0015-minimal-io-and-process.md)（Implemented） |
| 2026-11-20 | 相等性：值 `==` 递归容器；Bool/Int 全层严格；Dict/Set 使用独立键相等/哈希（Ruby `eql?` 模型）；移除相等/成员/集合代数的 HOST 投影 | [OP 0016](0016-equality-protocol.md)（Implemented） |
| 2026-11-20 | `oort-core` 初版薄探针：Int/Bool/Unit/函数、标注必填、独立检查器；`/`/`**` 因可能产生 Float 而拒绝；跨方言导入显式拒绝 | [OP 0017](0017-oort-core-thin-probe.md)（Implemented） |
| 2026-11-20 | core 同方言模块导入：`import` / `from`、模块命名空间只读、导出顶层名字与再导出、编译期循环检测；仍拒绝 object↔core 与 native 导入 | [OP 0017](0017-oort-core-thin-probe.md)（Implemented） |
| 2026-11-21 | core 单态 ADT 第一切片：模块顶层 `enum`、构造器、`match`、`_`/绑定/嵌套构造器模式、顶层构造器穷尽性；泛型 ADT、`Option[T]`/`Result[T,E]`、字面量/守卫/或模式与嵌套穷尽性留后 | [OP 0017](0017-oort-core-thin-probe.md)（Implemented） |
| 2026-11-21 | core 函数类型与函数值：`(Int, Bool) -> Int` 注解、显式参数 lambda、函数值/高阶函数；匿名/泛型/默认值 lambda 拒绝；expected-type 下推到 if/块/match 与实参 | [OP 0017](0017-oort-core-thin-probe.md)（Implemented） |

## 设计原则（所有提案必须满足）

- **正交性**：特性可自由组合，不为特定类型/场景写特判。
- **显式优于隐式**：隐式行为（自动转换、隐式捕获、隐式本地化）必须可关闭或有明确理由。
- **拒绝半成品**：未实现的语法要么移除，要么在语义分析阶段显式报错。
- **先语义后性能**：动态语义稳定前不引入字节码/JIT 复杂度。
- **元编程最后**：宏与编译期计算依赖稳定的 AST、作用域与类型模型。
| 2026-11-21 | 下标协议 `operator "[]"`/`"[]="`；缺失属性只读 fallback `on_missing`；不引入 dunder 魔术名与写钩子 | [OP 0018](0018-subscript-and-missing-attribute-protocol.md)（Implemented） |
| 2026-11-21 | 参数绑定进入 HIR/VM：共享绑定核心、默认值 proto（按闭包缓存）、`CALL_KW`、`SignatureSpec`；移除运行时 arity | [OP 0019](0019-hir-vm-parameter-binding.md)（Implemented） |
