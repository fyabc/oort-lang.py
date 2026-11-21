#! /usr/bin/env python

"""Disassemble bytecode protos to a stable human-readable form."""

from .code import BytecodeModule, ClassSpec, ImportSpec, Proto
from .opcodes import Decoded, Op, decode


def _const(proto: Proto, index: int) -> str:
    if 0 <= index < len(proto.constants):
        return repr(proto.constants[index])
    return f"<bad K{index}>"


def _format(proto: Proto, pc: int, decoded: Decoded) -> str:
    op = decoded.op
    if op is Op.LOAD_K:
        return f"LOAD_K R{decoded.a} K{decoded.bx}({_const(proto, decoded.bx)})"
    if op is Op.LOAD_L:
        return f"LOAD_L R{decoded.a} L{decoded.b}"
    if op is Op.STORE_L:
        return f"STORE_L L{decoded.a} R{decoded.b}"
    if op is Op.LOAD_G:
        return f"LOAD_G R{decoded.a} {_const(proto, decoded.bx)}"
    if op is Op.STORE_G:
        return f"STORE_G R{decoded.a} {_const(proto, decoded.bx)}"
    if op is Op.DEF_FUN:
        return f"DEF_FUN proto[{decoded.bx}]"
    if op is Op.MAKE_CLOSURE:
        return f"MAKE_CLOSURE R{decoded.a} proto[{decoded.bx}]"
    if op is Op.BUILD_CLASS:
        spec = proto.constants[decoded.bx] if 0 <= decoded.bx < len(proto.constants) else None
        if isinstance(spec, ClassSpec):
            methods = ", ".join(f"{name}=proto[{index}]" for name, index in spec.methods)
            return f"BUILD_CLASS R{decoded.a} {spec.name} bases={spec.base_count} {methods}"
        return f"BUILD_CLASS R{decoded.a} <bad spec>"
    if op is Op.IMPORT:
        spec = proto.constants[decoded.bx] if 0 <= decoded.bx < len(proto.constants) else None
        if isinstance(spec, ImportSpec):
            if spec.is_from:
                names = ", ".join(
                    name if alias is None else f"{name} as {alias}" for name, alias in spec.names
                )
                return f"IMPORT {spec.module_path!r} names=({names})"
            alias = "" if spec.alias is None else f" as {spec.alias}"
            return f"IMPORT {spec.module_path!r}{alias}"
        return "IMPORT <bad spec>"
    if op is Op.LOAD_OUTER:
        return f"LOAD_OUTER R{decoded.a} depth={decoded.b} slot={decoded.c}"
    if op is Op.STORE_OUTER:
        return f"STORE_OUTER depth={decoded.a} slot={decoded.b} R{decoded.c}"
    if op is Op.MOVE:
        return f"MOVE R{decoded.a} R{decoded.b}"
    if op in {
        Op.ADD,
        Op.SUB,
        Op.MUL,
        Op.DIV,
        Op.FLOORDIV,
        Op.MOD,
        Op.POW,
        Op.SHL,
        Op.SHR,
        Op.BAND,
        Op.BOR,
        Op.BXOR,
        Op.EQ,
        Op.NE,
        Op.LT,
        Op.LE,
        Op.GT,
        Op.GE,
        Op.IN,
        Op.NOT_IN,
        Op.IS,
        Op.IS_NOT,
    }:
        return f"{op.name} R{decoded.a} R{decoded.b} R{decoded.c}"
    if op in {Op.POS, Op.NEG, Op.INVERT, Op.NOT}:
        return f"{op.name} R{decoded.a} R{decoded.b}"
    if op is Op.JUMP:
        return f"JUMP {pc + 1 + decoded.sbx}"
    if op is Op.JUMP_FALSE:
        return f"JUMP_FALSE R{decoded.a} {pc + 1 + decoded.sbx}"
    if op is Op.JUMP_TRUE:
        return f"JUMP_TRUE R{decoded.a} {pc + 1 + decoded.sbx}"
    if op is Op.CALL:
        return f"CALL R{decoded.a} nargs={decoded.c}"
    if op is Op.RET:
        return f"RET R{decoded.a}"
    if op is Op.OPEN_ITER:
        return f"OPEN_ITER R{decoded.a} R{decoded.b}"
    if op is Op.ITER_NEXT:
        return f"ITER_NEXT R{decoded.a} R{decoded.b} R{decoded.c}"
    if op in (Op.NEW_LIST, Op.NEW_TUPLE, Op.NEW_SET):
        return f"{op.name} R{decoded.a} base=R{decoded.b} count={decoded.c}"
    if op is Op.NEW_DICT:
        return f"NEW_DICT R{decoded.a} base=R{decoded.b} pairs={decoded.c}"
    if op is Op.GET_ATTR:
        return f"GET_ATTR R{decoded.a} {_const(proto, decoded.bx)}"
    if op is Op.SET_ATTR:
        return f"SET_ATTR R{decoded.a} {_const(proto, decoded.bx)}"
    if op is Op.GET_ITEM:
        return f"GET_ITEM R{decoded.a} R{decoded.b}[R{decoded.c}]"
    if op is Op.SET_ITEM:
        return f"SET_ITEM R{decoded.a}[R{decoded.b}] = R{decoded.c}"
    if op is Op.BUILD_SLICE:
        return f"BUILD_SLICE R{decoded.a} base=R{decoded.b} flags={decoded.c:03b}"
    return f"{op.name} A={decoded.a} B={decoded.b} C={decoded.c}"


def disassemble_proto(proto: Proto, prefix: str = "") -> list[str]:
    params = ", ".join(proto.params)
    lines = [f"{prefix}Proto {proto.name} regs={proto.register_count} params=({params})"]
    for pc, word in enumerate(proto.code):
        try:
            decoded = decode(word)
        except ValueError as exc:
            lines.append(f"{prefix}  {pc:4d}  <decode error: {exc}>")
            continue
        text = _format(proto, pc, decoded)
        lines.append(f"{prefix}  {pc:4d}  {text}  ; line {proto.line_for(pc)}")
    return lines


def disassemble_module(module: BytecodeModule) -> str:
    lines = disassemble_proto(module.main)
    for index, proto in enumerate(module.functions):
        lines.append("")
        lines.extend(disassemble_proto(proto, prefix=f"[{index}] "))
    return "\n".join(lines)
