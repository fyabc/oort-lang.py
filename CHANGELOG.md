# 更新日志

本文件记录本项目所有值得注意的变更。
格式基于 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)，
本项目遵循 [语义化版本](https://semver.org/)。

## [Unreleased]

### 新增

- `oort-core` 轻量探针：`#lang oort-core` 搭配独立的静态检查器，支持 `Int`、`Bool`、
  `Unit`、带注解的函数、`val`/`var`、`if`/`return`、`print` 以及一小组运算符。
  同一份源码仍可在 `oort-object` 下动态运行，此时注解不做检查（OP 0017）。
- 通过静态检查的核心模块在现有解释器上执行；`-t astm` 显示推断出的静态类型，
  `Unit` 映射为运行时 `null`。
- 同一方言内的 `oort-core` 模块导入：`import "m"` / `from "m" import f`
  暴露带类型的模块导出，支持再导出，并在编译期检测缺失的导出与循环导入。
  跨方言导入和原生导入仍被拒绝。
- 单态 `oort-core` ADT：顶层 `enum` 声明、构造器值、带通配符/绑定/嵌套构造器
  模式的 `match` 表达式，以及顶层构造器的穷尽性检查。枚举值可以打印；枚举相等性、
  泛型 ADT 和完整的嵌套穷尽性检查暂缓。`oort-object` 显式拒绝 `enum`/`match`。
- `oort-core` 中的函数类型、lambda 与一等函数值：`(Int, Bool) -> Int`、
  `do(x: Int) -> Int { ... }`、高阶函数、函数值变量/ADT 载荷，以及从核心模块
  导出的函数值。函数类型箭头是右结合的（`Int -> Int -> Int` =
  `Int -> (Int -> Int)`），调用可以沿函数值链式进行（`add(1)(2)`）。多参数函数
  不会自动柯里化。匿名/泛型/默认参数 lambda 仍被拒绝。
- `oort-core` 中的双向期望类型传播：注解、赋值、返回、函数体和调用实参现在会把
  期望类型推入 `if` 分支、块尾和 `match` 分支，从而在确切的分支或参数处
  给出更好的诊断。
- VSCode 语法（0.1.3）高亮 `enum` 声明与名称、`match`、`=>` 和 `Unit`；
  0.1.2 添加了最初的 enum/match 作用域。
- 内部后端基础：一个共享的线性寄存器 HIR、一个 32 位字节码编译器/反汇编器，
  以及一个用于动态标量/集合/函数/循环子集的寄存器 VM，包括容器切片、属性读写、
  lambda 和被帧捕获的闭包。函数值可以存储、返回、索引和调用，并能传给 `map`
  等原生高阶辅助函数。顶层动态类和实例方法（包括继承、`__init__` 和
  `__iter__`）、模块导入（`import`/`from`、别名、相对路径和 `-I`）以及
  `oort-core` 子集（带类型的静态槽位、带 `match` 的单态 ADT，以及
  `break`/`continue`，含 `break value`）现在也能在 VM 上运行。导入的模块在
  同一 VM 上执行，全局环境相互隔离，并且每个 `examples/08_core` 程序都能在
  `-t vm` 下运行。完整的参数绑定（调用时默认值、关键字参数和仅位置/仅关键字
  参数、`*args`、`**kwargs`、`&block`）现在通过 `CALL_KW` 描述符在解释器和 VM
  之间共享同一个绑定器。嵌套的具名函数现在会降级为带自递归局部绑定的闭包，
  而会创建函数的循环仍被显式拒绝。`-t bc` 打印反汇编，`-t vm` 执行该子集；
  `-t eval` 仍是默认后端。
- HIR/VM 动态类补充类方法与运算符方法：`def class.f` 写入元类并在类/子类上绑定，
  `def operator "<sym>"` 注册到类型运算符表；下标读写改走共享的
  `get_item`/`set_item`，因此用户 `"[]"`/`"[]="` 与 `on_missing` 在 VM 下生效。
  增强赋值（名字、属性、下标目标）也降低为读-改-写；`examples/03_oop/03_03_protocols.ort`
  现可在 VM 下运行。元类、`super`、扩展方法与扩展运算符仍显式拒绝。
- `oort-object` 下标与缺失属性协议（OP 0018）：`def operator "[]"(index)` /
  `def operator "[]="(index, value)` 用于用户自定义索引（包括切片和元组索引），
  以及在字段、方法和扩展之后进行只读的 `on_missing(name)` 回退。内建容器保留
  原生索引；没有 `__setattr__` 风格的写钩子。
- `oort-core` 静态类与槽位：带固定类型 `val`/`var` 槽位的顶层类、在 `__init__`
  之前运行的每实例槽位初始化器、构造函数的确定性赋值检查、只读 `val` 槽位、
  带类型的方法/`this`，以及构造函数调用。继承、元类、类方法、运算符方法和
  动态字段仍被拒绝。
- `oort-core` 集合与循环：`List[T]`、`Set[T]`、`Dict[K, V]` 和 `Tuple[...]`
  注解，同构/空字面量检查，索引，特殊的 `len` 内建函数，同类型集合相等性，以及
  针对列表、集合、字典键、字符串和同构元组的 `while`/`for` 循环。集合是不可变的，
  切片、`in`、排序和异构元组迭代仍被拒绝。
- `oort-core` 标量表达式：`Float` 和 `String` 类型及字面量，混合 Int/Float
  算术，`/`（始终为 `Float`），数值和 String 的比较/相等性，以及二者的带注解
  参数/返回值。数值注解仍然严格（`val x: Float = 1` 会被拒绝）；`**` 仍不受
  支持，因为其结果类型取决于指数。

### 变更

- List/Tuple 排序现在使用递归的 Oort 比较（元素用 Oort 的 `==`/`<` 比较，包括
  用户运算符），而不是 Python 宿主比较；Dict 不再支持排序，Set 排序使用键协议。
  `Bool` 这类不可排序的元素现在会报错。
- List/Tuple 的 `+` 和 `*` 是值级运算符，会构建共享元素对象的新序列，而不是进行
  `HOST` 往返复制。
- 除 `__init__` 和 `__iter__` 之外的 dunder 方法在类体中被拒绝
  （`Special method '<name>' is not supported.`），而不是被存储却从不分派；
  未使用的 `__op_*__` 字段和被遮蔽的 `super` 内建函数已移除。
- `enum` 和 `match` 现在是硬关键字，`=>` 是保留的 `FATARROW` 记号（不是用户
  运算符），用于 `match` 分支；原先名为 `enum`/`match` 的标识符和拼写为 `=>`
  的用户运算符不再有效。
- 方言边界是显式的：`oort-core` 可以导入其他核心模块，而加载器在 FFI 跳板
  落地之前仍会拒绝 `oort-object` ↔ `oort-core` 导入。
- REPL 仍仅支持 `oort-object`，现在会以清晰的错误消息拒绝 `#lang` 指令，
  而不是静默地把提交内容当作动态代码处理。

### 修复

- 向 List 等内建对象赋值属性时，现在会报告
  `Cannot set attribute ... on 'List' object`，而不是内部断言。

- 在内建容器内部进行比较或成员测试时抛出的错误，现在会报告用户表达式的源码
  位置，而不是 `<builtin>`。
- 在没有显式参数列表的具名 `def` 中，`$0`/`$1` 不再被静默绑定到外层 lambda
  的匿名参数。
- 初始化导入模块时（REPL 中的 Ctrl-C）发生 `KeyboardInterrupt`，会丢弃失败的
  记录，以便可以重试导入。
- `zip` 的文档现在说明它会急切地耗尽所有输入，并在无限可迭代对象上挂起。
- `OortIterator.take_remaining` 始终返回其底层列表的副本。
- 已移除语法中 `.` 之前多余的 `NEWLINE*`；行首点号续行仍由词法记号后处理器
  处理。

## [0.3.1] - 2026-11-20

### 变更

- 相等性现在有一个递归的值协议和一个独立的键协议（OP 0016）：嵌套的
  `Bool`/`Int` 保持不同，Dict/Set 相等性和集合代数使用键相等性，Int/Float 仍
  值相等但键不同。相等性、成员测试或集合代数不再使用宿主投影。
- 带显式参数列表的 lambda 现在是 `$0`/`$1` 解析的屏障，因此它无法静默捕获
  外层的匿名参数。
- 行首 `.` 续行在解析前从解析器记号流中移除；REPL 仍要求 `\`，因为它看不到
  下一行。
- JSON 展示程序对无参数方法使用仅花括号的定义（`def parse { ... }`）。

### 修复

- 类对象写入（`C.f = ...`）不再能替换通过类/元类 MRO 继承的可调用成员。

## [0.3.0] - 2026-11-20

### 新增

- 模块系统（OP 0006）：`.ort` 模块，支持 `import "m" [as x]` 和
  `from "m" import a, b as c`，急切的顶层提升初始化，规范路径缓存，
  循环导入诊断，带自动再导出的模块命名空间，以及 `-I/--module-path`
  搜索目录。
- `examples/04_modules/` 下的多文件示例。
- 诊断信息现在让每个错误与其自身的源码输入配对，并跨文件排序，因此导入模块的
  错误会指向正确的文件和行。
- 最小标准库（OP 0012）：急切的 `map`、`filter`、`zip`、`enumerate` 和稳定的
  `sorted` 内建函数，以及可通过 `import "math"` / `from "string" import upper`
  导入的原生 `math` 和 `string` 模块。
- `examples/05_stdlib/` 下的标准库示例，以及 `benchmarks/test_stdlib.py` 中的
  宿主/标准库基准测试。
- 迭代器协议（OP 0013）：用户类实现 `__iter__`，返回一个产出 `(value, valid)`
  元组的可调用对象；`for` 是流式的，内建容器通过原生 `Iterator` 类型暴露
  同一协议。
- `examples/06_iterators/` 下的用户迭代器示例，以及
  `benchmarks/test_iterators.py` 中的内建/用户迭代器基准测试。
- 扩展方法（OP 0014）：`def C.f` 在类外部为现有类型定义方法。扩展具有词法
  作用域，由 `import`/`from` 激活，按运行时类型 MRO 分派，且从不覆盖成员、
  字段或内建运算符。扩展中的 `super` 只搜索类成员。
- 扩展运算符：`def C.operator "+"(x)` 填补目标类型未定义的运算符；类和原生
  运算符始终优先。
- `examples/03_oop/03_02_extensions.ort` 下的扩展示例和
  `benchmarks/test_extensions.py`。
- 最小 I/O 与进程支持（OP 0015）：用于 UTF-8 整文件访问的 `io.read_file` /
  `io.write_file`，`os.args` / `os.script` / `os.exit`，以及
  `string.ord` / `string.chr`。
- `examples/07_showcase/07_00_json.ort` 的 JSON 解析器/格式化器展示，包括
  `\uXXXX`/代理对处理和 CLI 文件参数。
- 使用 MkDocs Material 构建并部署到 GitHub Pages 的文档站点：
  <https://fyabc.github.io/oort-lang/>，新增了入门和示例页面。

### 变更

- 宿主边界重构：`OortObject.py_value` 变为 `host_value`，引入 `HostBridge`、
  HOST/VALUE/CONTEXT 原生调用模式和用于高阶原生函数的 `NativeContext`。
  `len` 不再投影整个容器。
- 导入只允许在模块顶层；嵌套导入会以显式诊断被拒绝。
- 每个模块拥有隔离的全局环境；全局查找针对定义该名字的模块解析，因此函数和
  方法在其他地方被调用时仍保有自己的模块全局。
- 语法不再内嵌宿主语言动作（OP 0008）：括号跟踪、换行过滤和行转义移至纯
  记号后处理器（`parser/token_processor.py`），词法分析器始终发出 `NEWLINE`。
- REPL 现在是 `ReplSession` + `ConsoleIO`：每次提交都重新解析其缓冲区，而不是
  修改 ANTLR 词法/语法分析器的内部状态。Ctrl-C 会取消当前输入或中断正在执行的
  语句而不退出；非 TTY 输入时隐藏提示符，EOF 干净退出。在 Windows 上，EOF 是
  Ctrl-Z 后跟 Enter；`exit` / `quit` 也会关闭 REPL。

### 修复

- VSCode 语法现在将 `import`、`from` 和 `as` 着色为导入关键字
  （`keyword.control.import.oort`）；此前 `as` 与运算符词共享作用域，某些主题
  下可能不着色。扩展版本 0.1.1。
- 不匹配的右括号（`)`、`]`、`}`）现在产生正常的语法诊断，而不是来自词法
  分析器栈动作的 `IndexError`。
- 管道/重定向的 REPL 输入在 EOF 时干净退出，而不会以 traceback 结束，语法
  错误也不再中止会话。

## [0.2.0] - 2026-11-19

### 新增

- `editors/vscode/` 中的 VSCode 扩展：TextMate 语法高亮、括号匹配、注释配置、
  轨道与彗星语言文件图标以及语法测试。
- 用于没有显式参数列表的 lambda 的匿名 lambda 参数 `$0` / `$1`
  （`do: $0 * 2`、`do: $0 + $1`；OP 0010）。
- 完整参数绑定：调用时默认值、关键字参数、仅位置（`/`）和仅关键字（`*`）
  参数、作为 Tuple 的 `*args`、作为 Dict 的 `**kwargs`，以及支持尾随块或
  关键字语法的 `&block`（OP 0011）。
- 方言契约：可选的首行 `#lang oort-object` 指令、`DialectConfig`（特性开关和
  每次编译的 Pratt 运算符表），以及针对未知、未实现（`oort-core`）或位置错误
  的方言声明的显式诊断。
