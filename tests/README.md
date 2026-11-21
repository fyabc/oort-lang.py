# 测试

```
tests/
├── conftest.py          # 共享 fixture：run_source、run_file、compiler_factory
├── helpers.py           # get_compiler、示例/资产路径
├── assets/              # 固定的 .ort 源文件与期望 AST
├── unit/
│   ├── frontend/        # 词法、token 后处理、解析、AST、语义分析、Binding、诊断
│   ├── backend/         # HIR lowering、字节码编码/反汇编与结构校验（VM 后续）
│   └── runtime/         # 解释器、函数/类/容器、模块加载、宿主边界、标准库、
│                        # 迭代器与扩展方法
├── property/            # hypothesis 属性测试（CI 用 --with hypothesis）
└── integration/         # CLI、REPL、全部示例程序
```

## 运行

```bash
uv run pytest tests/                  # 快速测试（默认排除 slow）
uv run pytest tests/ -m slow          # 仅 slow 测试（如 JSON showcase）
uv run pytest tests/unit              # 单元测试
uv run pytest tests/integration       # 集成测试
uv run pytest tests/ -k "collections" # 按名字筛选
```

耗时的端到端测试标记为 `pytest.mark.slow`，默认运行与 CI 快速任务会跳过；
CI 有独立的 `Slow tests` job。新增超过约 5 秒的测试时使用该标记。

## 编写约定

- 需要执行一段 Oort 源码时，使用 `run_source` fixture：

  ```python
  def test_something(run_source):
      result = run_source("print(1 + 2)\n")
      assert result.stdout == "3\n"
      assert result.value == 3
  ```

- 需要执行一个 `.ort` 文件（尤其是多文件模块）时，使用 `run_file` fixture：

  ```python
  def test_module(run_file, tmp_path):
      result = run_file(tmp_path / "main.ort")
      assert result.stdout == "42\n"
  ```

- 需要构造编译器（例如测试错误路径）时，使用 `get_compiler("NOT_EXIST -t eval")`
  或参数列表 `get_compiler(["NOT_EXIST", "-t", "eval", "-I", str(path)])`。
  语法/语义错误通过 `SystemExit` 结束；运行期/导入错误通过 `CompilerError` 结束。
- 未实现特性的诊断放在 `unit/frontend/test_unsupported.py`，用参数化列表维护。
- 新增示例时，在 `integration/test_examples.py` 的 `EXPECTED_OUTPUTS` 中登记输出；
  非确定性输出（如计时）单独处理。示例目录中的辅助模块不匹配
  `NN_NN_` 命名，因此不会被当作独立示例运行。
- 测试文件按**被测子系统**命名，而不是按实现文件命名。

## REPL 测试

REPL 按层次测试，不依赖手动输入：

- **单元**：括号/换行后处理、`is_complete` 判断、`ReplSession` 状态迁移；
- **集成**：脚本化 transcript（多行、错误恢复、变量持久化、空行、输出格式）；
- **子进程**：用管道 stdin 启动真实 CLI，检查退出码、stdout/stderr 与 EOF；
- **PTY（可选）**：Ctrl-C/Ctrl-D、行编辑、历史与粘贴，跨平台成本较高；
- **人工冒烟**：终端显示、颜色与快捷键等无法稳定自动化的部分，
  使用 `private/repl-smoke.md`（该目录不公开）。

自动化测试放在本目录；`private/` 只放人工检查清单。
词法后处理与 REPL 重构设计见
[OP 0008](../docs/proposals/0008-lexer-postprocessing-and-repl.md)。

## 覆盖范围

| 领域 | 测试文件 |
|------|----------|
| 词法 | `unit/frontend/test_lexer.py` |
| Token 后处理/完整性 | `unit/frontend/test_token_processor.py` |
| 解析与优先级 | `unit/frontend/test_parser.py` |
| AST 打印 | `unit/frontend/test_ast.py` |
| 名称解析/作用域 | `unit/frontend/test_semantic.py` |
| 方言分析器分发 | `unit/frontend/test_analyzer_dispatch.py` |
| `oort-core` 类型模型 | `unit/frontend/test_core_types.py` |
| `oort-core` 类型检查 | `unit/frontend/test_core_checker.py` |
| `oort-core` ADT 类型 | `unit/frontend/test_core_types.py` |
| 类型化 Binding / 作用域布局 | `unit/frontend/test_bindings.py` |
| 诊断配对/排序 | `unit/frontend/test_error_handler.py` |
| 未实现特性诊断 | `unit/frontend/test_unsupported.py` |
| 导入语法与 AST | `unit/frontend/test_imports.py` |
| 基础语句/增强赋值 | `unit/runtime/test_basic.py` |
| 控制流 | `unit/runtime/test_control_flow.py` |
| 声明与解包 | `unit/runtime/test_declarations.py` |
| 函数与闭包 | `unit/runtime/test_functions.py` |
| 匿名 lambda 参数 | `unit/runtime/test_anonymous_params.py` |
| 默认值/关键字/变长/块参数 | `unit/runtime/test_parameter_binding.py` |
| 解释器运行时隔离 | `unit/runtime/test_runtime_isolation.py` |
| `oort-core` 执行 | `unit/runtime/test_core_execution.py` |
| `oort-core` 模块导入 | `unit/runtime/test_core_modules.py` |
| `oort-core` ADT/match 执行 | `unit/runtime/test_core_adt_execution.py` |
| `oort-core` 函数值 | `unit/runtime/test_core_function_values.py` |
| 宿主投影/原生模式 | `unit/runtime/test_host_boundary.py` |
| 迭代器协议/流式 for | `unit/runtime/test_iterators.py` |
| 集合助手 | `unit/runtime/test_collection_builtins.py` |
| `math` / `string` 模块 | `unit/runtime/test_math_string_modules.py` |
| 原生标准库导入 | `unit/runtime/test_native_modules.py` |
| `io` / `os` / `ord` / `chr` | `unit/runtime/test_io_os_modules.py` |
| 模块路径解析 | `unit/runtime/test_module_resolution.py` |
| 模块加载/缓存/循环 | `unit/runtime/test_modules.py` |
| 类与继承 | `unit/runtime/test_classes.py` |
| 运算符重载 | `unit/runtime/test_operators.py` |
| 相等性/键协议 | `unit/runtime/test_equality.py` |
| 扩展方法/扩展运算符 | `unit/runtime/test_extensions.py` |
| 容器与切片 | `unit/runtime/test_collections.py` |
| 内建函数 | `unit/runtime/test_builtins.py` |
| CLI | `integration/test_cli.py` |
| REPL | `integration/test_repl.py` |
| 示例程序 | `integration/test_examples.py` |
| JSON showcase | `integration/test_json_example.py` |
| 属性测试 | `property/test_properties.py`（`uv run --with hypothesis pytest tests/property`） |
