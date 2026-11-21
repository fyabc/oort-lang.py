#! /usr/bin/env python

"""Lower HIR into fixed 32-bit bytecode words."""

import dataclasses

from ..diagnostics.syntax_errors import UnsupportedSyntax
from ..hir.nodes import (
    BinOp,
    BuildDict,
    BuildList,
    BuildSet,
    BuildSlice,
    BuildTuple,
    Call,
    DefineFunction,
    GetAttr,
    GetItem,
    HirFunction,
    HirModule,
    Instruction,
    IteratorNext,
    Jump,
    JumpIfFalse,
    JumpIfTrue,
    Label,
    LoadConst,
    LoadGlobal,
    LoadLocal,
    Move,
    OpenIterator,
    Return,
    SetAttr,
    SetItem,
    StoreGlobal,
    StoreLocal,
    UnOp,
)
from ..source.source_position import SourcePosition
from .code import BytecodeModule, Proto
from .opcodes import (
    BINARY_OPCODES,
    UNARY_OPCODES,
    Op,
    encode_abc,
    encode_abx,
    encode_asbx,
)

_MAX_REGISTERS = 256


class _Constants:
    def __init__(self):
        self.values: list[object] = []
        self.index: dict[tuple[str, str], int] = {}

    def add(self, value: object) -> int:
        key = (type(value).__name__, repr(value))
        existing = self.index.get(key)
        if existing is not None:
            return existing
        index = len(self.values)
        if index > 0xFFFF:
            raise ValueError("constant pool exceeds 65535 entries")
        self.values.append(value)
        self.index[key] = index
        return index


@dataclasses.dataclass(frozen=True, slots=True)
class _Fixup:
    word_index: int
    op: Op
    a: int
    label: str


