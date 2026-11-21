# 设计知识库索引

本目录整理了 Oort 语言的设计调研与决策记录。与 [语言规范](../spec/index.md)、
[提案](../proposals/README.md)、[实现笔记](../implementation/index.md) 的分工：

- **spec**：当前实现实际接受的语言行为；
- **proposals**：尚未实现或正在讨论的变更；
- **design**（本目录）：设计调研、备选方案与长期技术判断；
- **implementation**：编译器内部实现说明。

| 文档 | 主题 |
|------|------|
| [01-runtime-value-representation.md](01-runtime-value-representation.md) | 运行时值表示、整数层级、Tagged Pointer |
| [02-bytecode-vm-design.md](02-bytecode-vm-design.md) | 字节码 ISA、VM 架构、寄存器分配、闭包模型（**设计稿**，实现已移除，见 [OP 0004](../proposals/0004-bytecode-vm.md)） |
| [03-type-system-design.md](03-type-system-design.md) | 渐进类型、泛型、类型检查器、方法重载 |
| [04-class-object-model.md](04-class-object-model.md) | 元类、类声明、属性查找、Mixin、`this`、扩展方法 |
| [05-macro-system-design.md](05-macro-system-design.md) | 语法宏、`comptime`、AST 元编程 |
| [06-language-syntax-design.md](06-language-syntax-design.md) | 形参语法、运算符重载、导入时机、迭代器协议 |
| [07-concurrency-abi-design.md](07-concurrency-abi-design.md) | 多线程、ABI、FFI |
| [08-performance-benchmarking.md](08-performance-benchmarking.md) | 性能基准测试方法论 |
| [09-version-naming.md](09-version-naming.md) | 天体命名版本号方案 |
| [10-category-theory-notes.md](10-category-theory-notes.md) | 范畴论在编译器中的应用笔记 |
| [11-latest-research-2025.md](11-latest-research-2025.md) | 2025–2026 年语言设计前沿调研 |
| [12-host-boundary.md](12-host-boundary.md) | 宿主边界、HostBridge、原生调用模式与 Rust 迁移 |
| [13-hir-design.md](13-hir-design.md) | 共享 HIR 与 32 位字节码编码：指令、lowering 范围、调用约定与下一步 |

## 使用注意

本目录是**设计讨论**，不是规范。部分文档描述的是尚未实现或已放弃的方案：

1. HIR 第一切片已实现（13）；字节码编码与 VM（02）仍无实现，旧原型因静默错误已删除。
2. 宏系统（05）与 `comptime` 尚未实现，属于最晚期特性。
3. 类型系统（03）描述的是目标设计；当前动态方言不检查类型。
4. 文档中的示例使用 Oort 注释语法 `#`；保留的 `//` 只出现在 TypeScript 等对比代码中。
5. 部分性能/社区调研数据有时效性，引用前请复核。
