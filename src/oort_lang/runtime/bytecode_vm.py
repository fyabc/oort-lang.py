#! /usr/bin/env python

"""Register bytecode VM for the dynamic HIR/bytecode subset.

The VM reuses the existing runtime value types, builtins environment, operator
dispatch and iterator protocol. It deliberately rejects unsupported bytecode
instead of silently skipping it.
"""

from __future__ import annotations

from typing import Any

from ..bytecode import (
    BytecodeModule,
    CallSpec,
    ClassSpec,
    Decoded,
    EnumSpec,
    ExtensionSpec,
    ImportSpec,
    MatchSpec,
    PatternSpec,
    Proto,
    decode,
)
from ..bytecode.opcodes import (
    BINARY_OPCODES,
    UNARY_OPCODES,
    Op,
)
from ..diagnostics.runtime_errors import (
    OortImportError,
    OortNameError,
    OortRuntimeError,
    OortTypeError,
)
from ..source.source_position import SourcePosition
from .call_protocol import (
    ArgKind,
    ArgumentBindingError,
    EvaluatedArg,
    ParamKind,
    bind_arguments,
)
from .environment import DefineResult, Environment
from .functions import (
    OortNativeFunction,
    OortNativeMethod,
    OortVMInvokable,
)
from .native import NativeMode
from .objects import (
    OortADT,
    OortBool,
    OortDict,
    OortFloat,
    OortInstance,
    OortInt,
    OortList,
    OortObject,
    OortSet,
    OortSlice,
    OortString,
    OortSuperProxy,
    OortTuple,
)
from .type_system import OortType, SlotDefinition

_BINARY_SYMBOLS = {opcode: symbol for symbol, opcode in BINARY_OPCODES.items()}
_UNARY_SYMBOLS = {opcode: symbol for symbol, opcode in UNARY_OPCODES.items()}


class _Cell:
    """Mutable local binding shared by a frame and its closures."""

    __slots__ = ("value",)

    def __init__(self, value: OortObject):
        self.value = value


class VMFrame:
    """Activation record captured by closures (frame-capture, not upvalues)."""

    __slots__ = ("ext_env", "parent", "registers")

    def __init__(
        self,
        registers: list[Any],
        parent: VMFrame | None = None,
        ext_env: Environment | None = None,
    ):
        self.registers = registers
        self.parent = parent
        assert ext_env is not None
        self.ext_env: Environment = ext_env


class OortVMClosure(OortVMInvokable, OortObject):
    """A bytecode function, its module globals and optional captured frame."""

    def __init__(
        self,
        vm: BytecodeVM,
        module: BytecodeModule,
        proto: Proto,
        frame: VMFrame | None = None,
        env: Environment | None = None,
        definition_ext_env: Environment | None = None,
    ):
        super().__init__(vm.interpreter.runtime.types.function_type)
        self.vm = vm
        self.module = module
        self.proto = proto
        self.frame = frame
        self.env = env if env is not None else vm.globals
        self.definition_ext_env = definition_ext_env if definition_ext_env is not None else self.env
        self.defining_type: OortType | None = None
        self._default_closures: dict[int, OortVMClosure] = {}

    @property
    def is_initializer(self) -> bool:
        return self.proto.name == "__init__"

    def invoke(
        self,
        args: list[OortObject],
        position: SourcePosition | None = None,
    ) -> OortObject:
        interpreter = self.vm.interpreter
        previous = interpreter._current_method
        interpreter._current_method = self
        try:
            return self.vm.invoke_positional_closure(self, args, None, position)
        finally:
            interpreter._current_method = previous

    def invoke_as_method(
        self,
        this,
        args: list[OortObject],
        position: SourcePosition | None = None,
    ) -> OortObject:
        interpreter = self.vm.interpreter
        previous = interpreter._current_method
        interpreter._current_method = self
        try:
            return self.vm.invoke_positional_closure(self, args, this, position)
        finally:
            interpreter._current_method = previous

    def invoke_evaluated(
        self,
        args: list[EvaluatedArg],
        position: SourcePosition | None = None,
    ) -> OortObject:
        return self._invoke_evaluated(args, None, position)

    def invoke_evaluated_as_method(
        self,
        this,
        args: list[EvaluatedArg],
        position: SourcePosition | None = None,
    ) -> OortObject:
        return self._invoke_evaluated(args, this, position)

    def _invoke_evaluated(
        self,
        args: list[EvaluatedArg],
        this,
        position: SourcePosition | None,
    ) -> OortObject:
        interpreter = self.vm.interpreter
        previous = interpreter._current_method
        interpreter._current_method = self
        try:
            return self.vm.invoke_evaluated_closure(self, args, position, this)
        finally:
            interpreter._current_method = previous

    def default_closure(self, index: int) -> OortVMClosure:
        cached = self._default_closures.get(index)
        if cached is not None:
            return cached
        if not 0 <= index < len(self.module.functions):
            raise OortTypeError(
                f"Invalid default value proto index {index}.",
                self.proto.positions[0] if self.proto.positions else _fallback_position(),
            )
        cached = OortVMClosure(
            self.vm,
            self.module,
            self.module.functions[index],
            self.frame,
            self.env,
            self.definition_ext_env,
        )
        self._default_closures[index] = cached
        return cached

    def __repr__(self):
        return f"<Function {self.proto.name}>"


