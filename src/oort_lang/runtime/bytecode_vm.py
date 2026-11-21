#! /usr/bin/env python

"""Register bytecode VM for the dynamic HIR/bytecode subset.

The VM reuses the existing runtime value types, builtins environment, operator
dispatch and iterator protocol. It deliberately rejects unsupported bytecode
instead of silently skipping it.
"""

from __future__ import annotations

from ..bytecode import BytecodeModule, Decoded, Proto, decode
from ..bytecode.opcodes import (
    BINARY_OPCODES,
    UNARY_OPCODES,
    Op,
)
from ..diagnostics.runtime_errors import OortNameError, OortRuntimeError, OortTypeError
from ..source.source_position import SourcePosition
from .environment import Environment
from .objects import OortBool, OortFloat, OortInt, OortObject

_BINARY_SYMBOLS = {opcode: symbol for symbol, opcode in BINARY_OPCODES.items()}
_UNARY_SYMBOLS = {opcode: symbol for symbol, opcode in UNARY_OPCODES.items()}


class OortVMFunction(OortObject):
    """A top-level function produced by bytecode ``DEF_FUN``."""

    def __init__(self, vm: BytecodeVM, proto: Proto):
        super().__init__(vm.interpreter.runtime.types.function_type)
        self.vm = vm
        self.proto = proto

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
        self.module: BytecodeModule | None = None
        self._decoded_cache: dict[int, tuple[Decoded, ...]] = {}
        self._globals_cache: dict[str, OortObject] = {}

    def run(self, module: BytecodeModule) -> OortObject:
        self.module = module
        with self.interpreter.runtime.activate():
            return self._execute(module.main, [])

    # ------------------------------------------------------------------
    # Frames and dispatch
    # ------------------------------------------------------------------

    def _execute(self, proto: Proto, args: list[OortObject]) -> OortObject:
        if len(args) != len(proto.params):
            raise OortTypeError(
                f"Function '{proto.name}' expects {len(proto.params)} arguments, got {len(args)}.",
                proto.positions[0] if proto.positions else _fallback_position(),
            )
        registers: list[OortObject] = [
            self.interpreter.runtime.null for _ in range(proto.register_count)
        ]
        for index, value in enumerate(args):
            registers[index] = value
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
            elif op is Op.LOAD_L or op is Op.STORE_L:
                registers[a] = registers[b]
                pc += 1
            elif op is Op.LOAD_G:
                name = str(constants[decoded.bx])
                cached = self._globals_cache.get(name)
                if cached is not None:
                    registers[a] = cached
                else:
                    entry = self.globals.get(name)
                    if entry is None:
                        raise OortNameError(f"Name {name!r} is not defined in bytecode.", position)
                    registers[a] = entry.value
                    self._globals_cache[name] = entry.value
                pc += 1
            elif op is Op.STORE_G:
                name = str(constants[decoded.bx])
                self.globals.define(name, registers[a], mutable=True)
                self._globals_cache[name] = registers[a]
                pc += 1
            elif op is Op.DEF_FUN:
                assert self.module is not None
                proto_index = decoded.bx
                if not 0 <= proto_index < len(self.module.functions):
                    raise OortTypeError(f"Invalid bytecode function index {proto_index}.", position)
                function = OortVMFunction(self, self.module.functions[proto_index])
                self.globals.define(function.proto.name, function, mutable=False)
                self._globals_cache[function.proto.name] = function
                pc += 1
            elif op is Op.MOVE:
                registers[a] = registers[b]
                pc += 1
            elif op in _BINARY_SYMBOLS:
                registers[a] = self._binary(op, registers[b], registers[c], position)
                pc += 1
            elif op in _UNARY_SYMBOLS:
                registers[a] = self._unary(op, registers[b], position)
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
            elif op is Op.CALL:
                callee = registers[a]
                call_args = [registers[a + 1 + index] for index in range(c)]
                registers[a] = self._call(callee, call_args, position)
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
            elif op is Op.EXTEND:
                pc += 1
            else:
                raise OortTypeError(f"Bytecode VM does not support opcode {op.name}.", position)
        return self.interpreter.runtime.null

    def _binary(
        self,
        op: Op,
        left: OortObject,
        right: OortObject,
        position: SourcePosition,
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
        return self.interpreter.apply_binary(_BINARY_SYMBOLS[op], left, right, position)

    def _unary(self, op: Op, operand: OortObject, position: SourcePosition) -> OortObject:
        if type(operand) is OortInt:
            if op is Op.NEG:
                return OortInt(-operand.value)
            if op is Op.POS:
                return OortInt(operand.value)
            if op is Op.INVERT:
                return OortInt(~operand.value)
        return self.interpreter.apply_unary(_UNARY_SYMBOLS[op], operand, position)

    def _call(
        self,
        callee: OortObject,
        args: list[OortObject],
        position: SourcePosition,
    ) -> OortObject:
        if isinstance(callee, OortVMFunction):
            return self._execute(callee.proto, args)
        return self.interpreter.call_value(callee, args, position)

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
