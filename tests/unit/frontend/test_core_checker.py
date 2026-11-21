#! /usr/bin/env python

"""Positive and rejection tests for the `oort-core` type checker."""

import pytest

from tests.helpers import get_compiler


def core(source: str) -> str:
    return "#lang oort-core\n" + source


def check_error(caplog: pytest.LogCaptureFixture, source: str, message: str) -> None:
    compiler = get_compiler("NOT_EXIST -t eval")
    with pytest.raises(SystemExit):
        compiler.run_string(core(source))
    assert message in caplog.text


class TestCorePositive:
    def test_literals_and_print(self, run_source):
        result = run_source(core("print(1)\nprint(true)\nprint()\n"))
        assert result.stdout == "1\ntrue\n\n"

    def test_local_inference_and_mutation(self, run_source):
        result = run_source(core("var x = 1\nx = x + 2\nprint(x)\n"))
        assert result.stdout == "3\n"

    def test_annotated_declarations(self, run_source):
        result = run_source(
            core("var count: Int = 1\nval enabled: Bool = true\nprint(count)\nprint(enabled)\n")
        )
        assert result.stdout == "1\ntrue\n"

    def test_operators(self, run_source):
        result = run_source(
            core(
                "print((1 + 2) * 3 // 2 % 5)\n"
                "print(1 < 2)\n"
                "print(1 == 1)\n"
                "print(true != false)\n"
                "print(true and false)\n"
                "print(true or false)\n"
                "print(not false)\n"
                "print(-1)\n"
            )
        )
        assert result.stdout == "4\ntrue\ntrue\ntrue\nfalse\ntrue\ntrue\n-1\n"

    def test_float_arithmetic_and_division(self, run_source):
        result = run_source(
            core(
                "val half = 5 / 2\n"
                "val mixed = 1 + 2.5\n"
                "print(half)\n"
                "print(mixed * 2.0)\n"
                "print(5 // 2.0, 5 % 2.0)\n"
                "print(-1.5)\n"
            )
        )
        assert result.stdout == "2.5\n7.0\n2.0 1.0\n-1.5\n"

    def test_numeric_comparisons_allow_mixed_int_and_float(self, run_source):
        result = run_source(core("print(1 == 1.0, 1 < 1.5, 2.5 >= 2, 1 != 2.5)\n"))
        assert result.stdout == "true true true true\n"

    def test_string_concatenation_and_comparison(self, run_source):
        result = run_source(
            core(
                'val name: String = "oort"\n'
                'print(name + "!")\n'
                'print("a" < "b", "a" == "a", "a" != "b")\n'
                'print("a" <= "a", "b" > "a")\n'
            )
        )
        assert result.stdout == "oort!\ntrue true true\ntrue true\n"

    def test_float_and_string_annotations_in_functions(self, run_source):
        result = run_source(
            core(
                "def average(a: Float, b: Float) -> Float {\n"
                "    (a + b) / 2.0\n"
                "}\n"
                "def greet(who: String) -> String {\n"
                '    "Hello, " + who\n'
                "}\n"
                "print(average(1.0, 2.0))\n"
                'print(greet("Oort"))\n'
            )
        )
        assert result.stdout == "1.5\nHello, Oort\n"

    def test_functions_and_recursion(self, run_source):
        result = run_source(
            core(
                "def fact(n: Int) -> Int {\n"
                "    if n <= 1 { 1 } else { n * fact(n - 1) }\n"
                "}\n"
                "print(fact(5))\n"
            )
        )
        assert result.stdout == "120\n"

    def test_unit_function(self, run_source):
        result = run_source(core("def show(n: Int) -> Unit {\n    print(n)\n}\nshow(7)\n"))
        assert result.stdout == "7\n"

    def test_if_as_expression(self, run_source):
        result = run_source(core("val x = if true { 1 } else { 2 }\nprint(x)\n"))
        assert result.stdout == "1\n"

    def test_block_scoping(self, run_source):
        result = run_source(core("var x = 1\n{ var x = 2\n  print(x) }\nprint(x)\n"))
        assert result.stdout == "2\n1\n"

    def test_return_on_all_paths(self, run_source):
        result = run_source(
            core(
                "def sign(n: Int) -> Bool {\n"
                "    if n < 0 { return false } else { return true }\n"
                "}\n"
                "print(sign(1))\n"
            )
        )
        assert result.stdout == "true\n"