class BytecodeVM:
    def __init__(self, interpreter):
        self.interpreter = interpreter
        self.globals = Environment(
            outer=interpreter.builtins_env,
            name="<bytecode>",
            allow_redefine=True,
            is_module_root=True,
        )
        self._decoded_cache: dict[int, tuple[Decoded, ...]] = {}
        self._global_caches: dict[Environment, dict[str, OortObject]] = {}

    def run(self, module: BytecodeModule, env: Environment | None = None) -> OortObject:
        return self.run_module(module, env if env is not None else self.globals)

    def run_module(self, module: BytecodeModule, env: Environment) -> OortObject:
        """Execute one module's main proto with its own globals environment."""
        with self.interpreter.runtime.activate():
            return self._execute(module, module.main, {}, None, env)

    # ------------------------------------------------------------------
    # Frames and dispatch
    # ------------------------------------------------------------------

    def _new_registers(self, proto: Proto) -> list[Any]:
        null = self.interpreter.runtime.null
        if proto.uses_cells:
            return [
                *(_Cell(null) for _ in range(proto.local_count)),
                *(null for _ in range(proto.register_count - proto.local_count)),
            ]
        return [null for _ in range(proto.register_count)]

    @staticmethod
    def _read_slot(proto: Proto, registers: list[Any], slot: int) -> OortObject:
        value = registers[slot]
        if proto.uses_cells:
            assert isinstance(value, _Cell)
            return value.value
        assert isinstance(value, OortObject)
        return value

    @staticmethod
    def _write_slot(proto: Proto, registers: list[Any], slot: int, value: OortObject) -> None:
        if proto.uses_cells:
            cell = registers[slot]
            assert isinstance(cell, _Cell)
            cell.value = value
        else:
            registers[slot] = value

    def invoke_positional_closure(
        self,
        closure: OortVMClosure,
        args: list[OortObject],
        this: OortObject | None,
        position: SourcePosition | None,
    ) -> OortObject:
        signature = closure.proto.signature
        params = signature.params
        if len(args) == len(params) and all(
            param.kind in (ParamKind.POS_ONLY, ParamKind.POS_OR_KW) and not param.has_default
            for param in params
        ):
            if signature.has_this and this is None:
                raise OortTypeError(
                    f"Method {closure.proto.name!r} requires a receiver.",
                    position
                    or (
                        closure.proto.positions[0]
                        if closure.proto.positions
                        else _fallback_position()
                    ),
                )
            registers = self._new_registers(closure.proto)
            if signature.has_this:
                assert this is not None
                self._write_slot(closure.proto, registers, 0, this)
            for param, value in zip(params, args, strict=True):
                self._write_slot(closure.proto, registers, param.slot, value)
            return self._execute(
                closure.module,
                closure.proto,
                None,
                closure.frame,
                closure.env,
                registers=registers,
                definition_ext_env=closure.definition_ext_env,
            )
        evaluated = [EvaluatedArg(value) for value in args]
        return self.invoke_evaluated_closure(closure, evaluated, position, this)

    def invoke_evaluated_closure(
        self,
        closure: OortVMClosure,
        args: list[EvaluatedArg],
        position: SourcePosition | None = None,
        this: OortObject | None = None,
    ) -> OortObject:
        bound = self._bind_closure(closure, args, this, position)
        return self._execute(
            closure.module,
            closure.proto,
            bound,
            closure.frame,
            closure.env,
            definition_ext_env=closure.definition_ext_env,
        )

    def _bind_closure(
        self,
        closure: OortVMClosure,
        args: list[EvaluatedArg],
        this: OortObject | None,
        position: SourcePosition | None,
    ) -> dict[int, OortObject]:
        signature = closure.proto.signature
        error_position = position or (
            closure.proto.positions[0] if closure.proto.positions else _fallback_position()
        )
        params = signature.params
        if (
            len(args) == len(params)
            and all(arg.kind is ArgKind.POSITIONAL for arg in args)
            and all(
                param.kind in (ParamKind.POS_ONLY, ParamKind.POS_OR_KW) and not param.has_default
                for param in params
            )
        ):
            if signature.has_this and this is None:
                raise OortTypeError(
                    f"Method {closure.proto.name!r} requires a receiver.",
                    error_position,
                )
            fast_values: dict[int, OortObject] = {}
            if signature.has_this:
                assert this is not None
                fast_values[0] = this
            for param, arg in zip(params, args, strict=True):
                fast_values[param.slot] = arg.value
            return fast_values

        try:
            plan = bind_arguments(signature, args, closure.proto.name)
        except ArgumentBindingError as exc:
            raise OortTypeError(str(exc), error_position) from exc

        values: dict[int, OortObject] = {}
        by_name: dict[str, OortObject] = {}
        if signature.has_this:
            if this is None:
                raise OortTypeError(
                    f"Method {closure.proto.name!r} requires a receiver.",
                    error_position,
                )
            values[0] = this

        for index, param in enumerate(signature.params):
            if param.kind in (
                ParamKind.POS_ONLY,
                ParamKind.POS_OR_KW,
                ParamKind.KW_ONLY,
            ):
                if param.name in plan.provided:
                    value = plan.provided[param.name]
                else:
                    if param.default_index is None:
                        raise AssertionError(f"unbound required parameter {param.name!r}")
                    earlier = [by_name[earlier.name] for earlier in signature.params[:index]]
                    value = self._invoke_default(
                        closure,
                        param.default_index,
                        earlier,
                        error_position,
                    )
            elif param.kind is ParamKind.VAR_POS:
                value = OortTuple(tuple(plan.extra_pos))
            elif param.kind is ParamKind.VAR_KW:
                value = OortDict({OortString(key): item for key, item in plan.extra_kw.items()})
            elif param.kind is ParamKind.BLOCK:
                if param.name in plan.provided:
                    value = plan.provided[param.name]
                else:
                    value = plan.block if plan.block is not None else self.interpreter.runtime.null
            else:
                raise AssertionError(f"Unexpected parameter kind {param.kind}")
            values[param.slot] = value
            by_name[param.name] = value

        return values

    def _invoke_default(
        self,
        closure: OortVMClosure,
        index: int,
        earlier: list[OortObject],
        position: SourcePosition,
    ) -> OortObject:
        default = closure.default_closure(index)
        bound = {
            param.slot: value
            for param, value in zip(default.proto.signature.params, earlier, strict=False)
        }
        return self._execute(
            default.module,
            default.proto,
            bound,
            default.frame,
            default.env,
            definition_ext_env=default.definition_ext_env,
        )

    def _execute(
        self,
        module: BytecodeModule,
        proto: Proto,
        bound_values: dict[int, OortObject] | None,
        parent_frame: VMFrame | None = None,
        env: Environment | None = None,
        *,
        registers: list[Any] | None = None,
        definition_ext_env: Environment | None = None,
    ) -> OortObject:
        if env is None:
            env = self.globals
        if registers is None:
            registers = self._new_registers(proto)
            for slot, value in (bound_values or {}).items():
                self._write_slot(proto, registers, slot, value)
        if proto is module.main:
            ext_env = env
        else:
            base_env = definition_ext_env if definition_ext_env is not None else env
            ext_env = (
                Environment(outer=base_env, name="<extensions>")
                if proto.defines_extensions
                else base_env
            )
        frame = VMFrame(registers, parent_frame, ext_env)
        constants = proto.constants
        instructions = self._decoded(proto)
        positions = proto.positions
        pc = 0
        while pc < len(instructions):
            decoded = instructions[pc]
            position = positions[pc] if pc < len(positions) else _fallback_position()
            op = decoded.op
            a = decoded.a
            b = decoded.b
            c = decoded.c

            if op is Op.LOAD_K:
                registers[a] = self._wrap_constant(constants[decoded.bx])
                pc += 1
            elif op is Op.LOAD_L:
                registers[a] = self._read_slot(proto, registers, b)
                pc += 1
            elif op is Op.STORE_L:
                value = registers[b]
                assert isinstance(value, OortObject)
                self._write_slot(proto, registers, a, value)
                pc += 1
            elif op is Op.LOAD_G:
                name = str(constants[decoded.bx])
                cache = self._cache_for(env)
                cached = cache.get(name)
                if cached is not None:
                    registers[a] = cached
                else:
                    entry = env.get(name)
                    if entry is None:
                        raise OortNameError(f"Name {name!r} is not defined in bytecode.", position)
                    registers[a] = entry.value
                    cache[name] = entry.value
                pc += 1
            elif op is Op.STORE_G:
                name = str(constants[decoded.bx])
                env.define(name, registers[a], mutable=True)
                self._cache_for(env)[name] = registers[a]
                pc += 1
            elif op is Op.IMPORT:
                spec = constants[decoded.bx]
                if not isinstance(spec, ImportSpec):
                    raise OortTypeError("Invalid import descriptor in bytecode.", position)
                loader = self.interpreter.module_loader
                if loader is None:
                    raise OortImportError(
                        "Module imports are not available in this context.",
                        position,
                    )
                if spec.is_from:
                    imported_module, values = loader.import_names(
                        spec.module_path,
                        [name for name, _ in spec.names],
                        position,
                    )
                    for source, alias in spec.names:
                        self._define_import(
                            env,
                            alias or source,
                            values[source],
                            position,
                        )
                    env.add_imported_extension_scope(imported_module.env)
                else:
                    imported = loader.import_module(spec.module_path, position)
                    name = spec.alias or loader.binding_name(spec.module_path, position)
                    self._define_import(env, name, imported, position)
                    env.add_imported_extension_scope(imported.env)
                pc += 1
            elif op is Op.LOAD_OUTER:
                outer = frame
                for _ in range(b):
                    if outer.parent is None:
                        raise OortTypeError(
                            "Invalid closure depth in bytecode.",
                            position,
                        )
                    outer = outer.parent
                value = outer.registers[c]
                registers[a] = value.value if isinstance(value, _Cell) else value
                pc += 1
            elif op is Op.STORE_OUTER:
                outer = frame
                for _ in range(a):
                    if outer.parent is None:
                        raise OortTypeError(
                            "Invalid closure depth in bytecode.",
                            position,
                        )
                    outer = outer.parent
                target = outer.registers[b]
                value = registers[c]
                assert isinstance(value, OortObject)
                if isinstance(target, _Cell):
                    target.value = value
                else:
                    outer.registers[b] = value
                pc += 1
            elif op is Op.MAKE_CLOSURE:
                proto_index = decoded.bx
                if not 0 <= proto_index < len(module.functions):
                    raise OortTypeError(
                        f"Invalid bytecode function index {proto_index}.",
                        position,
                    )
                captured = (
                    VMFrame(
                        list(registers[: proto.local_count]),
                        frame.parent,
                        frame.ext_env,
                    )
                    if proto.uses_cells
                    else frame
                )
                registers[a] = OortVMClosure(
                    self,
                    module,
                    module.functions[proto_index],
                    captured,
                    env,
                    frame.ext_env,
                )
                pc += 1
            elif op is Op.BUILD_ENUM:
                spec = constants[decoded.bx]
                if not isinstance(spec, EnumSpec):
                    raise OortTypeError("Invalid enum descriptor in bytecode.", position)
                enum_type = OortType.create_type_object(
                    spec.name,
                    bases=[self.interpreter.runtime.types.object_type],
                )
                enum_type.adt_variants = dict(spec.constructors)
                for constructor, arity in spec.constructors:
                    constructor_value: OortObject
                    if arity == 0:
                        constructor_value = OortADT(enum_type, constructor)
                    else:

                        def construct(
                            *values: OortObject,
                            _name: str = constructor,
                            _arity: int = arity,
                            _type: OortType = enum_type,
                        ) -> OortADT:
                            if len(values) != _arity:
                                raise TypeError(
                                    f"Constructor {_name!r} expects {_arity} "
                                    f"argument(s), got {len(values)}"
                                )
                            return OortADT(_type, _name, values)

                        constructor_value = OortNativeFunction(
                            construct,
                            name=constructor,
                            mode=NativeMode.VALUE,
                        )
                    self._define_import(env, constructor, constructor_value, position)
                registers[a] = enum_type
                pc += 1
            elif op is Op.MATCH:
                spec = constants[decoded.bx]
                if not isinstance(spec, MatchSpec):
                    raise OortTypeError("Invalid match descriptor in bytecode.", position)
                scrutinee = registers[proto.scratch_base]
                for arm in spec.arms:
                    bindings: dict[str, OortObject] = {}
                    if not self._match_pattern(arm.pattern, scrutinee, bindings, position):
                        continue
                    if not 0 <= arm.function_index < len(module.functions):
                        raise OortTypeError(
                            f"Invalid bytecode match arm index {arm.function_index}.",
                            position,
                        )
                    closure = OortVMClosure(
                        self,
                        module,
                        module.functions[arm.function_index],
                        frame,
                        env,
                    )
                    args = [bindings[name] for name in closure.proto.params]
                    registers[a] = closure.invoke(args, position)
                    break
                else:
                    raise OortRuntimeError(
                        f"No match arm matched value {scrutinee!r}.",
                        position,
                    )
                pc += 1
            elif op is Op.BUILD_CLASS:
                spec = constants[decoded.bx]
                if not isinstance(spec, ClassSpec):
                    raise OortTypeError("Invalid class descriptor in bytecode.", position)
                bases: list[OortType] = []
                for index in range(spec.base_count):
                    base = registers[proto.scratch_base + index]
                    if not isinstance(base, OortType):
                        raise OortTypeError(
                            f"{base.type.name!r} object is not a class",
                            position,
                        )
                    bases.append(base)
                metaclass = None
                if spec.has_metaclass:
                    candidate = registers[proto.scratch_base + spec.base_count]
                    if not isinstance(candidate, OortType):
                        raise OortTypeError(
                            f"{candidate.type.name!r} object is not a class",
                            position,
                        )
                    metaclass = candidate
                try:
                    cls = OortType.create_type_object(
                        spec.name,
                        bases=bases,
                        metaclass=metaclass,
                    )
                except TypeError as exc:
                    raise OortTypeError(str(exc), position) from exc
                for method_name, method_index in spec.methods:
                    if not 0 <= method_index < len(module.functions):
                        raise OortTypeError(
                            f"Invalid bytecode method index {method_index}.",
                            position,
                        )
                    method = OortVMClosure(
                        self,
                        module,
                        module.functions[method_index],
                        frame,
                        env,
                        frame.ext_env,
                    )
                    method.defining_type = cls
                    cls.set(method_name, method)
                for method_name, method_index in spec.class_methods:
                    if not 0 <= method_index < len(module.functions):
                        raise OortTypeError(
                            f"Invalid bytecode class method index {method_index}.",
                            position,
                        )
                    method = OortVMClosure(
                        self,
                        module,
                        module.functions[method_index],
                        frame,
                        env,
                        frame.ext_env,
                    )
                    method.defining_type = cls
                    cls.set_class_field(method_name, method)
                for symbol, operand_count, method_index in spec.operators:
                    if not 0 <= method_index < len(module.functions):
                        raise OortTypeError(
                            f"Invalid bytecode operator index {method_index}.",
                            position,
                        )
                    method = OortVMClosure(
                        self,
                        module,
                        module.functions[method_index],
                        frame,
                        env,
                        frame.ext_env,
                    )
                    method.defining_type = cls
                    cls.set_operator(symbol, operand_count, method)
                for slot_name, mutable, initializer_index in spec.slots:
                    initializer_closure = None
                    if initializer_index is not None:
                        if not 0 <= initializer_index < len(module.functions):
                            raise OortTypeError(
                                f"Invalid bytecode slot initializer index {initializer_index}.",
                                position,
                            )
                        initializer_closure = OortVMClosure(
                            self,
                            module,
                            module.functions[initializer_index],
                            frame,
                            env,
                            frame.ext_env,
                        )
                    cls.slots[slot_name] = SlotDefinition(
                        name=slot_name,
                        mutable=mutable,
                        initializer=None,
                        closure=env,
                        position=position,
                        initializer_callable=initializer_closure,
                    )
                cls.static_layout = bool(spec.slots)
                registers[a] = cls
                pc += 1
            elif op is Op.DEF_FUN:
                proto_index = decoded.bx
                if not 0 <= proto_index < len(module.functions):
                    raise OortTypeError(f"Invalid bytecode function index {proto_index}.", position)
                function = OortVMClosure(
                    self,
                    module,
                    module.functions[proto_index],
                    None,
                    env,
                    frame.ext_env,
                )
                env.define(function.proto.name, function, mutable=False)
                self._cache_for(env)[function.proto.name] = function
                pc += 1
            elif op is Op.MOVE:
                registers[a] = registers[b]
                pc += 1
            elif op in _BINARY_SYMBOLS:
                registers[a] = self._binary(
                    op,
                    registers[b],
                    registers[c],
                    position,
                    frame.ext_env,
                )
                pc += 1
            elif op in _UNARY_SYMBOLS:
                registers[a] = self._unary(op, registers[b], position, frame.ext_env)
                pc += 1
            elif op is Op.JUMP:
                pc = pc + 1 + decoded.sbx
            elif op is Op.JUMP_FALSE:
                if self.interpreter.is_truthy(registers[a]):
                    pc += 1
                else:
                    pc = pc + 1 + decoded.sbx
            elif op is Op.JUMP_TRUE:
                if self.interpreter.is_truthy(registers[a]):
                    pc = pc + 1 + decoded.sbx
                else:
                    pc += 1
            elif op is Op.NEW_LIST:
                registers[a] = OortList([registers[b + index] for index in range(c)])
                pc += 1
            elif op is Op.NEW_TUPLE:
                registers[a] = OortTuple(tuple(registers[b + index] for index in range(c)))
                pc += 1
            elif op is Op.NEW_SET:
                registers[a] = OortSet({registers[b + index] for index in range(c)})
                pc += 1
            elif op is Op.NEW_DICT:
                mapping: dict[OortObject, OortObject] = {}
                for index in range(c):
                    mapping[registers[b + 2 * index]] = registers[b + 2 * index + 1]
                registers[a] = OortDict(mapping)
                pc += 1
            elif op is Op.BUILD_SLICE:
                registers[a] = OortSlice(
                    registers[b] if c & 1 else None,
                    registers[b + 1] if c & 2 else None,
                    registers[b + 2] if c & 4 else None,
                )
                pc += 1
            elif op is Op.SUPER:
                receiver = registers[b]
                assert isinstance(receiver, OortObject)
                defining_type = getattr(self.interpreter._current_method, "defining_type", None)
                if defining_type is None or not (
                    isinstance(receiver, OortObject) and defining_type in receiver.type.mro()
                ):
                    defining_type = receiver.type
                registers[a] = OortSuperProxy(defining_type, receiver)
                pc += 1
            elif op is Op.REGISTER_EXT:
                spec = constants[decoded.bx]
                if not isinstance(spec, ExtensionSpec):
                    raise OortTypeError("Invalid extension descriptor in bytecode.", position)
                if not 0 <= spec.function_index < len(module.functions):
                    raise OortTypeError(
                        f"Invalid bytecode extension index {spec.function_index}.",
                        position,
                    )
                receiver = registers[a]
                if not isinstance(receiver, OortType):
                    raise OortTypeError("Extension receiver is not a type.", position)
                extension = OortVMClosure(
                    self,
                    module,
                    module.functions[spec.function_index],
                    frame,
                    env,
                    frame.ext_env,
                )
                extension.defining_type = receiver
                if spec.symbol is not None:
                    result = frame.ext_env.register_extension_operator(
                        receiver,
                        spec.symbol,
                        spec.operand_count,
                        extension,
                    )
                    duplicate = (
                        f"Extension operator {spec.symbol!r} for {receiver.name!r} "
                        "is already defined in this scope."
                    )
                else:
                    result = frame.ext_env.register_extension(
                        receiver,
                        spec.name,
                        extension,
                    )
                    duplicate = (
                        f"Extension method {receiver.name!r}.{spec.name} "
                        "is already defined in this scope."
                    )
                if result == DefineResult.REDEFINED:
                    raise OortTypeError(duplicate, position)
                pc += 1
            elif op is Op.GET_ATTR:
                name = str(constants[decoded.bx])
                registers[a] = self.interpreter.get_attribute(
                    registers[a],
                    name,
                    position,
                    env=frame.ext_env,
                )
                pc += 1
            elif op is Op.SET_ATTR:
                name = str(constants[decoded.bx])
                self.interpreter.set_attribute(registers[a], name, registers[a + 1], position)
                pc += 1
            elif op is Op.GET_ITEM:
                registers[a] = self.interpreter.get_item(
                    registers[b],
                    registers[c],
                    position,
                    env=frame.ext_env,
                )
                pc += 1
            elif op is Op.SET_ITEM:
                self.interpreter.set_item(
                    registers[a],
                    registers[b],
                    registers[c],
                    position,
                    env=frame.ext_env,
                )
                pc += 1
            elif op is Op.CALL:
                callee = registers[a]
                positional_values = [registers[a + 1 + index] for index in range(c)]
                registers[a] = self._call_positional(
                    callee,
                    positional_values,
                    position,
                )
                pc += 1
            elif op is Op.CALL_KW:
                spec = constants[decoded.bx]
                if not isinstance(spec, CallSpec):
                    raise OortTypeError("Invalid call descriptor in bytecode.", position)
                call_base = a
                callee = registers[call_base]
                evaluated_args = [
                    EvaluatedArg(registers[call_base + 1 + index])
                    for index in range(spec.positional_count)
                ]
                kw_base = call_base + 1 + spec.positional_count
                evaluated_args.extend(
                    EvaluatedArg(
                        registers[kw_base + index],
                        ArgKind.KEYWORD,
                        keyword,
                    )
                    for index, keyword in enumerate(spec.keywords)
                )
                if spec.has_block:
                    evaluated_args.append(
                        EvaluatedArg(
                            registers[kw_base + len(spec.keywords)],
                            ArgKind.BLOCK,
                        )
                    )
                registers[call_base] = self._call(
                    callee,
                    evaluated_args,
                    position,
                )
                pc += 1
            elif op is Op.RET:
                return registers[a]
            elif op is Op.OPEN_ITER:
                registers[a] = self.interpreter.open_iterator(registers[b], position)
                pc += 1
            elif op is Op.ITER_NEXT:
                value, valid = self.interpreter.iterator_next(registers[b], position)
                registers[a] = self.interpreter.runtime.null if value is None else value
                registers[c] = OortBool.get_bool_value(valid)
                pc += 1
            elif op is Op.UNPACK:
                item = registers[a]
                if not isinstance(item, (OortTuple, OortList)):
                    raise OortTypeError(
                        "Cannot unpack a non-tuple value in for loop",
                        position,
                    )
                values = list(item.value)
                if len(values) != c:
                    raise OortTypeError(
                        f"Cannot unpack {len(values)} value(s) into {c} loop variable(s)",
                        position,
                    )
                for index, element in enumerate(values):
                    self._write_slot(proto, registers, b + index, element)
                pc += 1
            elif op is Op.FRESH:
                slots = constants[decoded.bx]
                if not isinstance(slots, tuple):
                    raise OortTypeError("Invalid fresh-locals descriptor.", position)
                if proto.uses_cells:
                    for slot in slots:
                        registers[slot] = _Cell(self.interpreter.runtime.null)
                pc += 1
            elif op is Op.EXTEND:
                pc += 1
            else:
                raise OortTypeError(f"Bytecode VM does not support opcode {op.name}.", position)
        return self.interpreter.runtime.null

    def _match_pattern(
        self,
        pattern: PatternSpec,
        value: OortObject,
        bindings: dict[str, OortObject],
        position: SourcePosition,
    ) -> bool:
        if pattern.kind == "wildcard":
            return True
        if pattern.kind == "name":
            if isinstance(value, OortADT) and value.type.adt_variants is not None:
                arity = value.type.adt_variants.get(pattern.name)
                if arity is not None:
                    if arity != 0:
                        raise OortTypeError(
                            f"Constructor {pattern.name!r} expects {arity} argument(s).",
                            position,
                        )
                    if value.variant != pattern.name:
                        return False
                    bindings[pattern.name] = value
                    return True
            bindings[pattern.name] = value
            return True
        if pattern.kind == "constructor":
            if not isinstance(value, OortADT) or value.variant != pattern.name:
                return False
            if len(value.values) != len(pattern.args):
                raise OortTypeError(
                    f"Constructor {pattern.name!r} expects {len(value.values)} "
                    f"argument(s), got {len(pattern.args)}.",
                    position,
                )
            for subpattern, payload in zip(pattern.args, value.values, strict=True):
                if not self._match_pattern(subpattern, payload, bindings, position):
                    return False
            return True
        return False

    def _define_import(
        self,
        env: Environment,
        name: str,
        value: OortObject,
        position: SourcePosition,
    ) -> None:
        if env.define(name, value, mutable=False) == DefineResult.REDEFINED:
            raise OortNameError(f"Name {name!r} is already defined", position)
        self._cache_for(env)[name] = value

    def _cache_for(self, env: Environment) -> dict[str, OortObject]:
        return self._global_caches.setdefault(env, {})

    def _binary(
        self,
        op: Op,
        left: OortObject,
        right: OortObject,
        position: SourcePosition,
        env: Environment,
    ) -> OortObject:
        if type(left) is OortInt and type(right) is OortInt:
            lv = left.value
            rv = right.value
            if op is Op.ADD:
                return OortInt(lv + rv)
            if op is Op.SUB:
                return OortInt(lv - rv)
            if op is Op.MUL:
                return OortInt(lv * rv)
            if op is Op.DIV:
                try:
                    return OortFloat(lv / rv)
                except ZeroDivisionError as exc:
                    raise OortRuntimeError(str(exc), position) from exc
            if op is Op.FLOORDIV:
                try:
                    return OortInt(lv // rv)
                except ZeroDivisionError as exc:
                    raise OortRuntimeError(str(exc), position) from exc
            if op is Op.MOD:
                try:
                    return OortInt(lv % rv)
                except ZeroDivisionError as exc:
                    raise OortRuntimeError(str(exc), position) from exc
            if op is Op.EQ:
                return OortBool.get_bool_value(lv == rv)
            if op is Op.NE:
                return OortBool.get_bool_value(lv != rv)
            if op is Op.LT:
                return OortBool.get_bool_value(lv < rv)
            if op is Op.LE:
                return OortBool.get_bool_value(lv <= rv)
            if op is Op.GT:
                return OortBool.get_bool_value(lv > rv)
            if op is Op.GE:
                return OortBool.get_bool_value(lv >= rv)
        return self.interpreter.apply_binary(
            _BINARY_SYMBOLS[op],
            left,
            right,
            position,
            env=env,
        )

    def _unary(
        self,
        op: Op,
        operand: OortObject,
        position: SourcePosition,
        env: Environment,
    ) -> OortObject:
        if type(operand) is OortInt:
            if op is Op.NEG:
                return OortInt(-operand.value)
            if op is Op.POS:
                return OortInt(operand.value)
            if op is Op.INVERT:
                return OortInt(~operand.value)
        return self.interpreter.apply_unary(
            _UNARY_SYMBOLS[op],
            operand,
            position,
            env=env,
        )

    def _call(
        self,
        callee: OortObject,
        args: list[EvaluatedArg],
        position: SourcePosition,
    ) -> OortObject:
        if isinstance(callee, OortType):
            return self._construct(callee, args, position)
        if isinstance(callee, OortVMInvokable):
            if all(arg.kind is ArgKind.POSITIONAL for arg in args):
                return callee.invoke(
                    [arg.value for arg in args],
                    position,
                )
            return callee.invoke_evaluated(args, position)

        has_keyword = any(arg.kind is ArgKind.KEYWORD for arg in args)
        if has_keyword:
            if isinstance(callee, (OortNativeFunction, OortNativeMethod)):
                raise OortTypeError(
                    f"Built-in function {callee.name!r} does not accept keyword arguments",
                    position,
                )
            raise OortTypeError(
                f"{callee.type.name} object does not accept keyword arguments",
                position,
            )

        values = [arg.value for arg in args if arg.kind is not ArgKind.BLOCK]
        values.extend(arg.value for arg in args if arg.kind is ArgKind.BLOCK)
        return self.interpreter.call_value(callee, values, position)

    def _call_positional(
        self,
        callee: OortObject,
        args: list[OortObject],
        position: SourcePosition,
    ) -> OortObject:
        if isinstance(callee, OortType):
            evaluated = [EvaluatedArg(value) for value in args]
            return self._construct(callee, evaluated, position)
        if isinstance(callee, OortVMInvokable):
            return callee.invoke(args, position)
        return self.interpreter.call_value(callee, args, position)

    def _construct(
        self,
        cls: OortType,
        args: list[EvaluatedArg],
        position: SourcePosition,
    ) -> OortObject:
        instance = OortInstance(type_=cls)
        init_func = cls.get("__init__")
        if init_func is None:
            if args:
                raise OortTypeError(
                    f"{cls.name}() takes 0 arguments but {len(args)} were given",
                    position,
                )
            self.interpreter.initialize_instance_slots(instance, cls)
            self.interpreter.check_instance_slots(instance, cls)
            return instance

        self.interpreter.initialize_instance_slots(instance, cls)
        if isinstance(init_func, OortVMInvokable):
            init_func.invoke_evaluated_as_method(
                instance,
                args,
                position,
            )
        else:
            raise OortTypeError(
                f"Class {cls.name!r} has a non-bytecode initializer.",
                position,
            )
        self.interpreter.check_instance_slots(instance, cls)
        return instance

    def _decoded(self, proto: Proto) -> tuple[Decoded, ...]:
        cached = self._decoded_cache.get(id(proto))
        if cached is not None:
            return cached
        decoded = tuple(decode(word) for word in proto.code)
        self._decoded_cache[id(proto)] = decoded
        return decoded

    def _wrap_constant(self, value: object) -> OortObject:
        if value is None:
            return self.interpreter.runtime.null
        if isinstance(value, bool):
            return self.interpreter.runtime.true if value else self.interpreter.runtime.false
        # Literals are freshly wrapped on each evaluation, matching the
        # tree-walking interpreter's identity semantics (`1 is 1` is false).
        return self.interpreter.runtime.host.from_host(value)


def _fallback_position() -> SourcePosition:
    return SourcePosition.from_location(1, 0, "<bytecode>", filename="<bytecode>")