- 运算符重载：用于一元和二元运算符（包括比较和成员测试）的
  `def operator "<sym>"` 方法。内建类型使用同一张分派表，`!=` / `!in` 由
  `==` / `in` 派生，`is` / `!is` 比较对象标识。
- 表达式与表层语法清理（OP 0009）：Python/Rust 优先级，严格的 `Bool`/`Int`
  分离，带括号的参数列表，禁用隐式中缀，`break value`，DOT 续行和 Oort
  容器显示。
- 语言规范（`docs/spec/`）和提案流程（`docs/proposals/`，OP 0001–0011）。
- Linux 和 Windows 上的 CI（Python 3.11–3.13）：lint、格式、类型检查和
  覆盖率门禁。
- 贡献、安全和 issue/PR 模板。

### 变更

- 质量基础设施现在包括 bandit、pip-audit、deptry、vulture、hypothesis 属性
  测试、markdown/actionlint 检查和 CI 中的 wheel/sdist 安装冒烟测试。
- 基准测试基础设施现在覆盖微操作、宏工作负载、启动、内存上限和历史
  Fibonacci，并带有 CI 历史工作流和性能分析说明。
- 包被重组为 `source/`、`diagnostics/`、`ast/`、`parser/`、`semantics/`、
  `runtime/` 和 `driver/` 层。`objects.py`、`ast_builder.py` 和 `pass1.py`
  按职责拆分，import-linter 契约保持层边界强制执行。
