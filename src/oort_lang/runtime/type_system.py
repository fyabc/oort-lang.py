#! /usr/bin/env python

"""Per-runtime type system and built-in operators."""

import dataclasses
import operator
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from .call_args import ArgumentBindingError
from .context import activate_runtime
from .functions import (
    OortCallableMixin,
    OortFunction,
    OortFunctionMixin,
    OortIterator,
    OortMethod,
    OortMethodMixin,
    OortNativeFunction,
    OortVMInvokable,
)
from .host import HostBridge, PythonHost
from .native import NativeMode

if TYPE_CHECKING:
    from ..ast import nodes
    from ..source.source_position import SourcePosition
    from .environment import Environment

from .objects import (
    OortBool,
    OortDict,
    OortFloat,
    OortInstance,
    OortInt,
    OortList,
    OortModule,
    OortNull,
    OortObject,
    OortSet,
    OortSlice,
    OortString,
    OortSuperProxy,
    OortTuple,
)


@dataclasses.dataclass(slots=True)
class SlotDefinition:
    """One declared instance slot on a static (`oort-core`) class."""

    name: str
    mutable: bool
    initializer: "nodes.ASTNode | None"
    closure: "Environment"
    position: "SourcePosition"


class OortType(OortInstance, OortCallableMixin):
    """Oort type objects."""

    def __init__(
        self, name: str, fields: dict | None = None, bases: list["OortType"] | None = None
    ):
        super().__init__(type_=None)  # type: ignore[arg-type]  # Lazy init.

        self.name = name
        if fields:
            self.fields.update(fields)
        self.bases: list[OortType] = bases or []
        self._mro_cache: list[OortType] | None = None
        self._has_class_method: bool = False
        # Variant name -> payload arity for enum/ADT types, else None.
        self.adt_variants: dict[str, int] | None = None
        # Operator methods, keyed by (symbol, operand count).
        self.operators: dict[tuple[str, int], OortObject] = {}
        # Declared slots for static classes; empty for open field-bag classes.
        self.slots: dict[str, SlotDefinition] = {}
        self.static_layout = False

    def __repr__(self):
        return f"<Type {self.name!r}>"

    def get(self, name: str) -> "OortObject | None":
        """Look up class attributes.

        Class objects need two lookup domains: the class MRO (ordinary
        attributes and methods, returned unbound) and the metaclass MRO
        (class methods, bound to the class). `OortObject.get` only knows
        about the latter, so handle the class MRO here first.
        """
        for mro_type in self.mro():
            value = mro_type.fields.get(name, None)
            if value is not None:
                return value
        return super().get(name)

    def _find_defining_type(self, name: str) -> "OortType | None":
        """Find the type in the MRO that defines `name`."""
        for mro_type in self.mro():
            if name in mro_type.fields:
                return mro_type
        return None

    @classmethod
    def create_type_object(
        cls,
        name: str,
        fields: dict | None = None,
        bases: list | None = None,
        metaclass: "OortType | None" = None,
    ):
        """Create type object, resolve bases and metaclass."""
        type_obj = cls(name=name, fields=fields, bases=bases)

        # Calculate correct metaclass.
        winner = metaclass or cls.get_type_object()
        for base_type in type_obj.mro()[1:]:
            base_metatype = base_type.type
            if winner.is_subclass_of(base_metatype):
                continue
            if base_metatype.is_subclass_of(winner):
                winner = base_metatype
                continue
            raise TypeError(
                "Metaclass conflict: the metaclass of a derived class must be a (non-strict) "
                "subclass of the metaclasses of all its bases."
            )
        type_obj.type = winner
        return type_obj

    def set_operator(self, symbol: str, operand_count: int, value: OortObject):
        """Register an operator method (`def operator "<sym>"`)."""
        self.operators[(symbol, operand_count)] = value

    def set_class_field(self, name: str, value: OortObject):
        """Set class-level fields, create metaclass if not exist."""
        if not self._has_class_method:
            new_type = OortType(name=f"{self.name}#Meta", fields={name: value}, bases=[self.type])
            new_type.type = self.type
            self.type = new_type
            self._has_class_method = True
        else:
            self.type.set(name, value)

    @property
    def arity(self) -> int:
        init_func = self.get("__init__")
        if init_func is None:
            return 0
        if not isinstance(init_func, OortCallableMixin):
            raise TypeError(f"{self.name}.__init__ is not callable")
        return init_func.arity

    def __call__(self, interpreter, args):
        instance = OortInstance(type_=self)

        # Call initializer.
        init_func = self.get("__init__")
        if init_func is None and args:
            raise ArgumentBindingError(
                f"{self.name}() takes 0 arguments but {len(args)} were given"
            )

        # Slot initializers run in base-to-derived, declaration order, before
        # the constructor body (OP 0007 §6).
        interpreter.initialize_instance_slots(instance, self)
        if init_func is None:
            interpreter.check_instance_slots(instance, self)
            return instance

        if isinstance(init_func, OortVMInvokable):
            interpreter.call_value(init_func.bind(instance), args)
        else:
            assert isinstance(init_func, OortFunction)
            init_method = OortMethod(
                this=instance,
                node=init_func.node,
                closure=init_func.closure,
                defining_type=self._find_defining_type("__init__"),
            )
            init_method(interpreter, args)
        interpreter.check_instance_slots(instance, self)
        return instance

    def find_slot(self, name: str) -> SlotDefinition | None:
        for mro_type in self.mro():
            slot = mro_type.slots.get(name)
            if slot is not None:
                return slot
        return None

    def slot_definitions(self):
        """Yield inherited slots once, base classes first."""
        seen: set[str] = set()
        for mro_type in reversed(self.mro()):
            for slot in mro_type.slots.values():
                if slot.name not in seen:
                    seen.add(slot.name)
                    yield slot

    def mro(self) -> list["OortType"]:
        if not self._mro_cache:
            self._build_mro()
        assert self._mro_cache is not None
        return self._mro_cache

    def _build_mro(self):
        """Build MRO cache, using C3-linear algorithm."""
        if not self.bases:
            self._mro_cache = [self, OortObject.get_type_object()]
            return
        parent_mros = [list(base.mro()) for base in self.bases]
        parent_mros.append(list(self.bases))

        self._mro_cache = [self, *self._c3_merge(parent_mros)]
        if self._mro_cache[-1] != OortObject.get_type_object():
            self._mro_cache.append(OortObject.get_type_object())

    @staticmethod
    def _c3_merge(sequences: list[list["OortType"]]) -> list["OortType"]:
        """C3 merge algorithm."""
        result: list[OortType] = []
        while True:
            sequences = [seq for seq in sequences if seq]
            if not sequences:
                return result

            for seq in sequences:
                candidate = seq[0]
                if not any(candidate in s[1:] for s in sequences):
                    result.append(candidate)
                    for s in sequences:
                        if s and s[0] == candidate:
                            s.pop(0)
                    break
            else:
                raise TypeError(
                    "Cannot create a consistent method resolution order (MRO) for bases."
                )

    def is_subclass_of(self, other: "OortType") -> bool:
        """Check if `self` is subclass of `other`."""
        return other in self.mro()

    @property
    def is_metaclass(self) -> bool:
        return self.get_type_object() in self.mro()


