#! /usr/bin/env python

"""Lower the checked dynamic AST into the shared low-level HIR.

This slice covers arithmetic, locals, globals, branches, loops, calls,
top-level functions, lambdas/closures, first-class function values and dynamic
classes/methods. Anything else is rejected explicitly (OP 0004: never rely on a
visitor's default traversal).
"""

import dataclasses
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import NoReturn

from ..ast import nodes
from ..diagnostics.syntax_errors import UnsupportedSyntax
from ..runtime.call_protocol import ParamKind, ParamSpec, SignatureSpec
from ..source.source_position import SourcePosition
from .nodes import (
    BinOp,
    BuildClass,
    BuildDict,
    BuildEnum,
    BuildList,
    BuildSet,
    BuildSlice,
    BuildTuple,
    Call,
    DefineFunction,
    FreshLocals,
    GetAttr,
    GetItem,
    HirFunction,
    HirModule,
    ImportFrom,
    ImportModule,
    Instruction,
    IteratorNext,
    Jump,
    JumpIfFalse,
    JumpIfTrue,
    Label,
    LoadConst,
    LoadGlobal,
    LoadLocal,
    LoadOuter,
    MakeClosure,
    Match,
    MatchArm,
    Move,
    OpenIterator,
    Pattern,
    RegisterExtension,
    Return,
    SetAttr,
    SetItem,
    StoreGlobal,
    StoreLocal,
    StoreOuter,
    SuperProxy,
    UnOp,
    Unpack,
    validate_module,
)

_MAX_REGISTERS = 256

_AUGMENTED_OPS = {
    "+=": "+",
    "-=": "-",
    "*=": "*",
    "/=": "/",
    "//=": "//",
    "%=": "%",
    "**=": "**",
    "<<=": "<<",
    ">>=": ">>",
    "&=": "&",
    "^=": "^",
    "|=": "|",
}

_PARAM_KINDS = {
    nodes.ParameterKind.POS_ONLY: ParamKind.POS_ONLY,
    nodes.ParameterKind.DEFAULT: ParamKind.POS_OR_KW,
    nodes.ParameterKind.KW_ONLY: ParamKind.KW_ONLY,
    nodes.ParameterKind.VAR_POS: ParamKind.VAR_POS,
    nodes.ParameterKind.VAR_KW: ParamKind.VAR_KW,
    nodes.ParameterKind.BLOCK: ParamKind.BLOCK,
}


@dataclasses.dataclass(slots=True)
class _ScopeName:
    slot: int
    mutable: bool


@dataclasses.dataclass(slots=True)
class _FunctionState:
    name: str
    code: list[Instruction]
    scopes: list[dict[str, _ScopeName]]
    next_reg: int = 0
    max_reg: int = 0
    label_counter: int = 0
    is_main: bool = False
    loop_depth: int = 0
    loop_stack: list[tuple[str, str, int]] = dataclasses.field(default_factory=list)
    in_match_arm: bool = False
    local_slots: set[int] = dataclasses.field(default_factory=set)


