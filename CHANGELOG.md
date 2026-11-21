# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `oort-core` thin probe: `#lang oort-core` with an independent static checker
  for `Int`, `Bool`, `Unit`, annotated functions, `val`/`var`, `if`/`return`,
  `print`, and a small operator subset. The same source still runs dynamically
  under `oort-object`, where annotations remain unchecked (OP 0017).
- Checked core modules execute on the existing interpreter; `-t astm` shows
  inferred static types and `Unit` maps to runtime `null`.
- Same-dialect `oort-core` module imports: `import "m"` / `from "m" import f`
  expose typed module exports, support re-exports, and detect missing exports
  and circular imports during compilation. Cross-dialect and native imports
  remain rejected.
- Monomorphic `oort-core` ADTs: top-level `enum` declarations, constructor
  values, `match` expressions with wildcard/binding/nested constructor
  patterns, and top-level constructor exhaustiveness checks. Enum values can
  be printed; enum equality, generic ADTs and full nested exhaustiveness are
  deferred. `oort-object` rejects `enum`/`match` explicitly.
- Function types, lambdas and first-class function values in `oort-core`:
  `(Int, Bool) -> Int`, `do(x: Int) -> Int { ... }`, higher-order functions,
  function-valued variables/ADT payloads, and function values exported from
  core modules. Function-type arrows are right-associative
  (`Int -> Int -> Int` = `Int -> (Int -> Int)`), and calls may chain through
  function values (`add(1)(2)`). Multi-argument functions are not automatically
  curried. Anonymous/generic/default-argument lambdas remain rejected.
- Bidirectional expected-type propagation in `oort-core`: annotations,
  assignments, returns, function bodies and call arguments now push expected
  types into `if` branches, block tails and `match` arms, improving diagnostics
  at the exact branch or argument.
- The VSCode grammar (0.1.3) highlights `enum` declarations and names,
  `match`, `=>` and `Unit`; 0.1.2 added the first enum/match scopes.
- Internal backend foundation: a shared linear-register HIR, a 32-bit
  bytecode compiler/disassembler and a register VM for the dynamic
  scalar/collection/function/loop subset, including container slices,
  attribute reads/writes, lambdas and frame-captured closures. Function values
  can be stored, returned, indexed and called, and passed to native
  higher-order helpers such as `map`. Top-level dynamic classes and instance
  methods (including inheritance, `__init__` and `__iter__`), plus module
  imports (`import`/`from`, aliases, relative paths and `-I`), now run on the
  VM as well; imported modules execute on the same VM with isolated globals.
  `-t bc` prints the disassembly and `-t vm` executes that subset; `-t eval`
  remains the default backend.
- `oort-object` subscript and missing-attribute protocols (OP 0018):
  `def operator "[]"(index)` / `def operator "[]="(index, value)` for
  user-defined indexing (including slices and tuple indices), and a read-only
  `on_missing(name)` fallback after fields, methods and extensions. Built-in
  containers keep native indexing; there is no `__setattr__`-style write hook.
- `oort-core` static classes and slots: top-level classes with fixed typed
  `val`/`var` slots, per-instance slot initializers that run before `__init__`,
  definite-assignment checking of constructors, read-only `val` slots,
  typed methods/`this`, and constructor calls. Inheritance, metaclasses,
  class methods, operator methods and dynamic fields remain rejected.
- `oort-core` collections and loops: `List[T]`, `Set[T]`, `Dict[K, V]` and
  `Tuple[...]` annotations, homogeneous/empty literal checking, indexing,
  the special `len` builtin, same-type collection equality, and `while`/`for`
  loops over lists, sets, dict keys, strings and uniform tuples. Collections
  are immutable and slices, `in`, ordering and heterogeneous-tuple iteration
  remain rejected.
- `oort-core` scalar expressions: `Float` and `String` types and literals,
  mixed Int/Float arithmetic, `/` (always `Float`), numeric and String
  comparison/equality, and annotated parameters/returns for both. Numeric
  annotations remain strict (`val x: Float = 1` is rejected); `**` stays
  unsupported because its result type depends on the exponent.

### Changed

- List/Tuple ordering is now recursive Oort comparison (elements are compared
  with Oort `==`/`<`, including user operators) instead of Python host
  comparison; Dict no longer supports ordering, and Set ordering uses the key
  protocol. Non-orderable elements such as `Bool` now report an error.