class TestCoreRejections:
    def test_annotation_mismatch(self, caplog):
        check_error(caplog, "var x: Bool = 1\n", "Expected Bool, got Int.")

    def test_assignment_mismatch(self, caplog):
        check_error(
            caplog,
            "var x = 1\nx = true\n",
            "Expected Int, got Bool.",
        )

    def test_assignment_to_val(self, caplog):
        check_error(
            caplog,
            "val x = 1\nx = 2\n",
            "Cannot assign to immutable binding 'x'",
        )

    def test_assignment_to_parameter(self, caplog):
        check_error(
            caplog,
            "def f(x: Int) -> Int { x = 2\nx }\n",
            "Cannot assign to immutable binding 'x'",
        )

    def test_unknown_name(self, caplog):
        check_error(caplog, "def f() -> Int { missing }\n", "Unknown name 'missing'.")

    def test_duplicate_declaration(self, caplog):
        check_error(
            caplog,
            "val x = 1\nval x = 2\n",
            "Duplicate declaration of 'x'",
        )

    def test_missing_parameter_annotation(self, caplog):
        check_error(
            caplog,
            "def f(x) -> Int { x }\n",
            "Parameter 'x' requires a type annotation",
        )

    def test_missing_return_annotation(self, caplog):
        check_error(
            caplog,
            "def f(x: Int) { x }\n",
            "requires a return type annotation",
        )

    def test_unit_in_variable_annotation(self, caplog):
        check_error(
            caplog,
            "var x: Unit = print(1)\n",
            "Unit is only allowed as a function return type",
        )

    def test_unknown_type_name(self, caplog):
        check_error(
            caplog,
            "var x: Nope = 1\n",
            "Unknown type 'Nope' in oort-core",
        )

    def test_numeric_annotations_do_not_coerce(self, caplog):
        check_error(
            caplog,
            "var x: Float = 1\n",
            "Expected Float, got Int.",
        )

    def test_non_name_annotation(self, caplog):
        check_error(
            caplog,
            "var x: Foo[Int] = 1\n",
            "Generic type applications are only supported for List, Set, Dict and Tuple.",
        )

    def test_if_condition_must_be_bool(self, caplog):
        check_error(
            caplog,
            "if 1 { print(1) }\n",
            "if condition must be Bool",
        )

    def test_function_body_type(self, caplog):
        check_error(
            caplog,
            "def f() -> Int { true }\n",
            "Expected Int, got Bool.",
        )

    def test_function_missing_return_on_some_path(self, caplog):
        check_error(
            caplog,
            "def f(n: Int) -> Int { if n < 0 { return 0 } }\n",
            "An if without else has type Unit, expected Int.",
        )

    def test_bare_return_in_non_unit_function(self, caplog):
        check_error(
            caplog,
            "def f() -> Int { return }\n",
            "a bare return is only allowed for Unit functions",
        )

    def test_value_return_in_unit_function(self, caplog):
        check_error(
            caplog,
            "def f() -> Unit { return 1 }\n",
            "Expected Unit, got Int.",
        )

    def test_call_arity(self, caplog):
        check_error(
            caplog,
            "def f(a: Int, b: Int) -> Int { a + b }\nf(1)\n",
            "Function 'f' expects 2 arguments, got 1.",
        )

    def test_call_argument_type(self, caplog):
        check_error(
            caplog,
            "def f(a: Int) -> Int { a }\nf(true)\n",
            "Expected Int, got Bool.",
        )

    def test_call_non_function(self, caplog):
        check_error(
            caplog,
            "val x = 1\nx(1)\n",
            "'x' is not callable.",
        )

    def test_branch_types_must_match(self, caplog):
        check_error(
            caplog,
            "val x = if true { 1 } else { true }\n",
            "branches of this if have incompatible types",
        )

    def test_branches_do_not_promote_int_to_float(self, caplog):
        check_error(
            caplog,
            "val x = if true { 1 } else { 1.5 }\n",
            "branches of this if have incompatible types",
        )

    def test_arithmetic_requires_numbers_or_strings(self, caplog):
        check_error(
            caplog,
            "def f(x: Int) -> Int { x + true }\n",
            "Operator '+' requires two numbers or two String operands",
        )
        check_error(
            caplog,
            'print(1 - "x")\n',
            "Operator '-' requires two numbers",
        )

    def test_comparison_requires_numbers_or_strings(self, caplog):
        check_error(
            caplog,
            "print(1 < true)\n",
            "requires two numbers or two String operands",
        )

    def test_equality_requires_comparable_types(self, caplog):
        check_error(
            caplog,
            "print(1 == true)\n",
            "requires two numbers, two Bool or two String operands",
        )

    def test_boolean_operators_require_bool(self, caplog):
        check_error(
            caplog,
            "print(true and 1)\n",
            "Expected Bool, got Int.",
        )

    def test_not_requires_bool(self, caplog):
        check_error(
            caplog,
            "print(not 1)\n",
            "Expected Bool, got Int.",
        )

    def test_power_is_rejected(self, caplog):
        check_error(
            caplog,
            "print(2 ** -1)\n",
            "The '**' operator is not supported in oort-core yet",
        )

    def test_unary_bitwise_is_rejected(self, caplog):
        check_error(
            caplog,
            "print(~1)\n",
            "Unary operator '~' is not supported",
        )

    def test_cannot_infer_unit_variable(self, caplog):
        check_error(
            caplog,
            "val x = print(1)\n",
            "Cannot infer a usable type for 'x'",
        )

    def test_augmented_assignment_is_rejected(self, caplog):
        check_error(
            caplog,
            "var x = 1\nx += 1\n",
            "Augmented assignment is not supported in oort-core yet.",
        )

    def test_multi_target_declaration_is_rejected(self, caplog):
        check_error(
            caplog,
            "val x, y = 1, 2\n",
            "Multi-target declarations are not supported in oort-core yet.",
        )

    def test_native_import_is_rejected(self, caplog):
        check_error(
            caplog,
            'import "math"\n',
            "Native modules are not supported in oort-core imports yet.",
        )

    @pytest.mark.parametrize(
        ("source", "message"),
        [
            ("print(null)\n", "null is not supported"),
            (
                "val f = do: 1\n",
                "Lambdas without an explicit parameter list are not supported",
            ),
            ("print([1][0:1])\n", "Slices are not supported"),
            ("print([1].length)\n", "Attribute access is only supported on imported modules"),
        ],
    )
    def test_unsupported_constructs(self, caplog, source: str, message: str):
        check_error(caplog, source, message)

    def test_defaults_are_rejected(self, caplog):
        check_error(
            caplog,
            "def f(x: Int = 1) -> Int { x }\n",
            "Defaults, keyword-only/positional-only markers",
        )

    def test_keyword_arguments_are_rejected(self, caplog):
        check_error(
            caplog,
            "def f(x: Int) -> Int { x }\nf(x = 1)\n",
            "Keyword, variadic and block arguments are not supported",
        )

    def test_error_recovery_reports_independent_errors(self, caplog):
        compiler = get_compiler("NOT_EXIST -t eval")
        with pytest.raises(SystemExit):
            compiler.run_string(core("var a: Bool = 1\nvar b: Int = true\n"))
        assert "Expected Bool, got Int." in caplog.text
        assert "Expected Int, got Bool." in caplog.text

    def test_unsupported_initializer_does_not_cascade(self, caplog):
        compiler = get_compiler("NOT_EXIST -t eval")
        with pytest.raises(SystemExit):
            compiler.run_string(core("var x = null\nprint(x)\n"))
        assert "null is not supported" in caplog.text
        assert "Cannot infer a usable type" not in caplog.text


