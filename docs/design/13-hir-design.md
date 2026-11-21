# HIR 设计（共享后端）

> **状态**：HIR、32 位字节码编码/反汇编与寄存器 VM 第一切片已实现，当前子集
> 包含 lambda/闭包、一等函数值、动态类/方法与模块导入（`src/oort_lang/hir/`、
> `bytecode/`、`runtime/bytecode_vm.py`）。`-t eval` 仍是默认；差分测试已
> 覆盖当前 HIR 子集。字节码 ISA 参考
> [02-bytecode-vm-design.md](02-bytecode-vm-design.md)，重实现约束见
> [OP 0004](../proposals/0004-bytecode-vm.md)。

## 1. 定位

HIR 是 AST 与字节码之间的**线性寄存器中间表示**：

```text
源码 → 共享前端 → 方言语义分析 → 统一 HIR → 字节码 VM
```

- HIR 不承载方言策略；类、ADT、match 等必须先降低或显式拒绝。
- 指令显式使用虚拟寄存器；局部变量、临时值和调用参数都在寄存器中。
- 所有未实现节点在 lowering 阶段抛 `UnsupportedSyntax`，禁止默认穿透
  （OP 0004 的核心教训）。
- 先保证语义正确，再做寄存器复用、常量池和类型特化。

## 2. 第一切片范围

支持的动态子集：

- 模块顶层 `val`/`var`、赋值、函数定义与调用；
- 函数值/lambda（显式参数与匿名 `$0`/`$1`）、闭包捕获外层局部变量；
- 模块顶层动态类、实例方法、单/多继承与 `this`；`__init__` 构造与
  `__iter__` 迭代协议方法；
- 顶层 `import` / `from ... import ...`（含别名、相对路径与 `-I` 搜索路径）；
  导入模块同样以字节码执行，并拥有独立的模块全局环境；
- `Int`/`Float`/`String`/`Bool`/`null` 字面量；
- List/Tuple/Set/Dict 字面量、下标读取/赋值、切片（读取与赋值）、属性读写；
- 一元/二元运算、`and`/`or` 短路；
- `if`/`else`、`while`、`for`（通过迭代器协议）、块作用域；
- 模块顶层函数：位置参数、局部变量、递归、`return`。

显式拒绝：

- enum、match、嵌套函数定义、扩展方法、运算符方法、泛型；
- 类方法、元类、类体槽声明/任意语句、嵌套类与类表达式、`super`；
- 关键字/默认/变长/块参数；
- `break`/`continue`、`val`/参数/外层 `val` 赋值、模块级可变重定义
  （当前按不可变名处理）；
- 循环体内创建 lambda（每迭代新绑定的捕获语义尚未实现）。

这些限制是临时的；后续切片逐项放开并补差分测试。

## 3. 指令集

每条指令携带源码位置；寄存器编号为函数内的非负整数。

| 指令 | 语义 |
|---|---|
| `LOAD_K dst value` | 常量 |
| `LOAD_L dst slot` / `STORE_L slot src` | 局部变量 |
| `LOAD_G dst name` / `STORE_G name src` | 模块/内建全局名 |
| `DEF_FUN name proto` | 按源码顺序定义函数 |
| `MAKE_CLOSURE dst proto` | 创建闭包，捕获当前帧 |
| `BUILD_CLASS dst name bases... methods...` | 创建动态类并绑定方法 |
| `IMPORT module_path [as name]` / `IMPORT_FROM module_path names...` | 顶层模块导入 |
| `LOAD_OUTER dst depth slot` / `STORE_OUTER depth slot src` | 读写外层帧局部槽 |
| `MOVE dst src` | 寄存器复制 |
| `BINOP dst op lhs rhs` / `UNOP dst op src` | 运算符，仍走 Oort 语义 |
| `JUMP label` / `JUMP_FALSE R label` / `JUMP_TRUE R label` | 控制流 |
| `LABEL name` | 跳转目标 |
| `CALL dst callee args...` | 调用；参数按显式寄存器列表 |
| `RET R` | 函数/主模块返回 |
| `OPEN_ITER dst iterable` | 打开迭代器（复用现有协议） |
| `ITER_NEXT value iterator done_label` | 取值；无效时跳到 done |
| `BUILD_LIST/TUPLE/SET dst elements` | 集合字面量 |
| `BUILD_DICT dst key:value...` | 字典字面量 |
| `GET_ITEM dst container index` / `SET_ITEM container index src` | 下标读写 |
| `BUILD_SLICE dst start? stop? step?` | 切片对象 |
| `GET_ATTR dst value name` / `SET_ATTR value name src` | 属性读写 |

