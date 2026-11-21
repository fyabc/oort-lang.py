# HIR 设计（共享后端）

> **状态**：HIR、32 位字节码编码/反汇编与寄存器 VM 第一切片已实现，当前子集
> 包含 lambda/闭包、一等函数值、完整参数绑定、动态/静态类、模块导入与
> `oort-core` 的 ADT/match（`src/oort_lang/hir/`、`bytecode/`、
> `runtime/bytecode_vm.py`）。
> `-t eval` 仍是默认；差分测试已覆盖当前 HIR 子集，`examples/08_core` 全部
> 可在 `-t vm` 下运行。字节码 ISA 参考
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

### 1.1 后端文档关系

| 文档 | 角色 |
|---|---|
| 本文（13） | **当前实现参考**：已支持子集、HIR 指令、编码约定、VM 行为 |
| [02-bytecode-vm-design.md](02-bytecode-vm-design.md) | 长期设计目标：ISA 备选、寄存器分配、JIT 路线；未实现部分不作为规范 |
| [OP 0004](../proposals/0004-bytecode-vm.md) | 决策与实现进展记录（为什么做、做到哪一步） |
| [08-performance-benchmarking.md](08-performance-benchmarking.md) | 基准方法与 VM/解释器对比 |

正式的 HIR/字节码/VM 规范尚未编写；当前以本文、`opcodes.py` 与差分测试为
事实来源。等默认后端/优化方向稳定后再提炼为 `docs/spec` 下的规范性文档。

## 2. 第一切片范围

支持的子集：

- 模块顶层 `val`/`var`、赋值、函数定义与调用；
- 完整参数绑定：默认值、关键字实参、位置/关键字限定、`*args`、`**kwargs`、
  `&block`；默认值在调用时求值，可引用定义处闭包与更早参数；
- 函数值/lambda（显式参数与匿名 `$0`/`$1`）、嵌套具名函数（含自递归）、
  闭包捕获外层局部变量；循环内创建的函数按迭代获得独立绑定；
- 多变量 `for` 解包（Tuple/List 元素，运行期校验长度）；
- 模块顶层动态类、实例方法、类方法、运算符方法、单/多继承、元类与 `this`；
  `__init__` 构造、`__iter__` 迭代协议方法与 `super` 调用；
- 扩展方法与扩展运算符：`def C.f` / `def C.operator` 按词法作用域注册并参与
  属性/运算符回退，包含导入模块的扩展激活与扩展内 `super`；
- 增强赋值：先读左侧当前值，再计算并写回；支持名字、属性与下标目标，
  下标/属性的接收者在读写两侧按解释器顺序求值；
- 顶层 `import` / `from ... import ...`（含别名、相对路径与 `-I` 搜索路径）；
  导入模块同样以字节码执行，并拥有独立的模块全局环境；
- `oort-core` 静态类与槽：`val`/`var` 槽、槽初始化表达式、构造前初始化、
  确定赋值检查与只读 `val` 槽；槽初始器降低为独立 proto；
- `oort-core` 单态 ADT 与 `match`：构造器调用、通配/绑定/嵌套构造器模式、
  顶层穷尽性（前端检查）；每个 arm 降低为独立函数，运行时匹配后调用；
- `Int`/`Float`/`String`/`Bool`/`null` 字面量；
- List/Tuple/Set/Dict 字面量、下标读取/赋值、切片（读取与赋值）、属性读写；
- 一元/二元运算、`and`/`or` 短路；
- `if`/`else`、`while`、`for`（通过迭代器协议）、块作用域；
- 模块顶层函数：完整参数绑定、局部变量、递归、`return`。

显式拒绝：

- 泛型类/函数/方法、命名空间类与方法、匿名类与类表达式；
- 类体中方法/槽以外的语句、嵌套类、显式 `super(...)`；
- 调用侧 `*`/`**` 展开（`f(*xs)`/`f(**d)`）；匿名 lambda 的关键字实参；
- 默认表达式引用类体成员（第一切片显式拒绝）；
- `match` arm 内的 `return`（以及落到 arm 函数后会被当作“循环外”的
  `break`/`continue`）；
