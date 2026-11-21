#! /usr/bin/env python

"""Low-level, backend-neutral HIR for the shared bytecode pipeline.

The HIR is a linear register instruction list, not an AST wrapper. Dialect
specific constructs must be lowered (or rejected) before this layer.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from ..runtime.call_protocol import SignatureSpec

if TYPE_CHECKING:
    from ..source.source_position import SourcePosition


@dataclasses.dataclass(frozen=True, slots=True)
class Instruction:
    position: SourcePosition


@dataclasses.dataclass(frozen=True, slots=True)
class LoadConst(Instruction):
    dst: int
    value: object


@dataclasses.dataclass(frozen=True, slots=True)
class LoadLocal(Instruction):
    dst: int
    slot: int


@dataclasses.dataclass(frozen=True, slots=True)
class StoreLocal(Instruction):
    slot: int
    src: int


@dataclasses.dataclass(frozen=True, slots=True)
class FreshLocals(Instruction):
    """Replace per-iteration local cells at the top of a loop body."""

    slots: tuple[int, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class LoadOuter(Instruction):
    dst: int
    depth: int
    slot: int


@dataclasses.dataclass(frozen=True, slots=True)
class StoreOuter(Instruction):
    depth: int
    slot: int
    src: int


@dataclasses.dataclass(frozen=True, slots=True)
class MakeClosure(Instruction):
    dst: int
    function_index: int


@dataclasses.dataclass(frozen=True, slots=True)
class LoadGlobal(Instruction):
    dst: int
    name: str


@dataclasses.dataclass(frozen=True, slots=True)
class StoreGlobal(Instruction):
    name: str
    src: int


@dataclasses.dataclass(frozen=True, slots=True)
class DefineFunction(Instruction):
    name: str
    function_index: int


@dataclasses.dataclass(frozen=True, slots=True)
class BuildClass(Instruction):
    dst: int
    name: str
    bases: tuple[int, ...]
    methods: tuple[tuple[str, int], ...]
    slots: tuple[tuple[str, bool, int | None], ...] = ()
    class_methods: tuple[tuple[str, int], ...] = ()
    operators: tuple[tuple[str, int, int], ...] = ()
    metaclass: int | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class Pattern:
    """Serializable match-pattern descriptor."""

    kind: str
    name: str = ""
    args: tuple[Pattern, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class MatchArm:
    pattern: Pattern
    function_index: int


@dataclasses.dataclass(frozen=True, slots=True)
class Match(Instruction):
    dst: int
    scrutinee: int
    arms: tuple[MatchArm, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class BuildEnum(Instruction):
    dst: int
    name: str
    constructors: tuple[tuple[str, int], ...]


@dataclasses.dataclass(frozen=True, slots=True)
class ImportModule(Instruction):
    module_path: str
    alias: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class ImportFrom(Instruction):
    module_path: str
    names: tuple[tuple[str, str | None], ...]


@dataclasses.dataclass(frozen=True, slots=True)
class Move(Instruction):
    dst: int
    src: int


@dataclasses.dataclass(frozen=True, slots=True)
class BinOp(Instruction):
    dst: int
    op: str
    lhs: int
    rhs: int


@dataclasses.dataclass(frozen=True, slots=True)
class UnOp(Instruction):
    dst: int
    op: str
    operand: int


@dataclasses.dataclass(frozen=True, slots=True)
class Jump(Instruction):
    target: str


@dataclasses.dataclass(frozen=True, slots=True)
class JumpIfFalse(Instruction):
    src: int
    target: str


@dataclasses.dataclass(frozen=True, slots=True)
class JumpIfTrue(Instruction):
    src: int
    target: str


@dataclasses.dataclass(frozen=True, slots=True)
class Label(Instruction):
    name: str


@dataclasses.dataclass(frozen=True, slots=True)
class BuildList(Instruction):
    dst: int
    elements: tuple[int, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class BuildTuple(Instruction):
    dst: int
    elements: tuple[int, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class BuildSet(Instruction):
    dst: int
    elements: tuple[int, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class BuildDict(Instruction):
    dst: int
    items: tuple[tuple[int, int], ...]


@dataclasses.dataclass(frozen=True, slots=True)
class BuildSlice(Instruction):
    dst: int
    start: int | None
    stop: int | None
    step: int | None


@dataclasses.dataclass(frozen=True, slots=True)
class GetAttr(Instruction):
    dst: int
    value: int
    name: str


@dataclasses.dataclass(frozen=True, slots=True)
class RegisterExtension(Instruction):
    receiver: int
    name: str
    function_index: int
    symbol: str | None = None
    operand_count: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class SuperProxy(Instruction):
    dst: int
    receiver: int


@dataclasses.dataclass(frozen=True, slots=True)
class SetAttr(Instruction):
    value: int
    name: str
    src: int


@dataclasses.dataclass(frozen=True, slots=True)
class GetItem(Instruction):
    dst: int
    container: int
    index: int


@dataclasses.dataclass(frozen=True, slots=True)
class SetItem(Instruction):
    container: int
    index: int
    src: int


@dataclasses.dataclass(frozen=True, slots=True)
class Call(Instruction):
    dst: int
    callee: int
    args: tuple[int, ...]
    keywords: tuple[tuple[str, int], ...] = ()
    block: int | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class Return(Instruction):
    src: int


@dataclasses.dataclass(frozen=True, slots=True)
class OpenIterator(Instruction):
    dst: int
    iterable: int


@dataclasses.dataclass(frozen=True, slots=True)
class IteratorNext(Instruction):
    value_dst: int
    iterator: int
    done: str


@dataclasses.dataclass(frozen=True, slots=True)
class Unpack(Instruction):
    source: int
    base: int
    count: int


@dataclasses.dataclass(frozen=True, slots=True)
class HirFunction:
    name: str
    params: tuple[str, ...]
    local_count: int
    code: tuple[Instruction, ...]
    position: SourcePosition
    is_main: bool = False
    is_lambda: bool = False
    has_this: bool = False
    signature: SignatureSpec = dataclasses.field(default_factory=lambda: SignatureSpec(()))


@dataclasses.dataclass(frozen=True, slots=True)
class HirModule:
    main: HirFunction
    functions: tuple[HirFunction, ...]


def register_reads(instruction: Instruction) -> tuple[int, ...]:
    """Registers read by an instruction."""
    if isinstance(instruction, (LoadLocal,)):
        return ()
    if isinstance(instruction, (LoadConst, LoadGlobal, Label, Jump, DefineFunction, FreshLocals)):
        return ()
    if isinstance(instruction, BuildClass):
        return instruction.bases
    if isinstance(instruction, Match):
        return (instruction.scrutinee,)
    if isinstance(instruction, LoadOuter):
        return ()
    if isinstance(instruction, StoreOuter):
        return (instruction.src,)
    if isinstance(instruction, MakeClosure):
        return ()
    if isinstance(instruction, (StoreLocal,)):
        return (instruction.src,)
    if isinstance(instruction, StoreGlobal):
        return (instruction.src,)
    if isinstance(instruction, Move):
        return (instruction.src,)
    if isinstance(instruction, BinOp):
        return (instruction.lhs, instruction.rhs)
    if isinstance(instruction, UnOp):
        return (instruction.operand,)
    if isinstance(instruction, (JumpIfFalse, JumpIfTrue)):
        return (instruction.src,)
    if isinstance(instruction, (BuildList, BuildTuple, BuildSet)):
        return instruction.elements
    if isinstance(instruction, BuildDict):
        return tuple(reg for pair in instruction.items for reg in pair)
    if isinstance(instruction, BuildSlice):
        return tuple(
            reg
            for reg in (instruction.start, instruction.stop, instruction.step)
            if reg is not None
        )
    if isinstance(instruction, GetAttr):
        return (instruction.value,)
    if isinstance(instruction, SuperProxy):
        return (instruction.receiver,)
    if isinstance(instruction, RegisterExtension):
        return (instruction.receiver,)
    if isinstance(instruction, SetAttr):
        return (instruction.value, instruction.src)
    if isinstance(instruction, GetItem):
        return (instruction.container, instruction.index)
    if isinstance(instruction, SetItem):
        return (instruction.container, instruction.index, instruction.src)
    if isinstance(instruction, Call):
        return (
            instruction.callee,
            *instruction.args,
            *(reg for _, reg in instruction.keywords),
            *((instruction.block,) if instruction.block is not None else ()),
        )
    if isinstance(instruction, Return):
        return (instruction.src,)
    if isinstance(instruction, OpenIterator):
        return (instruction.iterable,)
    if isinstance(instruction, IteratorNext):
        return (instruction.iterator,)
    if isinstance(instruction, Unpack):
        return (instruction.source,)
    return ()


def register_writes(instruction: Instruction) -> tuple[int, ...]:
    """Registers written by an instruction."""
    if isinstance(
        instruction,
        (
            LoadConst,
            LoadLocal,
            LoadGlobal,
            Move,
            BinOp,
            UnOp,
            Call,
            OpenIterator,
            BuildList,
            BuildTuple,
            BuildSet,
            BuildDict,
            BuildSlice,
            GetAttr,
            GetItem,
            SuperProxy,
            LoadOuter,
            MakeClosure,
            BuildClass,
            BuildEnum,
            Match,
        ),
    ):
        return (instruction.dst,)
    if isinstance(instruction, IteratorNext):
        return (instruction.value_dst,)
    if isinstance(instruction, Unpack):
        return tuple(range(instruction.base, instruction.base + instruction.count))
    return ()


def validate_module(module: HirModule) -> None:
    """Assert structural invariants; raise ValueError on invalid HIR."""
    functions = (module.main, *module.functions)
    for function in functions:
        if function.local_count < 0 or function.local_count > 256:
            raise ValueError(f"{function.name}: invalid local_count {function.local_count}")
        labels: set[str] = set()
        targets: list[str] = []
        for instruction in function.code:
            if isinstance(instruction, Label):
                if instruction.name in labels:
                    raise ValueError(f"{function.name}: duplicate label {instruction.name}")
                labels.add(instruction.name)
            elif isinstance(instruction, (Jump, JumpIfFalse, JumpIfTrue)):
                targets.append(instruction.target)
            elif isinstance(instruction, IteratorNext):
                targets.append(instruction.done)
            elif isinstance(instruction, (DefineFunction, MakeClosure, RegisterExtension)):
                if not 0 <= instruction.function_index < len(module.functions):
                    raise ValueError(
                        f"{function.name}: bad function index {instruction.function_index}"
                    )
            elif isinstance(instruction, Match):
                for arm in instruction.arms:
                    if not 0 <= arm.function_index < len(module.functions):
                        raise ValueError(
                            f"{function.name}: bad match arm index {arm.function_index}"
                        )
            elif isinstance(instruction, BuildClass):
                for method_name, method_index in instruction.methods:
                    if not 0 <= method_index < len(module.functions):
                        raise ValueError(
                            f"{function.name}: bad method index {method_index} for {method_name!r}"
                        )
                for slot_name, _, initializer in instruction.slots:
                    if initializer is not None and not 0 <= initializer < len(module.functions):
                        raise ValueError(
                            f"{function.name}: bad slot initializer index {initializer} "
                            f"for {slot_name!r}"
                        )
            if isinstance(instruction, FreshLocals):
                for slot in instruction.slots:
                    if not 0 <= slot < function.local_count:
                        raise ValueError(
                            f"{function.name}: fresh local slot {slot} outside local_count"
                        )
            if isinstance(instruction, (LoadOuter, StoreOuter)):
                if instruction.depth < 1:
                    raise ValueError(f"{function.name}: invalid outer depth {instruction.depth}")
                if not 0 <= instruction.slot < 256:
                    raise ValueError(f"{function.name}: invalid outer slot {instruction.slot}")
            for reg in (*register_reads(instruction), *register_writes(instruction)):
                if not 0 <= reg < function.local_count:
                    raise ValueError(
                        f"{function.name}: register R{reg} outside 0..{function.local_count - 1}"
                    )
        for target in targets:
            if target not in labels:
                raise ValueError(f"{function.name}: missing label {target}")