class TypeSystem:
    """Per-runtime built-in type registry."""

    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime
        # Make the registry visible to object constructors used below.
        runtime.types = self
        self.by_class: dict[type, OortType] = {}

        # Bootstrap `Type` and `Object` without resolving their MROs, which
        # would recurse back into the type system.
        t_type = OortType(name="Type")
        t_type.type = t_type
        t_object = OortType(name="Object")
        t_object.type = t_type
        t_type._mro_cache = [t_type, t_object]
        t_object._mro_cache = [t_object]
        self.by_class[OortType] = t_type
        self.by_class[OortObject] = t_object
        self.type_type = t_type
        self.object_type = t_object

        self.function_type = self._add_basic_type("Function", OortFunctionMixin)
        self.method_type = self._add_basic_type("Method", OortMethodMixin)
        self.iterator_type = self._add_basic_type("Iterator", OortIterator)
        self.super_proxy_type = self._add_basic_type("SuperProxy", OortSuperProxy)
        self.module_type = self._add_basic_type("Module", OortModule)
        self.null_type = self._add_basic_type("Null", OortNull)
        self.int_type = self._add_basic_type("Int", OortInt)
        # Bool is deliberately not a subtype of Int. `true + true` and
        # `true == 1` should not silently work just because Python's bool is int.
        self.bool_type = self._add_basic_type("Bool", OortBool)
        self.float_type = self._add_basic_type("Float", OortFloat)
        self.string_type = self._add_basic_type("String", OortString)
        self.list_type = self._add_basic_type("List", OortList)
        self.tuple_type = self._add_basic_type("Tuple", OortTuple)
        self.dict_type = self._add_basic_type("Dict", OortDict)
        self.set_type = self._add_basic_type("Set", OortSet)
        self.slice_type = self._add_basic_type("Slice", OortSlice)

        _setup_native_operators(
            t_object=t_object,
            t_null=self.null_type,
            t_bool=self.bool_type,
            t_int=self.int_type,
            t_float=self.float_type,
            t_string=self.string_type,
            t_list=self.list_type,
            t_tuple=self.tuple_type,
            t_dict=self.dict_type,
            t_set=self.set_type,
        )

    def _add_basic_type(
        self, name: str, cls: type, bases: list["OortType"] | None = None
    ) -> "OortType":
        t_name = OortType(name=name)
        t_name.type = self.type_type
        t_name.bases = bases or [self.object_type]
        t_name._mro_cache = [t_name]
        for base in t_name.bases:
            for base_type in base.mro():
                if base_type not in t_name._mro_cache:
                    t_name._mro_cache.append(base_type)
        self.by_class[cls] = t_name
        return t_name

    def for_class(self, cls: type) -> "OortType":
        """Find the built-in type for a Python storage class."""
        for base in cls.__mro__:
            type_obj = self.by_class.get(base)
            if type_obj is not None:
                return type_obj
        raise KeyError(f"No Oort type registered for {cls.__name__}")


