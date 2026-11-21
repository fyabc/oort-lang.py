# 为 Oort 做贡献

感谢你的帮助！Oort 是一个面向学习的语言项目，因此清晰度和明确的设计决策比功能数量更重要。

## 开发环境搭建

```bash
uv sync --extra dev
pre-commit install

uv run --frozen pytest tests/
uv run --frozen ruff check src tests benchmarks scripts
uv run --frozen ruff format --check src tests benchmarks scripts
uv run --frozen mypy src/
```

仅在从 `grammars/Oort.g4` 重新生成解析器时才需要 Java 17+：

```bash
uv sync --extra build-grammar
python scripts/build_grammar.py   # or: make build-grammar
```

不要手动编辑 `src/oort_lang/parser/grammar/` 中的文件；它们是由工具生成的。

文档站点使用 MkDocs Material 构建：

```bash
make docs-serve   # preview at http://127.0.0.1:8000/
make docs         # strict build, same as CI
```

## 各部分的位置

| 路径 | 内容 |
|------|------|
| `docs/spec/` | 规范性语言参考（必须与实现保持一致） |
| `docs/proposals/` | PEP/RFC 风格的设计提案 |
| `docs/implementation/` | 编译器实现说明 |
| `mkdocs.yml` | 文档站点的导航与主题配置 |
| `src/oort_lang/source/` | 源文本、位置与输入抽象 |
| `src/oort_lang/diagnostics/` | 异常、错误处理器与 ANTLR 错误监听器 |
| `src/oort_lang/ast/` | AST 节点、visitor、类型化绑定与打印器 |
| `src/oort_lang/parser/` | 文法、Pratt 解析器与 AST 构建器 |
| `src/oort_lang/semantics/` | 名称解析与语义检查 |
| `src/oort_lang/runtime/` | 树遍历运行时与对象模型 |
| `src/oort_lang/driver/` | 编译器、REPL 与 CLI 入口 |
| `tests/unit/`, `tests/integration/` | 单元测试、CLI/REPL/示例测试 |

## 语言变更规则

1. **先提交提案**：任何非平凡的改动（新语法、语义、类型系统变更）都需要先提交提案。复制 `docs/proposals/0000-template.md`。
2. **不要半成品功能。** 如果某个构造已被解析但尚未实现，必须在
   `src/oort_lang/semantics/pass1.py` 中以 `UnsupportedSyntax` 拒绝，并列入
   `docs/spec/06-conformance.md`。
3. **同步更新规范与测试。** 只有当 `docs/spec/` 和 `tests/` 都反映了该功能时，功能才算完成。
4. **保持功能正交。** 避免针对特定类型或语法的特例；优先使用显式、可组合的机制。
5. **不要添加元编程捷径**（宏、`comptime`、隐藏的代码生成），除非运行时语义已经稳定。

## 测试

- 在 `tests/unit/` 下为你所改动的子系统添加或扩展测试。
- CLI/REPL/示例行为应放在 `tests/integration/`。
- 新示例必须注册到 `tests/integration/test_examples.py`
  （如果需要昂贵的初始化，可放到专门的测试模块）。
- 耗时超过几秒的测试应使用 `@pytest.mark.slow`；
  它们被排除在默认运行之外，由 CI 的 slow 任务执行。
- 核心代码应保持在 CI 覆盖率阈值（87%）以上。

## 质量门禁

`make check` 运行 lint、格式化、mypy、导入边界和测试。以下可选门禁在 `quality` CI 任务中或通过 `make quality` 运行：

| 门禁 | 工具 | 命令 |
|------|------|------|
| 安全 | bandit | `make security` |
| 依赖 CVE | pip-audit | `make audit` |
| 依赖卫生 | deptry | `make deps` |
| 死代码 | vulture | `make dead-code` |
| 属性测试 | hypothesis | `make property` |
| Markdown | markdownlint-cli2 | `make markdown` |

Mutmut/`cosmic-ray` 变异测试是偶尔进行的本地检查，而不是每次推送的门禁；
在修改解释器核心时，针对 `src/oort_lang/runtime` 运行它。

## 提交与拉取请求

- 使用约定式提交前缀（`feat:`、`fix:`、`docs:`、`test:` 等）。
- 每个提交保持聚焦；避免将重构与行为变更混在一起。
- 在 PR 描述中说明改动了什么、为什么改、适用的提案/规范章节，以及如何测试。
- CI 必须在 Linux 和 Windows 上通过。

## 报告缺陷

请附上最小的 `.ort` 复现程序、你运行的命令以及完整的诊断输出。安全问题请参阅 [SECURITY.md](SECURITY.md)。