if __name__ == "__main__":
    pytest.main([__file__])


class TestCoreAdt:
    def test_enum_construction_and_match(self, run_source):
        result = run_source(
            core(
                "enum Shape { Circle(r: Int), Rect(w: Int, h: Int), Empty }\n"
                "val s = Circle(3)\n"
                "print(match s { Circle(r) => r, Rect(w, h) => w * h, Empty => 0 })\n"
            )
        )
        assert result.stdout == "3\n"

    def test_nullary_constructor_and_wildcard(self, run_source):
        result = run_source(
            core(
                "enum Color { Red, Green }\n"
                "print(match Green { Red => 1, Green => 2 })\n"
                "print(match Red { _ => 9 })\n"
            )
        )
        assert result.stdout == "2\n9\n"

    def test_recursive_enum(self, run_source):
        result = run_source(
            core(
                "enum IntList { Cons(head: Int, tail: IntList), Nil }\n"
                "val xs = Cons(1, Cons(2, Nil))\n"
                "def total(xs: IntList) -> Int { "
                "match xs { Cons(h, t) => h + total(t), Nil => 0 } }\n"
                "print(total(xs))\n"
            )
        )
        assert result.stdout == "3\n"

    def test_nested_match(self, run_source):
        result = run_source(
            core(
                "enum Inner { A(x: Int), B }\n"
                "enum Outer { Wrap(inner: Inner), Empty }\n"
                "val o = Wrap(A(7))\n"
                "print(match o { Wrap(inner) => match inner { A(v) => v, B => 0 }, "
                "Empty => -1 })\n"
            )
        )
        assert result.stdout == "7\n"

    def test_print_enum_value(self, run_source):
        result = run_source(core("enum E { A, B(x: Int) }\nprint(A)\nprint(B(2))\n"))
        assert result.stdout == "A\nB(2)\n"

    def test_return_from_match_arm(self, run_source):
        result = run_source(
            core(
                "enum E { A, B }\n"
                "def f(x: E) -> Int { match x { A => return 1, B => 2 } }\n"
                "print(f(A))\nprint(f(B))\n"
            )
        )
        assert result.stdout == "1\n2\n"


class TestCoreAdtRejections:
    def test_non_exhaustive_match(self, caplog):
        check_error(
            caplog,
            "enum E { A, B }\nval x = A\nprint(match x { A => 1 })\n",
            "Match is not exhaustive; missing: B.",
        )

    def test_unknown_constructor_pattern(self, caplog):
        check_error(
            caplog,
            "enum E { A, B }\nval x = A\nprint(match x { A => 1, C() => 2 })\n",
            "Enum 'E' has no constructor 'C'.",
        )

    def test_constructor_pattern_arity(self, caplog):
        check_error(
            caplog,
            "enum E { A(x: Int), B }\nval x = A(1)\nprint(match x { A() => 1, B => 0 })\n",
            "Constructor 'A' expects 1 argument(s), got 0.",
        )

    def test_constructor_payload_type(self, caplog):
        check_error(
            caplog,
            "enum E { A(x: Int) }\nprint(A(true))\n",
            "Expected Int, got Bool.",
        )

    def test_duplicate_pattern_binding(self, caplog):
        check_error(
            caplog,
            "enum E { A(x: Int) }\nprint(match A(1) { A(v, v) => v })\n",
            "already defined",
        )

    def test_incompatible_arm_types(self, caplog):
        check_error(
            caplog,
            "enum E { A, B }\nprint(match A { A => 1, B => true })\n",
            "arms of this match have incompatible types",
        )

    def test_generic_enum_is_rejected(self, caplog):
        check_error(
            caplog,
            "enum E[T] { A }\n",
            "Generic enums are not supported in oort-core yet.",
        )

    def test_empty_enum_is_rejected(self, caplog):
        check_error(
            caplog,
            "enum E { }\n",
            "An enum must declare at least one constructor.",
        )

    def test_reserved_enum_name(self, caplog):
        check_error(
            caplog,
            "enum Int { A }\n",
            "Enum name 'Int' is reserved in oort-core.",
        )

    def test_match_on_non_enum(self, caplog):
        check_error(
            caplog,
            "print(match 1 { _ => 1 })\n",
            "The scrutinee of match must have an enum type in oort-core, got Int.",
        )

    def test_enum_equality_is_rejected(self, caplog):
        check_error(
            caplog,
            "enum E { A }\nprint(A == A)\n",
            "Enum equality is not supported in oort-core yet; use match.",
        )

    def test_nested_enum_is_rejected(self, caplog):
        check_error(
            caplog,
            "def f() -> Unit { enum E { A } }\n",
            "Enum declarations are only allowed at module top level",
        )

    def test_unknown_field_type(self, caplog):
        check_error(
            caplog,
            "enum E { A(x: Missing) }\n",
            "Unknown type 'Missing' in oort-core.",
        )

    def test_duplicate_constructor(self, caplog):
        check_error(
            caplog,
            "enum E { A, A }\n",
            "Constructor 'A' is already declared",
        )

    def test_payload_constructor_bare_pattern(self, caplog):
        check_error(
            caplog,
            "enum E { A(x: Int) }\nprint(match A(1) { A => 1 })\n",
            "Constructor 'A' expects 1 argument(s).",
        )