- List/Tuple `+` and `*` are value-level operators that build a new sequence
  sharing element objects, instead of a HOST round-trip copy.
- Dunder methods other than `__init__` and `__iter__` are rejected in class
  bodies (`Special method '<name>' is not supported.`) instead of being stored
  but never dispatched; the unused `__op_*__` fields and the shadowed `super`
  builtin were removed.
- `enum` and `match` are now hard keywords, and `=>` is a reserved
  `FATARROW` token (not a user operator) used for `match` arms; existing
  identifiers named `enum`/`match` and user operators spelled `=>` are no
  longer valid.
- Dialect boundaries are explicit: `oort-core` may import other core modules,
  while the loader still rejects `oort-object` ↔ `oort-core` imports until FFI
  trampolines land.
- The REPL stays `oort-object`-only and now rejects `#lang` directives with a
  clear message instead of silently treating the submission as dynamic code.

### Fixed

- Assigning an attribute to a built-in object such as a List now reports
  `Cannot set attribute ... on 'List' object` instead of an internal assertion.

- Errors raised while comparing or testing membership inside built-in
  containers now report the user expression's source position instead of
  `<builtin>`.
- `$0`/`$1` inside a named `def` without an explicit parameter list is no
  longer silently bound to an enclosing lambda's anonymous parameter.
- A `KeyboardInterrupt` while initializing an imported module (Ctrl-C in the
  REPL) discards the failed record so the import can be retried.
- `zip` documentation now states that it eagerly drains every input and hangs
  on infinite iterables.
- `OortIterator.take_remaining` always returns a copy of its backing list.
- The redundant `NEWLINE*` before `.` in the grammar was removed; leading-dot
  continuation is still handled by the token post-processor.

## [0.3.1] - 2026-11-20

### Changed

- Equality now has one recursive value protocol and a separate key protocol
  (OP 0016): nested `Bool`/`Int` stay distinct, Dict/Set equality and set
  algebra use key equality, and Int/Float remain value-equal but distinct keys.
  Host projection is no longer used for equality, membership or set algebra.
- A lambda with an explicit parameter list is now a barrier for `$0`/`$1`
  resolution, so it cannot silently capture an outer anonymous parameter.
