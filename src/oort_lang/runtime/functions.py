#! /usr/bin/env python

"""Callable Oort objects."""

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from .context import get_runtime
from .control_flow_exceptions import OortReturn
from .native import NativeContext, NativeMode
from .objects import (
    OortBool,
    OortInstance,
    OortNativeMixin,
    OortNull,
    OortObject,
    OortTuple,
)
from .signature import build_call_env

if TYPE_CHECKING:
    from ..ast import nodes
    from .environment import Environment
    from .type_system import OortType


class OortCallableMixin:
    """Callable objects."""

    @classmethod
    def get_type_object(cls) -> "OortType":
        return get_runtime().types.for_class(cls)

    @property
    def arity(self) -> int:
        """Get arity."""
        raise NotImplementedError

    def __call__(self, interpreter, args):
        raise NotImplementedError


class OortVMInvokable(OortCallableMixin):
    """Callable owned by a bytecode VM, invokable from native helpers."""

    def invoke(self, args, position=None):
        raise NotImplementedError

    def __call__(self, interpreter, args, position=None):
        return self.invoke(args, position)


class OortFunctionMixin(OortCallableMixin):
    def __init__(self, name: str = "<lambda>"):
        # Cooperative init: the next class in the concrete MRO is an OortObject.
        super().__init__(type_=self.get_type_object())  # type: ignore[call-arg]
        self.name = name


class OortNativeFunction(OortFunctionMixin, OortNativeMixin, OortObject):
    """Oort native function object."""

    def __init__(
        self,
        value: Callable,
        name: str = "<lambda>",
        *,
        mode: NativeMode = NativeMode.HOST,
    ):
        super().__init__(name=name)
        self.value = value
        self.mode = mode

    def __repr__(self):
        return f"<Built-in function {self.name}>"

    def __call__(self, interpreter, args, position=None):
        host = interpreter.runtime.host
        if self.mode is NativeMode.HOST:
            result = self.value(*(host.to_host(arg) for arg in args))
        elif self.mode is NativeMode.VALUE:
            result = self.value(*args)
        else:
            result = self.value(NativeContext(interpreter, position), *args)
        return host.from_host(result)


class OortIterator(OortNativeFunction):
    """Native callable iterator over a snapshot of Oort values."""

    def __init__(self, values: Iterable[OortObject], name: str = "<iterator>"):
        self._values = list(values)
        self._index = 0
        super().__init__(self._next_tuple, name=name, mode=NativeMode.VALUE)

    def __repr__(self):
        return f"<Iterator object at {hex(id(self))}>"

    def next_value(self) -> tuple[OortObject | None, bool]:
        """Return the next value and whether it is valid."""
        if self._index >= len(self._values):
            return None, False
        value = self._values[self._index]
        self._index += 1
        return value, True

    def take_remaining(self) -> list[OortObject]:
        """Consume and return a copy of the remaining values (used by eager helpers)."""
        remaining = self._values[self._index :]
        self._index = len(self._values)
        return remaining

    def _next_tuple(self) -> OortTuple:
        value, valid = self.next_value()
        if not valid:
            return OortTuple((OortNull.get_null_value(), OortBool.get_false_value()))
        assert value is not None
        return OortTuple((value, OortBool.get_true_value()))


class OortFunction(OortFunctionMixin, OortInstance):
    """Oort function object."""

    def __init__(self, node: "nodes.FunctionDef", closure: "Environment"):
        super().__init__(name=node.name)
        self.node = node
        self.closure = closure

    def __repr__(self):
        return f"<Function {self.name} at {hex(id(self))}>"

    @property
    def arity(self) -> int:
        return self.node.param_count

    def __call__(self, interpreter, args):
        call_env = build_call_env(self.node, interpreter, args, self.closure, self.name)
        try:
            result = interpreter.run_block(self.node.body, call_env)
        except OortReturn as e:
            result = e.value
        return result


class OortMethodMixin(OortCallableMixin):
    def __init__(self, this: OortObject, name: str = "<lambda>"):
        # Cooperative init: the next class in the concrete MRO is an OortObject.
        super().__init__(type_=self.get_type_object())  # type: ignore[call-arg]
        self.this = this
        self.name = name


class OortNativeMethod(OortMethodMixin, OortNativeMixin, OortObject):
    """Oort native bound method object."""

    def __init__(
        self,
        this: OortObject,
        value: Callable,
        name: str = "<lambda>",
        *,
        mode: NativeMode = NativeMode.HOST,
    ):
        super().__init__(this, name)
        self.value = value
        self.mode = mode

    def __repr__(self):
        return f"<Built-in bound method {self.this.type.name}.{self.name} of {self.this}>"

    def __call__(self, interpreter, args, position=None):
        host = interpreter.runtime.host
        if self.mode is NativeMode.HOST:
            result = self.value(host.to_host(self.this), *(host.to_host(arg) for arg in args))
        elif self.mode is NativeMode.VALUE:
            result = self.value(self.this, *args)
        else:
            result = self.value(NativeContext(interpreter, position), self.this, *args)
        return host.from_host(result)

    @classmethod
    def from_native_func(cls, this: OortObject, func: OortNativeFunction):
        return cls(this, value=func.value, name=func.name, mode=func.mode)


class OortMethod(OortMethodMixin, OortInstance):
    """Oort bound method object."""

    def __init__(
        self,
        this: OortObject,
        node: "nodes.FunctionDef",
        closure: "Environment",
        defining_type: "OortType | None" = None,
    ):
        super().__init__(this, name=node.name)
        self.node = node
        self.closure = closure
        self.defining_type = defining_type

    def __repr__(self):
        return f"<Bound method {self.this.type.name}.{self.name} of {self.this} at {hex(id(self))}>"

    @property
    def is_initializer(self) -> bool:
        return self.name == "__init__"

    @property
    def arity(self) -> int:
        return self.node.param_count

    def __call__(self, interpreter, args):
        call_env = build_call_env(self.node, interpreter, args, self.closure, self.name)

        # `this` is bound after defaults; default expressions cannot depend on
        # the instance (OP 0011 D7).
        call_env.define("this", self.this)

        prev_method = getattr(interpreter, "_current_method", None)
        interpreter._current_method = self
        try:
            result = interpreter.run_block(self.node.body, call_env)
        except OortReturn as e:
            result = e.value
        finally:
            interpreter._current_method = prev_method
        if self.is_initializer:
            result = self.this
        return result