class TestCoreFunctionValues:
    def test_annotated_lambda_and_call(self, run_source):
        result = run_source(
            core("val inc: (Int) -> Int = do(x: Int) -> Int { x + 1 }\nprint(inc(2))\n")
        )
        assert result.stdout == "3\n"

    def test_inferred_lambda(self, run_source):
        result = run_source(core("val twice = do(x: Int) -> Int { x * 2 }\nprint(twice(4))\n"))
        assert result.stdout == "8\n"

    def test_higher_order_function_and_lambda_argument(self, run_source):
        result = run_source(
            core(
                "def apply(f: (Int) -> Int, x: Int) -> Int { f(x) }\n"
                "print(apply(do(x: Int) -> Int { x * 3 }, 4))\n"
            )
        )
        assert result.stdout == "12\n"

    def test_zero_argument_and_unit_function_values(self, run_source):
        result = run_source(
            core(
                "val zero: () -> Int = do() -> Int { 42 }\n"
                "val show: (Int) -> Unit = do(x: Int) -> Unit { print(x) }\n"
                "print(zero())\nshow(7)\n"
            )
        )
        assert result.stdout == "42\n7\n"

    def test_nested_function_type(self, run_source):
        result = run_source(
            core(
                "val apply: ((Int) -> Int) -> Int = "
                "do(g: (Int) -> Int) -> Int { g(1) }\n"
                "print(apply(do(x: Int) -> Int { x + 1 }))\n"
            )
        )
        assert result.stdout == "2\n"

    def test_closure_over_outer_local(self, run_source):
        result = run_source(
            core(
                "def make(n: Int) -> (Int) -> Int {\n"
                "    do(x: Int) -> Int { x + n }\n"
                "}\n"
                "val add10 = make(10)\nprint(add10(5))\n"
            )
        )
        assert result.stdout == "15\n"


class TestCoreFunctionValueRejections:
    def test_anonymous_lambda_is_rejected(self, caplog):
        check_error(
            caplog,
            "val f = do: 1\n",
            "Lambdas without an explicit parameter list are not supported",
        )

    def test_lambda_parameter_annotation_required(self, caplog):
        check_error(
            caplog,
            "val f: (Int) -> Int = do(x) -> Int { x }\n",
            "Parameter 'x' requires a type annotation",
        )

    def test_lambda_return_annotation_required(self, caplog):
        check_error(
            caplog,
            "val f: (Int) -> Int = do(x: Int) { x }\n",
            "requires a return type annotation",
        )

    def test_function_type_mismatch(self, caplog):
        check_error(
            caplog,
            "val f: (Int) -> Bool = do(x: Int) -> Int { x }\n",
            "Expected (Int) -> Bool, got (Int) -> Int.",
        )

    def test_unit_parameter_is_rejected(self, caplog):
        check_error(
            caplog,
            "val f: (Unit) -> Int = do(x: Unit) -> Int { 1 }\n",
            "Unit is only allowed as a function return type",
        )

    def test_generic_lambda_is_rejected(self, caplog):
        check_error(
            caplog,
            "val f = do[T](x: Int) -> Int { x }\n",
            "Generic functions are not implemented yet.",
        )

    def test_default_parameter_in_lambda_is_rejected(self, caplog):
        check_error(
            caplog,
            "val f: (Int) -> Int = do(x: Int = 1) -> Int { x }\n",
            "Defaults, keyword-only/positional-only markers",
        )

    def test_function_value_is_not_printable(self, caplog):
        check_error(
            caplog,
            "val f = do(x: Int) -> Int { x }\nprint(f)\n",
            "only accepts Int, Float, Bool, String, Unit, enum or collection",
        )


class TestCoreCurriedFunctions:
    def test_right_associative_function_types_and_chained_calls(self, run_source):
        result = run_source(
            core(
                "val add: Int -> Int -> Int = "
                "do(x: Int) -> Int -> Int { do(y: Int) -> Int { x + y } }\n"
                "print(add(1)(2))\n"
                "val same: Int -> (Int -> Int) = add\n"
                "print(same(3)(4))\n"
            )
        )
        assert result.stdout == "3\n7\n"

    def test_parenthesized_function_parameter_type(self, run_source):
        result = run_source(
            core(
                "val apply: (Int -> Int) -> Int = "
                "do(f: Int -> Int) -> Int { f(1) }\n"
                "print(apply(do(x: Int) -> Int { x + 1 }))\n"
            )
        )
        assert result.stdout == "2\n"

    def test_non_callable_expression(self, caplog):
        check_error(
            caplog,
            "print((1)(2))\n",
            "Expression is not callable.",
        )


class TestCoreExpectedTypes:
    def test_annotation_propagates_into_if_and_block(self, run_source):
        result = run_source(
            core("val a: Int = if true { 1 } else { 2 }\nval b: Int = { 3 }\nprint(a)\nprint(b)\n")
        )
        assert result.stdout == "1\n3\n"

    def test_function_body_expected_type_reaches_branches(self, run_source):
        result = run_source(
            core(
                "def pick(flag: Bool) -> Int { if flag { 1 } else { 2 } }\n"
                "print(pick(true))\nprint(pick(false))\n"
            )
        )
        assert result.stdout == "1\n2\n"

    def test_assignment_and_return_propagate_expected_types(self, run_source):
        result = run_source(
            core(
                "var x = 0\nx = if true { 4 } else { 5 }\n"
                "def f(flag: Bool) -> Int { return if flag { 6 } else { 7 } }\n"
                "print(x)\nprint(f(false))\n"
            )
        )
        assert result.stdout == "4\n7\n"

    def test_match_arms_receive_expected_type(self, run_source):
        result = run_source(
            core("enum E { A, B }\nval x: Int = match A { A => 1, B => 2 }\nprint(x)\n")
        )
        assert result.stdout == "1\n"

    def test_if_without_else_needs_unit(self, caplog):
        check_error(
            caplog,
            "val x: Int = if true { 1 }\n",
            "An if without else has type Unit, expected Int.",
        )

    def test_block_last_expression_expected_type(self, caplog):
        check_error(
            caplog,
            "val x: Int = { 1\ntrue }\n",
            "Expected Int, got Bool.",
        )

    def test_match_arm_expected_type_error(self, caplog):
        check_error(
            caplog,
            "enum E { A, B }\nval x: Int = match A { A => 1, B => true }\n",
            "Expected Int, got Bool.",
        )

    def test_return_expected_type_reaches_branches(self, caplog):
        check_error(
            caplog,
            "def f(flag: Bool) -> Int { return if flag { 1 } else { true } }\n",
            "Expected Int, got Bool.",
        )


