#! /usr/bin/env python

"""Bytecode encoding, HIR compilation and disassembly."""

import pytest

from oort_lang.bytecode import (
    Op,
    compile_module,
    decode,
    disassemble_module,
    encode_abc,
    encode_abx,
    encode_asbx,
    encode_ax,
)
from oort_lang.hir import lower_module
from tests.helpers import build_ast


def compile_source(source: str):
    return compile_module(lower_module(build_ast(source)))


def test_abc_abx_asbx_ax_round_trips():
    word = encode_abc(Op.CALL, 1, 2, 3)
    decoded = decode(word)
    assert (decoded.op, decoded.a, decoded.b, decoded.c) == (Op.CALL, 1, 2, 3)

    word = encode_abx(Op.LOAD_K, 4, 0xBEEF)
    decoded = decode(word)
    assert (decoded.op, decoded.a, decoded.bx) == (Op.LOAD_K, 4, 0xBEEF)

    word = encode_asbx(Op.JUMP, 5, -3)
    decoded = decode(word)
    assert (decoded.op, decoded.a, decoded.sbx) == (Op.JUMP, 5, -3)

    word = encode_ax(Op.EXTEND, 0xABCDEF)
    decoded = decode(word)
    assert (decoded.op, decoded.ax) == (Op.EXTEND, 0xABCDEF)


@pytest.mark.parametrize(
    "encode",
    [
        lambda: encode_abc(Op.MOVE, 256, 0, 0),
        lambda: encode_abx(Op.LOAD_K, 0, 0x10000),
        lambda: encode_asbx(Op.JUMP, 0, 0x8000),
        lambda: encode_ax(Op.EXTEND, 0x1000000),
    ],
)
def test_encoding_rejects_out_of_range_operands(encode):
    with pytest.raises(ValueError):
        encode()


def test_fib_compiles_to_valid_bytecode():
    module = compile_source(
        """\
def fib(n) {
    if n <= 1: return n
    fib(n - 1) + fib(n - 2)
}
print(fib(10))
"""
    )
    assert module.main.name == "<main>"
    assert [proto.name for proto in module.functions] == ["fib"]
    for proto in (module.main, *module.functions):
        assert len(proto.code) == len(proto.line_table)
        assert proto.register_count <= 256
        for pc, word in enumerate(proto.code):
            decoded = decode(word)
            if decoded.op in (Op.JUMP, Op.JUMP_FALSE, Op.JUMP_TRUE):
                target = pc + 1 + decoded.sbx
                assert 0 <= target <= len(proto.code)
    assert any(decode(word).op is Op.DEF_FUN for word in module.main.code)


def test_constant_pool_distinguishes_bool_and_int():
    module = compile_source("print(true)\nprint(1)\nprint(1.0)\n")
    constants = module.main.constants
    assert True in constants
    assert 1 in constants
    assert 1.0 in constants
    assert len({(type(value).__name__, repr(value)) for value in constants}) == len(constants)


def test_call_arguments_use_scratch_registers():
    module = compile_source("def f(a, b) { a + b }\nprint(f(1, 2))\n")
    proto = module.main
    call = next(
        decode(word) for word in proto.code if decode(word).op is Op.CALL and decode(word).c == 2
    )
    assert call.a + call.c < proto.register_count


def test_disassembly_mentions_protos_and_calls():
    text = disassemble_module(compile_source("def f(a) { a }\nprint(f(1))\n"))
    assert "Proto <main>" in text
    assert "Proto f" in text
    assert "DEF_FUN" in text
    assert "CALL" in text
    assert "LOAD_G" in text