- 名称解析现在向 AST 名称节点附加带类型的 `Binding`（作用域深度加槽位索引），
  而不是写入无类型的 `metadata` 键；作用域布局与未来的槽位/上值后端共享。
- 每个解释器现在拥有独立的 `Runtime`，带有自己的内建类型表和
  `null`/`true`/`false` 单例，因此多个解释器可以在同一进程中共享而不会互相
  覆盖类型。
- mypy 现在是有效的门禁：排除生成的解析器/词法分析器代码，手写代码以
  `check_untyped_defs` 和严格 optional 检查，pre-commit 使用项目锁定的
  工具版本。
- 运算符优先级现在遵循 Python/Rust：按位 `& ^ |` 比较运算符绑得更紧，比较
  运算符不具结合性（`a < b < c` 会报错）。
- `Bool` 不再是 `Int` 的子类型：布尔运算和 `true == 1` 会被拒绝；容器成员
  测试保持布尔值与整数不同。
- 标识符不再接受尾随 `!`，因此 `a!=b`、`x!in xs` 和 `a!is b` 在无空格时也能
  正确分词。
- 所有参数列表现在都要求括号。`def f x: ...` 和 `do x: ...` 等裸形式是语法
  错误，消除了 `:` 类型与函数体的歧义。
- 隐式中缀调用（`a b c`）在显式 `infix` 设计落地之前被禁用；`def C.f`、
  `class A.B` 和显式 `super(...)` 调用会被拒绝。