def test_call_argument_receives_expected_type(caplog):
    check_error(
        caplog,
        "def f(x: Int) -> Int { x }\nval y = f(if true { 1 } else { true })\n",
        "Expected Int, got Bool.",
    )


class TestCoreCollections:
    def test_list_inference_index_and_length(self, run_source):
        result = run_source(core("val xs = [3, 1, 2]\nprint(xs[1], len(xs))\nprint(xs)\n"))
        assert result.stdout == "1 3\n[3, 1, 2]\n"

    def test_empty_collections_use_annotations(self, run_source):
        result = run_source(
            core(
                "val xs: List[Int] = []\n"
                "val s: Set[String] = {. .}\n"
                "val d: Dict[String, Int] = {: :}\n"
                "print(xs, len(s), len(d))\n"
            )
        )
        assert result.stdout == "[] 0 0\n"

    def test_empty_literal_expected_type_reaches_call_and_return(self, run_source):
        result = run_source(
            core(
                "def count(xs: List[Int]) -> Int { len(xs) }\n"
                "def none() -> List[Int] { [] }\n"
                "print(count([]), none())\n"
            )
        )
        assert result.stdout == "0 []\n"

    def test_tuple_literal_and_literal_index(self, run_source):
        result = run_source(
            core(
                "val pair: Tuple[Int, Bool] = (7, true)\n"
                "print(pair[0], pair[1], len(pair))\n"
                "print((1, 2)[-1])\n"
            )
        )
        assert result.stdout == "7 true 2\n2\n"

    def test_uniform_tuple_allows_dynamic_index(self, run_source):
        result = run_source(core("val xs = (1, 2)\nvar i = 1\nprint(xs[i])\n"))
        assert result.stdout == "2\n"

    def test_dict_index_and_length(self, run_source):
        result = run_source(
            core(
                'val scores: Dict[String, Int] = {: "a": 1, "b": 2 :}\n'
                'print(scores["b"], len(scores))\n'
                "print(scores)\n"
            )
        )
        assert result.stdout == "2 2\n{: a: 1, b: 2 :}\n"

    def test_nested_collection_types(self, run_source):
        result = run_source(
            core(
                'val table: Dict[String, List[Int]] = {: "a": [1, 2] :}\n'
                "val rows: List[Tuple[Int, Bool]] = [(1, true)]\n"
                'print(table["a"][1], rows[0][1], len(table))\n'
            )
        )
        assert result.stdout == "2 true 1\n"

    def test_string_index_and_length(self, run_source):
        result = run_source(core('print("abc"[1], len("abc"))\n'))
        assert result.stdout == "b 3\n"

    def test_empty_tuple_is_inferred(self, run_source):
        result = run_source(core("val t = ()\nprint(t, len(t))\n"))
        assert result.stdout == "() 0\n"

    def test_collection_equality(self, run_source):
        result = run_source(
            core(
                "print([1] == [1], [1] == [2])\n"
                "print((1, true) == (1, true), [1] != [2])\n"
                'print({: "a": 1 :} == {: "a": 1 :})\n'
            )
        )
        assert result.stdout == "true false\ntrue true\ntrue\n"

    def test_empty_list_without_annotation_is_rejected(self, caplog):
        check_error(
            caplog,
            "val xs = []\n",
            "Cannot infer the element type of an empty List",
        )

    def test_empty_dict_without_annotation_is_rejected(self, caplog):
        check_error(
            caplog,
            "val d = {: :}\n",
            "Cannot infer the key/value types of an empty Dict",
        )

    def test_heterogeneous_list_is_rejected(self, caplog):
        check_error(
            caplog,
            "val xs = [1, true]\n",
            "List elements have incompatible types: Int and Bool.",
        )

    def test_unit_element_is_rejected(self, caplog):
        check_error(
            caplog,
            "val xs = [print(1)]\n",
            "Unit cannot be stored in a List",
        )

    def test_set_elements_must_be_key_types(self, caplog):
        check_error(
            caplog,
            "val s = {. [1] .}\n",
            "Set elements must be Int, Float, Bool, String, an enum or a Tuple",
        )

    def test_dict_keys_must_be_key_types(self, caplog):
        check_error(
            caplog,
            "val d = {: [1]: 2 :}\n",
            "Dict keys must be Int, Float, Bool, String, an enum or a Tuple",
        )

    def test_container_annotations_validate_key_types(self, caplog):
        check_error(
            caplog,
            "val s: Set[List[Int]] = {. .}\n",
            "Set elements must be Int, Float, Bool, String, an enum or a Tuple",
        )

    def test_tuple_arity_mismatch(self, caplog):
        check_error(
            caplog,
            "val pair: Tuple[Int, Bool] = (1,)\n",
            "Tuple has 1 elements, expected 2.",
        )

    def test_tuple_literal_out_of_range(self, caplog):
        check_error(
            caplog,
            "print((1, 2)[5])\n",
            "Index 5 is out of range for Tuple[Int, Int].",
        )

    def test_heterogeneous_tuple_needs_literal_index(self, caplog):
        check_error(
            caplog,
            'val pair = (1, "a")\nvar i = 1\nprint(pair[i])\n',
            "Tuple subscripts with a non-literal index require all elements",
        )

    def test_list_index_must_be_int(self, caplog):
        check_error(
            caplog,
            "val xs = [1]\nprint(xs[true])\n",
            "Expected Int, got Bool.",
        )

    def test_dict_index_must_match_key_type(self, caplog):
        check_error(
            caplog,
            'val d: Dict[String, Int] = {: "a": 1 :}\nprint(d[1])\n',
            "Expected String, got Int.",
        )

    def test_set_is_not_subscriptable(self, caplog):
        check_error(
            caplog,
            "val s = {. 1 .}\nprint(s[0])\n",
            "Type Set[Int] is not subscriptable",
        )

    def test_cross_kind_collection_equality_is_rejected(self, caplog):
        check_error(
            caplog,
            "print([1] == (1,))\n",
            "requires both operands to have the same collection type",
        )

    def test_bare_container_type_requires_arguments(self, caplog):
        check_error(
            caplog,
            "val xs: List = []\n",
            "Type 'List' requires type arguments",
        )

    def test_container_type_arity(self, caplog):
        check_error(
            caplog,
            "val xs: List[Int, Bool] = []\n",
            "Type 'List' expects 1 type argument(s), got 2.",
        )

    def test_len_requires_a_collection_or_string(self, caplog):
        check_error(
            caplog,
            "print(len(1))\n",
            "The built-in 'len' only accepts String or collection arguments",
        )