- `val`/参数/外层 `val` 赋值、模块级可变重定义（当前按不可变名处理）；
- 循环体块级扩展定义的作用域收窄（当前按函数调用作用域注册）。

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
| `BUILD_CLASS dst name bases... methods... slots...` | 创建类、方法与静态槽 |
| `BUILD_ENUM dst name constructors...` | 创建 ADT 类型与构造器 |
| `MATCH dst scrutinee arms...` | 模式匹配；arm 为独立函数 |
| `IMPORT module_path [as name]` / `IMPORT_FROM module_path names...` | 顶层模块导入 |
| `LOAD_OUTER dst depth slot` / `STORE_OUTER depth slot src` | 读写外层帧局部槽 |
| `MOVE dst src` | 寄存器复制 |
| `BINOP dst op lhs rhs` / `UNOP dst op src` | 运算符，仍走 Oort 语义 |
| `JUMP label` / `JUMP_FALSE R label` / `JUMP_TRUE R label` | 控制流 |
| `LABEL name` | 跳转目标 |
| `CALL dst callee args...` | 位置参数快路径调用 |
| `CALL_KW dst callee args... keywords... block?` | 关键字/块调用；编译为 `CALL_KW` |
| `RET R` | 函数/主模块返回 |
| `OPEN_ITER dst iterable` | 打开迭代器（复用现有协议） |
| `ITER_NEXT value iterator done_label` | 取值；无效时跳到 done |
| `UNPACK source base count` | 多变量 `for` 解包到连续槽 |
| `FRESH_LOCALS slots...` | 循环每轮替换局部 cell，隔离迭代闭包 |
| `SUPER dst receiver` | 基于当前方法的定义类型创建 `super` 代理 |
| `REGISTER_EXT receiver name proto` | 注册当前词法作用域的扩展方法/运算符 |
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
- 闭包采用**帧 + 局部 cell**：VM 仅在含 `MAKE_CLOSURE` 的函数中把局部槽
  表示为 cell；闭包捕获一份 cell 引用快照，外层变量共享同一 cell，循环变量与
  循环体内声明的局部变量每轮由 `FRESH_LOCALS` 换成新 cell，因此每个迭代闭包
  持有独立绑定。`LOAD_OUTER`/`STORE_OUTER` 沿帧链解引用 cell。
- loop lowering 维护 `(continue_label, break_label, result_reg)` 栈：
  `continue` 跳到下一轮，`break` 跳到循环结束；带值 `break` 先 `MOVE` 到
  循环结果寄存器，保持循环表达式的值语义。
- 寄存器单调分配，不复用；上限 256（与设计 02 的 A/B/C 8 位字段一致）。
  超过上限报 `UnsupportedSyntax`。后续由寄存器分配器复用临时值。
- `for` 循环变量按局部槽处理；多变量 `for` 用 `UNPACK` 把 Tuple/List 元素
  写入连续槽。循环体仍复用同一帧，但循环作用域内声明的槽在每轮开始时通过
  `FRESH_LOCALS` 换成新 cell，使迭代闭包捕获本轮值。

## 5. 函数与调用

- 顶层函数按源码顺序用 `DEF_FUN` 写入全局；因此在定义前调用与解释器一样
  会失败。
- `CALL` 的被调者是任意表达式：名字、下标、属性或嵌套调用结果都先求值到
  寄存器，再按 scratch 约定调用。因此函数值、`fs[0](x)`、`f(1)(2)` 与
  原生高阶助手（如 `map(xs, do: ...)`）共用同一条路径。
- 函数签名在 HIR 中显式保存参数种类、固定槽与默认值 proto。`this` 固定槽 0，
  显式参数从槽 1 开始；参数槽在 lowering 时确定，VM 绑定后直接按槽填帧。
  默认表达式降低为 `<default ...>` proto，参数为更早的可见参数；运行时仅在
  参数缺失时调用，默认 proto 闭包按拥有它的函数闭包缓存。
