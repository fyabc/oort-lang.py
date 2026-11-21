# 开始使用

Oort 目前处于 0.x 阶段，推荐从源码安装。要求 Python 3.11+。

## 安装

### 使用 uv（推荐）

```bash
git clone https://github.com/fyabc/oort-lang.git
cd oort-lang
pip install uv
uv sync
```

之后用 `uv run oort ...` 或激活虚拟环境后直接使用 `oort`。

### 使用 pip

```bash
git clone https://github.com/fyabc/oort-lang.git
cd oort-lang
pip install .
```

## 第一个程序

创建 `hello.ort`：

```oort
def greet(name) {
    "Hello, " + name + "!"
}

print(greet("Oort"))
```

运行：

```bash
oort hello.ort
```

其他运行方式：

```bash
oort -c "print(1 + 2)"   # 直接执行一段代码
oort hello.ort -t ast    # 打印 AST
oort hello.ort -t astm   # 打印带元数据的 AST
oort -I ./libs app.ort   # 增加模块搜索路径
```

## REPL

直接运行 `oort` 进入交互环境：

```text
In [0]: var xs = [1, 2, 3]
In [1]: xs[1]
Out[1]: 2
```

- 支持多行输入：括号未闭合时自动续行。
- `Ctrl-C` 取消当前输入；执行中按 `Ctrl-C` 会中断当前语句。
- 退出：Unix `Ctrl-D`；Windows `Ctrl-Z` 后按 Enter；也可以输入 `exit` 或 `quit`。

## 编辑器支持

仓库内置 VSCode 语法高亮插件（TextMate、文件图标，暂未上 Marketplace）：

<https://github.com/fyabc/oort-lang/tree/main/editors/vscode>

## 下一步

- [语言规范](spec/index.md) — 当前实现实际接受的行为
- [示例](examples.md) — 从基础语法到模块、迭代器与扩展方法
- [提案](proposals/README.md) — 语言演进流程与设计决策
- [路线图](roadmap.md) — 当前阶段与后续计划
