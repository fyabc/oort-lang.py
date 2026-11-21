# OP 0019: 参数绑定进入 HIR / VM

- **状态**：Implemented（2026-11-21）
- **作者**：Oort 设计讨论
- **相关**：[OP 0011](0011-parameter-binding.md)、
  [OP 0004](0004-bytecode-vm.md)、
  [HIR 设计 13](../design/13-hir-design.md)、
  [规范：函数](../spec/04-functions.md)

## 摘要

把 OP 0011 已实现的完整参数绑定（默认值、关键字实参、位置/关键字限定、
`*args`、`**kwargs`、`&block`）带入 HIR、字节码与 VM。核心做法：

1. 抽出与 AST 无关的**共享绑定算法**，AST 与 VM 共用同一套错误语义；
2. 每个默认值编译为独立的 `<default ...>` proto，调用时按声明顺序求值；
3. `Proto` 携带完整签名（参数种类、固定槽、默认值 proto、是否有 `this`）；
4. 保留位置参数快路径 `CALL`，新增携带关键字/块描述符的 `CALL_KW`；
5. VM 绑定后按固定槽填充寄存器，不再要求实参恰好连续或数量精确。

目标是让 Oort 的参数语义只有一个实现、两个适配层，而不是在解释器与 VM
各写一套绑定规则。

## 动机

当前 `-t vm` 在 `examples/` 中 20/29 通过，失败项里有 3 个直接由参数绑定缺口
导致：

- `01_functions/01_01_call_with_block.ort`：尾随块参数；
- `01_functions/01_03_parameters.ort`：默认值 + 关键字实参；
- `05_stdlib/05_00_collections.ort`：`map(xs) do(x): ...` 的尾随块。

原因不是语义未定义，而是 OP 0011 只在树遍历解释器实现：

- HIR lowering 拒绝默认值、关键字限定、`*args`、`**kwargs`、`&block`；
- HIR 调用只接受位置实参；
- `Proto.params` 只是名字元组，`_execute` 精确检查位置参数数量；
- 字节码 `CALL` 只传连续位置值，没有关键字名或块通道。

如果继续在 VM 侧复制一套简化绑定，会逐渐产生错误消息、默认值时机和块参数
行为的漂移。因此本提案先解决调用协议，再继续扩大后端子集。

## 现状

- **语义已定义**：OP 0011 已定稿 D1–D14，`runtime/signature.py` 的 `Signature`
  与 `build_call_env` 已覆盖全部参数种类、默认值调用时求值、关键字规则、
  `Tuple`/`Dict`/`null` 容器与错误消息。
- **AST 形状完整**：`ParameterKind` 已包含 `POS_ONLY`、`KW_ONLY`、`VAR_POS`、
  `VAR_KW`、`BLOCK`；调用实参已有 `KEYWORD`/`BLOCK` 种类。
- **HIR 限制**：`_lower_parameters` 只允许 `DEFAULT`/`POS_ONLY` 且无默认值；
  `_lower_call` 拒绝关键字与块实参。
- **字节码限制**：`CALL A B C` 的 `R(A)` 为被调者，`R(A+1..A+C)` 为连续位置
  实参；没有关键字名/值区，也没有块描述符。
- **VM 限制**：`_execute` 以 `len(args) != len(proto.params)` 做精确 arity 检查，
  然后按位置写入寄存器 0..n。
- **原生内建**：按 OP 0011 D8 只接受位置实参；VM 回退到
  `interpreter.call_value`。

本提案不改变源语言语义，只把已实现的语义下沉到共享后端。

## 跨语言调研（2026-11-21）

