# Oort Programming Language

[![CI](https://github.com/fyabc/oort-lang.py/actions/workflows/ci.yml/badge.svg)](https://github.com/fyabc/oort-lang.py/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

文档站点：<https://fyabc.github.io/oort-lang.py/>（规范、提案、设计与示例）

## 简介

Oort 是一门用于**编译原理与编程语言设计学习**的玩具语言。Python 实现目前作为原型，
未来可能迁移到 Rust。

Oort 的命名来自天文学中的“[奥尔特云](https://en.wikipedia.org/wiki/Oort_cloud)”，
相关工具链的命名也会使用天文学词汇。

## 当前状态

当前只有一条执行路径：**树遍历解释器**（动态类型）。语法前端（ANTLR + Pratt）
解析的语言超集比运行时更大；**未实现的特性会在语义分析阶段显式报错**，不会静默
产生错误结果。完整的实现/拒绝清单见
[规范：实现状态](docs/spec/06-conformance.md)。

开发以**方言垂直切片**为主轴：`oort-object` 动态方言的 v1 已完成；
`oort-core` 已落地薄探针（`#lang oort-core`，Int/Float/Bool/String/Unit 与
函数、独立静态检查器、跨方言导入拒绝）；共享字节码后端在两个方言 v1 之后。详见
[路线图](docs/roadmap.md) 与
[OP 0001 §5](docs/proposals/0001-feature-layers-and-dialects.md#5-开发模型共享骨架--方言垂直切片2026-11-18-已接受)。

### 已实现

- 类 C 语法；换行分隔语句，括号内可自由换行
- 整数/浮点/字符串/布尔/`null`
- List、Tuple、Dict、Set 字面量与下标、切片
- 一等函数、`do` lambda、闭包、尾随闭包调用；匿名参数 `do: $0 * 2`
- 默认参数、关键字实参、位置/关键字限定、`*args`、`**kwargs`、`&block`
- 迭代器协议：用户类实现 `__iter__` 返回 `(value, valid)` 闭包；内置容器与
  用户对象统一用于 `for ... in`
- `if` / `elif` / `else`、`while`、`for ... in`（含解包）、`break expr`
- `var` / `val`、多目标声明与元组解包、增强赋值（含 `//=`）
- 类、方法、类方法、多重继承（C3 MRO）、元类、`this` / `super`
- 扩展方法与扩展运算符：类外 `def C.f` / `def C.operator "+"(x)`，按词法
  作用域生效，导入激活，成员/字段/类内运算符优先
- 运算符重载：`def operator "+"(other)` 等方法，内建类型使用同一套调度；
  下标 `operator "[]"`/`"[]="` 与缺失属性 `on_missing`
- 行首 `.` 方法链续行；`Bool` 与 `Int` 语义分离
- 内建：`print`、`clock`、`type`、`len`、`range`、`str`、`repr`、
  `int`、`float`、`bool`；集合助手 `map`/`filter`/`sorted`/`zip`/`enumerate`
- 标准库：`math`（常量与数学函数）、`string`（切分/连接/大小写/查找/替换/
  `ord`/`chr`）、`io`（UTF-8 整文件读写）与 `os`（参数、脚本路径、退出码）
- 模块：`import "./lib"`、`import "./lib" as l`、`from "./lib" import a, b as c`；
  规范路径缓存、循环诊断、`-I/--module-path` 搜索路径
- REPL（多行输入；Ctrl-C 取消输入或中断执行；Unix Ctrl-D、Windows Ctrl-Z+Enter、
  `exit` / `quit` 或管道 EOF 正常退出）
- `oort-core` 薄探针：`#lang oort-core`、Int/Float/Bool/String/Unit、List/Tuple/Dict/Set、循环、静态类/槽、标注必填的函数、
  `if`/`return`、单态 ADT（`enum`）、`match` 与顶层构造器穷尽性、函数类型/
  lambda/高阶函数、独立静态检查器；同方言模块导入与导出类型接口；
  `oort-object` 仍忽略标注。见 [规范](docs/spec/11-core-probe.md)

### 待实现（见 proposals）

- 泛型 ADT、`Option[T]`/`Result[T,E]`、完整模式匹配与槽 — [OP 0005](docs/proposals/0005-type-system.md)
- 自定义运算符声明与优先级 — [OP 0002](docs/proposals/0002-dsl-support.md)
- 宏系统与 `comptime` — [设计笔记](docs/design/05-macro-system-design.md)
- 字节码 VM 与 LLVM 后端 — [OP 0004](docs/proposals/0004-bytecode-vm.md)
- 语言方言（core / object / systems） — [OP 0001](docs/proposals/0001-feature-layers-and-dialects.md)

## 样例

各种样例参见 [examples](./examples)，包括一个可读取文件的
[JSON 解析/格式化 CLI](./examples/07_showcase/07_00_json.ort)。

## 文档

- [文档中心](docs/index.md)
- [语言规范](docs/spec/index.md) — 当前实现的行为
- [提案系统](docs/proposals/README.md) — 语言演进流程
- [实现笔记](docs/implementation/index.md)
- [设计知识库](docs/design/00-INDEX.md)
- [路线图](docs/roadmap.md)

## 安装与使用

### 使用 uv（推荐）

```bash
pip install uv
uv sync

# 运行文件（默认执行）
oort test.ort

# 执行一行代码
oort -c "print(42)"

# 启动 REPL
oort

# 只打印 AST / 带元数据的 AST
oort test.ort -t ast
oort test.ort -t astm
oort test.ort -t bc       # 打印 HIR/字节码反汇编（动态子集）
```

### 使用 pip

```bash
pip install .

oort test.ort
```

### VSCode 语法高亮

仓库内置 `.ort` 高亮插件（TextMate，含文件图标，无需 Marketplace）：

```bash
cd editors/vscode
npm install
npm run package
code --install-extension oort-lang-0.1.0.vsix
```

安装后重载窗口即可生效。开发方式、scope 说明与已知限制见
[editors/vscode/README.md](editors/vscode/README.md)。

## 开发

```bash
uv sync --extra dev
pre-commit install

# 测试（默认排除 slow；完整运行用 -m slow）
uv run pytest tests/
uv run pytest tests/ -m slow

# 基准测试
uv run pytest benchmarks/

# 代码质量
uv run ruff check src/ tests/ benchmarks/ scripts/
uv run ruff format src/ tests/ benchmarks/ scripts/
uv run mypy src/
```

### 重新生成语法

需要 Java（17+）。语法文件位于 `grammars/Oort.g4`：

```bash
uv sync --extra build-grammar
python scripts/build_grammar.py
```

## 目录结构

```
src/oort_lang/
├── source/           # 源文本、位置与输入抽象
├── diagnostics/      # 异常、错误报告与 ANTLR 错误监听
├── ast/              # AST 节点、visitor、Binding 与打印器
├── parser/           # 语法、Pratt 解析器与 AST 构建
│   └── grammar/      # ANTLR 生成的词法/语法分析器（勿手改）
├── semantics/        # 名字解析与语义检查
├── runtime/          # 树遍历解释器、对象模型、内建
└── driver/           # 编译器、REPL 与命令行入口
grammars/Oort.g4      # 语法定义
tests/                # 单元测试与集成测试
examples/             # 示例程序
editors/vscode/       # VSCode 语法高亮插件
docs/                 # 规范、提案、实现笔记、设计调研
benchmarks/           # 性能基线
```

## 相关工具

- [ANTLR 4](https://www.antlr.org/) — 词法与语法分析器生成
- [uv](https://docs.astral.sh/uv/) — 依赖与虚拟环境管理
- [ruff](https://docs.astral.sh/ruff/) / [mypy](https://mypy-lang.org/) — 代码质量

## 参与贡献

- [CONTRIBUTING.md](CONTRIBUTING.md) — 开发环境、测试与提案流程
- [CHANGELOG.md](CHANGELOG.md) — 变更记录
- [SECURITY.md](SECURITY.md) — 漏洞报告方式

语言变更请先阅读 [提案流程](docs/proposals/README.md)；未实现的功能会被显式拒绝，
不会静默产生错误结果。
