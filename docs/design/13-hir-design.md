# HIR 设计（共享后端）

> **状态**：HIR、32 位字节码编码/反汇编与寄存器 VM 第一切片已实现
> （`src/oort_lang/hir/`、`bytecode/`、`runtime/bytecode_vm.py`）。`-t eval`
> 仍是默认；差分测试已覆盖当前 HIR 子集。字节码 ISA 参考
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
- `Int`/`Float`/`String`/`Bool`/`null` 字面量；
- List/Tuple/Set/Dict 字面量、下标读取/赋值（不含切片）；
- 一元/二元运算、`and`/`or` 短路；
- `if`/`else`、`while`、`for`（通过迭代器协议）、块作用域；
- 模块顶层函数：位置参数、局部变量、递归、`return`。

显式拒绝：

- 类、enum、match、lambda/嵌套函数、扩展方法、运算符方法、泛型；
- 属性访问、切片、导入、关键字/默认/变长/块参数；
- `break`/`continue`、`val`/参数赋值、闭包捕获外层函数局部变量、模块级
  可变重定义（当前按不可变名处理）。

这些限制是临时的；后续切片逐项放开并补差分测试。

## 3. 指令集

每条指令携带源码位置；寄存器编号为函数内的非负整数。

| 指令 | 语义 |
|---|---|
| `LOAD_K dst value` | 常量 |
| `LOAD_L dst slot` / `STORE_L slot src` | 局部变量 |
| `LOAD_G dst name` / `STORE_G name src` | 模块/内建全局名 |
| `DEF_FUN name proto` | 按源码顺序定义函数 |
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

`and`/`or` 降低为 `JUMP_FALSE`/`JUMP_TRUE` + `MOVE`，保持短路和返回操作数
本身的语义。`if`/`while` 用标签与跳转展开。

## 4. 作用域与寄存器

- 每个函数有独立的 `HirFunction.local_count`；主模块也是一个 `HirFunction`。
- 主模块顶层名字是**全局**（`LOAD_G`/`STORE_G`）；块内声明是主模块的局部
  寄存器。函数参数与函数内声明都是局部寄存器。
- lowering 使用词法作用域栈解析名字；`Binding.is_global` 决定全局访问。
  函数内引用外层函数局部变量（闭包）当前显式拒绝。
- 寄存器单调分配，不复用；上限 256（与设计 02 的 A/B/C 8 位字段一致）。
  超过上限报 `UnsupportedSyntax`。后续由寄存器分配器复用临时值。
- `for` 循环变量按局部槽处理；当前不支持捕获闭包与 `break`/`continue`。

## 5. 函数与调用

- 顶层函数按源码顺序用 `DEF_FUN` 写入全局；因此在定义前调用与解释器一样
  会失败。
- 调用目前只接受 `Name` 被调者，先 `LOAD_G` 到基寄存器，再 `CALL`。函数值、
  lambda 与高阶调用留后续。
- 函数体隐式返回最后一个表达式的值；显式 `return` 直接生成 `RET`。
- 参数/局部变量不可变（与解释器一致）；HIR 第一切片在 lowering 阶段拒绝
  对不可变名的赋值，而不是延迟到 VM。

## 6. 结构校验

`validate_module` 检查：

- 寄存器编号在 `0..local_count-1`；
- 跳转目标存在且标签不重复；
- `DEF_FUN` 的 proto 索引有效；
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
- 下标用 `GET_ITEM`/`SET_ITEM`；当前只覆盖内建容器，用户下标运算符与切片
  仍未进入 HIR。
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
  迭代器协议。第一切片现已覆盖集合字面量与内建容器下标读写。
- 顶层函数由 `DEF_FUN` 创建 `OortVMFunction`；VM 内调用直接进入新帧，内建函数
  仍走 `call_value`。VM 函数暂不能作为一等值传给 `map` 等原生高阶助手。
- Int 算术/比较和一元运算有快速路径；其余类型回退到解释器的
  `apply_binary`/`apply_unary`，除法零仍产生带位置的 `OortRuntimeError`。
- `-t vm` 执行当前 HIR 子集；`-t eval` 保持默认，未支持的构造由 HIR 明确拒绝。

## 9. 下一步

1. 扩大 HIR/VM 子集：切片、属性、类/方法、模块与 core 方言。
2. 对 VM 与解释器做更广的差分/错误路径测试；逐步把 CLI 默认后端切到 VM。
3. 继续优化：寄存器复用、常量内联、当前帧内联、类型特化；用基准证明。