| 语言 / 运行时 | 调用数据布局 | 默认值时机 | 关键字 | 变长 / 块 |
|---|---|---|---|---|
| CPython | vectorcall：位置值与关键字值在同一数组，`kwnames` 单独给出关键字名 | **定义时**求值并存于函数对象 | 运行时按 `kwnames` 绑定 | `*args` Tuple、`**kwargs` Dict |
| JavaScript | 位置实参列表 | **调用时**、左到右，更早参数可见 | 无关键字 | rest 参数收集为数组 |
| Kotlin / JVM | JVM 固定 descriptor；调用点生成 `$default` 合成方法与位掩码 | **调用时**，由合成方法/调用点处理 | 编译期解析命名实参 | JVM varargs 为数组 |
| Swift | 调用标签编译期解析；默认参数由 default argument generator 产生 | **调用时**，区分 caller-side / callee-side generator | 编译期解析标签 | 无通用关键字/块；闭包为普通参数 |
| Ruby | 位置实参、关键字实参、块是三个独立通道 | **调用时** | 关键字独立于位置 Hash | `&block` 独立、可缺省 |
| Lua 5.4 | 寄存器/栈传参；固定参数 + `...` | 语言无默认值 | 无关键字 | `...` 提供多值 vararg |

结论：

- **动态被调者必须运行时绑定。** Kotlin/Swift 的调用点默认值注入依赖静态可知的
  签名；Oort 的函数值、方法、构造器都可能是运行时值，因此不能只在 HIR/调用点
  展开默认值。
- **Oort 保持 OP 0011 D1 的调用时默认值**。这与 JavaScript/Ruby/Kotlin/Swift
  接近；Python 的定义时求值不作为目标。
- **关键字使用“名字表 + 值区”而非打包成 Dict**。CPython vectorcall 与
  Ruby 3 的关键字分离都表明：独立关键字通道能在不分配 Dict 的前提下完成绑定，
  也更符合 OP 0011 的错误规则。
- **块保持独立通道**。Ruby 的 `&block` 证明块不应与关键字或普通位置参数混在
  一个结构里；仅在“被调者没有 `&block` 参数”时，按 OP 0011 D12 退化为最后
  一个位置实参。
- **默认值编译为生成器函数**。Swift 的 default argument generator 与 Kotlin 的
  `$default` 合成方法都说明默认表达式应成为可调用单元；Oort 的生成器由**被调
  函数自己的绑定器**在缺失参数处调用，以便看到更早参数和定义处闭包。

