#! /usr/bin/env python

"""Lower the checked dynamic AST into the shared low-level HIR.

This first slice covers arithmetic, locals, globals, branches, loops, calls and
top-level functions. Anything else is rejected explicitly (OP 0004: never rely
on a visitor's default traversal).
"""

import dataclasses
from collections.abc import Iterable
from typing import NoReturn

from ..ast import nodes
from ..diagnostics.syntax_errors import UnsupportedSyntax
from ..source.source_position import SourcePosition
from .nodes import (
    BinOp,
    Call,
    DefineFunction,
    HirFunction,
    HirModule,
    Instruction,
    IteratorNext,
    Jump,
    JumpIfFalse,
    JumpIfTrue,
    Label,
    LoadConst,
    LoadGlobal,
    LoadLocal,
    Move,
    OpenIterator,
    Return,
    StoreGlobal,
    StoreLocal,
    UnOp,
    validate_module,
)

_MAX_REGISTERS = 256


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


class HirLowerer:
    def __init__(self):
        self.module: nodes.ModuleNode | None = None
        self.functions: list[HirFunction] = []
        self._states: list[_FunctionState] = []
        self._global_mutability: dict[str, bool] = {}

    @property
    def state(self) -> _FunctionState:
        return self._states[-1]

    def lower(self, module: nodes.ModuleNode) -> HirModule:
        self.module = module
        statements = list(module.body.statements)
        function_defs: dict[int, int] = {}
        for stmt in statements:
            if isinstance(stmt, nodes.FunctionDef):
                if stmt.is_lambda:
                    self._reject(stmt, "lambda definitions")
                self._validate_top_level_function(stmt)
                function_defs[id(stmt)] = len(function_defs)

        main = self._lower_main(statements, function_defs)
        functions = tuple(
            self._lower_function(stmt, function_defs[id(stmt)])
            for stmt in statements
            if isinstance(stmt, nodes.FunctionDef)
        )
        result = HirModule(main=main, functions=functions)
        validate_module(result)
        return result

    # ------------------------------------------------------------------
    # Functions and main
    # ------------------------------------------------------------------

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
        self, statements: list[nodes.ASTNode], function_defs: dict[int, int]
    ) -> HirFunction:
        state = _FunctionState(name="<main>", code=[], scopes=[{}], is_main=True)
        self._states.append(state)
        try:
            last: int | None = None
            for stmt in statements:
                if isinstance(stmt, nodes.FunctionDef):
                    self._validate_top_level_function(stmt)
                    name = stmt.name
                    index = function_defs[id(stmt)]
                    self._emit(DefineFunction(stmt.position, name, index))
                    self._global_mutability[name] = False
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
        state = _FunctionState(name=node.name, code=[], scopes=[{}])
        self._states.append(state)
        try:
            params: list[str] = []
            for param in node.params:
                if param.default_value is not None or param.kind not in (
                    nodes.ParameterKind.DEFAULT,
                    nodes.ParameterKind.POS_ONLY,
                ):
                    self._reject(
                        param,
                        "default, keyword-only, variadic or block parameters",
                    )
                slot = self._declare_local(param.name, mutable=False, position=param.position)
                params.append(param.name)
                if slot != len(params) - 1:
                    self._reject(param, "non-contiguous parameter slots")

            last: int | None = None
            for stmt in node.body.statements:
                last = self._lower_stmt(stmt)
            if last is None:
                last = self._const(None, node.position)
            self._emit(Return(node.position, last))
            return HirFunction(
                name=node.name,
                params=tuple(params),
                local_count=state.max_reg,
                code=tuple(state.code),
                position=node.position,
            )
        finally:
            self._states.pop()

    # ------------------------------------------------------------------
    # Statements and expressions
    # ------------------------------------------------------------------

    def _lower_stmt(self, node: nodes.ASTNode) -> int | None:
        if isinstance(node, nodes.VarDecl):
            return self._lower_var_decl(node)
        if isinstance(node, nodes.Assignment):
            return self._lower_assignment(node)
        if isinstance(node, nodes.ReturnExpr):
            if self.state.is_main:
                self._reject(node, "top-level return")
            value = self._lower_expr(node.value) if node.value is not None else None
            if value is None:
                value = self._const(None, node.position)
            self._emit(Return(node.position, value))
            return None
        if isinstance(node, (nodes.ImportStmt, nodes.ImportFromStmt)):
            self._reject(node, "imports")
        if isinstance(node, (nodes.ClassDef, nodes.EnumDef, nodes.MatchExpr)):
            self._reject(node, type(node).__name__)
        if isinstance(node, (nodes.BreakExpr, nodes.ContinueExpr)):
            self._reject(node, "break/continue")
        if isinstance(node, nodes.FunctionDef):
            self._reject(node, "nested function definitions")
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
            self._reject(node, "augmented assignment")
        if not isinstance(node.lhs, nodes.Name):
            self._reject(node, "attribute/subscript assignment")
        value = self._lower_expr(node.rhs)
        if value is None:
            value = self._const(None, node.position)
        binding = node.lhs.binding
        if binding is None or binding.is_global:
            if not self._global_mutability.get(node.lhs.id, True):
                self._reject(node.lhs, "assignment to an immutable global")
            self._emit(StoreGlobal(node.lhs.position, node.lhs.id, value))
            return None
        name = self._find_local(node.lhs.id)
        if name is None:
            self._reject(node.lhs, "closures over outer function locals")
        if not name.mutable:
            self._reject(node.lhs, "assignment to an immutable local")
        self._emit(StoreLocal(node.lhs.position, name.slot, value))
        return None

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
        self._reject(node, type(node).__name__)

    def _lower_name(self, node: nodes.Name) -> int:
        binding = node.binding
        if binding is None or binding.is_global:
            dst = self._alloc(node.position)
            self._emit(LoadGlobal(node.position, dst, node.id))
            return dst
        local = self._find_local(node.id)
        if local is None:
            self._reject(node, "closures over outer function locals")
        dst = self._alloc(node.position)
        self._emit(LoadLocal(node.position, dst, local.slot))
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
        self._emit(Label(node.position, start))
        condition = self._require_value(node.condition)
        self._emit(JumpIfFalse(node.position, condition, end))
        self._lower_block(node.body)
        self._emit(Jump(node.position, start))
        self._emit(Label(node.position, end))
        return result

    def _lower_for(self, node: nodes.ForExpr) -> int:
        if len(node.vars) != 1:
            self._reject(node, "multiple loop variables")
        result = self._const(None, node.position)
        iterable = self._require_value(node.iterator)
        iterator = self._alloc(node.position)
        self._emit(OpenIterator(node.position, iterator, iterable))
        start = self._new_label("for")
        end = self._new_label("endfor")
        self._emit(Label(node.position, start))
        value = self._alloc(node.position)
        self._emit(IteratorNext(node.position, value, iterator, end))
        loop_var = node.vars[0]
        self._push_scope()
        try:
            slot = self._declare_local(
                loop_var.name,
                mutable=False,
                position=loop_var.position,
            )
            self._emit(StoreLocal(loop_var.position, slot, value))
            self._lower_block(node.body)
        finally:
            self._pop_scope()
        self._emit(Jump(node.position, start))
        self._emit(Label(node.position, end))
        return result

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
        if not isinstance(node.func, nodes.Name):
            self._reject(node, "calls through function values/attributes")
        args: list[int] = []
        for arg in node.args:
            if arg.keyword is not None or arg.kind != nodes.ArgumentKind.DEFAULT:
                self._reject(arg, "keyword, variadic or block arguments")
            args.append(self._require_value(arg.value))
        callee = self._alloc(node.position)
        self._emit(LoadGlobal(node.func.position, callee, node.func.id))
        dst = self._alloc(node.position)
        self._emit(Call(node.position, dst, callee, tuple(args)))
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
        return slot

    def _find_local(self, name: str) -> _ScopeName | None:
        for scope in reversed(self.state.scopes):
            found = scope.get(name)
            if found is not None:
                return found
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


def module_position(statements: Iterable[nodes.ASTNode]) -> SourcePosition:
    for stmt in statements:
        return stmt.position
    return SourcePosition.from_location(1, 0, "<hir>")


def constants_source(statements: Iterable[nodes.ASTNode]) -> SourcePosition:
    return module_position(statements)


def lower_module(module: nodes.ModuleNode) -> HirModule:
    return HirLowerer().lower(module)
