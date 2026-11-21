#! /usr/bin/env python

"""Shared 32-bit bytecode: code objects, compiler, opcodes and disassembler."""

from .code import (
    BytecodeModule,
    CallSpec,
    ClassSpec,
    EnumSpec,
    ExtensionSpec,
    ImportSpec,
    MatchArmSpec,
    MatchSpec,
    PatternSpec,
    Proto,
)
from .compile import compile_module
from .disasm import disassemble_module, disassemble_proto
from .opcodes import (
    BINARY_OPCODES,
    UNARY_OPCODES,
    Decoded,
    Op,
    decode,
    encode_abc,
    encode_abx,
    encode_asbx,
    encode_ax,
)

__all__ = [
    "BINARY_OPCODES",
    "UNARY_OPCODES",
    "BytecodeModule",
    "CallSpec",
    "ClassSpec",
    "Decoded",
    "EnumSpec",
    "ExtensionSpec",
    "ImportSpec",
    "MatchArmSpec",
    "MatchSpec",
    "Op",
    "PatternSpec",
    "Proto",
    "compile_module",
    "decode",
    "disassemble_module",
    "disassemble_proto",
    "encode_abc",
    "encode_abx",
    "encode_asbx",
    "encode_ax",
]
