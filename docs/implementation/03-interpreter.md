# 树遍历解释器

默认执行后端是 `src/oort_lang/runtime/` 中的树遍历解释器，入口参数
`-t eval`。`-t vm` 已能在 HIR/字节码子集（含动态类、模块与 `oort-core`
静态槽/ADT/match）上执行，但仍以 `eval` 为默认与语义参照。

选择先稳定树遍历语义，是因为语言特性仍在快速变化：每加一个语法节点只需
实现一个 visitor；而字节码后端会把寄存器分配、闭包布局、异常表等工程问题
提前引入（早期寄存器 VM 原型因此被移除，见
[proposal 0004](../proposals/0004-bytecode-vm.md)）。

## 对象表示

所有 Oort 值都是 `OortObject` 的实例，带一个 `type`（类型对象）：

| Oort 类型 | Python 类 | 说明 |
|-----------|-----------|------|
| `Int` / `Float` / `String` / `Bool` / `Null` | `OortInt` 等 | 装箱的标量；实现简单，牺牲性能 |
| `List` / `Tuple` / `Dict` / `Set` / `Slice` | `OortList` 等 | 容器与切片 |
| `Type` | `OortType` | 类型对象本身也是对象；`Type.type is Type` |
| `Function` / `Method` | `OortFunction` / `OortMethod` | 用户函数与绑定方法 |
| `Object` | `OortInstance` | 用户类实例 |
| `Module` | `OortModule` | 模块命名空间的只读视图 |
| `SuperProxy` | `OortSuperProxy` | `super` 的中间对象 |

- 标量实现 `__eq__` / `__hash__`，因此可以作为字典键和集合元素；
  `List`/`Dict`/`Set` 不可哈希。
- 每个 `ASTInterpreter` 拥有独立的 `Runtime`：类型表与 `null`/`true`/`false`
  单例按运行时创建。解释器执行期间通过 contextvar 激活当前运行时，因此同一
  进程中的多个解释器不会互相覆盖内建类型。
- `Bool` 不是 `Int` 的子类型；`Bool` 只登记 `==` / `!=`，不参与算术、位运算
  或大小比较。容器成员测试也对 `Bool`/`Int` 做严格区分。
- lambda 的匿名参数 `$0` / `$1` 在调用时按位置绑定到 `OortFunction` 的调用
  环境；参数数量与绑定规则由 `runtime/call_protocol.py` 的签名绑定器提供。
- `host_value` 是 Python 宿主的投影；原生调用通过 `HostBridge`、`NativeMode`
  与 `NativeContext` 显式处理参数/结果，详见
  [05-stdlib.md](05-stdlib.md) 与
  [设计 12](../design/12-host-boundary.md)。
- 运算符通过 `OortType.operators` 表调度，键为 `(符号, 操作数个数)`：
  - 用户类在类体中用 `def operator "<sym>"` 定义，解释器在
    `visit_class_def` 中调用 `set_operator` 登记；
  - 内建类型在 `TypeSystem` 中登记原生运算符方法，
    因此 `1 + 2` 与 `Vec(1) + Vec(2)` 走同一条查找/调用路径；
  - `OortMethod.defining_type` 让运算符方法内部的 `super` 正确定位；
  - `is` / `!is` 直接比较对象身份，`and` / `or` / `not` 不走运算符表；
  - `!=` 与 `!in` 在没有显式方法时分别由 `==` 与 `in` 取反；
  - 下标复用运算符表：`("[]", 2)` 读、`("[]=", 3)` 写；内置容器仍走原生下标，
    用户实例缺少 operator 时报错。
  - 属性 miss 在扩展查找之后调用 `on_missing(name)`，按接收者 id 防重入；
    不提供全量写钩子。
  设计背景见 [proposal 0002](../proposals/0002-dsl-support.md)。

## 作用域与闭包

`Environment` 是链式作用域：

- 每个块、函数调用、循环迭代都创建新的 `Environment`；
- 语义分析（`pass1.py`）为每个名字节点附加类型化的 `Binding`（作用域深度
  与槽位索引），运行时直接按深度访问，避免每次线性查找；
- 函数对象保存定义时的 `Environment`，即形成闭包；
- 模块顶层与入口模块的根环境允许重定义同名变量（`allow_redefine=True`），
  局部作用域重复定义报错；
- 每个环境都有 `module_root`：模块根指向自身，其余环境继承外层的值。
  `Binding.depth is None` 的全局名按**定义模块**的根环境解析，因此 A 模块
  的函数被 B 模块调用时，仍读取 A 的全局变量；
- 模块根的外层是共享的 `<builtins>` 环境；内建名不属于模块命名空间；
- `val` 的不可变性在赋值时检查。
- 每个环境还持有扩展方法与扩展运算符表；属性/运算符 miss 时按词法作用域
  查找，详见 [实现笔记 07](07-extensions.md)。

`for` 循环**每次迭代创建新的绑定环境**，因此闭包捕获的是当次迭代的值
（对应 JavaScript `let` / C# 5+ `foreach`；Python 的循环变量是共享绑定）：