- `CALL` 无关键字/块时保留位置快路径；有关键字或块时生成 `CALL_KW`，
  `CallSpec` 记录位置数量、关键字名与块标志。绑定器与解释器共享同一套错误
  规则；类构造器与方法也走同一绑定器，`this` 预绑定。
- lambda 降低为独立的 `HirFunction(is_lambda=True)`；显式参数列表与匿名
  `$0`/`$1` 参数都映射为普通参数槽，定义处生成 `MAKE_CLOSURE`。lambda 与普通
  函数共用同一 `SignatureSpec`；匿名 `$0`/`$1` 参数为位置限定，不接受关键字。
- 顶层函数由 `DEF_FUN` 创建，不捕获帧；lambda 与嵌套具名函数由
  `MAKE_CLOSURE` 捕获当前帧。嵌套函数在定义处先分配局部槽再降低函数体，
  因此自递归可通过外层槽解析；函数对象由 `MakeClosure` + `StoreLocal` 绑定。
- 顶层导入按解释器语义**提升**到其他顶层语句之前，并按源码顺序执行；导入
  绑定写入当前模块环境。导入只允许模块顶层（前端已保证），块内/函数内导入
  显式拒绝。
- 顶层类降低为 `BUILD_CLASS` + `STORE_G`；类体允许实例方法与槽声明，方法
  降低为 `has_this=True` 的函数，槽 0 固定为 `this`，显式参数从槽 1 开始。
  方法定义时捕获类定义帧；基类表达式先求值到寄存器。带初始化表达式的槽
  额外降低为无参 `<slot name>` proto，实例化时先于 `__init__` 调用。
- 枚举在定义处生成 `BUILD_ENUM`：构造器以不可变全局绑定，零参构造器为
  单例 ADT 值，有参构造器为原生构造函数。
- `match` 先求值 scrutinee 一次；每个 arm 的绑定名成为 arm 函数的参数，
  arm 降低为可捕获当前帧的独立函数。运行时按模式依次匹配，命中后以绑定值
  调用对应 arm 函数并把返回值写入 `MATCH` 的目标寄存器。
- 函数体隐式返回最后一个表达式的值；显式 `return` 直接生成 `RET`。
- 参数/局部变量不可变（与解释器一致）；HIR 第一切片在 lowering 阶段拒绝
  对不可变名的赋值，而不是延迟到 VM。

## 6. 结构校验

`validate_module` 检查：

- 寄存器编号在 `0..local_count-1`；
- 跳转目标存在且标签不重复；
- `DEF_FUN`/`MAKE_CLOSURE` 的 proto 索引有效；
- `BUILD_CLASS` 的方法与槽初始器 proto 索引有效；
- `MATCH` 的 arm proto 索引有效；
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
- 多变量 `for` 用 `UNPACK`（ABC：source、目标起始槽、变量数）；VM 校验元素为
  Tuple/List 且数量匹配，否则报与解释器相同的错误。`FRESH`（ABx：槽元组）
  在每轮替换 cell。
- 类用 `BUILD_CLASS`（ABx：常量池中的 `ClassSpec`）。基类寄存器与可选元类
  先 MOVE 到 scratch 区（`Proto.scratch_base`），`ClassSpec` 记录类名、基类
  数量、是否带元类、实例方法 `(name, proto)` 表、类方法 `(name, proto)` 表、
  运算符 `(symbol, operand_count, proto)` 表与槽
  `(name, mutable, initializer proto?)` 表；方法 proto 以 `has_this` 标记，
  参数表包含 `this`。类方法写入元类字段，实例方法写入类字段；运算符方法写入
  `OortType.operators`。`SUPER` 基于当前方法的 `defining_type` 创建代理。
- 扩展用 `REGISTER_EXT`（ABx：常量池中的 `ExtensionSpec` + receiver 寄存器）
  在当前帧的扩展作用域注册方法或运算符；VM 的属性/运算符回退使用该词法
  作用域，并在 `IMPORT` 时激活被导入模块的顶层扩展。
