#! /usr/bin/env python

"""Evaluated function-call arguments and binding errors."""

import dataclasses
from typing import TYPE_CHECKING

from ..ast.nodes.argument import ArgumentKind
from .call_protocol import ArgumentBindingError

__all__ = ["ArgumentBindingError", "EvaluatedArgument", "normalize_args"]

if TYPE_CHECKING:
    from .objects import OortObject


@dataclasses.dataclass
class EvaluatedArgument:
    """One already-evaluated call argument."""

    value: "OortObject"
    keyword: str | None = None
    kind: ArgumentKind = ArgumentKind.DEFAULT


def normalize_args(args) -> list[EvaluatedArgument]:
    """Accept either raw Oort values (operators, internal calls) or evaluated args."""
    normalized = []
    for arg in args:
        if isinstance(arg, EvaluatedArgument):
            normalized.append(arg)
        else:
            normalized.append(EvaluatedArgument(arg))
    return normalized
