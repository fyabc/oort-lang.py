#! /usr/bin/env python

"""Human-readable HIR dumps for tests and debugging."""

from .nodes import (
    BinOp,
    BuildDict,
    BuildList,
    BuildSet,
    BuildTuple,
    Call,
    DefineFunction,
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
    SetItem,
    StoreGlobal,
    StoreLocal,
    UnOp,
)


def format_instruction(instruction: Instruction) -> str:
    if isinstance(instruction, LoadConst):
        return f"LOAD_K R{instruction.dst} {instruction.value!r}"
    if isinstance(instruction, LoadLocal):
        return f"LOAD_L R{instruction.dst} slot{instruction.slot}"
    if isinstance(instruction, StoreLocal):
        return f"STORE_L slot{instruction.slot} R{instruction.src}"
    if isinstance(instruction, LoadGlobal):
        return f"LOAD_G R{instruction.dst} {instruction.name}"
    if isinstance(instruction, StoreGlobal):
        return f"STORE_G {instruction.name} R{instruction.src}"
    if isinstance(instruction, DefineFunction):
        return f"DEF_FUN {instruction.name} proto[{instruction.function_index}]"
    if isinstance(instruction, Move):
        return f"MOVE R{instruction.dst} R{instruction.src}"
    if isinstance(instruction, BinOp):
        return f"BINOP R{instruction.dst} {instruction.op} R{instruction.lhs} R{instruction.rhs}"
    if isinstance(instruction, UnOp):
        return f"UNOP R{instruction.dst} {instruction.op} R{instruction.operand}"
    if isinstance(instruction, Jump):
        return f"JMP {instruction.target}"
    if isinstance(instruction, JumpIfFalse):
        return f"JMP_FALSE R{instruction.src} {instruction.target}"
    if isinstance(instruction, JumpIfTrue):
        return f"JMP_TRUE R{instruction.src} {instruction.target}"
    if isinstance(instruction, Label):
        return f"{instruction.name}:"
    if isinstance(instruction, (BuildList, BuildTuple, BuildSet)):
        values = ", ".join(f"R{value}" for value in instruction.elements)
        return f"{type(instruction).__name__.upper()} R{instruction.dst} ({values})"
    if isinstance(instruction, BuildDict):
        values = ", ".join(f"R{key}:R{value}" for key, value in instruction.items)
        return f"BUILD_DICT R{instruction.dst} ({values})"
    if isinstance(instruction, GetItem):
        return f"GET_ITEM R{instruction.dst} R{instruction.container}[R{instruction.index}]"
    if isinstance(instruction, SetItem):
        return f"SET_ITEM R{instruction.container}[R{instruction.index}] = R{instruction.src}"
    if isinstance(instruction, Call):
        args = ", ".join(f"R{arg}" for arg in instruction.args)
        return f"CALL R{instruction.dst} R{instruction.callee}({args})"
    if isinstance(instruction, Return):
        return f"RET R{instruction.src}"
    if isinstance(instruction, OpenIterator):
        return f"OPEN_ITER R{instruction.dst} R{instruction.iterable}"
    if isinstance(instruction, IteratorNext):
        return f"ITER_NEXT R{instruction.value_dst} R{instruction.iterator} -> {instruction.done}"
    return type(instruction).__name__


def format_function(function: HirFunction) -> str:
    params = ", ".join(function.params)
    header = f"{function.name}({params}) local_count={function.local_count}"
    lines = [header]
    for index, instruction in enumerate(function.code):
        lines.append(f"  {index:4d}  {format_instruction(instruction)}")
    return "\n".join(lines)


def format_module(module: HirModule) -> str:
    lines = [format_function(module.main)]
    for function in module.functions:
        lines.append("")
        lines.append(format_function(function))
    return "\n".join(lines)