```oort
var fs = []
for i in [1, 2] {
    fs = fs + [do: i]
}
print(fs[0](), fs[1]())   # 1 2
```

`for` 通过 `open_iterator` / `iterator_next` 流式拉取：`__iter__` 返回可调用
迭代器，每步返回 `(value, valid)`；内置容器使用原生 `OortIterator` 快路径，
用户对象使用任意 Oort 闭包。`iter_values` 只负责把迭代器 drain 成 List，供
急切集合助手使用。协议见 [规范 09](../spec/09-iterators.md)。

## 模块加载

- `runtime/modules.py` 的 `ModuleLoader` 负责路径解析、缓存与初始化；它通过
  回调注入编译（`Compiler.compile_unit`）、执行（`ASTInterpreter.run_module`）
  与环境/模块工厂，不依赖 driver，满足 import-linter 的分层约束。
- 缓存键是 `Path.resolve()`；记录状态为 `LOADING → LOADED / FAILED`。
  重新进入 `LOADING` 记录即报告循环导入，链中包含入口文件。初始化抛错时标记
  `FAILED`；`KeyboardInterrupt`（REPL 中 Ctrl-C）则丢弃记录，便于重试。
- 顶层 import 在 `visit_module` 中被提升到其他语句之前执行（ES/Go 式）。
- `OortModule` 是 native 值，`get` 只读模块根环境的 `values`，因此导入名
  自动再导出，而内建名与写入 (`m.x = ...`) 都不可见。
- 被导入模块的编译/运行诊断与摘要错误都由入口或 REPL 统一 `report` 一次；
  `CompilerErrorHandler` 保存 `(error, input_info)` 对，按
  `(filename, line, column)` 排序，并为 traceback 位置单独查找输入。

## 控制流

- `if` / `elif` / `else` 都是表达式；`elif` 在 AST 中降级为嵌套 `if`。
- `while`、`for` 支持 `break` / `continue`（通过内部异常实现）。
- `break value` 使循环表达式返回该值；裸 `break` 或正常结束返回 `null`。
- 块的值是最后一条语句的值；函数体返回值同理。

## 参数绑定

`runtime/signature.py` 的 `Signature` 把 `FunctionDef.params` 分为
位置限定、位置或关键字、`*args`、关键字限定、`**kwargs` 与 `&block` 六组。
`visit_call` 先按源代码顺序求值所有实参（带 `keyword` / `BLOCK` 元数据），
再由 `Signature.bind` 完成绑定：

- 默认值在绑定阶段按声明顺序求值，求值环境包含闭包与更早的参数；
  `this` 在默认值之后才写入方法调用环境。
- `*args` 构造成 Tuple，`**kwargs` 构造成 String 键 Dict。
- 尾随块在函数有 `&block` 时绑定到块参数；没有时保持位置实参行为。
- 绑定错误由 `ArgumentBindingError` 转换为 `OortTypeError`，位置取调用表达式。

原生内建函数仍走位置参数路径；`visit_call` 在进入原生函数前拒绝关键字实参。

## 内建函数与类型

`builtins.py` 注册：

- 类型对象：`Object`、`Type`、`Int`、`Float`、`String`、`Bool`、`Null`、
  `List`、`Tuple`、`Dict`、`Set`、`Function`、`Method`。
- 函数：`print`、`clock`、`type`、`len`、`range`、`str`、`repr`、
  `int`、`float`、`bool`；集合助手 `map`、`filter`、`zip`、`enumerate`、`sorted`。

原生函数通过 `NativeMode` 决定参数/结果如何跨越宿主边界：

- `HOST`：参数经 `HostBridge.to_host` 投影，结果再装箱（运算符、`math`、
  `string`）；
- `VALUE`：参数保持 Oort 对象（`print`、`type`、`str`、`repr`、`len`）；
- `CONTEXT`：额外传入 `NativeContext`，可调用 Oort lambda、读取 truthiness、
  迭代容器并应用运算符（集合助手）。

`str` / `repr` 调用宿主 Python 的 `str()` / `repr()`，即各运行时包装类自己的
格式化；用户类不能定义 `__str__` / `__repr__`（见规范）。容器因此输出 Oort
字面量形式。`len` 直接在 Oort 容器上取长度，避免深投影。

## 未实现功能的处理

`ASTVisitor` 为每个节点提供了默认的 `visit_children`。如果解释器漏实现某个
visitor，默认行为会“穿过”节点执行子节点——这正是旧字节码后端静默出错的根源。
因此，当前策略是：

1. 解释器实现所有语法分析阶段接受的**核心**节点；
2. `Pass1Analyzer` 对未实现的特性显式报 `UnsupportedSyntax`；
   `oort-core` 的 `CoreTypeChecker` 还会拒绝静态子集之外的构造；
3. 新增语法节点时，必须同时实现 visitor 或加入拒绝列表。

拒绝清单见 [规范：一致性矩阵](../spec/06-conformance.md)。
