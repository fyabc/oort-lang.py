#! /usr/bin/env python

"""Human-readable HIR dumps used by tests and debugging."""

from oort_lang.hir import (
    BinOp,
    BuildClass,
    BuildDict,
    BuildEnum,
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
    ImportFrom,
    ImportModule,
    Instruction,
    IteratorNext,
    Jump,
    JumpIfFalse,
    JumpIfTrue,
    Label,
    LoadConst,
    LoadGlobal,
    LoadLocal,
    LoadOuter,
    MakeClosure,
    Match,
    MatchArm,
    Move,
    OpenIterator,
    Pattern,
    Return,
    SetAttr,
    SetItem,
    StoreGlobal,
    StoreLocal,
    StoreOuter,
    UnOp,
    format_function,
    format_instruction,
    format_module,
)
from oort_lang.source.source_position import SourcePosition


def pos() -> SourcePosition:
    return SourcePosition.from_location(1, 0, "<dump>")


def test_every_instruction_has_a_readable_dump():
    p = pos()
    instructions: list[tuple[Instruction, str]] = [
        (LoadConst(p, 0, 1), "LOAD_K R0 1"),
        (LoadLocal(p, 0, 1), "LOAD_L R0 slot1"),
        (StoreLocal(p, 1, 0), "STORE_L slot1 R0"),
        (LoadOuter(p, 0, 1, 2), "LOAD_OUTER R0 depth=1 slot=2"),
        (StoreOuter(p, 1, 2, 0), "STORE_OUTER depth=1 slot=2 R0"),
        (MakeClosure(p, 0, 1), "MAKE_CLOSURE R0 proto[1]"),
        (
            BuildClass(
                p,
                0,
                "C",
                (2,),
                (("f", 3),),
                (("x", False, 4), ("y", True, None)),
            ),
            "BUILD_CLASS R0 C bases=(R2) f=proto[3] slots=(x=proto[4], y)",
        ),
        (BuildEnum(p, 0, "E", (("A", 1), ("B", 0))), "BUILD_ENUM R0 E (A/1, B/0)"),
        (
            Match(
                p,
                0,
                1,
                (
                    MatchArm(Pattern("constructor", "A", (Pattern("name", "v"),)), 2),
                    MatchArm(Pattern("name", "B"), 3),
                ),
            ),
            "MATCH R0 R1 (constructor:A=proto[2], name:B=proto[3])",
        ),
        (ImportModule(p, "./lib", "l"), "IMPORT ./lib as l"),
        (ImportModule(p, "./lib"), "IMPORT ./lib"),
        (ImportFrom(p, "./lib", (("a", None), ("b", "c"))), "IMPORT_FROM ./lib (a, b as c)"),
        (LoadGlobal(p, 0, "g"), "LOAD_G R0 g"),
        (StoreGlobal(p, "g", 0), "STORE_G g R0"),
        (DefineFunction(p, "f", 1), "DEF_FUN f proto[1]"),
        (Move(p, 0, 1), "MOVE R0 R1"),
        (BinOp(p, 0, "+", 1, 2), "BINOP R0 + R1 R2"),
        (UnOp(p, 0, "-", 1), "UNOP R0 - R1"),
        (Jump(p, "end"), "JMP end"),
        (JumpIfFalse(p, 0, "end"), "JMP_FALSE R0 end"),
        (JumpIfTrue(p, 0, "end"), "JMP_TRUE R0 end"),
        (Label(p, "end"), "end:"),
        (BuildList(p, 0, (1, 2)), "BUILDLIST R0 (R1, R2)"),
        (BuildTuple(p, 0, (1,)), "BUILDTUPLE R0 (R1)"),
        (BuildSet(p, 0, (1,)), "BUILDSET R0 (R1)"),
        (BuildDict(p, 0, ((1, 2),)), "BUILD_DICT R0 (R1:R2)"),
        (BuildSlice(p, 0, 1, None, 2), "BUILD_SLICE R0 (1, None, 2)"),
        (GetAttr(p, 0, 1, "x"), "GET_ATTR R0 R1.x"),
        (SetAttr(p, 1, "x", 0), "SET_ATTR R1.x = R0"),
        (GetItem(p, 0, 1, 2), "GET_ITEM R0 R1[R2]"),
        (SetItem(p, 1, 2, 0), "SET_ITEM R1[R2] = R0"),
        (Call(p, 0, 1, (2, 3)), "CALL R0 R1(R2, R3)"),
        (
            Call(p, 0, 1, (2,), (("k", 3),), 4),
            "CALL R0 R1(R2, k=R3, block=R4)",
        ),
        (Return(p, 0), "RET R0"),
        (OpenIterator(p, 0, 1), "OPEN_ITER R0 R1"),
        (IteratorNext(p, 0, 1, "done"), "ITER_NEXT R0 R1 -> done"),
    ]
    for instruction, expected in instructions:
        assert format_instruction(instruction) == expected


def test_function_and_module_dumps_include_headers_and_instructions():
    p = pos()
    main = HirFunction("<main>", (), 2, (LoadConst(p, 0, None), Return(p, 0)), p, is_main=True)
    function = HirFunction("f", ("a",), 2, (LoadLocal(p, 0, 0), Return(p, 0)), p)
    module = HirModule(main, (function,))
    text = format_module(module)
    assert "<main>() local_count=2" in text
    assert "LOAD_K R0 None" in text
    assert "f(a) local_count=2" in text
    assert text.index("<main>") < text.index("f(a)")
    assert format_function(function).splitlines()[0] == "f(a) local_count=2"