- `break expr` 使 `while` / `for` 表达式返回值；以 `.` 开头的行继续方法链；
  支持 `//=`。
- Dict/set 显示使用 Oort 字面量分隔符（`{: ... :}` / `{. ... .}`）。
- `oort-object` 拒绝在类体中直接声明 `var` / `val`。实例是开放的字段包；
  字段必须在 `__init__` 中用 `this.name = ...` 创建（OP 0007）。
- 实例字段不再能遮蔽实例方法或类方法；缺失属性抛出 `OortAttributeError`。
  默认相等性和哈希使用对象标识。
- 源文件以 UTF-8 读取，可选 BOM（`utf-8-sig`）。
- 公开路线图现在是高层次的；详细规划位于私有账本和 GitHub 里程碑/issue 中。
  开发围绕共享主干上的方言垂直切片组织：先 `oort-object` v1，接着是轻量
  `oort-core` 探针，两个方言 v1 之后是共享字节码后端。类槽位限定在
  `oort-core`；`oort-object` 保持开放字段包（OP 0001 §5、OP 0007）。
- 最低 Python 版本现在是 3.11（3.10 已到生命周期终点）；CI 在 Linux 上测试
  3.11–3.13，在 Windows 上测试 3.13。
- 开发依赖已更新（ruff、mypy、pytest、pytest-benchmark、pre-commit、
  virtualenv、filelock），解决了未决的 Dependabot 警报。

