#! /usr/bin/env python

"""Function signatures and argument binding."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..ast.nodes.argument import ArgumentKind
from ..ast.nodes.declarations import Parameter, ParameterKind
from .call_args import ArgumentBindingError, normalize_args
from .call_protocol import (
    ArgKind,
    EvaluatedArg,
    ParamKind,
    ParamSpec,
    SignatureSpec,
    bind_arguments,
)

if TYPE_CHECKING:
    from ..ast.nodes.function_def import FunctionDef


_PARAM_KINDS = {
    ParameterKind.POS_ONLY: ParamKind.POS_ONLY,
    ParameterKind.DEFAULT: ParamKind.POS_OR_KW,
    ParameterKind.KW_ONLY: ParamKind.KW_ONLY,
    ParameterKind.VAR_POS: ParamKind.VAR_POS,
    ParameterKind.VAR_KW: ParamKind.VAR_KW,
    ParameterKind.BLOCK: ParamKind.BLOCK,
}

_NAMED_KINDS = (ParamKind.POS_ONLY, ParamKind.POS_OR_KW, ParamKind.KW_ONLY)


class Signature:
    """Classified parameters of a user callable."""

    def __init__(self, params: list[Parameter]):
        self.params = list(params)
        self.spec = SignatureSpec(
            tuple(
                ParamSpec(
                    name=param.name,
                    kind=_PARAM_KINDS[param.kind],
                    slot=index,
                    has_default=param.default_value is not None,
                )
                for index, param in enumerate(self.params)
            )
        )
        self._by_name = {param.name: param for param in self.params}
        self._spec_by_name = {spec.name: spec for spec in self.spec.params}
        self._simple_positional = all(
            param.kind in (ParameterKind.DEFAULT, ParameterKind.POS_ONLY)
            and param.default_value is None
            for param in self.params
        )

    def _params_for(self, specs: list[ParamSpec]) -> list[Parameter]:
        return [self._by_name[spec.name] for spec in specs]

    @property
    def positional_only(self) -> list[Parameter]:
        return self._params_for(self.spec.positional_only)

    @property
    def positional_or_keyword(self) -> list[Parameter]:
        return self._params_for(self.spec.positional_or_keyword)

    @property
    def positional_params(self) -> list[Parameter]:
        return [*self.positional_only, *self.positional_or_keyword]

    @property
    def ordered_params(self) -> list[Parameter]:
        return self._params_for(self.spec.ordered_params)

    def positional_only_names(self) -> set[str]:
        return {param.name for param in self.positional_only}

    def keyword_target(self, name: str) -> Parameter | None:
        target = self.spec.keyword_target(name)
        return None if target is None else self._by_name[target.name]

    def bind(self, interpreter, args, closure, name: str):
        """Bind evaluated arguments and return the call environment."""
        from .environment import Environment
        from .objects import OortDict, OortNull, OortString, OortTuple

        args = normalize_args(args)
        if (
            self._simple_positional
            and len(args) == len(self.params)
            and all(arg.kind == ArgumentKind.DEFAULT and arg.keyword is None for arg in args)
        ):
            env = Environment(outer=closure, name=name)
            for param, arg in zip(self.params, args, strict=True):
                env.define(param.name, arg.value)
            return env

        shared = [
            EvaluatedArg(
                arg.value,
                ArgKind.BLOCK
                if arg.kind == ArgumentKind.BLOCK
                else ArgKind.KEYWORD
                if arg.keyword is not None
                else ArgKind.POSITIONAL,
                arg.keyword,
            )
            for arg in args
        ]
        plan = bind_arguments(self.spec, shared, name)

        env = Environment(outer=closure, name=name)
        for param in self.ordered_params:
            param_spec = self._spec_by_name[param.name]
            if param_spec.kind in _NAMED_KINDS:
                if param.name in plan.provided:
                    value = plan.provided[param.name]
                else:
                    assert param.default_value is not None
                    previous_env = interpreter.env
                    try:
                        interpreter.env = env
                        value = param.default_value.accept(interpreter)
                    finally:
                        interpreter.env = previous_env
            elif param_spec.kind is ParamKind.VAR_POS:
                value = OortTuple(tuple(plan.extra_pos))
            elif param_spec.kind is ParamKind.VAR_KW:
                value = OortDict({OortString(key): item for key, item in plan.extra_kw.items()})
            elif param_spec.kind is ParamKind.BLOCK:
                if param.name in plan.provided:
                    value = plan.provided[param.name]
                else:
                    value = plan.block if plan.block is not None else OortNull.get_null_value()
            else:
                raise AssertionError(f"Unexpected parameter kind {param_spec.kind}")

            env.define(param.name, value)

        return env


def get_signature(node: FunctionDef) -> Signature:
    """Build and cache the signature of a function/lambda node."""
    signature = getattr(node, "_signature", None)
    if signature is None:
        signature = Signature(node.params)
        node._signature = signature
    return signature


def build_call_env(node: FunctionDef, interpreter, args, closure, name: str):
    """Build the call environment for a function, lambda or method."""
    from .environment import Environment

    args = normalize_args(args)

    if node.anonymous_count:
        if any(arg.keyword is not None for arg in args):
            raise ArgumentBindingError(f"{name}() does not accept keyword arguments")
        values = [arg.value for arg in args]
        if len(values) != node.anonymous_count:
            raise ArgumentBindingError(
                f"{name}() takes {node.anonymous_count} arguments but {len(values)} were given"
            )
        env = Environment(outer=closure, name=name)
        for index, value in enumerate(values):
            env.define(f"${index}", value)
        return env

    return get_signature(node).bind(interpreter, args, closure, name)
