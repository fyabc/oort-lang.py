# Oort 字节码虚拟机设计

> **状态：设计目标；第一切片已实现。** 当前实际子集、指令语义、opcode 编号
> 与编码以 [HIR 设计](13-hir-design.md) 和 `src/oort_lang/bytecode/opcodes.py`
> 为准。本文保留字节码 ISA、寄存器分配、闭包模型、错误定位与 JIT 的长期
> 设计讨论；部分 opcode 名称是目标方案，尚未与当前实现一一对应。
> 早期寄存器 VM 原型曾因“未实现节点静默穿透、产生错误结果”整体移除，教训见
> [提案 0004](../proposals/0004-bytecode-vm.md)。

---

## 目录

1. [架构概述](#1-架构概述)
2. [指令格式与编码](#2-指令格式与编码)
3. [操作码分类](#3-操作码分类)
4. [寄存器分配](#4-寄存器分配)
5. [闭包模型](#5-闭包模型)
6. [错误报告](#6-错误报告)
7. [JIT 路线图（未来）](#7-jit-路线图未来)
8. [参考文献](#8-参考文献)

---

## 1. 架构概述

### 1.1 核心选型：寄存器式 VM

Oort 采用**寄存器式字节码虚拟机**（Lua 5.x 风格），而非栈式 VM（如 CPython、JVM）。

| 维度 | 寄存器式 | 栈式 |
|------|---------|------|
| 指令密度 | 高（操作数内嵌在指令中） | 低（频繁 PUSH/POP） |
| JIT 友好度 | 高（显式寄存器→CPU 寄存器映射直接） | 低（需额外的栈分析才能映射到寄存器） |
| 编译器实现 | 中等 | 简单 |
| 代表 | Lua 5.x, V8 Ignition, Dalvik | CPython, JVM, WebAssembly |

**选型理由：**

1. **更高的指令密度**：一条 `ADD R1, R2, R3` 等价于栈式的 `LOAD R2; LOAD R3; ADD; STORE R1`（4 条指令），减少了取指和分派的开销。
2. **JIT 编译更友好**：寄存器字节码可以直接映射到 CPU 物理寄存器，省去了"栈→寄存器"转换的大量中间工作。
3. **寄存器窗口机制**：函数调用时，寄存器是基于当前栈帧的一个窗口，局部变量直接映射到固定偏移，访问极快。

### 1.2 渐进类型与双轨架构

Oort 支持以模块为单位的渐进类型系统。编译流程在类型检查后分叉：
- **动态模块** → `ByteCodeGen` → `DynamicCodeObject`（字节码 + 常量池 + Upvalue 描述 + 调试信息）
- **静态模块** → `LLVM IR Gen` → `StaticCodeObject`（函数指针 + 类型签名 + DWARF 调试信息）

两者使用**完全解耦**的代码对象，仅在边界调用时通过 `box`/`unbox` 协议交互。

### 1.3 值表示

所有寄存器存储统一值类型（详见 `01-runtime-value-representation.md`）。动态模块使用带标签值（Tagged Value），静态模块可生成直接操作未箱化数据的指令。

---

## 2. 指令格式与编码

### 2.1 定长 32 位指令

所有指令为 32 位（4 字节）定长，解码极快，仅需位运算提取操作数。

### 2.2 三种指令格式

```
ABC: [Op:8][A:8][B:8][C:8]    算术、比较、移动、属性/下标、容器构建
ABx: [Op:8][A:8][Bx:16]       加载/存储、跳转、调用
Ax:  [Op:8][Ax:24]            扩展操作数、返回
```

| 字段 | 位宽 | 范围 | 用途 |
|------|------|------|------|
| Op | 8 | 0–255 | 操作码 |
| A | 8 | 0–255 | 目标寄存器 |
| B, C | 8 | 0–255 | 源寄存器或常量索引 |
| Bx | 16 | 0–65535 | 常量池索引 / 无符号立即数 |
| sBx | 16 | ±32767 | 有符号跳转偏移 |
| Ax | 24 | 0–16M | 扩展操作数 |

> **与 Lua 的区别**：Lua 用 6 位 Opcode（≤64 条），Oort 用 8 位（≤256 条），为
> 类型特化指令（`ADD_I`/`ADD_F`）和边界指令预留空间。A/B/C 各 8 位（Lua 是 8/9/9），
> 简化编译器但寄存器上限为 256。

### 2.3 64 位指令考量

曾考虑 64 位格式（可寻址 1024 寄存器）。**当前决策**：保持 32 位，通过 `LOAD_SLOT`/`STORE_SLOT` 处理溢出。静态模块由 LLVM 处理寄存器，不需要字节码层面的大寄存器空间。

### 2.4 寄存器溢出机制

当单函数寄存器需求超过 256 时，不采用 Lua 的硬限制（编译报错），而是引入溢出指令：

```
LOAD_SLOT   R(A), Slot[Bx]    ; R(A) = stack_frame[Bx]
STORE_SLOT  Slot[Bx], R(A)    ; stack_frame[Bx] = R(A)
```

**设计要点**：
- 字节码中的寄存器 0–255 为"物理寄存器"，用于热路径。
- 超出部分溢出到栈槽（Stack Slot），通过专用指令访问。
- JIT 编译器可将这些指令优化为直接的寄存器-寄存器移动甚至消除。

---

## 3. 操作码分类

### 3.1 双轨操作码设计

Oort 的核心特色是**同一操作提供动态和静态两个版本**：

| 指令 | 语义 | 使用场景 |
|------|------|---------|
| `ADD` | 动态加法，检查标签，处理多态 | 动态模块默认使用 |
| `ADD_I` | 整数加法，无类型检查 | 静态模块推断为 `int` 时使用 |
| `ADD_F` | 浮点加法，无类型检查 | 静态模块推断为 `float` 时使用 |

同理适用于 `SUB`、`MUL`、`DIV` 等所有算术运算。

**设计原则**：
- 不要为每种类型组合设计指令（如 `ADD_II`、`ADD_IF`、`ADD_FI`……）。
- 使用 `ADD_I` + `guard` 模式更灵活。
- 静态模块编译器优先生成特化指令，动态模块生成通用指令。

### 3.2 类型守卫指令

静态模块在入口处需验证从动态模块传入的参数类型：

```
GUARD_TYPE    R(A), TypeTag, sBx    ; 若 R(A) 不是 TypeTag，跳转到去优化/报错
GUARD_CLASS   R(A), ClassID, sBx    ; 若 R(A) 不是 ClassID 的实例，跳转
```

这允许静态代码在内部假设类型安全，仅在入口处防守。

### 3.3 边界调用指令

处理静态与动态模块之间的交互：

```
CALL_BOUNDARY  R(A), B, C    ; 边界调用：自动 box/unbox 参数
BOX            R(A), R(B)    ; 将未箱化值 R(B) 装箱为动态对象 R(A)
UNBOX          R(A), R(B)    ; 将动态对象 R(B) 解箱为原生值 R(A)
```

**调用约定：**

| 路径 | 行为 | 性能 |
|------|------|------|
| Static → Static | 直接调用，参数不装箱 | 最快 |
| Dynamic → Dynamic | 标准动态调用 | 标准 |
| Static ↔ Dynamic | `CALL_BOUNDARY`，自动 box/unbox | 有转换开销 |

### 3.4 当前已实现的指令分类

基于 `src/oort_lang/bytecode/opcodes.py`，指令按 ABC/ABx/Ax 格式组织为以下类别：

- **数据移动**（ABC/ABx）：`MOVE`, `LOAD_K`, `LOAD_NULL`, `LOAD_BOOL`, `LOAD_SMALL_INT`
- **变量访问**（ABx）：`LOAD_FAST`, `STORE_FAST`, `LOAD_GLOBAL`, `STORE_GLOBAL`
- **Upvalue**（ABx）：`LOAD_UPVALUE`, `STORE_UPVALUE`, `CLOSE_UPVALUE`
- **属性/下标**（ABC）：`LOAD_ATTR`, `STORE_ATTR`, `LOAD_SUBSCR`, `STORE_SUBSCR`
- **算术/位/一元运算**（ABC）：`ADD`–`POW`, `AND`–`RSHIFT`, `UNARY_POS`–`UNARY_INVERT`
- **比较运算**（ABC）：`LT`–`GE`, `IS`, `IS_NOT`, `IN`, `NOT_IN`
- **控制流**（ABx）：`JUMP`, `JMP_FALSE`, `JMP_TRUE`, `FOR_ITER`
- **函数调用**（ABx/Ax）：`CALL`, `CALL_KW`, `TAIL_CALL`, `RETURN`
- **对象/容器**（ABC/Ax）：`CREATE_INSTANCE`, `BUILD_CLASS`, `BUILD_LIST`–`BUILD_MAP`
- **异常处理**（ABx）：`SETUP_EXCEPT`, `SETUP_FINALLY`, `RAISE`, `RERAISE`
- **导入**（ABx）：`IMPORT_NAME`, `IMPORT_FROM`, `IMPORT_STAR`

### 3.5 内联缓存预留（未来）

为支持未来的 JIT 内联缓存（Inline Cache），方法调用指令预留 `ic_slot` 参数：

```
INVOKE_VIRTUAL  R(A), R(B), K(method_name), ic_slot
```

`ic_slot` 指向可修改的内存位置，JIT 可在此填充快速跳转地址。如果静态模块中类是 `final` 或方法不可覆盖，可降级为 `INVOKE_DIRECT`。

---

## 4. 寄存器分配

### 4.1 动态模块：Lua 式线性分配

动态模块采用 Lua 风格的**基于作用域的线性分配**策略，实现简单、编译速度快。

#### 核心机制：`freereg` 指针

编译器维护 `freereg`（当前可用的第一个寄存器索引）：

1. **局部变量**：按声明顺序依次占用 `freereg`, `freereg+1`, ...
2. **临时变量**：表达式中间结果占用 `freereg` 之后的寄存器。
3. **作用域结束**：块内变量失效，`freereg` 回退。

#### 特殊情况

- **函数调用**：参数需要连续寄存器，`f(a, b, c)` 要求 `f` 在 `R[n]`，参数在 `R[n+1..n+3]`。
- **多返回值**：`CALL` 指定返回个数，连续分配。
- **闭包捕获**：被捕获变量不能简单回收，需生成 `CLOSE_UPVALUE`。

#### 优化：简单活性分析

Lua 不重用已声明但未使用的变量寄存器。Oort 引入简单活性分析：记录 `last_use`，变量最后使用后立即可回收寄存器，减少 `freereg` 峰值。

### 4.2 静态模块：SSA + 线性扫描

静态模块使用完全不同的分配策略：

1. **前端**：生成 SSA 形式的 IR（无限虚拟寄存器）。
2. **后端**：使用标准的**线性扫描寄存器分配（Linear Scan Register Allocation）**。
3. **溢出**：物理寄存器不够时，自动 spill 到栈槽。
4. **类型感知**：分配时考虑类型，将同类型变量优先分配到特定寄存器组。

这一部分由 LLVM 后端自动处理，不需要在字节码层面实现。

### 4.3 混合策略总结

```
┌─────────────────────────────────────────────────┐
│  动态模块                                        │
│  Lua 式线性分配 + 简单活性分析                      │
│  目标：编译速度快，255 寄存器以内                   │
│  溢出：LOAD_SLOT / STORE_SLOT                    │
├─────────────────────────────────────────────────┤
│  静态模块                                        │
│  SSA IR + Linear Scan                           │
│  目标：最优寄存器利用，由 LLVM 处理                 │
│  溢出：LLVM 自动 spill 到栈内存                   │
└─────────────────────────────────────────────────┘
```

---

## 5. 闭包模型

### 5.1 选型：Lua 式 Upvalue（统一模型）

Oort 采用 Lua 的 **Upvalue** 模型，而非 Python 的 Cell/Free 分离模型。

**对比三种主流闭包实现：**

| 特性 | Python (Cell) | Lua (Upvalue) | V8 (Context) |
|------|--------------|---------------|-------------|
| 存储 | Cell 对象（堆） | Upvalue 指针（栈或堆） | Context 对象（堆） |
| 分配时机 | 急切（函数入口即分配） | 惰性（函数退出时若需捕获才移堆） | 急切（检测到闭包即分配） |
| 访问开销 | 高（解引用 Cell） | 低（未逃逸则在栈上） | 中（解引用 Context） |
| 指令复杂度 | 高（LOAD_FAST/LOAD_DEREF 两套） | 低（统一 LOAD_UPVALUE） | 中 |
| CodeObject 属性 | `co_cellvars` + `co_freevars` | 统一 `upvalues` 列表 | `context_slots` |

**选择 Lua 模型的理由：**

1. **统一访问**：不需要区分 `cellvars` 和 `freevars`，一套 `LOAD_UPVALUE`/`STORE_UPVALUE` 指令搞定。
2. **惰性分配**：如果闭包在外部函数返回前未被调用，变量一直留在栈上，零开销。
3. **透明切换**：变量在栈上和堆上之间透明切换，闭包内部代码不感知。

### 5.2 Upvalue 数据结构

编译期 `UpvalueDescriptor`（见 `src/oort_lang/bytecode/code_object.py`）：

```python
@dataclass
class UpvalueDescriptor:
    index: int          # 变量在当前函数局部变量表中的栈槽索引
    is_local: bool = True  # True=Open（在栈上），False=Closed（在堆上）
```

运行时 `Upvalue` 对象包含：`v: *TValue`（指向栈槽或堆上 `value`）、`value: TValue`（堆备份）、`next: *Upvalue`（链表指针）。

### 5.3 闭包相关指令

| 指令 | 语义 |
|------|------|
| `CLOSURE R(A), Proto[Bx]` | 创建闭包对象，消费后续 N 条指令初始化 Upvalue |
| `LOAD_UPVALUE R(A), Upval[Bx]` | 读取 Upvalue 指向的值 |
| `STORE_UPVALUE Upval[Bx], R(A)` | 写入 Upvalue 指向的位置 |
| `CLOSE_UPVALUE R(A)` | 关闭 R(A) 及以上寄存器的所有 Open Upvalue |

#### `CLOSURE` 的特殊初始化序列

`CLOSURE` 指令不是独立执行的。创建闭包后，VM 立即读取紧随其后的 N 条指令作为参数：

- `MOVE A, B` → 第 i 个 Upvalue 捕获**当前函数的局部变量** `R[B]`。
- `LOAD_UPVALUE A, B` → 第 i 个 Upvalue 捕获自**外层函数的第 B 个 Upvalue**（传递捕获）。

```
; outer 函数
0: LOAD_K     R1, 10       ; R1 = 10 (x)
1: CLOSURE    R2, proto[0] ; 创建 inner 闭包
2:    MOVE    0, 1         ; inner.upvals[0] 捕获 outer.R1 (x)

; inner 函数
0: LOAD_UPVALUE R1, 0      ; R1 = upvals[0] (即 x)
1: SETUPVAL     R3, 0      ; upvals[0] = R3 (修改 x)
```

#### `CLOSE_UPVALUE` 的执行流程

当函数返回或跳出作用域时，遍历 `open_upvalue` 链表，将指向当前栈帧的 Upvalue 的值**迁移到堆上**（复制到 `Upvalue.value`，修改指针），然后从链表移除。多个闭包捕获同一变量时共享同一个 `Upvalue` 对象。

### 5.4 渐进类型下的闭包处理

- **DynamicCodeObject**：保留完整 Upvalue 支持（`upvalues: list[UpvalueDescriptor]`）。
- **StaticCodeObject**：通过 **Lambda Lifting + Context Struct** 编译为 LLVM IR：

1. **Lambda Lifting**：将嵌套函数提升为顶层函数，捕获变量转为额外参数。
   - `fn inner() -> int` → `fn inner_lifted(ctx: *ClosureCtx) -> int`
2. **Context Struct**：定义 LLVM Struct 存储所有捕获变量，在堆上分配。
   - `%ClosureCtx = type { i64, i64* }`
3. **闭包对象表示**：Fat Pointer = `{ 函数指针, Context 指针 }`。
4. **调用时**：解包 Fat Pointer，将 Context 指针作为第一个参数传入。

```llvm
; 定义上下文结构体（捕获了一个 int）
%ClosureCtx = type { i64 }

; 提升后的函数，增加 ctx 参数
define i64 @inner_lifted(%ClosureCtx* %ctx) {
  %val_ptr = getelementptr %ClosureCtx, %ClosureCtx* %ctx, i32 0, i32 0
  %val = load i64, i64* %val_ptr
  ret i64 %val
}
```

**内存管理**：Context 结构体必须纳入内存管理（引用计数或 GC 根），确保闭包存活时不被释放。

### 5.5 静态模块中的闭包优化

在静态模块中，如果编译器能证明：
1. 捕获变量类型固定。
2. 闭包不逃逸出当前作用域（或可内联）。
3. 变量生命周期与栈帧一致。

则可完全省略 Upvalue 结构体的分配和间接寻址，通过寄存器传递或栈帧指针偏移直接访问。

---

## 6. 错误报告

### 6.1 扩展调试信息表

采用 **Python 3.11+ 模型**：为字节码指令维护扩展的位置映射表，包含列号信息。

**数据结构**：`Opcode → (start_line, end_line, start_column, end_column)` 四元组序列。

**压缩策略**：使用**差分编码**（Delta Encoding）+ 变长整数（VarInt）：
- 只存储相对于上一条指令的行号/列号变化量。
- 大多数指令的位置变化很小甚至为 0，压缩率高。

**按需存储**：不需要每条指令都有列号。仅为"可能抛出异常"的指令存储精确位置：
- 除法（`DIV`）
- 属性访问（`LOAD_ATTR`）
- 函数调用（`CALL`）
- 下标访问（`LOAD_SUBSCR`）

其他指令复用上一条的位置信息。

### 6.2 性能考量

获取列号仅在**错误路径**（Error Path）上发生，不干扰正常的指令分发循环。

```
正常执行路径：解释器 dispatch loop → 不查位置表（零开销）
异常抛出路径：查找位置表 → 提取行列号 → 格式化错误信息
```

### 6.3 行号表实现

当前实现使用 `dict[int, int]`（偏移→行号映射），见 `CodeObject.line_table`：

```python
def get_line_number(self, offset: int) -> int:
    return self.line_table.get(offset, self.first_lineno)
```

**未来扩展**：替换为差分编码的位置表，增加列号字段：

```python
@dataclass
class SourceLocation:
    start_line: int
    end_line: int
    start_col: int
    end_col: int

# line_table 升级为 positions_table
positions_table: dict[int, SourceLocation]
```

### 6.4 REPL 与 stdin 的处理

#### 虚拟文件名

| 输入来源 | 虚拟文件名 | 行号策略 |
|---------|-----------|---------|
| 标准输入（管道） | `<stdin>` | 连续计数，同脚本文件 |
| 交互式 REPL | `<interactive>` | 每个编译块从 1 开始 |
| `eval()` / `exec()` | `<string>` | 基于传入字符串 |

#### REPL 特殊处理

- **源码常驻内存**：Code Object 必须持有源码字符串引用（无法按需读盘）。
- **编译单元**：每次确认一个逻辑块独立编译，行号在该块内从 1 开始。
- **列号计算**：与文件模式相同，基于字符偏移量（非字节数）。
- **内存管理**：可配置 `traceback limit` 清理历史源码；Code Object 被 GC 时自动释放。

---

## 7. JIT 路线图（未来）

> 本节记录 JIT 编译的设计方向和决策，属于远期规划。当前阶段专注于解释器的正确性。

### 7.1 分阶段实施

```
阶段 0：纯解释器 ← 当前目标
  │  验证语言语义，建立调试基础
  ▼
阶段 1：基线 JIT (Baseline JIT)
  │  不做复杂优化，直接将字节码翻译成机器码
  │  目标：比解释器快 5–10 倍
  ▼
阶段 2：优化 JIT (Optimizing JIT)
     引入热点探测，SSA 转换，内联，常量折叠
     目标：追求极致性能
```

### 7.2 SSA：强烈推荐但非必须

**结论**：SSA 是"强烈推荐"而非"绝对必须"。

| 策略 | 性能 | 复杂度 | 适用场景 |
|------|------|--------|---------|
| **A：内存映射法** | 2–5x | 极低 | 原型验证、冷代码路径 |
| **B：直接映射 + 活性分析** | 5–20x | 中等 | 基线 JIT |
| **C：IR + SSA + 寄存器分配** | 20–50x | 高 | 优化 JIT |

- **方案 A**：VM 寄存器映射到 Native 栈帧内存区域，每次操作都访存，但实现极简单。
- **方案 B**：不转 SSA，分析虚拟寄存器生命周期，线性扫描分配物理寄存器。处理控制流合并较麻烦。
- **方案 C**：Bytecode → IR → SSA → 优化 → 寄存器分配 → 机器码。SSA 消除数据依赖歧义，生命周期不重叠，寄存器分配更容易。

### 7.3 代码生成工具选择

| 工具 | 语言 | 推荐度 | 说明 |
|------|------|--------|------|
| **AsmJit** | C++ | ⭐⭐⭐⭐⭐ | 功能强大，内置寄存器分配器，API 友好 |
| **Cranelift** | Rust | ⭐⭐⭐⭐ | 现代化设计，专为 JIT 场景打造 |
| **DynASM** | C/Lua | ⭐⭐⭐⭐ | LuaJIT 使用，极轻量 |
| **LLVM** | C++ | ⭐⭐ | 工业级，但过重，编译慢，不适合 JIT 场景 |

**建议**：C/C++ 实现选 AsmJit，Rust 实现选 Cranelift。

### 7.4 GC 与 JIT 的冲突

JIT 代码中寄存器可能持有堆指针，GC 需要精确的 Stack Maps。**第一版 JIT 跳过自动 GC**，使用引用计数或保守式 GC（如 Boehm GC），先跑通框架再添加精确支持。

### 7.5 注意事项

- JIT 代码必须遵守宿主 ABI（System V AMD64 / Windows x64）。
- 机器码内存页需标记为可执行（注意 W^X 保护）。
- 初期只锁定 x86_64，稳定后再移植 ARM。

---

## 8. 参考文献

### 核心参考

- **Lua 5.x 源码**：`lopcodes.h`, `lvm.c`, `lcode.c`, `lfunc.c`
  - 寄存器字节码设计的最佳教材
  - Upvalue 机制的参考实现
  - `luaV_execute` 函数是解释器循环的典范
- **Python 3.11+ Precise Exceptions**：`co_positions` 和列号报错机制
- **V8 Ignition 字节码**：字节码作为优化 IR 的设计思路

### 相关设计文档

- `01-runtime-value-representation.md`：值表示、整数层级、Tagged Pointer
- `03-type-system-design.md`：渐进类型系统、类型检查器
- `07-concurrency-abi-design.md`：多线程、ABI 设计

### 学术与工程参考

- **LuaJIT**：追踪 JIT 和汇编生成的巅峰（Mike Pall）
- **《Engineering a Compiler》**：编译器后端理论基础
- **《Virtual Machines》** (Smith & Nair)：虚拟机架构全面参考
- **Linear Scan Register Allocation** (Poletto & Sarkar, 1999)：JIT 寄存器分配算法
- **SSA Book** (Braun et al.)：SSA 形式转换与优化

### 设计讨论来源

本文档整理自项目早期的设计讨论（ISA、寄存器分配、JIT 选型、错误定位、
闭包模型与 CodeObject 设计）。原始讨论记录未纳入仓库。