class HirLowerer:
    def __init__(self):
        self.module: nodes.ModuleNode | None = None
        self._function_slots: dict[int, HirFunction] = {}
        self._next_function_index: int = 0
        self._states: list[_FunctionState] = []
        self._global_mutability: dict[str, bool] = {}

    @property
    def state(self) -> _FunctionState:
        return self._states[-1]

    def lower(self, module: nodes.ModuleNode) -> HirModule:
        self.module = module
        statements = list(module.body.statements)
        function_defs: dict[int, int] = {}
        class_methods: dict[int, tuple[tuple[nodes.FunctionDef, int], ...]] = {}
        class_level_methods: dict[int, tuple[tuple[nodes.FunctionDef, int], ...]] = {}
        class_operators: dict[int, tuple[tuple[nodes.FunctionDef, int], ...]] = {}
        class_slots: dict[int, tuple[tuple[nodes.VarDecl, int | None], ...]] = {}
        for stmt in statements:
            if isinstance(stmt, nodes.FunctionDef) and not stmt.is_lambda:
                if stmt.is_extension:
                    self._validate_extension_function(stmt)
                else:
                    self._validate_top_level_function(stmt)
                function_defs[id(stmt)] = self._reserve_function_index()
            elif isinstance(stmt, nodes.ClassDef):
                methods: list[tuple[nodes.FunctionDef, int]] = []
                level_methods: list[tuple[nodes.FunctionDef, int]] = []
                operators: list[tuple[nodes.FunctionDef, int]] = []
                slots: list[tuple[nodes.VarDecl, int | None]] = []
                self._validate_top_level_class(stmt)
                for member in stmt.body.statements:
                    if isinstance(member, nodes.VarDecl):
                        self._validate_class_slot(member)
                        initializer = (
                            None if member.init_value is None else self._reserve_function_index()
                        )
                        slots.append((member, initializer))
                        continue
                    if not isinstance(member, nodes.FunctionDef) or member.is_lambda:
                        self._reject(
                            member,
                            "class-body statements other than methods or slots",
                        )
                    self._validate_class_method(member)
                    entry = (member, self._reserve_function_index())
                    if member.is_operator:
                        operators.append(entry)
                    elif member.is_class_method:
                        level_methods.append(entry)
                    else:
                        methods.append(entry)
                class_methods[id(stmt)] = tuple(methods)
                class_level_methods[id(stmt)] = tuple(level_methods)
                class_operators[id(stmt)] = tuple(operators)
                class_slots[id(stmt)] = tuple(slots)

        main = self._lower_main(
            statements,
            function_defs,
            class_methods,
            class_level_methods,
            class_operators,
            class_slots,
        )
        for stmt in statements:
            if isinstance(stmt, nodes.FunctionDef) and not stmt.is_lambda:
                if stmt.is_extension:
                    self._lower_extension_function(stmt, function_defs[id(stmt)])
                else:
                    self._lower_function(stmt, function_defs[id(stmt)])
            elif isinstance(stmt, nodes.ClassDef):
                for method, index in (
                    *class_methods[id(stmt)],
                    *class_level_methods[id(stmt)],
                    *class_operators[id(stmt)],
                ):
                    self._lower_method(method, index)
                for slot, slot_index in class_slots[id(stmt)]:
                    if slot_index is not None:
                        self._lower_slot_initializer(slot, slot_index)
        functions = tuple(self._function_slots[index] for index in range(self._next_function_index))
        result = HirModule(main=main, functions=functions)
        validate_module(result)
        return result

    # ------------------------------------------------------------------
    # Functions and main
    # ------------------------------------------------------------------

    def _reserve_function_index(self) -> int:
        index = self._next_function_index
        self._next_function_index += 1
        return index

    def _lower_import(self, node: nodes.ImportStmt | nodes.ImportFromStmt) -> None:
        if isinstance(node, nodes.ImportStmt):
            self._emit(ImportModule(node.position, node.module_path, node.alias))
            binding = node.alias or _derive_import_binding(node.module_path)
            if binding is not None:
                self._global_mutability[binding] = False
            return
        self._emit(
            ImportFrom(
                node.position,
                node.module_path,
                tuple(node.names.items()),
            )
        )
        for source, alias in node.names.items():
            self._global_mutability[alias or source] = False

    def _validate_class_slot(self, node: nodes.VarDecl) -> None:
        if len(node.decl_targets) != 1:
            self._reject(node, "multi-target slot declarations")

    def _validate_top_level_class(self, node: nodes.ClassDef) -> None:
        if len(node.names) != 1:
            self._reject(node, "namespaced or anonymous classes")
        if node.type_params:
            self._reject(node, "generic classes")

    def _validate_class_method(self, node: nodes.FunctionDef) -> None:
        if node.is_extension:
            self._reject(node, "extension methods in class bodies")
        if not node.is_class_method and len(node.names) != 1:
            self._reject(node, "namespaced methods")
        if node.type_params:
            self._reject(node, "generic methods")
        if node.is_class_method and node.operator_symbol is not None:
            self._reject(node, "class operator methods")
        if _is_reserved_method_name(node.name) and (
            node.is_class_method or node.name not in ("__init__", "__iter__")
        ):
            self._reject(node, f"special method {node.name!r}")

    def _validate_extension_function(self, node: nodes.FunctionDef) -> None:
        if not node.is_extension:
            self._reject(node, "extension method without a receiver type")
        if node.type_params:
            self._reject(node, "generic extension methods")
        if _is_reserved_method_name(node.name):
            self._reject(node, f"special extension method {node.name!r}")

    def _lower_identifier(self, name: str, position: SourcePosition) -> int:
        local = self._find_local(name)
        if local is not None:
            dst = self._alloc(position)
            self._emit(LoadLocal(position, dst, local.slot))
            return dst
        outer = self._find_outer(name)
        if outer is not None:
            owner_index, binding = outer
            dst = self._alloc(position)
            self._emit(
                LoadOuter(
                    position,
                    dst,
                    len(self._states) - 1 - owner_index,
                    binding.slot,
                )
            )
            return dst
        dst = self._alloc(position)
        self._emit(LoadGlobal(position, dst, name))
        return dst

    def _emit_extension_registration(self, node: nodes.FunctionDef, index: int) -> None:
        receiver_name = node.extension_receiver
        assert receiver_name is not None
        receiver = self._lower_identifier(receiver_name, node.name_position)
        symbol = node.operator_symbol
        operand_count = node.operator_operand_count
        self._emit(
            RegisterExtension(
                node.position,
                receiver,
                node.name,
                index,
                symbol,
                operand_count if operand_count is not None else 0,
            )
        )

    def _lower_extension_function(self, node: nodes.FunctionDef, index: int) -> None:
        self._lower_method(node, index)

    def _validate_top_level_function(self, node: nodes.FunctionDef) -> None:
        if node.is_extension:
            self._reject(node, "extension methods")
        if node.is_class_method:
            self._reject(node, "class methods")
        if node.operator_symbol is not None:
            self._reject(node, "operator methods")
        if node.type_params:
            self._reject(node, "generic functions")
        if len(node.names) != 1:
            self._reject(node, "namespaced functions")

    def _lower_main(
        self,
        statements: list[nodes.ASTNode],
        function_defs: dict[int, int],
        class_methods: dict[int, tuple[tuple[nodes.FunctionDef, int], ...]],
        class_level_methods: dict[int, tuple[tuple[nodes.FunctionDef, int], ...]],
        class_operators: dict[int, tuple[tuple[nodes.FunctionDef, int], ...]],
        class_slots: dict[int, tuple[tuple[nodes.VarDecl, int | None], ...]],
    ) -> HirFunction:
        state = _FunctionState(name="<main>", code=[], scopes=[{}], is_main=True)
        self._states.append(state)
        try:
            for stmt in statements:
                if isinstance(stmt, (nodes.ImportStmt, nodes.ImportFromStmt)):
                    self._lower_import(stmt)
            last: int | None = None
            for stmt in statements:
                if isinstance(stmt, (nodes.ImportStmt, nodes.ImportFromStmt)):
                    continue
                if isinstance(stmt, nodes.FunctionDef) and not stmt.is_lambda:
                    index = function_defs[id(stmt)]
                    if stmt.is_extension:
                        self._emit_extension_registration(stmt, index)
                        last = None
                        continue
                    self._validate_top_level_function(stmt)
                    name = stmt.name
                    self._emit(DefineFunction(stmt.position, name, index))
                    self._global_mutability[name] = False
                    last = None
                    continue
                if isinstance(stmt, nodes.ClassDef):
                    self._lower_class_def(
                        stmt,
                        class_methods[id(stmt)],
                        class_level_methods[id(stmt)],
                        class_operators[id(stmt)],
                        class_slots[id(stmt)],
                    )
                    last = None
                    continue
                last = self._lower_stmt(stmt)
            if last is None:
                last = self._const(None, constants_source(statements))
            self._emit(Return(self._position_of(statements), last))
            return HirFunction(
                name="<main>",
                params=(),
                local_count=state.max_reg,
                code=tuple(state.code),
                position=module_position(statements),
                is_main=True,
            )
        finally:
            self._states.pop()

    def _lower_function(self, node: nodes.FunctionDef, index: int) -> HirFunction:
        names, signature = self._lower_signature(node, anonymous=False, start_slot=0)
        state = _FunctionState(name=node.name, code=[], scopes=[{}])
        self._states.append(state)
        try:
            self._declare_signature_params(
                names,
                node,
                anonymous=False,
                start_slot=0,
            )
            self._lower_function_body(node)
            result = HirFunction(
                name=node.name,
                params=names,
                local_count=state.max_reg,
                code=tuple(state.code),
                position=node.position,
                signature=signature,
            )
        finally:
            self._states.pop()
        self._function_slots[index] = result
        return result

    def _lower_method(self, node: nodes.FunctionDef, index: int) -> HirFunction:
        names, signature = self._lower_signature(
            node,
            anonymous=False,
            start_slot=1,
            has_this=True,
        )
        state = _FunctionState(name=node.name, code=[], scopes=[{}])
        self._states.append(state)
        try:
            self._declare_local("this", mutable=False, position=node.position)
            self._declare_signature_params(
                names,
                node,
                anonymous=False,
                start_slot=1,
            )
            self._lower_function_body(node)
            result = HirFunction(
                name=node.name,
                params=("this", *names),
                local_count=state.max_reg,
                code=tuple(state.code),
                position=node.position,
                has_this=True,
                signature=signature,
            )
        finally:
            self._states.pop()
        self._function_slots[index] = result
        return result

    def _lower_class_def(
        self,
        node: nodes.ClassDef,
        methods: tuple[tuple[nodes.FunctionDef, int], ...],
        class_level_methods: tuple[tuple[nodes.FunctionDef, int], ...],
        operators: tuple[tuple[nodes.FunctionDef, int], ...],
        slots: tuple[tuple[nodes.VarDecl, int | None], ...],
    ) -> None:
        bases = tuple(self._require_value(base) for base in node.bases)
        metaclass = None if node.meta is None else self._require_value(node.meta)
        dst = self._alloc(node.position)
        slot_specs = [
            (slot.decl_targets[0].name, slot.mutable, initializer) for slot, initializer in slots
        ]
        operator_specs: list[tuple[str, int, int]] = []
        for method, index in operators:
            symbol = method.operator_symbol
            operand_count = method.operator_operand_count
            assert symbol is not None and operand_count is not None
            operator_specs.append((symbol, operand_count, index))
        self._emit(
            BuildClass(
                node.position,
                dst,
                node.name,
                bases,
                tuple((method.name, index) for method, index in methods),
                tuple(slot_specs),
                tuple((method.name, index) for method, index in class_level_methods),
                tuple(operator_specs),
                metaclass=metaclass,
            )
        )
        self._emit(StoreGlobal(node.name_position, node.name, dst))
        self._global_mutability[node.name] = False

    def _lower_slot_initializer(self, node: nodes.VarDecl, index: int) -> HirFunction:
        name = node.decl_targets[0].name
        state = _FunctionState(name=f"<slot {name}>", code=[], scopes=[{}])
        self._states.append(state)
        try:
            value = self._require_value(node.init_value)
            self._emit(Return(node.position, value))
            result = HirFunction(
                name=f"<slot {name}>",
                params=(),
                local_count=state.max_reg,
                code=tuple(state.code),
                position=node.position,
                signature=SignatureSpec(()),
            )
        finally:
            self._states.pop()
        self._function_slots[index] = result
        return result

    def _lower_enum_def(self, node: nodes.EnumDef) -> None:
        dst = self._alloc(node.position)
        self._emit(
            BuildEnum(
                node.position,
                dst,
                node.name,
                tuple((ctor.name, len(ctor.fields)) for ctor in node.constructors),
            )
        )

    def _lower_match(self, node: nodes.MatchExpr) -> int:
        scrutinee = self._require_value(node.scrutinee)
        arms: list[MatchArm] = []
        for arm in node.arms:
            bindings = _pattern_bindings(arm.pattern)
            index = self._reserve_function_index()
            state = _FunctionState(
                name="<match arm>",
                code=[],
                scopes=[{}],
                in_match_arm=True,
            )
            self._states.append(state)
            try:
                for name in bindings:
                    self._declare_local(name, mutable=False, position=arm.body.position)
                value = self._require_value(arm.body)
                self._emit(Return(arm.body.position, value))
                function = HirFunction(
                    name="<match arm>",
                    params=bindings,
                    local_count=state.max_reg,
                    code=tuple(state.code),
                    position=arm.body.position,
                    signature=_simple_signature(bindings),
                )
            finally:
                self._states.pop()
            self._function_slots[index] = function
            arms.append(MatchArm(_pattern_descriptor(arm.pattern), index))
        dst = self._alloc(node.position)
        self._emit(Match(node.position, dst, scrutinee, tuple(arms)))
        return dst

    def _lower_nested_function(self, node: nodes.FunctionDef) -> int:
        self._validate_top_level_function(node)
        slot = self._declare_local(
            node.name,
            mutable=False,
            position=node.name_position,
        )
        index = self._reserve_function_index()
        names, signature = self._lower_signature(node, anonymous=False, start_slot=0)
        state = _FunctionState(name=node.name, code=[], scopes=[{}])
        self._states.append(state)
        try:
            self._declare_signature_params(
                names,
                node,
                anonymous=False,
                start_slot=0,
            )
            self._lower_function_body(node)
            result = HirFunction(
                name=node.name,
                params=names,
                local_count=state.max_reg,
                code=tuple(state.code),
                position=node.position,
                signature=signature,
            )
        finally:
            self._states.pop()
        self._function_slots[index] = result
        dst = self._alloc(node.position)
        self._emit(MakeClosure(node.position, dst, index))
        self._emit(StoreLocal(node.name_position, slot, dst))
        return dst

    def _lower_lambda(self, node: nodes.FunctionDef) -> int:
        if node.type_params:
            self._reject(node, "generic lambdas")
        names, signature = self._lower_signature(node, anonymous=True, start_slot=0)
        index = self._reserve_function_index()
        state = _FunctionState(name="<lambda>", code=[], scopes=[{}])
        self._states.append(state)
        try:
            self._declare_signature_params(
                names,
                node,
                anonymous=True,
                start_slot=0,
            )
            self._lower_function_body(node)
            result = HirFunction(
                name="<lambda>",
                params=names,
                local_count=state.max_reg,
                code=tuple(state.code),
                position=node.position,
                is_lambda=True,
                signature=signature,
            )
        finally:
            self._states.pop()
        self._function_slots[index] = result
        dst = self._alloc(node.position)
        self._emit(MakeClosure(node.position, dst, index))
        return dst

    def _lower_signature(
        self,
        node: nodes.FunctionDef,
        *,
        anonymous: bool,
        start_slot: int,
        has_this: bool = False,
    ) -> tuple[tuple[str, ...], SignatureSpec]:
        names: list[str] = []
        specs: list[ParamSpec] = []
        if anonymous and not node.has_explicit_param_list:
            for index in range(node.anonymous_count):
                name = f"${index}"
                names.append(name)
                specs.append(
                    ParamSpec(
                        name=name,
                        kind=ParamKind.POS_ONLY,
                        slot=start_slot + index,
                    )
                )
            return tuple(names), SignatureSpec(tuple(specs), has_this=has_this)

        for param in node.params:
            default_index = None
            if param.default_value is not None:
                default_index = self._lower_default_proto(
                    param.name,
                    tuple(names),
                    param.default_value,
                    param.position,
                )
            names.append(param.name)
            specs.append(
                ParamSpec(
                    name=param.name,
                    kind=_PARAM_KINDS[param.kind],
                    slot=start_slot + len(names) - 1,
                    has_default=default_index is not None,
                    default_index=default_index,
                )
            )
        return tuple(names), SignatureSpec(tuple(specs), has_this=has_this)

    def _lower_default_proto(
        self,
        name: str,
        earlier_names: tuple[str, ...],
        expression: nodes.ASTNode,
        position: SourcePosition,
    ) -> int:
        index = self._reserve_function_index()
        state = _FunctionState(name=f"<default {name}>", code=[], scopes=[{}])
        self._states.append(state)
        try:
            for earlier in earlier_names:
                self._declare_local(earlier, mutable=False, position=position)
            value = self._require_value(expression)
            self._emit(Return(position, value))
            result = HirFunction(
                name=f"<default {name}>",
                params=earlier_names,
                local_count=state.max_reg,
                code=tuple(state.code),
                position=position,
                signature=_simple_signature(earlier_names),
            )
        finally:
            self._states.pop()
        self._function_slots[index] = result
        return index

    def _declare_signature_params(
        self,
        names: tuple[str, ...],
        node: nodes.FunctionDef,
        *,
        anonymous: bool,
        start_slot: int,
    ) -> None:
        for index, name in enumerate(names):
            position = node.position if anonymous else node.params[index].position
            slot = self._declare_local(name, mutable=False, position=position)
            if slot != start_slot + index:
                self._reject(node, "non-contiguous parameter slots")

    def _lower_function_body(self, node: nodes.FunctionDef) -> int:
        last: int | None = None
        for stmt in node.body.statements:
            last = self._lower_stmt(stmt)
        if last is None:
            last = self._const(None, node.position)
        self._emit(Return(node.position, last))
        return last

    # ------------------------------------------------------------------
    # Statements and expressions
    # ------------------------------------------------------------------

    def _lower_stmt(self, node: nodes.ASTNode) -> int | None:
        if isinstance(node, nodes.VarDecl):
            return self._lower_var_decl(node)
        if isinstance(node, nodes.Assignment):
            return self._lower_assignment(node)
        if isinstance(node, nodes.ReturnExpr):
            if self.state.in_match_arm:
                self._reject(node, "return inside a match arm")
            if self.state.is_main:
                self._reject(node, "top-level return")
            value = self._lower_expr(node.value) if node.value is not None else None
            if value is None:
                value = self._const(None, node.position)
            self._emit(Return(node.position, value))
            return None
        if isinstance(node, (nodes.ImportStmt, nodes.ImportFromStmt)):
            self._reject(node, "nested imports")
        if isinstance(node, nodes.ClassDef):
            self._reject(node, "nested class definitions")
        if isinstance(node, nodes.EnumDef):
            self._lower_enum_def(node)
            return None
        if isinstance(node, nodes.BreakExpr):
            value = None if node.value is None else self._require_value(node.value)
            self._emit_loop_jump(node, break_target=True, value=value)
            return None
        if isinstance(node, nodes.ContinueExpr):
            self._emit_loop_jump(node, break_target=False)
            return None
        if isinstance(node, nodes.FunctionDef):
            if node.is_lambda:
                return self._lower_expr(node)
            if node.is_extension:
                self._validate_extension_function(node)
                index = self._reserve_function_index()
                self._emit_extension_registration(node, index)
                self._lower_extension_function(node, index)
                return None
            return self._lower_nested_function(node)
        return self._lower_expr(node)

    def _lower_var_decl(self, node: nodes.VarDecl) -> int | None:
        if len(node.decl_targets) != 1:
            self._reject(node, "multi-target declarations")
        target = node.decl_targets[0]
        if node.init_value is None:
            self._reject(node, "declarations without an initializer")
        value = self._lower_expr(node.init_value)
        if value is None:
            value = self._const(None, node.position)
        if self._is_module_scope():
            self._emit(StoreGlobal(target.position, target.name, value))
            self._global_mutability[target.name] = node.mutable
        else:
            slot = self._declare_local(target.name, mutable=node.mutable, position=target.position)
            self._emit(StoreLocal(target.position, slot, value))
        return None

    def _lower_assignment(self, node: nodes.Assignment) -> int | None:
        if node.op.text != "=":
            return self._lower_augmented_assignment(node)
        if isinstance(node.lhs, nodes.Attribute):
            receiver = self._require_value(node.lhs.value)
            rhs_value = self._require_value(node.rhs)
            self._emit(SetAttr(node.lhs.position, receiver, node.lhs.attribute, rhs_value))
            return None
        if isinstance(node.lhs, nodes.Subscript):
            container = self._require_value(node.lhs.value)
            index = self._require_value(node.lhs.index)
            rhs_value = self._require_value(node.rhs)
            self._emit(SetItem(node.lhs.position, container, index, rhs_value))
            return None
        if not isinstance(node.lhs, nodes.Name):
            self._reject(node, "attribute/tuple assignment")
        value = self._lower_expr(node.rhs)
        if value is None:
            value = self._const(None, node.position)
        self._store_name(node.lhs, value)
        return None

    def _lower_augmented_assignment(self, node: nodes.Assignment) -> int | None:
        base_op = _AUGMENTED_OPS.get(node.op.text)
        if base_op is None:
            self._reject(node, f"assignment operator {node.op.text!r}")

        if isinstance(node.lhs, nodes.Attribute):
            receiver = self._require_value(node.lhs.value)
            current = self._alloc(node.lhs.position)
            self._emit(GetAttr(node.lhs.position, current, receiver, node.lhs.attribute))
            rhs_value = self._require_value(node.rhs)
            result = self._alloc(node.position)
            self._emit(BinOp(node.position, result, base_op, current, rhs_value))
            target = self._require_value(node.lhs.value)
            self._emit(SetAttr(node.lhs.position, target, node.lhs.attribute, result))
            return None

        if isinstance(node.lhs, nodes.Subscript):
            container = self._require_value(node.lhs.value)
            index = self._require_value(node.lhs.index)
            current = self._alloc(node.lhs.position)
            self._emit(GetItem(node.lhs.position, current, container, index))
            rhs_value = self._require_value(node.rhs)
            result = self._alloc(node.position)
            self._emit(BinOp(node.position, result, base_op, current, rhs_value))
            target = self._require_value(node.lhs.value)
            target_index = self._require_value(node.lhs.index)
            self._emit(SetItem(node.lhs.position, target, target_index, result))
            return None

        if not isinstance(node.lhs, nodes.Name):
            self._reject(node, "augmented assignment target")
        current = self._lower_name(node.lhs)
        rhs_value = self._require_value(node.rhs)
        result = self._alloc(node.position)
        self._emit(BinOp(node.position, result, base_op, current, rhs_value))
        self._store_name(node.lhs, result)
        return None

    def _store_name(self, target: nodes.Name, value: int) -> None:
        binding = target.binding
        if binding is None or binding.is_global:
            if not self._global_mutability.get(target.id, True):
                self._reject(target, "assignment to an immutable global")
            self._emit(StoreGlobal(target.position, target.id, value))
            return
        local = self._find_local(target.id)
        if local is not None:
            if not local.mutable:
                self._reject(target, "assignment to an immutable local")
            self._emit(StoreLocal(target.position, local.slot, value))
            return
        outer = self._find_outer(target.id)
        if outer is None:
            self._reject(target, "closure over an unknown local")
        owner_index, outer_binding = outer
        if not outer_binding.mutable:
            self._reject(target, "assignment to an immutable outer local")
        depth = len(self._states) - 1 - owner_index
        self._emit(StoreOuter(target.position, depth, outer_binding.slot, value))

    def _lower_expr(self, node: nodes.ASTNode | None) -> int | None:
        if node is None:
            return None
        if isinstance(node, nodes.IntConstant):
            return self._const(node.value, node.position)
        if isinstance(node, nodes.FloatConstant):
            return self._const(node.value, node.position)
        if isinstance(node, nodes.StringConstant):
            return self._const(node.value, node.position)
        if isinstance(node, nodes.BooleanConstant):
            return self._const(node.value, node.position)
        if isinstance(node, nodes.NullConstant):
            return self._const(None, node.position)
        if isinstance(node, nodes.EllipsisConstant):
            self._reject(node, "ellipsis")
        if isinstance(node, nodes.Name):
            return self._lower_name(node)
        if isinstance(node, nodes.ImplicitSuperExpr):
            this = self._find_local("this")
            if this is None:
                self._reject(node, "super outside a method")
            dst = self._alloc(node.position)
            self._emit(SuperProxy(node.position, dst, this.slot))
            return dst
        if isinstance(node, nodes.ClassDef):
            self._reject(node, "class expressions")
        if isinstance(node, nodes.EnumDef):
            self._reject(node, "enum expressions")
        if isinstance(node, nodes.MatchExpr):
            return self._lower_match(node)
        if isinstance(node, nodes.UnaryExpr):
            operand = self._require_value(node.operand)
            dst = self._alloc(node.position)
            self._emit(UnOp(node.position, dst, node.op.text, operand))
            return dst
        if isinstance(node, nodes.AndExpr):
            return self._lower_logical(node, jump_on_true=False)
        if isinstance(node, nodes.OrExpr):
            return self._lower_logical(node, jump_on_true=True)
        if isinstance(node, nodes.BinaryExpr):
            lhs = self._require_value(node.lhs)
            rhs = self._require_value(node.rhs)
            dst = self._alloc(node.position)
            self._emit(BinOp(node.position, dst, node.op.text, lhs, rhs))
            return dst
        if isinstance(node, nodes.IfExpr):
            return self._lower_if(node)
        if isinstance(node, nodes.WhileExpr):
            return self._lower_while(node)
        if isinstance(node, nodes.ForExpr):
            return self._lower_for(node)
        if isinstance(node, nodes.BlockExpr):
            return self._lower_block(node)
        if isinstance(node, nodes.Call):
            return self._lower_call(node)
        if isinstance(node, nodes.Assignment):
            return self._lower_assignment(node)
        if isinstance(node, nodes.ReturnExpr):
            return self._lower_stmt(node)
        if isinstance(node, nodes.ListLiteral):
            return self._lower_sequence(node.elements, BuildList, node.position)
        if isinstance(node, nodes.TupleLiteral):
            return self._lower_sequence(node.elements, BuildTuple, node.position)
        if isinstance(node, nodes.SetLiteral):
            return self._lower_sequence(node.elements, BuildSet, node.position)
        if isinstance(node, nodes.DictLiteral):
            return self._lower_dict(node)
        if isinstance(node, nodes.Subscript):
            container = self._require_value(node.value)
            index = self._require_value(node.index)
            dst = self._alloc(node.position)
            self._emit(GetItem(node.position, dst, container, index))
            return dst
        if isinstance(node, nodes.Attribute):
            receiver = self._require_value(node.value)
            dst = self._alloc(node.position)
            self._emit(GetAttr(node.position, dst, receiver, node.attribute))
            return dst
        if isinstance(node, nodes.FunctionDef):
            if node.is_lambda:
                return self._lower_lambda(node)
            self._reject(node, "nested function definitions")
        if isinstance(node, nodes.SliceLiteral):
            start = None if node.start is None else self._require_value(node.start)
            stop = None if node.stop is None else self._require_value(node.stop)
            step = None if node.step is None else self._require_value(node.step)
            dst = self._alloc(node.position)
            self._emit(BuildSlice(node.position, dst, start, stop, step))
            return dst
        self._reject(node, type(node).__name__)

    def _lower_sequence(self, elements, instruction, position) -> int:
        values = tuple(self._require_value(element) for element in elements)
        dst = self._alloc(position)
        self._emit(instruction(position, dst, values))
        return dst

    def _lower_dict(self, node: nodes.DictLiteral) -> int:
        items: list[tuple[int, int]] = []
        for key, value in node.items:
            if key is None:
                self._reject(node, "dict unpacking")
            items.append((self._require_value(key), self._require_value(value)))
        dst = self._alloc(node.position)
        self._emit(BuildDict(node.position, dst, tuple(items)))
        return dst

    def _lower_name(self, node: nodes.Name) -> int:
        binding = node.binding
        if binding is None or binding.is_global:
            dst = self._alloc(node.position)
            self._emit(LoadGlobal(node.position, dst, node.id))
            return dst
        local = self._find_local(node.id)
        if local is not None:
            dst = self._alloc(node.position)
            self._emit(LoadLocal(node.position, dst, local.slot))
            return dst
        outer = self._find_outer(node.id)
        if outer is None:
            self._reject(node, "closure over an unknown local")
        owner_index, outer_binding = outer
        depth = len(self._states) - 1 - owner_index
        dst = self._alloc(node.position)
        self._emit(LoadOuter(node.position, dst, depth, outer_binding.slot))
        return dst

    def _lower_logical(self, node: nodes.BooleanExpr, *, jump_on_true: bool) -> int:
        dst = self._require_value(node.lhs)
        end = self._new_label("logic")
        jump_type = JumpIfTrue if jump_on_true else JumpIfFalse
        self._emit(jump_type(node.position, dst, end))
        rhs = self._require_value(node.rhs)
        self._emit(Move(node.position, dst, rhs))
        self._emit(Label(node.position, end))
        return dst

    def _lower_if(self, node: nodes.IfExpr) -> int:
        result = self._const(None, node.position)
        else_label = self._new_label("else")
        end_label = self._new_label("endif")
        condition = self._require_value(node.condition)
        self._emit(JumpIfFalse(node.position, condition, else_label))
        then_value = self._lower_block(node.if_block)
        if then_value is not None:
            self._emit(Move(node.position, result, then_value))
        self._emit(Jump(node.position, end_label))
        self._emit(Label(node.position, else_label))
        if node.else_block is not None:
            else_value = self._lower_block(node.else_block)
            if else_value is not None:
                self._emit(Move(node.position, result, else_value))
        self._emit(Label(node.position, end_label))
        return result

    def _lower_while(self, node: nodes.WhileExpr) -> int:
        result = self._const(None, node.position)
        start = self._new_label("while")
        end = self._new_label("endwhile")
        before = set(self.state.local_slots)
        self._emit(Label(node.position, start))
        condition = self._require_value(node.condition)
        self._emit(JumpIfFalse(node.position, condition, end))
        fresh_index = len(self.state.code)
        self.state.loop_depth += 1
        self.state.loop_stack.append((start, end, result))
        try:
            self._lower_block(node.body)
        finally:
            self.state.loop_stack.pop()
            self.state.loop_depth -= 1
        loop_slots = tuple(sorted(self.state.local_slots - before))
        if loop_slots:
            self.state.code.insert(
                fresh_index,
                FreshLocals(node.position, loop_slots),
            )
        self._emit(Jump(node.position, start))
        self._emit(Label(node.position, end))
        return result

    def _lower_for(self, node: nodes.ForExpr) -> int:
        if not node.vars:
            self._reject(node, "loop without variables")
        result = self._const(None, node.position)
        before = set(self.state.local_slots)
        iterable = self._require_value(node.iterator)
        iterator = self._alloc(node.position)
        self._emit(OpenIterator(node.position, iterator, iterable))
        start = self._new_label("for")
        end = self._new_label("endfor")
        self._emit(Label(node.position, start))
        value = self._alloc(node.position)
        self._emit(IteratorNext(node.position, value, iterator, end))
        self._push_scope()
        try:
            slots = [
                self._declare_local(
                    loop_var.name,
                    mutable=False,
                    position=loop_var.position,
                )
                for loop_var in node.vars
            ]
            fresh_index = len(self.state.code)
            if len(slots) == 1:
                self._emit(StoreLocal(node.vars[0].position, slots[0], value))
            else:
                self._emit(
                    Unpack(
                        node.position,
                        value,
                        slots[0],
                        len(slots),
                    )
                )
            self.state.loop_depth += 1
            self.state.loop_stack.append((start, end, result))
            try:
                self._lower_block(node.body)
            finally:
                self.state.loop_stack.pop()
                self.state.loop_depth -= 1
        finally:
            self._pop_scope()
        loop_slots = tuple(sorted(self.state.local_slots - before))
        if loop_slots:
            self.state.code.insert(
                fresh_index,
                FreshLocals(node.position, loop_slots),
            )
        self._emit(Jump(node.position, start))
        self._emit(Label(node.position, end))
        return result

    def _emit_loop_jump(
        self,
        node: nodes.BreakExpr | nodes.ContinueExpr,
        *,
        break_target: bool,
        value: int | None = None,
    ) -> None:
        if not self.state.loop_stack:
            self._reject(node, "break/continue outside a loop")
        continue_label, break_label, result = self.state.loop_stack[-1]
        if break_target:
            if value is not None:
                self._emit(Move(node.position, result, value))
            target = break_label
        else:
            target = continue_label
        self._emit(Jump(node.position, target))

    def _lower_block(self, block: nodes.BlockExpr) -> int | None:
        self._push_scope()
        try:
            last: int | None = None
            for stmt in block.statements:
                last = self._lower_stmt(stmt)
                if isinstance(stmt, nodes.ReturnExpr):
                    last = None
            return last
        finally:
            self._pop_scope()

    def _lower_call(self, node: nodes.Call) -> int:
        if node.infix:
            self._reject(node, "infix calls")
        callee = self._require_value(node.func)
        positional: list[int] = []
        keywords: list[tuple[str, int]] = []
        block: int | None = None
        for arg in node.args:
            if arg.kind == nodes.ArgumentKind.BLOCK:
                if block is not None:
                    self._reject(arg, "multiple trailing blocks")
                block = self._require_value(arg.value)
                continue
            if arg.keyword is not None:
                keywords.append((arg.keyword, self._require_value(arg.value)))
                continue
            if arg.kind != nodes.ArgumentKind.DEFAULT:
                self._reject(arg, "variadic call arguments")
            positional.append(self._require_value(arg.value))
        dst = self._alloc(node.position)
        self._emit(
            Call(
                node.position,
                dst,
                callee,
                tuple(positional),
                tuple(keywords),
                block,
            )
        )
        return dst

    # ------------------------------------------------------------------
    # Scopes and registers
    # ------------------------------------------------------------------

    def _is_module_scope(self) -> bool:
        return self.state.is_main and len(self.state.scopes) == 1

    def _push_scope(self) -> None:
        self.state.scopes.append({})

    def _pop_scope(self) -> None:
        self.state.scopes.pop()

    def _declare_local(self, name: str, *, mutable: bool, position: SourcePosition) -> int:
        slot = self._alloc(position)
        self.state.scopes[-1][name] = _ScopeName(slot=slot, mutable=mutable)
        self.state.local_slots.add(slot)
        return slot

    def _find_local(self, name: str) -> _ScopeName | None:
        for scope in reversed(self.state.scopes):
            found = scope.get(name)
            if found is not None:
                return found
        return None

    def _find_outer(self, name: str) -> tuple[int, _ScopeName] | None:
        for state_index in range(len(self._states) - 2, -1, -1):
            for scope in reversed(self._states[state_index].scopes):
                found = scope.get(name)
                if found is not None:
                    return state_index, found
        return None

    def _alloc(self, position: SourcePosition) -> int:
        reg = self.state.next_reg
        if reg >= _MAX_REGISTERS:
            self._reject_position(
                position,
                f"HIR register limit ({_MAX_REGISTERS}) exceeded",
            )
        self.state.next_reg += 1
        self.state.max_reg = max(self.state.max_reg, self.state.next_reg)
        return reg

    def _const(self, value: object, position: SourcePosition) -> int:
        dst = self._alloc(position)
        self._emit(LoadConst(position, dst, value))
        return dst

    def _require_value(self, node: nodes.ASTNode | None) -> int:
        value = self._lower_expr(node)
        if value is None:
            self._reject(node, "expression without a value")
        return value

    def _new_label(self, prefix: str) -> str:
        self.state.label_counter += 1
        return f"{prefix}{self.state.label_counter}"

    def _emit(self, instruction: Instruction) -> None:
        self.state.code.append(instruction)

    @staticmethod
    def _position_of(statements: Iterable[nodes.ASTNode]) -> SourcePosition:
        for stmt in statements:
            return stmt.position
        return module_position(statements)

    def _reject(self, node: nodes.ASTNode | None, detail: str) -> NoReturn:
        position = node.position if node is not None else module_position([])
        self._reject_position(position, f"HIR backend does not support {detail}")

    @staticmethod
    def _reject_position(position: SourcePosition, message: str) -> NoReturn:
        raise UnsupportedSyntax(message + ".", position)