- Line-leading `.` continuation is removed from the parser token stream before
  parsing; the REPL still requires `\` because it cannot see the next line.
- The JSON showcase uses brace-only definitions for no-argument methods
  (`def parse { ... }`).

### Fixed

- Class object writes (`C.f = ...`) can no longer replace callable members
  inherited through the class/metaclass MRO.

## [0.3.0] - 2026-11-20

### Added

- Module system (OP 0006): `.ort` modules with `import "m" [as x]` and
  `from "m" import a, b as c`, eager top-level-hoisted initialization,
  canonical-path caching, circular-import diagnostics, module namespaces with
  automatic re-export, and `-I/--module-path` search directories.
- Multi-file example under `examples/04_modules/`.
- Diagnostics now keep each error paired with its own source input and sort
  across files, so imported-module errors point at the right file and line.
- Minimal standard library (OP 0012): eager `map`, `filter`, `zip`, `enumerate`
  and stable `sorted` builtins, plus native `math` and `string` modules
  importable as `import "math"` / `from "string" import upper`.
- Standard-library examples under `examples/05_stdlib/` and host/stdlib
  benchmarks in `benchmarks/test_stdlib.py`.
- Iterator protocol (OP 0013): user classes implement `__iter__` returning a
  callable that yields `(value, valid)` tuples; `for` is streaming and builtin
  containers expose the same protocol through a native `Iterator` type.
- User-iterator example under `examples/06_iterators/` and builtin/user iterator
  benchmarks in `benchmarks/test_iterators.py`.
- Extension methods (OP 0014): `def C.f` defines a method on an existing type
  from outside the class. Extensions are lexically scoped, activated by
  `import`/`from`, dispatch on the runtime type MRO, and never override
  members, fields, or built-in operators. `super` in an extension searches
  class members only.
- Extension operators: `def C.operator "+"(x)` fills operators the target type
  does not define; class and native operators always win.
- Extension example under `examples/03_oop/03_02_extensions.ort` and
  `benchmarks/test_extensions.py`.
- Minimal I/O and process support (OP 0015): `io.read_file` / `io.write_file`
  for UTF-8 whole-file access, `os.args` / `os.script` / `os.exit`, and
  `string.ord` / `string.chr`.
- JSON parser/formatter showcase at `examples/07_showcase/07_00_json.ort`,
  including `\uXXXX`/surrogate handling and a CLI file argument.
- Documentation site built with MkDocs Material and deployed to GitHub Pages:
  <https://fyabc.github.io/oort-lang.py/>, with new getting-started and
  examples pages.

### Changed

- Host boundary refactor: `OortObject.py_value` becomes `host_value`, with a
  `HostBridge`, HOST/VALUE/CONTEXT native call modes and a `NativeContext` for
  higher-order native functions. `len` no longer projects whole containers.
- Imports are only allowed at module top level; nested imports are rejected
  with an explicit diagnostic.
- Each module owns an isolated global environment; global lookups resolve
  against the defining module, so functions and methods keep their own module
  globals when called from elsewhere.
- The grammar no longer embeds host-language actions (OP 0008): bracket
  tracking, newline filtering and line escapes moved to a pure token
  post-processor (`parser/token_processor.py`), and the lexer always emits
  `NEWLINE`.
- The REPL is now `ReplSession` + `ConsoleIO`: each submission reparses its
  buffer instead of mutating ANTLR lexer/parser internals. Ctrl-C cancels the
  current input or interrupts a running statement without exiting; prompts
  are hidden for non-TTY input, and EOF exits cleanly. On Windows, EOF is
  Ctrl-Z followed by Enter; `exit` / `quit` also close the REPL.

### Fixed

- The VSCode grammar now colors `import`, `from` and `as` as import keywords
  (`keyword.control.import.oort`); `as` previously shared the operator-word
  scope and could be left uncolored by some themes. Extension version 0.1.1.
- Unmatched closing brackets (`)`, `]`, `}`) now produce a normal syntax
  diagnostic instead of an `IndexError` from lexer stack actions.
- Piped/redirected REPL input exits cleanly on EOF instead of ending with a
  traceback, and syntax errors no longer abort the session.

## [0.2.0] - 2026-11-19

### Added

- VSCode extension in `editors/vscode/`: TextMate syntax highlighting,
  bracket matching, comment configuration, an orbit-and-comet language file
  icon and grammar tests.
- Anonymous lambda parameters `$0` / `$1` for lambdas without an explicit
  parameter list (`do: $0 * 2`, `do: $0 + $1`; OP 0010).
- Full parameter binding: call-time default values, keyword arguments,
  positional-only (`/`) and keyword-only (`*`) parameters, `*args` as a Tuple,
  `**kwargs` as a Dict, and `&block` with trailing-block or keyword syntax
  (OP 0011).
- Dialect contract: an optional first-line `#lang oort-object` directive,
  `DialectConfig` (feature gates and a per-compilation Pratt operator table),
  and explicit diagnostics for unknown, unimplemented (`oort-core`) or
  misplaced dialect declarations.
- Operator overloading: `def operator "<sym>"` methods for unary and binary
  operators, including comparisons and membership. Built-in types use the same
  dispatch table, `!=` / `!in` derive from `==` / `in`, and `is` / `!is`
  compare object identity.
- Expression and surface syntax cleanup (OP 0009): Python/Rust precedence,
  strict `Bool`/`Int` separation, parenthesized parameter lists, implicit
  infix disabled, `break value`, DOT continuation and Oort container display.
- Language specification (`docs/spec/`) and a proposal process
  (`docs/proposals/`, OP 0001–0011).
- CI on Linux and Windows (Python 3.11–3.13): lint, format, type check and a
  coverage gate.
- Contribution, security and issue/PR templates.

### Changed

- Quality infrastructure now includes bandit, pip-audit, deptry, vulture,
  hypothesis property tests, markdown/actionlint checks and a wheel/sdist
  installation smoke test in CI.
- Benchmark infrastructure now covers micro operations, macro workloads,
  startup, memory ceilings and historical Fibonacci, with a CI history
  workflow and profiling instructions.
- The package is reorganized into `source/`, `diagnostics/`, `ast/`,
  `parser/`, `semantics/`, `runtime/` and `driver/` layers. `objects.py`,
  `ast_builder.py` and `pass1.py` are split by responsibility, and an
  import-linter contract keeps the layer boundaries enforced.