`and`/`or` 降低为 `JUMP_FALSE`/`JUMP_TRUE` + `MOVE`，保持短路和返回操作数
本身的语义。`if`/`while` 用标签与跳转展开。

## 4. 作用域与寄存器

- 每个函数有独立的 `HirFunction.local_count`；主模块也是一个 `HirFunction`。
- 主模块顶层名字是**全局**（`LOAD_G`/`STORE_G`）；块内声明是主模块的局部
  寄存器。函数参数与函数内声明都是局部寄存器。
- lowering 使用词法作用域栈解析名字；`Binding.is_global` 决定全局访问。
  lambda 内引用外层局部时生成 `LOAD_OUTER depth slot`，`depth` 为按 lowering
  函数栈计算出的跨帧数。写入外层可变局部（`var`）生成 `STORE_OUTER`；外层
  `val`/参数写入在 lowering 阶段拒绝。
- 闭包采用**帧捕获**而非 cell/upvalue 元数据：lambda 值持有定义时的 VM
  帧，帧再指向其外层帧；`LOAD_OUTER`/`STORE_OUTER` 沿该链访问寄存器。
- 寄存器单调分配，不复用；上限 256（与设计 02 的 A/B/C 8 位字段一致）。
  超过上限报 `UnsupportedSyntax`。后续由寄存器分配器复用临时值。
- `for` 循环变量按局部槽处理；循环体复用同一帧，因此循环内创建 lambda 会
  共享最后一次迭代的绑定。第一切片在 lowering 阶段显式拒绝这种写法。

## 5. 函数与调用

- 顶层函数按源码顺序用 `DEF_FUN` 写入全局；因此在定义前调用与解释器一样
  会失败。
- `CALL` 的被调者是任意表达式：名字、下标、属性或嵌套调用结果都先求值到
  寄存器，再按 scratch 约定调用。因此函数值、`fs[0](x)`、`f(1)(2)` 与
  原生高阶助手（如 `map(xs, do: ...)`）共用同一条路径。
- lambda 降低为独立的 `HirFunction(is_lambda=True)`；显式参数列表与匿名
  `$0`/`$1` 参数都映射为普通参数槽，定义处生成 `MAKE_CLOSURE`。匿名参数
  数量由前端记录；第一切片支持位置参数，不支持默认值/变长/块参数。
- 顶层函数由 `DEF_FUN` 创建，不捕获帧；lambda 由 `MAKE_CLOSURE` 捕获当前帧。
- 顶层导入按解释器语义**提升**到其他顶层语句之前，并按源码顺序执行；导入
  绑定写入当前模块环境。导入只允许模块顶层（前端已保证），块内/函数内导入
  显式拒绝。
- 顶层类降低为 `BUILD_CLASS` + `STORE_G`；类体只允许实例方法定义，方法
  降低为 `has_this=True` 的函数，槽 0 固定为 `this`，显式参数从槽 1 开始。
  方法定义时捕获类定义帧；基类表达式先求值到寄存器。
- 函数体隐式返回最后一个表达式的值；显式 `return` 直接生成 `RET`。
- 参数/局部变量不可变（与解释器一致）；HIR 第一切片在 lowering 阶段拒绝
  对不可变名的赋值，而不是延迟到 VM。

## 6. 结构校验

`validate_module` 检查：

- 寄存器编号在 `0..local_count-1`；
- 跳转目标存在且标签不重复；
- `DEF_FUN`/`MAKE_CLOSURE` 的 proto 索引有效；
- `BUILD_CLASS` 的方法 proto 索引有效；
- `LOAD_OUTER`/`STORE_OUTER` 的 `depth >= 1`、`slot` 在 8 位范围；
- 每个函数的 `local_count` 不超过 256。

测试在 `tests/unit/backend/test_hir.py`，并包含 `format_module` 的人工可读
dump 用于调试。

## 7. 字节码编码（第一切片）

- 32 位定长：ABC（A/B/C 各 8 位）、ABx、AsBx、Ax；`Op` 为 8 位操作码。
- 跳转使用相对 sBx，编译后统一回填标签；`ITER_NEXT` 展开为
  `ITER_NEXT value iterator valid` + `JUMP_FALSE valid done`，因此一条 HIR
  可以生成多个机器字，标签映射按**机器字下标**计算。
- 常量池去重且区分 Bool/Int/Float/String/Null；全局名与字面量共用常量池。
- 集合构造复用 scratch 区，`NEW_LIST/NEW_TUPLE/NEW_SET/NEW_DICT` 从连续寄存器
  读取元素；Dict 按 key/value 成对存储。