参考：[CPython Call Protocol](https://docs.python.org/3/c-api/call.html)、
[PEP 570](https://peps.python.org/pep-0570/)、
[MDN Default parameters](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Functions/Default_parameters)、
[Kotlin ArgumentGenerator](https://github.com/JetBrains/kotlin/blob/master/compiler/backend/src/org/jetbrains/kotlin/codegen/ArgumentGenerator.java)、
[Swift SILGen](https://github.com/swiftlang/swift/blob/main/lib/SILGen/SILGen.cpp)、
[Ruby calling methods](https://github.com/ruby/ruby/blob/master/doc/syntax/calling_methods.rdoc)、
[Lua 5.4 Manual](https://www.lua.org/manual/5.4/manual.html)。

### 关于 arity

单整数 arity 在支持默认值/关键字/变长参数后无法准确描述签名：

- Ruby `Method#arity` 在存在可选参数或 rest 参数时返回负数约定；
- JavaScript `Function.length` 只统计第一个默认值/rest 之前的位置参数；
- Java 反射 `getParameterCount()` 只适用于固定 descriptor；
- Python 使用 `inspect.signature` / 代码对象标志，而不是一个整数。

Oort 目前没有反射/自省 API，代码中的 `OortCallableMixin.arity`、`OortFunction.arity`、
`OortMethod.arity`、`OortVMMethod.arity`、`OortVMClosure.arity` 与 `OortType.arity`
没有实际读取者（只互相委托）。绑定器接管参数检查后，保留一个语义不完整的整数
只会误导。因此本提案决定**移除运行时 arity 表面**，由 `SignatureSpec` 作为唯一
签名来源；如果未来工具链需要自省，再提供显式的 min/max/positional 计数。

参考：[Ruby Method#arity](https://docs.ruby-lang.org/en/master/Method.html#method-i-arity)、
[MDN Function.length](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Function/length)、
[Java Method.getParameterCount](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/reflect/Method.html#getParameterCount)、
[Python inspect.signature](https://docs.python.org/3/library/inspect.html#inspect.signature)。

## 实现（2026-11-21）

- 新增 `runtime/call_protocol.py`，AST 与 VM 共用绑定核心；原有参数测试保持通过。
- HIR/`Proto` 增加 `SignatureSpec`；默认值降低为 `<default ...>` proto，按函数
  闭包缓存默认 proto 闭包。
- 字节码新增 `CALL_KW`/`CallSpec`；位置调用保留 `CALL` 快路径。
- VM 绑定器支持关键字、默认值、`*args`/`**kwargs`/`&block`；方法/构造器共用
  绑定器并预绑定 `this`。
- 移除运行时 `arity` 表面与 `FunctionDef.param_count`；`SignatureSpec` 为唯一
  签名来源。
- 默认表达式引用类体成员仍显式拒绝；调用侧 `*`/`**` 展开仍另案。
- 验收示例：`01_01_call_with_block.ort`、`01_03_parameters.ort`、
  `05_00_collections.ort` 已在 VM 下与解释器输出一致。

## 设计决策

| 编号 | 决策 | 选择 | 理由 |
|---|---|---|---|
| D1 | 绑定算法归属 | **共享绑定核心 + AST/VM 适配层** | 避免两套错误消息与边界规则 |
| D2 | 默认值表示 | **独立 `<default ...>` proto** | 后端不携带 AST；可复用 HIR/字节码 |
| D3 | 默认值求值时机 | **调用时，仅缺失参数，声明顺序** | 延续 OP 0011 D1/D14 |
| D4 | 默认值可见范围 | **定义处闭包 + 更早已绑定参数**；不含 `this`/更晚参数 | 延续 OP 0011 D7 |
| D5 | 签名存储 | `Proto` 内 `SignatureSpec`，参数固定槽 | 绑定结果可直接填帧 |
| D6 | 调用快路径 | **无关键字/块时保留 `CALL`** | 保持常见调用性能 |
| D7 | 扩展调用 | 新增 `CALL_KW` + 调用点 `CallSpec` | 关键字/块只在需要时付出成本 |
| D8 | 关键字布局 | **名字表 + 独立值寄存器** | 不分配临时 Dict；与 vectorcall 同构 |
| D9 | 块布局 | 独立块寄存器；无 `&block` 时按 D12 退化为最后位置实参 | 对齐 OP 0011 与 Ruby |
| D10 | 原生内建 | **只接受位置实参**；关键字/块按现有规则报错 | 延续 OP 0011 D8 |
| D11 | 方法/构造器 | 共用绑定器；`this` 预绑定，不进入默认值作用域 | 类方法/`__init__` 行为一致 |
| D12 | 匿名 lambda | 所有 `$n` 为位置限定参数，不接受关键字 | 延续 OP 0011 D10 |
| D13 | 调用侧 `*`/`**` 展开 | **本提案不包含** | 当前文法/OP 0011 未支持，另案处理 |
| D14 | 默认 proto 闭包 | **按函数闭包惰性缓存** | 默认 proto 只依赖定义处帧/环境，可跨调用复用 |
| D15 | 运行时 arity | **移除**（`OortCallableMixin`/函数/方法/VM/`OortType`） | 无读取者；单整数无法表达完整签名；绑定器是唯一权威 |
| D16 | 类体成员默认值 | **第一切片不允许** | HIR 方法的定义帧不包含类体成员；显式拒绝避免 eval/vm 静默分歧 |
| D17 | 嵌套函数默认值 | 复用“定义处作用域”规则 | 不引入第二套默认值捕获规则 |

## 共享调用协议

### 1. 纯数据模型

新增 `src/oort_lang/runtime/call_protocol.py`，只包含纯数据与绑定算法，不依赖
AST；HIR/字节码只导入其中的数据类型：

```text
ParamKind: POS_ONLY | POS_OR_KW | VAR_POS | KW_ONLY | VAR_KW | BLOCK
ParamSpec(name, kind, slot, default_proto?)
SignatureSpec(params, has_this)
ArgKind: POSITIONAL | KEYWORD | BLOCK
EvaluatedArg(kind, value, keyword_name?)
BindPlan(provided, var_pos, var_kw, block, missing_defaults)
```

`SignatureSpec` 的 `params` 按声明顺序排列；每个 `ParamSpec` 直接携带寄存器槽号。
AST 的 `ParameterKind`/`ArgumentKind` 在适配层映射到该模型，避免 HIR/字节码
反向依赖 AST。

### 2. 绑定核心

`bind_arguments(signature, evaluated_args, display_name)` 复用 OP 0011 的规则：

- 先按源码顺序接收已求值实参，按位置/关键字/块分类；
- 位置实参填位置槽，溢出进入 `*args` 或报错；
- 关键字实参按名字填位置或关键字限定槽，未知关键字进入 `**kwargs` 或报错；
- 重复值、位置限定名、关键字限定、缺参等错误使用与解释器相同的消息；
- 返回 `BindPlan`：显式值、额外位置值、额外关键字、块值、缺失默认值列表。

默认值求值不在纯绑定核心中完成，而由调用方按 `BindPlan.missing_defaults`
按声明顺序解析。这样 AST 可以继续用 `default_value.accept(interpreter)`，
VM 可以调用默认 proto，两者共享其余规则。

类体成员默认值（如默认表达式引用同类的方法/槽）在本切片**不允许**：
`oort-core`/HIR 在 lowering 阶段显式拒绝，避免 VM 在定义帧中找不到类体名字时
静默改变行为。默认值只允许模块全局、定义处闭包变量和更早参数。

## HIR 设计

### 1. 签名

`HirFunction` 的参数从 `tuple[str, ...]` 扩展为：

```text
HirSignature(
  params: tuple[HirParam, ...],
  has_this: bool,
)
HirParam(name, kind, slot, default_index?)
```

- 方法：`this` 固定槽 0，`has_this=True`；显式参数从槽 1 开始。
- 普通函数/lambda：参数从槽 0 开始。
- 匿名 lambda：`$0..$n` 生成为 `POS_ONLY` 参数。
- `VAR_POS`/`VAR_KW`/`BLOCK` 参数占一个普通局部槽，分别存 Tuple/Dict/值或 null。
- 槽号在 lowering 时固定，绑定器只需按 `ParamSpec.slot` 写帧。

### 2. 默认值 proto

对每个有默认值的参数：

1. 预留一个函数索引；
2. 在**定义处作用域**中降低默认表达式，而不是在调用函数自己的帧中；
3. 默认 proto 的参数是“更早的可见参数”的名字，按声明顺序，不含 `this`；
4. 表达式结果用 `RET` 返回；
5. 在 `HirParam.default_index` 记录该 proto。

示例：

```oort
def f(a, b = a + 1) { ... }
```

```text
<default f.b>(a) local_count=2
  LOAD_L R0 slot0
  LOAD_K R1 1
  BINOP R2 + R0 R1
  RET R2
```

运行时只在该参数缺失时调用该 proto，并传入已绑定的更早参数值。默认表达式中的
其他名字按定义处闭包解析：顶层函数解析为模块全局；lambda 的默认表达式可捕获
lambda 定义处的外层帧。默认 proto 的父帧与拥有它的函数闭包保持一致。

`this`、更晚参数和函数体内的局部名字不会出现在默认 proto 的参数或作用域中，
与 OP 0011 D7 一致。

### 3. 调用

`Call` 从位置寄存器列表扩展为：

```text
Call(dst, callee, positional: tuple[int, ...],
     keywords: tuple[(name, reg), ...], block: int | None)
```

- lowering 仍按源码顺序求值每个实参（副作用顺序不变），再分组存名。
- 无关键字且无块时，编译器继续生成快速 `CALL`。
- 有关键字或块时生成 `CALL_KW`。
- 调用侧 `*`/`**` 展开不在本提案范围。

## 字节码设计

### 1. `Proto` 签名

`Proto.params: tuple[str, ...]` 替换/扩展为 `signature: SignatureSpec`，`has_this`
保留。`Proto` 仍是定长描述对象；反汇编显示：

```text
Proto f regs=8 params=(a, b=proto[3], /, c=proto[4], *args, d, **kwargs, &block)
```

参数种类、默认 proto 索引与槽号均在 `Proto` 中，运行时不回查 AST。

### 2. 调用指令

保留：

```text
CALL A B C      ; callee R(A), positional R(A+1..A+C), fast path
```

新增：

```text
CALL_KW A Bx    ; A = scratch base, Bx = 常量池 CallSpec
```

`CallSpec`：

```text
pos_count: int
keywords: tuple[str, ...]   # 源码顺序
has_block: bool
```

scratch 布局：

```text
R(A)                  callee
R(A+1 .. A+P)         positional values
R(A+P+1 .. A+P+K)     keyword values, 名字在 CallSpec.keywords
R(A+P+K+1)            block value（has_block 时）
```

编译器先按源码顺序求值到普通寄存器，再 MOVE 到 scratch；求值副作用顺序不受
布局影响。没有关键字/块时仍使用 `CALL`，避免为常见路径增加常量索引与描述符。

### 3. 错误位置

调用点描述符只保存名字与计数；错误位置使用 `CALL_KW` 的源码位置。默认表达式
自身的错误使用默认 proto 的位置。

## VM 设计

### 1. 调用流程

```text
call_closure(closure, evaluated_args, this?):
    plan = bind_arguments(closure.proto.signature, evaluated_args, name)
    values = [null] * proto.register_count
    if this: values[0] = this
    for param in signature.params in declaration order:
        if param in plan.provided: value = provided
        elif param.kind == VAR_POS: value = Tuple(extra_pos)
        elif param.kind == VAR_KW: value = Dict(extra_kw)
        elif param.kind == BLOCK: value = plan.block or null
        elif param.default_index is not None:
            default_closure = OortVMClosure(
                vm, closure.module, proto.defaults[param.default_index],
                closure.frame, closure.env,
            )
            value = invoke_raw(default_closure, earlier_values)
        else: binder 已报缺参
        values[param.slot] = value
    return _execute(module, proto, values, closure.frame, closure.env)
```

- `_execute` 不再检查位置参数个数；它接收已按槽填好的值。
- 默认 proto 用 `invoke_raw` 直接执行，不再走签名绑定（其参数全是位置参数）。
- 每个 `OortVMClosure` 惰性缓存 `dict[default_index, OortVMClosure]`；默认 proto
  只依赖闭包的模块、定义帧与环境，跨调用复用。默认值仍每次调用重新求值，
  缓存的是 proto 闭包而不是默认值。
- `OortVMClosure.invoke` 从 native helper（如 `map`）收到纯位置实参时，也走同一
  binder；因此默认值/`*args` 在回调中同样生效。

### 2. 方法与构造器

- `OortVMMethod` 把 `this` 作为预绑定值，不把它传给默认值作用域。
- VM 类构造：创建实例、执行槽初始化，然后按 `__init__` 的签名绑定；支持
  关键字/默认值/块（若 `__init__` 声明）。
- 无 `__init__` 时，带实参构造仍按现有规则报错。
- 原生内建保持位置 only：有关键字/块时使用现有错误，不静默丢弃。
- 绑定器成为参数数量的唯一权威；移除 `OortCallableMixin.arity` 及各覆写、
  `OortType.arity`，并清理只服务于它的 `FunctionDef.param_count`。

### 3. 块参数的特殊规则

`EvaluatedArg(BLOCK, value)` 保留独立种类：

- 被调签名有 `&block`：绑定到块槽；缺失为 `null`；
- 没有 `&block`：按 OP 0011 D12 作为最后一个位置实参，并跳过已被关键字填充的
  位置槽；
- 原生函数没有 `&block`：块值作为最后位置值传入，保持
  `map(xs) do(x): ...` 的现有行为。

### 4. 快路径

若签名只含 `POS_ONLY`/`POS_OR_KW` 且无默认值/变长/块，并且调用只有位置实参、
数量精确，则跳过通用映射与容器分配，直接填槽。基准必须证明 `fib`/循环调用
没有明显回退。

## 语义与错误

- 默认值：仅缺失时求值、声明顺序、更早参数可见、每次调用重新求值。
- 位置限定：不能按名传入；有 `**kwargs` 时同名关键字进入 `**kwargs`。
- 关键字限定：只能按名；可带默认值。
- `*args`：Tuple，包括空 Tuple；`**kwargs`：String 键 Dict，包括空 Dict。
- `&block`：尾随块或 `block = ...`；两者同时出现报错；缺失为 `null`。
- 重复值、缺失参数、未知关键字、位置参数跟在关键字之后、原生函数收到关键字
  的错误消息与 AST 解释器一致。
- 默认表达式中的错误位置指向默认表达式；绑定错误指向调用点。

## 正交性检查

- **类型系统**：`oort-core` 继续在静态检查阶段验证签名；HIR/VM 不读取类型。
- **类/对象**：实例方法、构造器、绑定方法共用绑定器；`this` 预绑定。
- **函数/闭包**：默认 proto 使用定义处帧/环境；闭包变量解析规则不变。
- **模块**：默认 proto 的模块环境与拥有函数一致，跨模块调用不改变。
- **原生边界**：原生函数继续只接受位置实参。
- **宏/编译期**：不涉及。

## 替代方案

1. **调用点静态绑定（Kotlin/Swift 风格）**：依赖静态可知被调者；Oort 的函数值/
   方法/构造器是运行时值，无法覆盖，放弃。
2. **Python 式定义时默认值**：与 OP 0011 D1 冲突，且可变默认值共享状态，放弃。
3. **把默认表达式 AST 存进 Proto 交给解释器**：会让字节码依赖 AST 和解释器，
   破坏后端独立性与显式失败约束，放弃。
4. **所有调用都打包一个 Dict/Tuple**：实现简单，但每次调用分配容器并破坏位置
   参数性能，放弃；仅 `CALL_KW` 携带额外信息。
5. **VM 复制一份简化绑定器**：最快落地，但会长期漂移，放弃；改为共享核心。

## 向后兼容

- 源语言语义不变；只扩大 `-t bc`/`-t vm` 子集。
- 现有 OP 0011 测试应全部保持通过；新增测试是差分与结构测试。
- 不需要迁移；`-t eval` 继续是默认后端。
- 字节码尚未持久化，无二进制兼容负担。

## 实现计划

1. **共享绑定核心**：新增 `runtime/call_protocol.py`，从 `runtime/signature.py`
   提取纯数据/算法；AST 结果与错误消息保持不变。
2. **HIR**：签名模型、默认 proto lowering、方法 `this` 槽、扩展 `Call`；移除
   参数/调用拒绝。
3. **字节码**：`Proto.signature`、`CallSpec`、`CALL_KW`、反汇编；保留 `CALL`。
4. **VM**：绑定器接入、默认 proto 闭包缓存、`*args`/`**kwargs`/块、方法/构造器、
   原生错误路径与快路径；移除运行时 arity 表面。
5. **测试**：HIR/字节码结构、eval/vm 差分、错误矩阵、三个失败示例、
   `map(xs) do...`、构造器关键字、默认值副作用顺序。
6. **文档**：更新 HIR 设计 13、OP 0004 进展、CHANGELOG；稳定后再补正式规范。

## 验收标准

- `01_01_call_with_block.ort`、`01_03_parameters.ort`、`05_00_collections.ort`
  在 `-t vm` 下与 `-t eval` 输出一致。
- 默认值、关键字、位置/关键字限定、`*args`、`**kwargs`、`&block` 的正向与
  错误路径差分测试通过。
- 同一错误在 eval/vm 下消息与位置一致。
- `benchmarks/test_vm.py` 的位置参数基准无明显回退（以现有噪声/门限为准）。
- 字节码/HIR 不依赖 AST 默认表达式对象。
- 运行时不再有 `arity` 读取者；若未来需要自省，另提供签名计数 API。

## 未解决问题

- 类体成员默认值的拒绝应在 core 检查器还是 HIR lowering 层实现，以及诊断措辞；
  本提案只规定“第一切片显式拒绝”。
- `FunctionDef.param_count` 已随 arity 一并移除；若未来工具链需要数量信息，
  使用 `SignatureSpec` 显式计算。
- 调用侧 `*`/`**` 展开（`f(*xs)`/`f(**d)`）另立提案，不在本切片。
- 默认 proto 闭包缓存的生命周期与清理策略（当前按拥有它的 `OortVMClosure`
  存活；若未来支持热重载/模块卸载需重新评估）。
- 自省 API（`SignatureSpec` 的 min/max/positional 计数）暂不提供。