class Runtime:
    """Type system and singleton values owned by one interpreter."""

    def __init__(self):
        self.host: HostBridge = PythonHost()
        with self.activate():
            self.types: TypeSystem = TypeSystem(self)
            self.null: OortNull = OortNull()
            self.true: OortBool = OortBool(True)
            self.false: OortBool = OortBool(False)

    def activate(self) -> AbstractContextManager["Runtime"]:
        """Make this runtime current for object construction and dispatch."""
        return activate_runtime(self)


def _install_operators(
    type_obj: "OortType",
    unary: dict[str, Callable] | None = None,
    binary: dict[str, Callable] | None = None,
    *,
    mode: NativeMode = NativeMode.HOST,
):
    """Install native operator implementations on a built-in type."""
    for symbol, func in (unary or {}).items():
        type_obj.operators[(symbol, 1)] = OortNativeFunction(
            func, name=f"operator {symbol}", mode=mode
        )
    for symbol, func in (binary or {}).items():
        type_obj.operators[(symbol, 2)] = OortNativeFunction(
            func, name=f"operator {symbol}", mode=mode
        )


def _setup_native_operators(
    t_object: "OortType",
    t_null: "OortType",
    t_bool: "OortType",
    t_int: "OortType",
    t_float: "OortType",
    t_string: "OortType",
    t_list: "OortType",
    t_tuple: "OortType",
    t_dict: "OortType",
    t_set: "OortType",
):
    """Define built-in operators as methods, like user-defined ones.

    Native operator functions receive host values (`this.host_value` and the
    operands' `host_value`), because `OortNativeMethod` projects them before
    the call. Results are wrapped again by the host bridge.
    """
    comparisons = {
        "==": operator.eq,
        "<": operator.lt,
        "<=": operator.le,
        ">": operator.gt,
        ">=": operator.ge,
    }
    # `!=` and `!in` are derived from `==` and `in` unless a type overrides
    # them explicitly.

    def _bool_eq(lhs, rhs):
        # `False == 0` in Python; Oort keeps booleans and integers distinct.
        return isinstance(lhs, bool) and isinstance(rhs, bool) and lhs == rhs

    def _numeric_eq(lhs, rhs):
        if isinstance(lhs, bool) or isinstance(rhs, bool):
            return False
        return lhs == rhs

    def _numeric_binop(op):
        def wrapped(lhs, rhs):
            if isinstance(lhs, bool) or isinstance(rhs, bool):
                raise TypeError("Bool values are not numbers")
            return op(lhs, rhs)

        return wrapped

    def _numeric_cmp(op):
        def wrapped(lhs, rhs):
            if isinstance(lhs, bool) or isinstance(rhs, bool):
                raise TypeError("Bool values are not ordered with numbers")
            return op(lhs, rhs)

        return wrapped

    def _sequence_eq(ctx, lhs, rhs):
        return OortBool.get_bool_value(ctx.equal(lhs, rhs))

    def _dict_eq(ctx, lhs, rhs):
        return OortBool.get_bool_value(ctx.equal(lhs, rhs))

    def _sequence_contains(ctx, container, item):
        return OortBool.get_bool_value(ctx.contains(container, item))

    def _set_eq(lhs, rhs):
        # Python sets already use the Oort key protocol (Bool/Int strict,
        # Int/Float distinct, identity for instances).
        return lhs.value == rhs.value

    def _set_contains(container, item):
        return item in container.value

    def _set_op(op):
        def wrapped(lhs, rhs):
            return OortSet(op(lhs.value, rhs.value))

        return wrapped

    def _sequence_concat(lhs, rhs):
        if type(lhs) is not type(rhs):
            raise TypeError("Cannot concatenate a List and a Tuple")
        return type(lhs)(lhs.value + rhs.value)

    def _sequence_repeat(lhs, count):
        if not isinstance(count, OortInt):
            raise TypeError("Sequence repetition requires an Int count")
        return type(lhs)(lhs.value * count.value)

    def _sequence_cmp(ctx, lhs, rhs):
        if type(lhs) is not type(rhs):
            raise TypeError("Cannot order a List and a Tuple")
        for left, right in zip(lhs.value, rhs.value):
            if ctx.equal(left, right):
                continue
            if ctx.truthy(ctx.binary("<", left, right)):
                return -1
            if ctx.truthy(ctx.binary("<", right, left)):
                return 1
            raise TypeError(
                f"Elements of type {left.type.name!r} and {right.type.name!r} are not orderable"
            )
        return (len(lhs.value) > len(rhs.value)) - (len(lhs.value) < len(rhs.value))

    def _sequence_lt(ctx, lhs, rhs):
        return _sequence_cmp(ctx, lhs, rhs) < 0

    def _sequence_le(ctx, lhs, rhs):
        return _sequence_cmp(ctx, lhs, rhs) <= 0

    def _sequence_gt(ctx, lhs, rhs):
        return _sequence_cmp(ctx, lhs, rhs) > 0

    def _sequence_ge(ctx, lhs, rhs):
        return _sequence_cmp(ctx, lhs, rhs) >= 0

    def _set_compare(op):
        def wrapped(lhs, rhs):
            return op(lhs.value, rhs.value)

        return wrapped

    numeric_comparisons = {
        "==": _numeric_eq,
        "<": _numeric_cmp(operator.lt),
        "<=": _numeric_cmp(operator.le),
        ">": _numeric_cmp(operator.gt),
        ">=": _numeric_cmp(operator.ge),
    }

    _install_operators(t_object, binary={"==": operator.eq})
    _install_operators(t_null, binary={"==": operator.eq})
    _install_operators(t_bool, binary={"==": _bool_eq})

    _install_operators(
        t_int,
        unary={"+": operator.pos, "-": operator.neg, "~": operator.inv},
        binary={
            "+": _numeric_binop(operator.add),
            "-": _numeric_binop(operator.sub),
            "*": _numeric_binop(operator.mul),
            "/": _numeric_binop(operator.truediv),
            "//": _numeric_binop(operator.floordiv),
            "%": _numeric_binop(operator.mod),
            "**": _numeric_binop(operator.pow),
            "<<": _numeric_binop(operator.lshift),
            ">>": _numeric_binop(operator.rshift),
            "&": _numeric_binop(operator.and_),
            "|": _numeric_binop(operator.or_),
            "^": _numeric_binop(operator.xor),
            **numeric_comparisons,
        },
    )
    _install_operators(
        t_float,
        unary={"+": operator.pos, "-": operator.neg},
        binary={
            "+": _numeric_binop(operator.add),
            "-": _numeric_binop(operator.sub),
            "*": _numeric_binop(operator.mul),
            "/": _numeric_binop(operator.truediv),
            "//": _numeric_binop(operator.floordiv),
            "%": _numeric_binop(operator.mod),
            "**": _numeric_binop(operator.pow),
            **numeric_comparisons,
        },
    )
    _install_operators(
        t_string,
        binary={
            "+": operator.add,
            "*": operator.mul,
            "%": operator.mod,
            "in": lambda text, part: part in text,
            **comparisons,
        },
    )
    for type_obj in (t_list, t_tuple):
        _install_operators(
            type_obj,
            binary={"+": _sequence_concat, "*": _sequence_repeat},
            mode=NativeMode.VALUE,
        )
        _install_operators(
            type_obj,
            binary={
                "==": _sequence_eq,
                "in": _sequence_contains,
                "<": _sequence_lt,
                "<=": _sequence_le,
                ">": _sequence_gt,
                ">=": _sequence_ge,
            },
            mode=NativeMode.CONTEXT,
        )
    _install_operators(
        t_dict,
        binary={
            # Keys are wrapped OortObjects, so Python's dict lookup is already
            # Bool/Int-strict and stays O(1).
            "in": lambda mapping, key: key in mapping,
        },
        mode=NativeMode.VALUE,
    )
    _install_operators(
        t_dict,
        binary={"==": _dict_eq},
        mode=NativeMode.CONTEXT,
    )
    _install_operators(
        t_set,
        binary={
            "&": _set_op(operator.and_),
            "|": _set_op(operator.or_),
            "^": _set_op(operator.xor),
            "-": _set_op(operator.sub),
            "in": _set_contains,
            "==": _set_eq,
            "<": _set_compare(operator.lt),
            "<=": _set_compare(operator.le),
            ">": _set_compare(operator.gt),
            ">=": _set_compare(operator.ge),
        },
        mode=NativeMode.VALUE,
    )
