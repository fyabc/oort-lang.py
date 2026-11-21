#! /usr/bin/env python

"""End-to-end command-line tests."""

import subprocess
import sys

import pytest

from oort_lang import __version__
from oort_lang.driver.main import main


def _run_cli(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["oort", *argv])
    with pytest.raises(SystemExit) as exc_info:
        main()
    return exc_info.value.code


def test_cmd_uses_eval_by_default(monkeypatch, capsys):
    assert _run_cli(monkeypatch, ["-c", "print(42)"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "42\n"


def test_file_input(monkeypatch, capsys, tmp_path):
    src = tmp_path / "hello.ort"
    src.write_text('print("hello")\n', encoding="utf-8")
    assert _run_cli(monkeypatch, [str(src)]) == 0
    assert capsys.readouterr().out == "hello\n"


def test_print_ast_target(monkeypatch, capsys):
    assert _run_cli(monkeypatch, ["-t", "ast", "-c", "print(1)"]) == 0
    out = capsys.readouterr().out
    assert "Module" in out
    assert "Call" in out


def test_vm_target_executes_supported_program(monkeypatch, capsys):
    source = """\
def fib(n) {
    if n <= 1: return n
    fib(n - 1) + fib(n - 2)
}
print(fib(10))
"""
    assert _run_cli(monkeypatch, ["-t", "vm", "-c", source]) == 0
    assert capsys.readouterr().out == "55\n"


def test_bytecode_target_prints_disassembly(monkeypatch, capsys):
    source = """\
def f(a) { a + 1 }
print(f(2))
"""
    assert _run_cli(monkeypatch, ["-t", "bc", "-c", source]) == 0
    out = capsys.readouterr().out
    assert "Proto <main>" in out
    assert "Proto f" in out
    assert "DEF_FUN" in out
    assert "CALL" in out


def test_bytecode_target_rejects_unsupported_syntax(monkeypatch, caplog):
    assert _run_cli(monkeypatch, ["-t", "bc", "-c", "class C {}\n"]) != 0
    assert "HIR backend does not support ClassDef" in caplog.text


def test_print_ast_with_metadata(monkeypatch, capsys):
    assert _run_cli(monkeypatch, ["-t", "astm", "-c", "print(1)"]) == 0
    out = capsys.readouterr().out
    assert "Module" in out
    assert "[Metadata]" in out


def test_parse_error_exits_nonzero(monkeypatch, caplog):
    assert _run_cli(monkeypatch, ["-c", "print("]) != 0
    assert "OortSyntaxError" in caplog.text


def test_version(monkeypatch, capsys):
    assert _run_cli(monkeypatch, ["--version"]) == 0
    assert f"Oort {__version__}" in capsys.readouterr().out


def test_core_dialect_runs(monkeypatch, capsys):
    source = "#lang oort-core\ndef f(x: Int) -> Int { x + 1 }\nprint(f(1))\n"
    assert _run_cli(monkeypatch, ["-c", source]) == 0
    assert capsys.readouterr().out == "2\n"


def test_core_type_error_exits_nonzero(monkeypatch, caplog):
    source = "#lang oort-core\nvar x: Bool = 1\n"
    assert _run_cli(monkeypatch, ["-c", source]) != 0
    assert "TypeCheckError" in caplog.text


def test_core_ast_target_skips_checking(monkeypatch, capsys):
    source = "#lang oort-core\nvar x: Bool = 1\n"
    assert _run_cli(monkeypatch, ["-t", "ast", "-c", source]) == 0
    assert "VarDecl" in capsys.readouterr().out


def test_core_astm_shows_types(monkeypatch, capsys):
    source = "#lang oort-core\nvar x = 1\nprint(x)\n"
    assert _run_cli(monkeypatch, ["-t", "astm", "-c", source]) == 0
    assert "type='Int'" in capsys.readouterr().out


def test_core_astm_shows_class_types(monkeypatch, capsys):
    source = """#lang oort-core
class C {
    val x: Int = 1
}
val c = C()
"""
    assert _run_cli(monkeypatch, ["-t", "astm", "-c", source]) == 0
    out = capsys.readouterr().out
    assert "ClassDef" in out
    assert "type='C'" in out


def test_core_astm_shows_collection_types(monkeypatch, capsys):
    source = """#lang oort-core
val xs = [1, 2]
val pair = (1, true)
"""
    assert _run_cli(monkeypatch, ["-t", "astm", "-c", source]) == 0
    out = capsys.readouterr().out
    assert "type='List[Int]'" in out
    assert "type='Tuple[Int, Bool]'" in out


def test_core_astm_shows_float_and_string_types(monkeypatch, capsys):
    source = """\
#lang oort-core
val x = 1.5
val s = "a" + "b"
"""
    assert _run_cli(monkeypatch, ["-t", "astm", "-c", source]) == 0
    out = capsys.readouterr().out
    assert "type='Float'" in out
    assert "type='String'" in out


def test_core_module_import_from_file(monkeypatch, capsys, tmp_path):
    (tmp_path / "lib.ort").write_text(
        "#lang oort-core\ndef add(a: Int, b: Int) -> Int { a + b }\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.ort"
    main.write_text(
        '#lang oort-core\nfrom "./lib" import add\nprint(add(2, 3))\n',
        encoding="utf-8",
    )
    assert _run_cli(monkeypatch, [str(main)]) == 0
    assert capsys.readouterr().out == "5\n"


def test_relative_import_from_file(monkeypatch, capsys, tmp_path):
    (tmp_path / "lib.ort").write_text("var value = 21\n", encoding="utf-8")
    main = tmp_path / "main.ort"
    main.write_text('import "./lib"\nprint(lib.value * 2)\n', encoding="utf-8")

    assert _run_cli(monkeypatch, [str(main)]) == 0
    assert capsys.readouterr().out == "42\n"


def test_module_path_option(monkeypatch, capsys, tmp_path):
    libs = tmp_path / "libs"
    libs.mkdir()
    (libs / "extra.ort").write_text("var value = 7\n", encoding="utf-8")
    main = tmp_path / "main.ort"
    main.write_text('import "extra"\nprint(extra.value)\n', encoding="utf-8")

    assert _run_cli(monkeypatch, ["-I", str(libs), str(main)]) == 0
    assert capsys.readouterr().out == "7\n"


def test_import_failure_exits_nonzero(monkeypatch, caplog, tmp_path):
    main = tmp_path / "main.ort"
    main.write_text('import "./missing"\n', encoding="utf-8")

    assert _run_cli(monkeypatch, [str(main)]) != 0
    assert "Cannot find module './missing'" in caplog.text


def test_print_ast_shows_import(monkeypatch, capsys, tmp_path):
    main = tmp_path / "main.ort"
    main.write_text('import "./lib" as l\n', encoding="utf-8")

    assert _run_cli(monkeypatch, ["-t", "ast", str(main)]) == 0
    assert "ImportStmt(module_path='./lib', alias='l')" in capsys.readouterr().out


def _run_repl_subprocess(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "oort_lang"],
        input=stdin,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def test_repl_piped_input_evaluates_and_eof_exits_cleanly():
    proc = _run_repl_subprocess("1 + 2\nprint(4)\n")
    assert proc.returncode == 0
    assert "Out[0]: 3" in proc.stdout
    assert "4\n" in proc.stdout
    assert "Traceback" not in proc.stdout
    assert "Traceback" not in proc.stderr


def test_repl_piped_multiline_input():
    proc = _run_repl_subprocess("var xs = [\n1,\n2,\n]\nprint(xs[1])\n")
    assert proc.returncode == 0
    assert "2\n" in proc.stdout
    assert "Traceback" not in proc.stderr


def test_repl_piped_error_recovers():
    proc = _run_repl_subprocess("1 +\nprint(7)\n")
    assert proc.returncode == 0
    assert "7\n" in proc.stdout
    assert "Traceback" not in proc.stdout
    assert "Traceback" not in proc.stderr


def test_repl_empty_piped_input_exits_zero():
    proc = _run_repl_subprocess("")
    assert proc.returncode == 0
    assert "Traceback" not in proc.stderr


def test_repl_incomplete_input_at_eof_reports_syntax_error():
    proc = _run_repl_subprocess("print(\n")
    assert proc.returncode == 0
    assert "Invalid syntax" in proc.stdout
    assert "Traceback" not in proc.stdout
    assert "Traceback" not in proc.stderr


def test_print_ast_with_metadata_accepts_import(monkeypatch, capsys, tmp_path):
    main = tmp_path / "main.ort"
    main.write_text('from "./lib" import value\n', encoding="utf-8")

    assert _run_cli(monkeypatch, ["-t", "astm", str(main)]) == 0
    assert "ImportFromStmt(module_path='./lib', names=[value])" in capsys.readouterr().out


def test_core_enum_match_eval(monkeypatch, capsys):
    source = "#lang oort-core\nenum E { A, B(x: Int) }\nprint(match B(3) { A => 0, B(v) => v })\n"
    assert _run_cli(monkeypatch, ["-c", source]) == 0
    assert capsys.readouterr().out == "3\n"


def test_core_enum_match_astm(monkeypatch, capsys):
    source = "#lang oort-core\nenum E { A }\nval x = match A { A => 1 }\n"
    assert _run_cli(monkeypatch, ["-t", "astm", "-c", source]) == 0
    out = capsys.readouterr().out
    assert "EnumDef" in out
    assert "MatchExpr" in out
    assert "type='Int'" in out
