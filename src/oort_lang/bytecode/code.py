#! /usr/bin/env python

"""Bytecode code objects shared by the compiler, disassembler and VM."""

import dataclasses

from ..runtime.call_protocol import SignatureSpec
from ..source.source_position import SourcePosition


@dataclasses.dataclass(frozen=True, slots=True)
class ClassSpec:
    """Constant-pool descriptor for one ``BUILD_CLASS`` instruction."""

    name: str
    base_count: int
    methods: tuple[tuple[str, int], ...]
    slots: tuple[tuple[str, bool, int | None], ...] = ()
    class_methods: tuple[tuple[str, int], ...] = ()
    operators: tuple[tuple[str, int, int], ...] = ()
    has_metaclass: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class PatternSpec:
    kind: str
    name: str = ""
    args: tuple["PatternSpec", ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class MatchArmSpec:
    pattern: PatternSpec
    function_index: int


@dataclasses.dataclass(frozen=True, slots=True)
class MatchSpec:
    arms: tuple[MatchArmSpec, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class EnumSpec:
    name: str
    constructors: tuple[tuple[str, int], ...]


@dataclasses.dataclass(frozen=True, slots=True)
class CallSpec:
    """Extended call descriptor: positional count, keyword names and block."""

    positional_count: int
    keywords: tuple[str, ...] = ()
    has_block: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class ExtensionSpec:
    """Constant-pool descriptor for one ``REGISTER_EXT`` instruction."""

    name: str
    function_index: int
    symbol: str | None = None
    operand_count: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class ImportSpec:
    """Constant-pool descriptor for one ``IMPORT`` instruction."""

    module_path: str
    alias: str | None = None
    names: tuple[tuple[str, str | None], ...] = ()
    is_from: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class Proto:
    name: str
    params: tuple[str, ...]
    register_count: int
    code: tuple[int, ...]
    constants: tuple[object, ...]
    line_table: tuple[int, ...]
    positions: tuple[SourcePosition, ...]
    scratch_base: int = 0
    has_this: bool = False
    signature: SignatureSpec = dataclasses.field(default_factory=lambda: SignatureSpec(()))
    local_count: int = 0
    uses_cells: bool = False
    defines_extensions: bool = False

    def line_for(self, pc: int) -> int:
        if 0 <= pc < len(self.line_table):
            return self.line_table[pc]
        return self.line_table[0] if self.line_table else 0


@dataclasses.dataclass(frozen=True, slots=True)
class BytecodeModule:
    main: Proto
    functions: tuple[Proto, ...]
