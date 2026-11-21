#! /usr/bin/env python

"""Bytecode code objects shared by the compiler, disassembler and VM."""

import dataclasses

from ..source.source_position import SourcePosition


@dataclasses.dataclass(frozen=True, slots=True)
class Proto:
    name: str
    params: tuple[str, ...]
    register_count: int
    code: tuple[int, ...]
    constants: tuple[object, ...]
    line_table: tuple[int, ...]
    positions: tuple[SourcePosition, ...]

    def line_for(self, pc: int) -> int:
        if 0 <= pc < len(self.line_table):
            return self.line_table[pc]
        return self.line_table[0] if self.line_table else 0


@dataclasses.dataclass(frozen=True, slots=True)
class BytecodeModule:
    main: Proto
    functions: tuple[Proto, ...]