class _ProtoCompiler:
    def __init__(self, function: HirFunction, module: HirModule):
        self.function = function
        self.module = module
        self.code: list[int] = []
        self.lines: list[int] = []
        self.positions: list[SourcePosition] = []
        self.constants = _Constants()
        self.labels: dict[str, int] = {}
        self.fixups: list[_Fixup] = []
        self.scratch_base = function.local_count
        self.max_args = max(
            (
                len(instruction.args)
                for instruction in function.code
                if isinstance(instruction, Call)
            ),
            default=-1,
        )
        self.has_iterator = any(
            isinstance(instruction, IteratorNext) for instruction in function.code
        )
        build_elements = max(
            (
                len(instruction.elements)
                for instruction in function.code
                if isinstance(instruction, (BuildList, BuildTuple, BuildSet))
            ),
            default=0,
        )
        build_dict_slots = max(
            (
                2 * len(instruction.items)
                for instruction in function.code
                if isinstance(instruction, BuildDict)
            ),
            default=0,
        )
        has_build = any(
            isinstance(instruction, (BuildList, BuildTuple, BuildSet, BuildDict))
            for instruction in function.code
        )
        has_slice = any(isinstance(instruction, BuildSlice) for instruction in function.code)
        has_get_attr = any(isinstance(instruction, GetAttr) for instruction in function.code)
        has_set_attr = any(isinstance(instruction, SetAttr) for instruction in function.code)
        attr_scratch = 2 if has_set_attr else 1 if has_get_attr else 0
        self.scratch = max(
            self.max_args + 1,
            1 if self.has_iterator else 0,
            1 if has_build else 0,
            3 if has_slice else 0,
            attr_scratch,
            build_elements,
            build_dict_slots,
        )
        self.register_count = function.local_count + self.scratch
        if self.register_count > _MAX_REGISTERS:
            raise UnsupportedSyntax(
                f"Bytecode register limit ({_MAX_REGISTERS}) exceeded in '{function.name}'.",
                function.position,
            )

    def compile(self) -> Proto:
        for instruction in self.function.code:
            self._emit(instruction)
        self._patch()
        return Proto(
            name=self.function.name,
            params=self.function.params,
            register_count=self.register_count,
            code=tuple(self.code),
            constants=tuple(self.constants.values),
            line_table=tuple(self.lines),
            positions=tuple(self.positions),
        )

    def _emit(self, instruction: Instruction) -> None:
        position = instruction.position
        if isinstance(instruction, Label):
            if instruction.name in self.labels:
                raise UnsupportedSyntax(f"Duplicate bytecode label {instruction.name!r}.", position)
            self.labels[instruction.name] = len(self.code)
            return
        if isinstance(instruction, LoadConst):
            bx = self._constant(instruction.value, position)
            self._word(encode_abx(Op.LOAD_K, instruction.dst, bx), position)
            return
        if isinstance(instruction, LoadLocal):
            self._word(
                encode_abc(Op.LOAD_L, instruction.dst, instruction.slot, 0),
                position,
            )
            return
        if isinstance(instruction, StoreLocal):
            self._word(
                encode_abc(Op.STORE_L, instruction.slot, instruction.src, 0),
                position,
            )
            return
        if isinstance(instruction, LoadGlobal):
            bx = self._constant(instruction.name, position)
            self._word(encode_abx(Op.LOAD_G, instruction.dst, bx), position)
            return
        if isinstance(instruction, StoreGlobal):
            bx = self._constant(instruction.name, position)
            self._word(encode_abx(Op.STORE_G, instruction.src, bx), position)
            return
        if isinstance(instruction, DefineFunction):
            self._word(encode_abx(Op.DEF_FUN, 0, instruction.function_index), position)
            return
        if isinstance(instruction, Move):
            self._word(
                encode_abc(Op.MOVE, instruction.dst, instruction.src, 0),
                position,
            )
            return
        if isinstance(instruction, BinOp):
            opcode = BINARY_OPCODES.get(instruction.op)
            if opcode is None:
                raise UnsupportedSyntax(
                    f"Bytecode backend does not support operator {instruction.op!r}.",
                    position,
                )
            self._word(
                encode_abc(opcode, instruction.dst, instruction.lhs, instruction.rhs),
                position,
            )
            return
        if isinstance(instruction, UnOp):
            opcode = UNARY_OPCODES.get(instruction.op)
            if opcode is None:
                raise UnsupportedSyntax(
                    f"Bytecode backend does not support unary operator {instruction.op!r}.",
                    position,
                )
            self._word(
                encode_abc(opcode, instruction.dst, instruction.operand, 0),
                position,
            )
            return
        if isinstance(instruction, Jump):
            self._emit_jump(Op.JUMP, 0, instruction.target, position)
            return
        if isinstance(instruction, JumpIfFalse):
            self._emit_jump(Op.JUMP_FALSE, instruction.src, instruction.target, position)
            return
        if isinstance(instruction, JumpIfTrue):
            self._emit_jump(Op.JUMP_TRUE, instruction.src, instruction.target, position)
            return
        if isinstance(instruction, (BuildList, BuildTuple, BuildSet)):
            opcode = {
                "BuildList": Op.NEW_LIST,
                "BuildTuple": Op.NEW_TUPLE,
                "BuildSet": Op.NEW_SET,
            }[type(instruction).__name__]
            self._emit_build(opcode, instruction.dst, instruction.elements, position)
            return
        if isinstance(instruction, BuildDict):
            values = tuple(reg for pair in instruction.items for reg in pair)
            self._emit_build(
                Op.NEW_DICT,
                instruction.dst,
                values,
                position,
                count=len(instruction.items),
            )
            return
        if isinstance(instruction, BuildSlice):
            base = self.scratch_base
            flags = 0
            for index, register in enumerate(
                (instruction.start, instruction.stop, instruction.step)
            ):
                if register is not None:
                    self._word(
                        encode_abc(Op.MOVE, base + index, register, 0),
                        position,
                    )
                    flags |= 1 << index
            self._word(
                encode_abc(Op.BUILD_SLICE, instruction.dst, base, flags),
                position,
            )
            return
        if isinstance(instruction, GetAttr):
            bx = self._constant(instruction.name, position)
            base = self.scratch_base
            self._word(encode_abc(Op.MOVE, base, instruction.value, 0), position)
            self._word(encode_abx(Op.GET_ATTR, base, bx), position)
            self._word(encode_abc(Op.MOVE, instruction.dst, base, 0), position)
            return
        if isinstance(instruction, SetAttr):
            bx = self._constant(instruction.name, position)
            base = self.scratch_base
            self._word(encode_abc(Op.MOVE, base, instruction.value, 0), position)
            self._word(encode_abc(Op.MOVE, base + 1, instruction.src, 0), position)
            self._word(encode_abx(Op.SET_ATTR, base, bx), position)
            return
        if isinstance(instruction, GetItem):
            self._word(
                encode_abc(
                    Op.GET_ITEM,
                    instruction.dst,
                    instruction.container,
                    instruction.index,
                ),
                position,
            )
            return
        if isinstance(instruction, SetItem):
            self._word(
                encode_abc(
                    Op.SET_ITEM,
                    instruction.container,
                    instruction.index,
                    instruction.src,
                ),
                position,
            )
            return
        if isinstance(instruction, Call):
            self._emit_call(instruction, position)
            return
        if isinstance(instruction, Return):
            self._word(encode_abc(Op.RET, instruction.src, 0, 0), position)
            return
        if isinstance(instruction, OpenIterator):
            self._word(
                encode_abc(
                    Op.OPEN_ITER,
                    instruction.dst,
                    instruction.iterable,
                    0,
                ),
                position,
            )
            return
        if isinstance(instruction, IteratorNext):
            if self.scratch < 1:
                raise UnsupportedSyntax(
                    "Bytecode iterator scratch register is unavailable.", position
                )
            valid = self.scratch_base
            self._word(
                encode_abc(
                    Op.ITER_NEXT,
                    instruction.value_dst,
                    instruction.iterator,
                    valid,
                ),
                position,
            )
            self._emit_jump(Op.JUMP_FALSE, valid, instruction.done, position)
            return
        raise UnsupportedSyntax(
            f"Bytecode backend does not support HIR {type(instruction).__name__}.",
            position,
        )

    def _emit_build(
        self,
        opcode: Op,
        dst: int,
        values: tuple[int, ...],
        position: SourcePosition,
        *,
        count: int | None = None,
    ) -> None:
        item_count = len(values) if count is None else count
        if item_count > 0xFF:
            raise UnsupportedSyntax("Collection literal has more than 255 elements.", position)
        base = self.scratch_base
        for index, register in enumerate(values):
            self._word(encode_abc(Op.MOVE, base + index, register, 0), position)
        self._word(encode_abc(opcode, dst, base, item_count), position)

    def _emit_call(self, instruction: Call, position: SourcePosition) -> None:
        nargs = len(instruction.args)
        if nargs > 0xFF:
            raise UnsupportedSyntax("Call has more than 255 arguments.", position)
        base = self.scratch_base
        self._word(encode_abc(Op.MOVE, base, instruction.callee, 0), position)
        for index, arg in enumerate(instruction.args):
            self._word(encode_abc(Op.MOVE, base + 1 + index, arg, 0), position)
        self._word(encode_abc(Op.CALL, base, 0, nargs), position)
        self._word(encode_abc(Op.MOVE, instruction.dst, base, 0), position)

    def _emit_jump(
        self,
        op: Op,
        a: int,
        label: str,
        position: SourcePosition,
    ) -> None:
        index = len(self.code)
        self._word(encode_asbx(op, a, 0), position)
        self.fixups.append(_Fixup(word_index=index, op=op, a=a, label=label))

    def _patch(self) -> None:
        for fixup in self.fixups:
            target = self.labels.get(fixup.label)
            if target is None:
                raise UnsupportedSyntax(
                    f"Missing bytecode label {fixup.label!r}.",
                    self.positions[fixup.word_index],
                )
            offset = target - (fixup.word_index + 1)
            try:
                self.code[fixup.word_index] = encode_asbx(fixup.op, fixup.a, offset)
            except ValueError as exc:
                raise UnsupportedSyntax(
                    f"Bytecode jump is out of range: {exc}.",
                    self.positions[fixup.word_index],
                ) from exc

    def _constant(self, value: object, position: SourcePosition) -> int:
        try:
            return self.constants.add(value)
        except ValueError as exc:
            raise UnsupportedSyntax(f"Bytecode constant error: {exc}.", position) from exc

    def _word(self, word: int, position: SourcePosition) -> None:
        self.code.append(word)
        self.lines.append(position.start_line)
        self.positions.append(position)


def compile_module(module: HirModule) -> BytecodeModule:
    """Compile HIR into bytecode protos (main + top-level functions)."""
    functions = tuple(_ProtoCompiler(function, module).compile() for function in module.functions)
    main = _ProtoCompiler(module.main, module).compile()
    return BytecodeModule(main=main, functions=functions)