### 修复

- 在循环内定义的函数中的 `break` / `continue` 不再逃逸到外层循环。
- 参数布局验证现在能处理索引 0 处的可变关键字参数和尾随块参数，并修正了
  标记顺序诊断。
- Pratt 绑定力是整数，而不是浮点 epsilon 值。

## [0.1.0] - 2026-11-18

### 新增

- 动态核心：函数、闭包、类、方法、类方法、多继承（C3 MRO）、元类、
  `this` / `super`。
- `for ... in` 循环（解构、逐次迭代绑定）、`if` / `elif` / `else`、带
  `break` / `continue` 的 `while`。
- List、tuple、dict 和 set 字面量；下标与切片；增强赋值；多声明目标和
  元组解包。
- 内建函数：`print`、`clock`、`type`、`super`、`len`、`range`、`str`、
  `repr`、`int`、`float`、`bool`。
- 带错误恢复的多行 REPL。
- 单元测试和集成测试、示例程序以及基准基线。
- 从 `grammars/Oort.g4` 生成的解析器，带有 Pratt 表达式解析器。

### 变更

- 默认执行目标是 `eval`（树遍历解释器）。
- 不支持的构造会以显式的 `UnsupportedSyntax` 诊断被拒绝，而不是静默地做出
  错误行为。
- `USER_OP` 排除 `.`、`:`、`@`；移除了死记号；支持 `elif` 和对称的 `else`
  形式。

### 移除

- 未完成的基于寄存器的字节码后端（会静默地错误编译不支持的构造）。设计与
  重新实现要求保留在 `docs/design/02-bytecode-vm-design.md` 和 OP 0004 中。