def _is_reserved_method_name(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _simple_signature(names: tuple[str, ...]) -> SignatureSpec:
    return SignatureSpec(
        tuple(
            ParamSpec(name=name, kind=ParamKind.POS_ONLY, slot=index)
            for index, name in enumerate(names)
        )
    )


def _pattern_bindings(pattern: nodes.Pattern) -> tuple[str, ...]:
    if isinstance(pattern, nodes.NamePattern):
        return (pattern.name,)
    if isinstance(pattern, nodes.ConstructorPattern):
        return tuple(name for arg in pattern.args for name in _pattern_bindings(arg))
    return ()


def _pattern_descriptor(pattern: nodes.Pattern) -> Pattern:
    if isinstance(pattern, nodes.WildcardPattern):
        return Pattern("wildcard")
    if isinstance(pattern, nodes.NamePattern):
        return Pattern("name", pattern.name)
    if isinstance(pattern, nodes.ConstructorPattern):
        return Pattern(
            "constructor",
            pattern.name,
            tuple(_pattern_descriptor(arg) for arg in pattern.args),
        )
    return Pattern("wildcard")


def _derive_import_binding(module_path: str) -> str | None:
    name = PurePosixPath(module_path.replace("\\", "/")).name
    if name.lower().endswith(".ort"):
        name = name[: -len(".ort")]
    return name if name.isidentifier() else None


def module_position(statements: Iterable[nodes.ASTNode]) -> SourcePosition:
    for stmt in statements:
        return stmt.position
    return SourcePosition.from_location(1, 0, "<hir>")


def constants_source(statements: Iterable[nodes.ASTNode]) -> SourcePosition:
    return module_position(statements)


def lower_module(module: nodes.ModuleNode) -> HirModule:
    return HirLowerer().lower(module)