- `Proto.signature` 保存 `SignatureSpec`：参数种类、槽、默认值 proto 索引与
  `has_this`；`Proto.local_count`/`uses_cells` 决定该帧是否使用局部 cell。
  `CALL` 保持 `A=base, C=位置参数数`；`CALL_KW A Bx=K(CallSpec)`
  的 scratch 布局为 callee、位置值、关键字值、块值。反汇编显示
  `CALL_KW R6 pos=1 kws=(c)`。
- 枚举用 `BUILD_ENUM`（ABx：`EnumSpec`）；`match` 用 `MATCH`（ABx：`MatchSpec`，
  arm 模式为 `PatternSpec`）。编译时 scrutinee MOVE 到 scratch 区，scratch
  需求随 `MATCH` 增至至少 1。
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
- 每次调用创建带 `parent` 与扩展作用域 `ext_env` 的 `VMFrame`；`OortVMClosure`
  保存 proto、定义帧与定义时的扩展作用域。顶层函数由 `DEF_FUN` 创建且不捕获
  帧；lambda/嵌套函数由 `MAKE_CLOSURE` 捕获当前帧的局部 cell 快照。
  `LOAD_OUTER`/`STORE_OUTER` 沿帧链读写 cell。
- VM 闭包是一等值：可作为参数/返回值、放入集合、经下标或嵌套调用发起调用；
  原生高阶助手通过 `interpreter.call_value` 的 `OortVMInvokable` 分支回调 VM。
- `BUILD_CLASS` 调用 `OortType.create_type_object`（含元类）并写入方法/类方法/
  运算符闭包；闭包记录 `defining_type` 供 `SUPER` 使用。属性查找把
  `OortVMInvokable` 绑定为 `OortVMMethod`（自动前置 `this`）。构造仍走
  `OortType.__call__`：`__init__` 若是 VM 方法则通过 `bind(instance)` 调用，
  因此类可作为 `map` 等原生助手的回调。
- 扩展方法/运算符注册到当前 `VMFrame.ext_env`；属性、下标与二元/一元运算的
  回退查询都显式传入该作用域，导入模块的顶层扩展在 `IMPORT` 时激活。
- 参数绑定由 `runtime/call_protocol.py` 的共享核心完成；VM 与 AST 解释器
  共用错误规则。VM 默认值经默认 proto 闭包求值（按闭包缓存），`*args`
  为 Tuple、`**kwargs` 为 Dict、缺失块为 `null`；原生函数仍只接受位置实参。
- 模块通过解释器现有的 `ModuleLoader` 加载：路径解析、缓存、循环检测、方言
  一致性检查与原生模块工厂全部复用；`execute_module` 回调把 AST 降低/编译后
  交给同一个 VM。每个模块使用独立 `Environment`；`OortVMClosure` 记录其模块与
  环境，因此跨模块调用仍能读写定义模块的全局。`IMPORT` 定义不可变绑定；
  lowering 同时记录导入绑定名，后续对它的赋值在 lowering 阶段拒绝。
- `BUILD_ENUM` 创建 `OortType`/`OortADT` 与构造器；`MATCH` 使用 VM 的模式匹配
  辅助函数绑定 payload，再以绑定值调用 arm 闭包。静态槽由 `SlotDefinition`
  记录（`initializer_callable` 为 VM 闭包）；`OortType.__call__` 在
  `__init__` 前调用槽初始化闭包。VM 方法执行期间设置 `_current_method`，
  使 `__init__` 能初始化只读 `val` 槽。
- Int 算术/比较和一元运算有快速路径；其余类型回退到解释器的
  `apply_binary`/`apply_unary`，除法零仍产生带位置的 `OortRuntimeError`。
- `-t vm` 执行当前 HIR 子集；`-t eval` 保持默认，未支持的构造由 HIR 明确拒绝。

## 9. 下一步

1. 完成剩余显式拒绝项：调用侧 `*`/`**`、`match` arm 内控制流、类体成员默认值等。
2. 扩大差分/错误路径测试，覆盖更多动态示例与边界组合。
3. 评估把 CLI 默认后端切到 VM（先做性能与兼容性基线）。
4. 继续优化：寄存器复用、常量内联、当前帧内联、类型特化；用基准证明。
5. HIR/VM 稳定后再补正式规范（参考 Lua/CPython/JVM）。