- 下标用 `GET_ITEM`/`SET_ITEM`；切片用 `BUILD_SLICE`（3 位 presence 标志 +
  scratch 寄存器）；属性用 `GET_ATTR`/`SET_ATTR`（名字在常量池，scratch 传
  receiver/value）。动态类/实例属性与模块对象属性共用同一条路径。
- 闭包用 `LOAD_OUTER`/`STORE_OUTER`（ABC：depth/slot 各 8 位）与
  `MAKE_CLOSURE`（ABx：proto 索引）。lambda proto 与顶层函数共用
  `BytecodeModule.functions`，由 `is_lambda` 仅在 HIR 层区分。
- 类用 `BUILD_CLASS`（ABx：常量池中的 `ClassSpec`）。基类寄存器先 MOVE 到
  scratch 区（`Proto.scratch_base`），`ClassSpec` 记录类名、基类数量和方法
  `(name, proto)` 表；方法 proto 以 `has_this` 标记，参数表包含 `this`。
- 导入用 `IMPORT`（ABx：常量池中的 `ImportSpec`）。`ImportSpec` 记录模块路径、
  别名、`from` 名单与 `is_from` 标志；无别名的 `import` 由运行时
  `ModuleLoader.binding_name` 推导绑定名。
- HIR `CALL dst callee args...` 使用函数末尾的 scratch 区约定：
  `CALL A B C` 中 `R(A)` 为被调者、`R(A+1..A+C)` 为实参、结果写回 `R(A)`；
  编译器先 MOVE 到 scratch 再回写 dst。`register_count` 包含 scratch，
  超过 256 报 `UnsupportedSyntax`。
- 每个机器字对应一条 line_table 记录；`Proto` 携带参数、寄存器数、常量池、
  指令字与行号表。
- `-t bc` 打印反汇编（文件名保持 `-t ast`/`-t astm` 的调试风格）；`eval`
  仍是默认执行后端。

## 8. 寄存器 VM（第一切片）

- `runtime/bytecode_vm.py`：Python 调用栈帧、寄存器数组、常量/字节码解码缓存、
  全局名缓存；复用现有 `Environment`、内建环境、类型对象、运算符调度和
  迭代器协议。第一切片现已覆盖集合字面量、内建容器下标/切片与属性读写。
- 每次调用创建带 `parent` 的 `VMFrame`；`OortVMClosure` 保存 proto 与定义帧。
  顶层函数由 `DEF_FUN` 创建且不捕获帧；lambda 由 `MAKE_CLOSURE` 捕获当前帧。
  `LOAD_OUTER`/`STORE_OUTER` 沿帧链读写外层寄存器，闭包内的赋值直接修改外层
  已捕获的寄存器。
- VM 闭包是一等值：可作为参数/返回值、放入集合、经下标或嵌套调用发起调用；
  原生高阶助手通过 `interpreter.call_value` 的 `OortVMInvokable` 分支回调 VM。
- `BUILD_CLASS` 调用 `OortType.create_type_object` 并写入方法闭包；属性查找把
  `OortVMInvokable` 绑定为 `OortVMMethod`（自动前置 `this`）。构造仍走
  `OortType.__call__`：`__init__` 若是 VM 方法则通过 `bind(instance)` 调用，
  因此类可作为 `map` 等原生助手的回调。
- 模块通过解释器现有的 `ModuleLoader` 加载：路径解析、缓存、循环检测、方言
  一致性检查与原生模块工厂全部复用；`execute_module` 回调把 AST 降低/编译后
  交给同一个 VM。每个模块使用独立 `Environment`；`OortVMClosure` 记录其模块与
  环境，因此跨模块调用仍能读写定义模块的全局。`IMPORT` 定义不可变绑定；
  lowering 同时记录导入绑定名，后续对它的赋值在 lowering 阶段拒绝。
- Int 算术/比较和一元运算有快速路径；其余类型回退到解释器的
  `apply_binary`/`apply_unary`，除法零仍产生带位置的 `OortRuntimeError`。
- `-t vm` 执行当前 HIR 子集；`-t eval` 保持默认，未支持的构造由 HIR 明确拒绝。

## 9. 下一步

1. 扩大 HIR/VM 子集：core 方言。
2. 对 VM 与解释器做更广的差分/错误路径测试；逐步把 CLI 默认后端切到 VM。
3. 继续优化：寄存器复用、常量内联、当前帧内联、类型特化；用基准证明。
