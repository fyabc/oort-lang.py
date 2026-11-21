# Oort 语言文档

Oort 得名于**奥尔特云**——太阳系最外缘那层包裹着一切的冰质云团。它遥远、
安静，却承载着无数尚未被命名的彗星与可能性。这正是我们对这门语言的期待：
边界可以很远，但核心必须清晰、稳定、可理解。

Oort 以“显式优于隐式、正交优于特例、先语义后性能”为准则：`oort-object`
动态方言的 v1 已完成，`oort-core` 已有薄静态探针，之后向完整静态方言与
共享后端演进。项目中的工具链也会延续天文学词汇的命名传统——你已经能在
左上角的轨道与彗星里看到它。

欢迎从[开始使用](getting-started.md)或[示例](examples.md)进入；想了解语言
当前确切行为，请直接阅读[语言规范](spec/index.md)。

## 快速入门

- [开始使用](getting-started.md) — 安装 Oort 并运行第一个程序
- [示例代码](examples.md) — 通过示例学习 Oort 语法
- [VSCode 插件](https://github.com/fyabc/oort-lang/tree/main/editors/vscode) —
  `.ort` 语法高亮与本地安装

## 语言规范

**规范**描述当前实现实际接受的行为，是语言使用者的主要参考：

- [规范索引](spec/index.md)
- [词法结构](spec/01-lexical.md) — 字面量、关键字、运算符表
- [表达式](spec/02-expressions.md) — 运算符、容器、下标与切片、调用
- [语句](spec/03-statements.md) — 声明、赋值、控制流
- [函数](spec/04-functions.md) — `def`、lambda、闭包、尾随闭包
- [类](spec/05-classes.md) — 继承、元类、`this` / `super`
- [模块与导入](spec/07-modules.md) — 路径解析、缓存、循环诊断
- [标准库](spec/08-stdlib.md) — 集合助手、`math` / `string`
- [迭代器协议](spec/09-iterators.md) — `__iter__`、流式 `for`
- [扩展方法与运算符](spec/10-extensions.md) — `def C.f`、作用域、导入、`super`
- [`oort-core` 薄探针](spec/11-core-probe.md) — Int/Float/Bool/String/Unit、集合与循环、静态类/槽、单态 ADT/`match`、静态检查与拒绝清单
- [实现状态矩阵](spec/06-conformance.md) — 已实现 / 被拒绝 / 计划中的特性

## 提案

Oort 的语言变更采用类 PEP/RFC 流程：

- [提案索引与流程](proposals/README.md)
- [OP 0001: 特性分层与语言方言](proposals/0001-feature-layers-and-dialects.md)
- [OP 0002: 嵌入式 DSL 支持](proposals/0002-dsl-support.md)
- [OP 0003: 文法清理与语义收紧](proposals/0003-grammar-cleanup.md)（已实现）
- [OP 0004: 字节码虚拟机](proposals/0004-bytecode-vm.md)
- [OP 0005: 类型系统、泛型、ADT 与模式匹配](proposals/0005-type-system.md)
- [OP 0006: 模块与导入系统](proposals/0006-modules-and-imports.md)（已实现）
- [OP 0007: `oort-object` 动态对象模型](proposals/0007-oort-object-object-model.md)（已实现）
- [OP 0008: 词法后处理层与 REPL 重构](proposals/0008-lexer-postprocessing-and-repl.md)
- [OP 0009: 表达式语义与语法表面积清理](proposals/0009-expression-and-surface-cleanup.md)（已实现）
- [OP 0010: Token 职责与匿名 lambda 参数](proposals/0010-token-responsibilities-and-anonymous-parameters.md)（已实现）
- [OP 0011: 参数绑定](proposals/0011-parameter-binding.md)（已实现）
- [OP 0012: 最小标准库与宿主边界](proposals/0012-standard-library.md)（已实现）
- [OP 0013: 迭代器协议](proposals/0013-iterator-protocol.md)（已实现）
- [OP 0014: 扩展方法与扩展运算符](proposals/0014-extension-methods.md)（已实现）
- [OP 0015: 最小 I/O、命令行参数与退出码](proposals/0015-minimal-io-and-process.md)
- [OP 0016: 统一相等性协议](proposals/0016-equality-protocol.md)（已实现）
- [OP 0017: `oort-core` 薄探针](proposals/0017-oort-core-thin-probe.md)（已实现）

## 实现与设计

- [实现笔记](implementation/index.md) — 语法、解析器、解释器、类系统
- [设计知识库](design/00-INDEX.md) — 调研与备选方案（非规范）
- [路线图](roadmap.md) — 里程碑与当前状态

## 开发

- [测试指南](https://github.com/fyabc/oort-lang/blob/main/tests/README.md) —
  单元测试与集成测试的使用方式
- [基准测试](https://github.com/fyabc/oort-lang/blob/main/benchmarks/README.md) —
  运行方式、统计规则与 profiling
- [基准结果](https://github.com/fyabc/oort-lang/blob/main/benchmarks/RESULTS.md) —
  当前基线、VM/解释器对比与跨语言参考
