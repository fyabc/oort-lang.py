#! /usr/bin/env python

from collections.abc import Iterable
from typing import TYPE_CHECKING

from antlr4 import ParserRuleContext

from ...source.source_position import SourcePosition
from ..ast_visitor import ASTVisitor
from .base import ASTNode
from .declarations import Parameter, TypeParameter
from .expressions import BlockExpr, StmtExpr

if TYPE_CHECKING:
    from ...runtime.signature import Signature

_OPERATOR_NAME_PREFIX = "operator "


class FunctionDef(StmtExpr):
    def __init__(
        self,
        context: ParserRuleContext,
        names: Iterable[str],
        type_params: Iterable[TypeParameter],
        params: Iterable[Parameter],
        ret_type: ASTNode | None,
        body: BlockExpr,
        name_position: SourcePosition,
        anonymous_count: int = 0,
        has_explicit_param_list: bool = False,
    ):
        super().__init__(context)
        self.names = [name for name in names]
        self.type_params = [type_param for type_param in type_params]
        self.params = [param for param in params]
        self.ret_type = ret_type
        self.body = body
        self.name_position = name_position
        # Lambdas may omit the parameter list and use `$0`, `$1`, ... instead.
        self.anonymous_count = anonymous_count
        self.has_explicit_param_list = has_explicit_param_list
        # Cached by `signature.get_signature`.
        self._signature: Signature | None = None

    def named_children(self) -> Iterable[tuple[str, ASTNode | None]]:
        for index, type_param in enumerate(self.type_params):
            yield f"type_param {index}", type_param
        for index, param in enumerate(self.params):
            yield f"param {index}", param
        yield "ret_type", self.ret_type
        yield "body", self.body

    def _accept(self, visitor: ASTVisitor):
        return visitor.visit_function_def(self)

    def str_attrs(self) -> str | None:
        return f"name={self.full_name!r}"

    @property
    def name(self) -> str:
        if not self.names:
            return "<lambda>"
        return self.names[-1]

    @property
    def full_name(self) -> str:
        if not self.names:
            return "<lambda>"
        return ".".join(self.names)

    @property
    def is_lambda(self) -> bool:
        return not self.names

    @property
    def has_class_prefix(self) -> bool:
        return bool(self.names) and self.names[0] == "class"

    @property
    def is_class_method(self) -> bool:
        return len(self.names) == 2 and self.names[0] == "class"

    @property
    def is_extension(self) -> bool:
        """True for `def C.f` and `def C.operator "<sym>"`."""
        return len(self.names) == 2 and self.names[0] != "class"

    @property
    def extension_receiver(self) -> str | None:
        """Receiver name of an extension method, else None."""
        return self.names[0] if self.is_extension else None

    @property
    def operator_symbol(self) -> str | None:
        """Operator symbol for `def operator "<sym>"`, else None."""
        if not self.names:
            return None
        name = self.names[-1]
        if not name.startswith(_OPERATOR_NAME_PREFIX):
            return None
        symbol = name[len(_OPERATOR_NAME_PREFIX) :]
        return symbol or None

    @property
    def is_operator(self) -> bool:
        return self.operator_symbol is not None

    @property
    def operator_operand_count(self) -> int | None:
        """Number of operands (including the receiver) for an operator method."""
        if not self.is_operator:
            return None
        return len(self.params) + 1
