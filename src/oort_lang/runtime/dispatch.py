#! /usr/bin/env python

"""Attribute and operator lookup helpers."""

from typing import TYPE_CHECKING

from .functions import (
    OortFunction,
    OortMethod,
    OortNativeFunction,
    OortNativeMethod,
    OortVMInvokable,
)
from .type_system import OortType

if TYPE_CHECKING:
    from .objects import OortObject


def _get_operator_from_cls(
    symbol: str, operand_count: int, start_type: "OortType", receiver: "OortObject"
) -> "OortObject | None":
    """Look up an operator method in the class MRO and bind it to `receiver`.

    Operator methods live in `OortType.operators`, keyed by (symbol, operand
    count), so unary and binary forms of the same symbol (e.g. `-x` and
    `x - y`) can coexist.
    """
    key = (symbol, operand_count)
    for mro_type in start_type.mro():
        value = mro_type.operators.get(key)
        if value is not None:
            if isinstance(value, OortFunction):
                return OortMethod(
                    this=receiver, node=value.node, closure=value.closure, defining_type=mro_type
                )
            elif isinstance(value, OortNativeFunction):
                return OortNativeMethod.from_native_func(this=receiver, func=value)
            elif isinstance(value, OortVMInvokable):
                return value.bind(receiver)
            else:
                return value
    return None


def _bind_extension_method(
    receiver: "OortObject", func: "OortObject", defining_type: "OortType"
) -> "OortObject":
    """Bind an extension function to a receiver as a method.

    `defining_type` is the type the extension matched on (not necessarily the
    receiver's dynamic type); `super` resumes after that type.
    """
    if isinstance(func, OortVMInvokable):
        return func.bind(receiver)
    if isinstance(func, OortFunction):
        return OortMethod(
            this=receiver,
            node=func.node,
            closure=func.closure,
            defining_type=defining_type,
        )
    raise TypeError(f"Extension {func!r} is not callable")


def _get_from_cls(name: str, start_type: "OortType", receiver: "OortObject") -> "OortObject | None":
    """Search method from class MRO and metaclass MRO."""

    # Search from class MRO.
    for mro_type in start_type.mro():
        value = mro_type.fields.get(name, None)
        if value is not None:
            # Wrap into methods.
            if isinstance(value, OortFunction):
                return OortMethod(
                    this=receiver, node=value.node, closure=value.closure, defining_type=mro_type
                )
            elif isinstance(value, OortNativeFunction):
                return OortNativeMethod.from_native_func(this=receiver, func=value)
            elif isinstance(value, OortVMInvokable):
                return value.bind(receiver)
            else:
                return value

    if start_type is not OortType.get_type_object():
        # `Type.type is Type`, so skip resolution.
        # Search from super metaclasses (bind with receiver.type).
        # TODO: Add complier option to disallow call class methods from instance.
        meta_mro = start_type.type.mro()
        for mro_type in meta_mro:
            value = mro_type.fields.get(name, None)
            if value is not None:
                # Wrap into class methods.
                if isinstance(value, OortFunction):
                    return OortMethod(this=receiver.type, node=value.node, closure=value.closure)
                elif isinstance(value, OortNativeFunction):
                    return OortNativeMethod.from_native_func(this=receiver.type, func=value)
                elif isinstance(value, OortVMInvokable):
                    return value.bind(receiver.type)
                else:
                    return value

    return None


_CALLABLE_CLASS_MEMBERS = (
    OortFunction,
    OortNativeFunction,
    OortMethod,
    OortNativeMethod,
    OortVMInvokable,
)


def find_callable_class_member(name: str, start_type: "OortType") -> "OortObject | None":
    """Find the callable class member that `name` resolves to, if any.

    Lookup follows the instance attribute order used by `OortObject.get`:
    the class MRO first, then the metaclass MRO (class methods). A
    non-callable class member stops the search and is returned as no conflict;
    callers may let an instance field shadow it (OP 0007 leaves the priority
    of non-callable class attributes undefined).
    """
    for mro_type in start_type.mro():
        value = mro_type.fields.get(name)
        if value is not None:
            return value if isinstance(value, _CALLABLE_CLASS_MEMBERS) else None

    metaclass = start_type.type
    if metaclass is not None:
        for mro_type in metaclass.mro():
            value = mro_type.fields.get(name)
            if value is not None:
                return value if isinstance(value, _CALLABLE_CLASS_MEMBERS) else None

    return None
