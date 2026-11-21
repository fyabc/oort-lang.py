#! /usr/bin/env python

"""Backend-neutral call signature and argument-binding model.

The tree-walking interpreter and the bytecode VM share this module so their
binding rules and diagnostics cannot drift. Default values are deliberately
not evaluated here: the caller resolves them in declaration order after the
structural plan is known.
"""

from __future__ import annotations

import dataclasses
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .objects import OortObject


class ArgumentBindingError(Exception):
    """Raised when evaluated arguments do not fit a signature."""


class ParamKind(Enum):
    POS_ONLY = auto()
    POS_OR_KW = auto()
    VAR_POS = auto()
    KW_ONLY = auto()
    VAR_KW = auto()
    BLOCK = auto()


class ArgKind(Enum):
    POSITIONAL = auto()
    KEYWORD = auto()
    BLOCK = auto()


@dataclasses.dataclass(frozen=True, slots=True)
class ParamSpec:
    """One parameter in a backend-neutral signature."""

    name: str
    kind: ParamKind
    slot: int = 0
    has_default: bool = False
    default_index: int | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class SignatureSpec:
    """Classified parameters in declaration order."""

    params: tuple[ParamSpec, ...]
    has_this: bool = False

    @property
    def positional_only(self) -> list[ParamSpec]:
        return [param for param in self.params if param.kind is ParamKind.POS_ONLY]

    @property
    def positional_or_keyword(self) -> list[ParamSpec]:
        return [param for param in self.params if param.kind is ParamKind.POS_OR_KW]

    @property
    def var_positional(self) -> ParamSpec | None:
        return next(
            (param for param in self.params if param.kind is ParamKind.VAR_POS),
            None,
        )

    @property
    def keyword_only(self) -> list[ParamSpec]:
        return [param for param in self.params if param.kind is ParamKind.KW_ONLY]

    @property
    def var_keyword(self) -> ParamSpec | None:
        return next(
            (param for param in self.params if param.kind is ParamKind.VAR_KW),
            None,
        )

    @property
    def block(self) -> ParamSpec | None:
        return next(
            (param for param in self.params if param.kind is ParamKind.BLOCK),
            None,
        )

    @property
    def positional_params(self) -> list[ParamSpec]:
        return [*self.positional_only, *self.positional_or_keyword]

    @property
    def ordered_params(self) -> list[ParamSpec]:
        result = [*self.positional_only, *self.positional_or_keyword]
        if self.var_positional is not None:
            result.append(self.var_positional)
        result.extend(self.keyword_only)
        if self.var_keyword is not None:
            result.append(self.var_keyword)
        if self.block is not None:
            result.append(self.block)
        return result

    def keyword_target(self, name: str) -> ParamSpec | None:
        for param in (*self.positional_or_keyword, *self.keyword_only):
            if param.name == name:
                return param
        if self.block is not None and self.block.name == name:
            return self.block
        return None


@dataclasses.dataclass(frozen=True, slots=True)
class EvaluatedArg:
    """One already-evaluated call argument."""

    value: OortObject
    kind: ArgKind = ArgKind.POSITIONAL
    keyword: str | None = None


@dataclasses.dataclass(slots=True)
class BindPlan:
    """Structural result before missing defaults are evaluated."""

    provided: dict[str, OortObject]
    extra_pos: list[OortObject]
    extra_kw: dict[str, OortObject]
    block: OortObject | None
    missing_defaults: list[ParamSpec]


def bind_arguments(
    signature: SignatureSpec,
    args: list[EvaluatedArg],
    name: str,
) -> BindPlan:
    """Classify evaluated arguments; evaluate no default expressions."""
    provided: dict[str, OortObject] = {}
    extra_pos: list[OortObject] = []
    extra_kw: dict[str, OortObject] = {}
    block: OortObject | None = None
    seen_keyword = False
    positional_count = 0
    pos_params = signature.positional_params
    pos_index = 0

    for arg in args:
        if arg.kind is ArgKind.BLOCK and signature.block is not None:
            if block is not None:
                raise ArgumentBindingError(
                    f"{name}() got multiple values for argument {signature.block.name!r}"
                )
            block = arg.value
            continue

        if arg.keyword is None:
            block_positional = arg.kind is ArgKind.BLOCK
            if seen_keyword and not block_positional:
                raise ArgumentBindingError(
                    f"{name}(): positional argument follows keyword argument"
                )
            positional_count += 1
            if block_positional:
                while pos_index < len(pos_params) and pos_params[pos_index].name in provided:
                    pos_index += 1
            if pos_index < len(pos_params):
                provided[pos_params[pos_index].name] = arg.value
                pos_index += 1
            elif signature.var_positional is not None:
                extra_pos.append(arg.value)
            else:
                raise ArgumentBindingError(
                    f"{name}() takes {len(pos_params)} positional arguments "
                    f"but {positional_count} were given"
                )
            continue

        seen_keyword = True
        if arg.keyword in extra_kw:
            raise ArgumentBindingError(f"{name}() got multiple values for argument {arg.keyword!r}")

        if arg.keyword in {param.name for param in signature.positional_only}:
            if signature.var_keyword is not None:
                extra_kw[arg.keyword] = arg.value
                continue
            raise ArgumentBindingError(f"{name}() argument {arg.keyword!r} is positional-only")

        param = signature.keyword_target(arg.keyword)
        if param is None:
            if signature.var_keyword is not None:
                extra_kw[arg.keyword] = arg.value
                continue
            raise ArgumentBindingError(
                f"{name}() got an unexpected keyword argument {arg.keyword!r}"
            )
        if arg.keyword in provided:
            raise ArgumentBindingError(f"{name}() got multiple values for argument {arg.keyword!r}")
        provided[param.name] = arg.value

    missing = [
        param.name
        for param in signature.ordered_params
        if param.kind in (ParamKind.POS_ONLY, ParamKind.POS_OR_KW, ParamKind.KW_ONLY)
        and param.name not in provided
        and not param.has_default
    ]
    if missing:
        if len(missing) == 1:
            raise ArgumentBindingError(f"{name}() missing required argument {missing[0]!r}")
        joined = ", ".join(repr(item) for item in missing)
        raise ArgumentBindingError(f"{name}() missing required arguments: {joined}")

    block_param = signature.block
    if block_param is not None and block_param.name in provided and block is not None:
        raise ArgumentBindingError(
            f"{name}() got multiple values for argument {block_param.name!r}"
        )

    missing_defaults = [
        param
        for param in signature.ordered_params
        if param.kind in (ParamKind.POS_ONLY, ParamKind.POS_OR_KW, ParamKind.KW_ONLY)
        and param.name not in provided
        and param.has_default
    ]
    return BindPlan(
        provided=provided,
        extra_pos=extra_pos,
        extra_kw=extra_kw,
        block=block,
        missing_defaults=missing_defaults,
    )


__all__ = [
    "ArgKind",
    "ArgumentBindingError",
    "BindPlan",
    "EvaluatedArg",
    "ParamKind",
    "ParamSpec",
    "SignatureSpec",
    "bind_arguments",
]