class TestCoreLoops:
    def test_for_over_collections_and_string(self, run_source):
        result = run_source(
            core(
                "val xs = [1, 2, 3]\n"
                "var total = 0\n"
                "for x in xs { total = total + x }\n"
                "print(total)\n"
                'for key in {: "a": 1, "b": 2 :} { print(key) }\n'
                'for ch in "ab" { print(ch) }\n'
            )
        )
        assert result.stdout == "6\na\nb\na\nb\n"

    def test_for_over_uniform_tuple_and_single_element_set(self, run_source):
        result = run_source(core("for n in (5, 6) { print(n) }\nfor x in {. 4 .} { print(x) }\n"))
        assert result.stdout == "5\n6\n4\n"

    def test_while_continue_and_break(self, run_source):
        result = run_source(
            core(
                "var i = 0\n"
                "while i < 5 {\n"
                "    i = i + 1\n"
                "    if i == 2: continue\n"
                "    if i == 4: break\n"
                "    print(i)\n"
                "}\n"
            )
        )
        assert result.stdout == "1\n3\n"

    def test_return_from_inside_for(self, run_source):
        result = run_source(
            core(
                "def first_positive(xs: List[Int]) -> Int {\n"
                "    for x in xs {\n"
                "        if x > 0 { return x }\n"
                "    }\n"
                "    0\n"
                "}\n"
                "print(first_positive([-2, 3, 4]))\n"
            )
        )
        assert result.stdout == "3\n"

    def test_loop_variable_annotation_is_checked(self, run_source):
        result = run_source(core("for x: Int in [1, 2] { print(x) }\n"))
        assert result.stdout == "1\n2\n"

    def test_loop_variable_shadows_outer_binding(self, run_source):
        result = run_source(core("var x = 9\nfor x in [1] { print(x) }\nprint(x)\n"))
        assert result.stdout == "1\n9\n"

    def test_while_condition_must_be_bool(self, caplog):
        check_error(
            caplog,
            "while 1 { print(1) }\n",
            "while condition must be Bool",
        )

    def test_loop_variable_annotation_mismatch(self, caplog):
        check_error(
            caplog,
            "for x: Bool in [1] { print(x) }\n",
            "Expected Bool, got Int.",
        )

    def test_multiple_loop_variables_are_rejected(self, caplog):
        check_error(
            caplog,
            "for a, b in [1] { print(a) }\n",
            "Multiple loop variables are not supported",
        )

    def test_iterating_a_non_iterable_is_rejected(self, caplog):
        check_error(
            caplog,
            "for x in 1 { print(x) }\n",
            "Cannot iterate over values of type Int",
        )

    def test_iterating_a_heterogeneous_tuple_is_rejected(self, caplog):
        check_error(
            caplog,
            "val pair = (1, true)\nfor x in pair { print(x) }\n",
            "Cannot iterate a Tuple with heterogeneous element types",
        )

    def test_break_value_is_rejected(self, caplog):
        check_error(
            caplog,
            "while true { break 1 }\n",
            "break values are not supported",
        )


def test_collection_equality_rejects_enum_elements(caplog):
    check_error(
        caplog,
        "enum E { A }\nval xs = [A]\nprint(xs == xs)\n",
        "Equality is not supported for collections containing enums or functions",
    )