- Name resolution now attaches a typed `Binding` (scope depth plus slot
  index) to AST name nodes instead of writing untyped `metadata` keys; scope
  layouts are shared with the future slot/upvalue backend.
- Each interpreter now owns an isolated `Runtime` with its own built-in type
  table and `null`/`true`/`false` singletons, so multiple interpreters can
  share a process without overwriting each other's types.
- mypy is now an effective gate: generated parser/lexer code is excluded,
  hand-written code is checked with `check_untyped_defs` and strict optionals,
  and pre-commit uses the project's locked tool versions.
- Operator precedence now follows Python/Rust: bitwise `& ^ |` bind tighter than
  comparisons, and comparisons are non-associative (`a < b < c` is an error).
- `Bool` is no longer a subtype of `Int`: boolean arithmetic and `true == 1` are
  rejected; container membership keeps booleans and integers distinct.
- Identifiers no longer accept a trailing `!`, so `a!=b`, `x!in xs` and `a!is b`
  lex correctly without spaces.
- All parameter lists now require parentheses. Bare forms such as `def f x: ...`
  and `do x: ...` are syntax errors, removing the `:` type-vs-body ambiguity.
- Implicit infix calls (`a b c`) are disabled until the explicit `infix` design
  lands; `def C.f`, `class A.B` and explicit `super(...)` calls are rejected.
- `break expr` makes `while` / `for` expressions return a value; a line starting
  with `.` continues a method chain; `//=` is supported.
- Dict/set display uses Oort literal delimiters (`{: ... :}` / `{. ... .}`).
- `oort-object` rejects `var` / `val` declarations directly in a class body.
  Instances are open field bags; fields must be created with
  `this.name = ...` in `__init__` (OP 0007).
- Instance fields can no longer shadow instance or class methods; missing
  attributes raise `OortAttributeError`. Default equality and hashing use
  object identity.
- Source files are read as UTF-8 with optional BOM (`utf-8-sig`).
- The public roadmap is now high-level; detailed planning lives in the private
  ledger and GitHub milestones/issues. Development is organized around dialect
  vertical slices on a shared spine: `oort-object` v1 first, a thin `oort-core` probe next, and a shared
  bytecode backend after both dialect v1s. Class slots are scoped to
  `oort-core`; `oort-object` keeps an open field bag (OP 0001 §5, OP 0007).
- Minimum Python is now 3.11 (3.10 reached end of life); CI tests 3.11–3.13
  on Linux, and 3.13 on Windows.
- Development dependencies updated (ruff, mypy, pytest, pytest-benchmark,
  pre-commit, virtualenv, filelock), resolving the open Dependabot alerts.

### Fixed

- `break` / `continue` inside a function defined in a loop no longer escape to
  the outer loop.
- Parameter-layout validation now handles variadic keyword and trailing block
  parameters at index 0, and the marker-order diagnostic is corrected.
- Pratt binding powers are integers instead of floating-point epsilon values.

## [0.1.0] - 2026-11-18

### Added

- Dynamic core: functions, closures, classes, methods, class methods,
  multiple inheritance (C3 MRO), metaclasses, `this` / `super`.
- `for ... in` loops (destructuring, per-iteration binding), `if` / `elif` /
  `else`, `while` with `break` / `continue`.
- List, tuple, dict and set literals; subscripting and slicing; augmented
  assignment; multiple declaration targets and tuple unpacking.
- Builtins: `print`, `clock`, `type`, `super`, `len`, `range`, `str`, `repr`,
  `int`, `float`, `bool`.
- Multi-line REPL with error recovery.
- Unit and integration tests, example programs and a benchmark baseline.
- Parser generated from `grammars/Oort.g4` with a Pratt expression parser.

### Changed

- Default execution target is `eval` (tree-walking interpreter).
- Unsupported constructs are rejected with explicit `UnsupportedSyntax`
  diagnostics instead of silently doing the wrong thing.
- `USER_OP` excludes `.`, `:`, `@`; dead tokens were removed; `elif` and
  symmetric `else` forms are supported.

### Removed

- The unfinished register-based bytecode backend (silently miscompiled
  unsupported constructs). Design and reimplementation requirements are kept in
  `docs/design/02-bytecode-vm-design.md` and OP 0004.
