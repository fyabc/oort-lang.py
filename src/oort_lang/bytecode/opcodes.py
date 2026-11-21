#! /usr/bin/env python

"""Fixed 32-bit bytecode encoding (ABC / ABx / AsBx / Ax).

See ``docs/design/02-bytecode-vm-design.md``. The HIR is lowered into these
words; the VM decoder is the next P4 slice.
"""

import dataclasses
from enum import IntEnum

_FORMAT_ABC = "ABC"
_FORMAT_ABX = "ABx"
_FORMAT_ASBX = "AsBx"
_FORMAT_AX = "Ax"


class Op(IntEnum):
    LOAD_K = 1
    LOAD_L = 2
    STORE_L = 3
    LOAD_G = 4
    STORE_G = 5
    DEF_FUN = 6
    MOVE = 7

    ADD = 10
    SUB = 11
    MUL = 12
    DIV = 13
    FLOORDIV = 14
    MOD = 15
    POW = 16
    SHL = 17
    SHR = 18
    BAND = 19
    BOR = 20
    BXOR = 21
    EQ = 22
    NE = 23
    LT = 24
    LE = 25
    GT = 26
    GE = 27
    IN = 28
    NOT_IN = 29
    IS = 30
    IS_NOT = 31

    POS = 35
    NEG = 36
    INVERT = 37
    NOT = 38

    JUMP = 40
    JUMP_FALSE = 41
    JUMP_TRUE = 42
    CALL = 43
    RET = 44
    OPEN_ITER = 45
    ITER_NEXT = 46

    NEW_LIST = 50
    NEW_TUPLE = 51
    NEW_SET = 52
    NEW_DICT = 53
    GET_ITEM = 54
    SET_ITEM = 55
    BUILD_SLICE = 56

    EXTEND = 47


OP_FORMAT: dict[Op, str] = {
    Op.LOAD_K: _FORMAT_ABX,
    Op.LOAD_L: _FORMAT_ABC,
    Op.STORE_L: _FORMAT_ABC,
    Op.LOAD_G: _FORMAT_ABX,
    Op.STORE_G: _FORMAT_ABX,
    Op.DEF_FUN: _FORMAT_ABX,
    Op.MOVE: _FORMAT_ABC,
    Op.ADD: _FORMAT_ABC,
    Op.SUB: _FORMAT_ABC,
    Op.MUL: _FORMAT_ABC,
    Op.DIV: _FORMAT_ABC,
    Op.FLOORDIV: _FORMAT_ABC,
    Op.MOD: _FORMAT_ABC,
    Op.POW: _FORMAT_ABC,
    Op.SHL: _FORMAT_ABC,
    Op.SHR: _FORMAT_ABC,
    Op.BAND: _FORMAT_ABC,
    Op.BOR: _FORMAT_ABC,
    Op.BXOR: _FORMAT_ABC,
    Op.EQ: _FORMAT_ABC,
    Op.NE: _FORMAT_ABC,
    Op.LT: _FORMAT_ABC,
    Op.LE: _FORMAT_ABC,
    Op.GT: _FORMAT_ABC,
    Op.GE: _FORMAT_ABC,
    Op.IN: _FORMAT_ABC,
    Op.NOT_IN: _FORMAT_ABC,
    Op.IS: _FORMAT_ABC,
    Op.IS_NOT: _FORMAT_ABC,
    Op.POS: _FORMAT_ABC,
    Op.NEG: _FORMAT_ABC,
    Op.INVERT: _FORMAT_ABC,
    Op.NOT: _FORMAT_ABC,
    Op.JUMP: _FORMAT_ASBX,
    Op.JUMP_FALSE: _FORMAT_ASBX,
    Op.JUMP_TRUE: _FORMAT_ASBX,
    Op.CALL: _FORMAT_ABC,
    Op.RET: _FORMAT_ABC,
    Op.OPEN_ITER: _FORMAT_ABC,
    Op.ITER_NEXT: _FORMAT_ABC,
    Op.NEW_LIST: _FORMAT_ABC,
    Op.NEW_TUPLE: _FORMAT_ABC,
    Op.NEW_SET: _FORMAT_ABC,
    Op.NEW_DICT: _FORMAT_ABC,
    Op.GET_ITEM: _FORMAT_ABC,
    Op.SET_ITEM: _FORMAT_ABC,
    Op.BUILD_SLICE: _FORMAT_ABC,
    Op.EXTEND: _FORMAT_AX,
}