class TestCoreClasses:
    def test_slots_constructor_and_methods(self, run_source):
        result = run_source(
            core(
                "class Counter {\n"
                "    val start: Int = 10\n"
                "    var count: Int\n"
                "    def __init__(step: Int) {\n"
                "        this.count = this.start\n"
                "        this.count = this.count + step\n"
                "    }\n"
                "    def get() -> Int { this.count }\n"
                "    def bump() -> Unit { this.count = this.count + 1 }\n"
                "}\n"
                "val c = Counter(5)\n"
                "print(c.get())\n"
                "c.bump()\n"
                "print(c.get(), c.start)\n"
            )
        )
        assert result.stdout == "15\n16 10\n"

    def test_val_slots_assigned_from_parameters(self, run_source):
        result = run_source(
            core(
                "class Point {\n"
                "    val x: Int\n"
                "    val y: Int\n"
                "    def __init__(x: Int, y: Int) {\n"
                "        this.x = x\n"
                "        this.y = y\n"
                "    }\n"
                "    def sum() -> Int { this.x + this.y }\n"
                "}\n"
                "print(Point(2, 3).sum())\n"
            )
        )
        assert result.stdout == "5\n"

    def test_slot_initializers_run_before_constructor(self, run_source):
        result = run_source(
            core(
                "def mark(n: Int) -> Int {\n"
                "    print(n)\n"
                "    n\n"
                "}\n"
                "class C {\n"
                "    val a: Int = mark(1)\n"
                "    val b: Int = mark(2)\n"
                "    def __init__() { print(3) }\n"
                "}\n"
                "C()\n"
            )
        )
        assert result.stdout == "1\n2\n3\n"

    def test_class_types_in_annotations_and_methods(self, run_source):
        result = run_source(
            core(
                "class Box {\n"
                "    val value: Int\n"
                "    def __init__(value: Int) { this.value = value }\n"
                "    def next() -> Box { Box(this.value + 1) }\n"
                "    def me() -> Box { this }\n"
                "}\n"
                "def unwrap(box: Box) -> Int { box.value }\n"
                "val b = Box(1).next().next().me()\n"
                "print(unwrap(b))\n"
            )
        )
        assert result.stdout == "3\n"

    def test_empty_class_and_method_reference(self, run_source):
        result = run_source(
            core(
                "class Empty {\n"
                "    def answer() -> Int { 42 }\n"
                "}\n"
                "val e = Empty()\n"
                "val f = e.answer\n"
                "print(f())\n"
            )
        )
        assert result.stdout == "42\n"

    def test_class_without_constructor_and_initialized_slots(self, run_source):
        result = run_source(
            core(
                "class Defaults {\n"
                "    val answer: Int = 7\n"
                '    var name: String = "oort"\n'
                "}\n"
                "val d = Defaults()\n"
                "print(d.answer, d.name)\n"
            )
        )
        assert result.stdout == "7 oort\n"

    def test_slot_initializer_uses_expected_collection_type(self, run_source):
        result = run_source(
            core(
                "class Bag {\n"
                "    val xs: List[Int] = []\n"
                "    def size() -> Int { len(this.xs) }\n"
                "}\n"
                "print(Bag().size())\n"
            )
        )
        assert result.stdout == "0\n"

    def test_definite_assignment_accepts_both_branches(self, run_source):
        result = run_source(
            core(
                "class C {\n"
                "    val x: Int\n"
                "    def __init__(flag: Bool) {\n"
                "        if flag { this.x = 1 } else { this.x = 2 }\n"
                "    }\n"
                "}\n"
                "print(C(true).x, C(false).x)\n"
            )
        )
        assert result.stdout == "1 2\n"

    def test_inheritance_is_rejected(self, caplog):
        check_error(
            caplog,
            "class A {}\nclass B < A {}\n",
            "Class inheritance is not supported",
        )

    def test_metaclass_is_rejected(self, caplog):
        check_error(
            caplog,
            "class A {}\nclass B :: A {}\n",
            "Metaclasses are not supported",
        )

    def test_generic_class_is_rejected(self, caplog):
        check_error(
            caplog,
            "class Box[T] {}\n",
            "Generic classes are not implemented yet.",
        )

    def test_class_method_is_rejected(self, caplog):
        check_error(
            caplog,
            "class C { def class.f() -> Int { 1 } }\n",
            "Only plain instance methods are supported",
        )

    def test_operator_method_is_rejected(self, caplog):
        check_error(
            caplog,
            'class C { def operator "+"(x: Int) -> Int { x } }\n',
            "Only plain instance methods are supported",
        )

    def test_other_special_method_is_rejected(self, caplog):
        check_error(
            caplog,
            'class C { def __str__() -> String { "x" } }\n',
            "Special method '__str__' is not supported",
        )

    def test_class_body_statement_is_rejected(self, caplog):
        check_error(
            caplog,
            "class C {\n    print(1)\n}\n",
            "Only slot and method declarations are allowed",
        )

    def test_slot_requires_annotation(self, caplog):
        check_error(
            caplog,
            "class C { val x = 1 }\n",
            "Slot 'x' requires a type annotation",
        )

    def test_slot_rejects_unit(self, caplog):
        check_error(
            caplog,
            "class C { val x: Unit = print(1) }\n",
            "Unit is only allowed as a function return type",
        )

    def test_slot_rejects_special_name(self, caplog):
        check_error(
            caplog,
            "class C { val __x__: Int = 1 }\n",
            "Slot name '__x__' is reserved",
        )

    def test_missing_constructor_for_uninitialized_slots(self, caplog):
        check_error(
            caplog,
            "class C { val x: Int }\n",
            "has slots without initializers but no __init__: x",
        )

    def test_definite_assignment_requires_all_branches(self, caplog):
        check_error(
            caplog,
            "class C {\n"
            "    val x: Int\n"
            "    def __init__(flag: Bool) {\n"
            "        if flag { this.x = 1 }\n"
            "    }\n"
            "}\n",
            "Constructor must initialize slot(s): x.",
        )

    def test_read_before_assignment(self, caplog):
        check_error(
            caplog,
            "class C {\n"
            "    val x: Int\n"
            "    def __init__() {\n"
            "        print(this.x)\n"
            "        this.x = 1\n"
            "    }\n"
            "}\n",
            "Slot 'x' is read before it is definitely assigned.",
        )

    def test_early_return_before_assignment(self, caplog):
        check_error(
            caplog,
            "class C {\n    var x: Int\n    def __init__() { return }\n}\n",
            "Constructor returns before initializing slot(s): x.",
        )

    def test_val_with_initializer_is_not_reassignable(self, caplog):
        check_error(
            caplog,
            "class C {\n    val x: Int = 0\n    def __init__() { this.x = 1 }\n}\n",
            "Cannot assign to read-only slot 'x'; it has an initializer.",
        )

    def test_val_without_initializer_can_be_assigned_only_once(self, caplog):
        check_error(
            caplog,
            "class C {\n"
            "    val x: Int\n"
            "    def __init__(flag: Bool) {\n"
            "        if flag { this.x = 1 }\n"
            "        this.x = 2\n"
            "    }\n"
            "}\n",
            "Read-only slot 'x' may already be assigned; it can be assigned only once.",
        )

    def test_val_is_read_only_in_methods(self, caplog):
        check_error(
            caplog,
            "class C {\n"
            "    val x: Int\n"
            "    def __init__() { this.x = 1 }\n"
            "    def set() -> Unit { this.x = 2 }\n"
            "}\n",
            "Cannot assign to read-only slot 'x'",
        )

    def test_val_cannot_be_assigned_in_a_loop(self, caplog):
        check_error(
            caplog,
            "class C {\n"
            "    val x: Int\n"
            "    def __init__() {\n"
            "        for i in [1, 2] { this.x = i }\n"
            "    }\n"
            "}\n",
            "Read-only slot 'x' cannot be assigned inside a loop.",
        )

    def test_definite_assignment_through_loops_and_member_writes(self, run_source):
        result = run_source(
            core(
                """class D { var v: Int = 0 }
class C {
    val x: Int
    def __init__() {
        var i: Int = 0
        while i < 1 { i = i + 1 }
        for k in [1, 2] { print(k) }
        var d = D()
        d.v = 1
        this.x = d.v
    }
}
print(C().x)
"""
            )
        )
        assert result.stdout == "1\n2\n1\n"

    def test_definite_assignment_through_match(self, run_source):
        result = run_source(
            core(
                """enum E { A, B }
class C {
    val x: Int
    def __init__(e: E) {
        match e {
            A => { this.x = 1 },
            B => { this.x = 2 }
        }
    }
}
print(C(A).x, C(B).x)
"""
            )
        )
        assert result.stdout == "1 2\n"

    def test_definite_assignment_through_break_and_continue(self, run_source):
        result = run_source(
            core(
                """class C {
    val x: Int
    def __init__() {
        var i: Int = 0
        while i < 3 {
            i = i + 1
            if i == 1 { continue }
            break
        }
        this.x = 1
    }
}
print(C().x)
"""
            )
        )
        assert result.stdout == "1\n"

    def test_definite_assignment_merges_early_returns(self, run_source):
        result = run_source(
            core(
                """class A {
    val x: Int
    def __init__(flag: Bool) {
        this.x = 1
        if flag { return }
    }
}
class B {
    val x: Int
    def __init__(flag: Bool) {
        this.x = 1
        if flag { print(1) } else { return }
    }
}
print(A(false).x, B(true).x)
"""
            )
        )
        assert result.stdout == "1\n1 1\n"

    def test_definite_assignment_all_match_arms_return(self, run_source):
        result = run_source(
            core(
                """enum E { A, B }
class C {
    val x: Int
    def __init__(e: E) {
        this.x = 1
        match e {
            A => { return },
            B => { return }
        }
    }
}
print(C(A).x)
"""
            )
        )
        assert result.stdout == "1\n"

    def test_definite_assignment_skips_unreachable_statements(self, run_source):
        result = run_source(
            core(
                """class C {
    val x: Int
    def __init__() {
        { this.x = 1 }
        return
        print(2)
    }
}
print(C().x)
"""
            )
        )
        assert result.stdout == "1\n"

    def test_undeclared_slot_assignment(self, caplog):
        check_error(
            caplog,
            "class C {\n    val x: Int = 1\n    def set() -> Unit { this.y = 2 }\n}\n",
            "Class 'C' has no slot 'y'.",
        )

    def test_method_assignment_is_rejected(self, caplog):
        check_error(
            caplog,
            "class C {\n    def f() -> Int { 1 }\n    def set() -> Unit { this.f = 2 }\n}\n",
            "Cannot assign to method 'f'.",
        )

    def test_unknown_member_read(self, caplog):
        check_error(
            caplog,
            "class C {\n    val x: Int = 1\n    def f() -> Int { this.missing }\n}\n",
            "Class 'C' has no member 'missing'.",
        )

    def test_constructor_argument_types(self, caplog):
        check_error(
            caplog,
            "class C {\n    val x: Int\n    def __init__(x: Int) { this.x = x }\n}\nC(true)\n",
            "Expected Int, got Bool.",
        )

    def test_method_argument_types(self, caplog):
        check_error(
            caplog,
            "class C {\n"
            "    val x: Int = 1\n"
            "    def add(n: Int) -> Int { this.x + n }\n"
            "}\n"
            "C().add(true)\n",
            "Expected Int, got Bool.",
        )

    def test_attribute_fallback_is_rejected(self, caplog):
        check_error(
            caplog,
            """\
class C {
    val x: Int = 1
    def on_missing(name: String) -> Int { 0 }
}
""",
            "Attribute fallback hooks are only supported in oort-object.",
        )

    def test_class_equality_is_rejected(self, caplog):
        check_error(
            caplog,
            "class C { val x: Int = 1 }\nval c = C()\nprint(c == c)\n",
            "Class equality is not supported",
        )

    def test_class_instances_are_not_printable(self, caplog):
        check_error(
            caplog,
            "class C { val x: Int = 1 }\nprint(C())\n",
            "got C.",
        )

    def test_type_name_collision_with_enum_or_class(self, caplog):
        check_error(
            caplog,
            "enum Foo { A }\nclass Foo {}\n",
            "Type name 'Foo' is already declared or reserved",
        )
        check_error(
            caplog,
            "class Foo {}\nenum Foo { A }\n",
            "Type name 'Foo' is already declared.",
        )

    def test_class_must_be_top_level(self, caplog):
        check_error(
            caplog,
            "def f() -> Unit {\n    class C {}\n    print(1)\n}\n",
            "Class declarations are only allowed at module top level",
        )

    def test_constructor_return_type_must_be_unit(self, caplog):
        check_error(
            caplog,
            "class C {\n    val x: Int = 1\n    def __init__() -> Int { this.x }\n}\n",
            "must return Unit",
        )