BINARY_OPCODES: dict[str, Op] = {
    "+": Op.ADD,
    "-": Op.SUB,
    "*": Op.MUL,
    "/": Op.DIV,
    "//": Op.FLOORDIV,
    "%": Op.MOD,
    "**": Op.POW,
    "<<": Op.SHL,
    ">>": Op.SHR,
    "&": Op.BAND,
    "|": Op.BOR,
    "^": Op.BXOR,
    "==": Op.EQ,
    "!=": Op.NE,
    "<": Op.LT,
    "<=": Op.LE,
    ">": Op.GT,
    ">=": Op.GE,
    "in": Op.IN,
    "!in": Op.NOT_IN,
    "is": Op.IS,
    "!is": Op.IS_NOT,
}

UNARY_OPCODES: dict[str, Op] = {
    "+": Op.POS,
    "-": Op.NEG,
    "~": Op.INVERT,
    "not": Op.NOT,
}


@dataclasses.dataclass(frozen=True, slots=True)
class Decoded:
    op: Op
    format: str
    a: int = 0
    b: int = 0
    c: int = 0
    bx: int = 0
    sbx: int = 0
    ax: int = 0


def _check_byte(value: int, name: str) -> None:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name}={value} does not fit in 8 bits")


def encode_abc(op: Op, a: int, b: int, c: int) -> int:
    _check_byte(a, "A")
    _check_byte(b, "B")
    _check_byte(c, "C")
    return (int(op) << 24) | (a << 16) | (b << 8) | c


def encode_abx(op: Op, a: int, bx: int) -> int:
    _check_byte(a, "A")
    if not 0 <= bx <= 0xFFFF:
        raise ValueError(f"Bx={bx} does not fit in 16 bits")
    return (int(op) << 24) | (a << 16) | bx


def encode_asbx(op: Op, a: int, sbx: int) -> int:
    if not -0x8000 <= sbx <= 0x7FFF:
        raise ValueError(f"sBx={sbx} does not fit in 16 signed bits")
    return encode_abx(op, a, sbx + 0x8000)


def encode_ax(op: Op, ax: int) -> int:
    if not 0 <= ax <= 0xFFFFFF:
        raise ValueError(f"Ax={ax} does not fit in 24 bits")
    return (int(op) << 24) | ax


def decode(word: int) -> Decoded:
    if not 0 <= word <= 0xFFFFFFFF:
        raise ValueError(f"word={word} does not fit in 32 bits")
    raw_op = word >> 24
    try:
        op = Op(raw_op)
    except ValueError as exc:
        raise ValueError(f"unknown opcode {raw_op}") from exc
    fmt = OP_FORMAT[op]
    a = (word >> 16) & 0xFF
    if fmt == _FORMAT_ABC:
        return Decoded(op=op, format=fmt, a=a, b=(word >> 8) & 0xFF, c=word & 0xFF)
    if fmt == _FORMAT_ABX:
        return Decoded(op=op, format=fmt, a=a, bx=word & 0xFFFF)
    if fmt == _FORMAT_ASBX:
        raw = word & 0xFFFF
        return Decoded(op=op, format=fmt, a=a, bx=raw, sbx=raw - 0x8000)
    return Decoded(op=op, format=fmt, ax=word & 0xFFFFFF)


def format_op(op: Op) -> str:
    return op.name
