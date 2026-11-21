#! /usr/bin/env python

import argparse
import dataclasses
import logging
import os
from pathlib import Path
from typing import Any

from antlr4 import CommonTokenStream
from antlr4.ListTokenSource import ListTokenSource

from ..ast import nodes
from ..ast.printer import ASTPrinter
from ..diagnostics import OortException, OortSyntaxError, TypeCheckError
from ..diagnostics.error_handler import CompilerErrorHandler
from ..diagnostics.error_listener import OortErrorListener
from ..diagnostics.runtime_errors import OortImportError
from ..parser.ast_builder import ASTBuilder, ASTNode
from ..parser.dialect import (
    DEFAULT_DIALECT,
    DialectConfig,
    LangDirective,
    known_dialect_names,
    lookup_dialect,
    parse_lang_directive,
)
from ..parser.grammar.OortLexer import OortLexer
from ..parser.grammar.OortParser import OortParser
from ..parser.token_processor import TokenizedInput, tokenize
from ..runtime.interpreter import ASTInterpreter
from ..runtime.modules import CompiledModule, ModuleLoader, resolve_module_path
from ..runtime.stdlib import NATIVE_MODULE_NAMES, native_module_factories
from ..semantics.analyzer import SemanticAnalyzer, create_semantic_analyzer
from ..semantics.core.types import CoreModuleInfo, Type
from ..source.input_info import FileInputInfo, InputInfo, StringInputInfo
from ..source.source_position import SourcePosition


class CompilerError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class CompiledUnit:
    """A compiled module plus the static interface of an `oort-core` module."""

    ast: nodes.ModuleNode
    dialect: DialectConfig
    exports: tuple[tuple[str, Type], ...] = ()


class Compiler:
    """Top-level instance of Oort compiler frontend."""

    def __init__(self, args: argparse.Namespace):
        # Compiler options. TODO: Replace raw args with better option class.
        self.args = args

        self.error_handler = CompilerErrorHandler()
        self.module_paths = tuple(Path(path) for path in (getattr(args, "module_path", None) or []))
        self._entry_dir: Path | None = None
        self._entry_path: Path | None = None
        self._unit_cache: dict[Path, CompiledUnit] = {}
        self._core_compile_stack: list[Path] = []

    def _run_input(self, input_info: InputInfo) -> Any:
        """Run a single input."""

        self.error_handler.register_input(input_info)
        self._entry_dir = input_info.module_dir
        self._entry_path = input_info.module_path
        dialect = self._resolve_dialect(input_info)
        assert dialect is not None

        parser = self._build_parser(input_info)
        ast = self.build_ast(parser, input_info, dialect=dialect)
        if not ast:
            raise CompilerError()

        # Print AST (no semantic analysis).
        if self.args.target == "ast":
            ast_printer = ASTPrinter(show_metadata=False)
            print(ast_printer.parse(ast))
            return None

        # Semantic analysis.
        analyzer = self.make_semantic_analyzer(input_info, dialect)
        ast = self.semantic_analyze(ast, analyzer)
        if not ast:
            raise CompilerError()

        # Print AST with metadata.
        if self.args.target == "astm":
            ast_printer = ASTPrinter(show_metadata=True)
            print(ast_printer.parse(ast))
            return None

        if self.args.target in ("bc", "vm"):
            from ..bytecode import compile_module, disassemble_module
            from ..hir import lower_module
            from ..runtime.bytecode_vm import BytecodeVM

            assert isinstance(ast, nodes.ModuleNode)
            try:
                program = compile_module(lower_module(ast))
            except OortException as e:
                matched = self.error_handler.input_info_for(e.position) or input_info
                self.error_handler.add(e, matched)
                self.error_handler.report(exit_on_error=False, clear=True)
                raise CompilerError() from None
            if self.args.target == "bc":
                print(disassemble_module(program))
                return None

            interpreter = ASTInterpreter(self.error_handler)
            interpreter.script_args = tuple(getattr(self.args, "script_args", ()) or ())
            interpreter.script_path = (
                str(input_info.module_path) if input_info.module_path is not None else None
            )
            try:
                result = BytecodeVM(interpreter).run(program)
            except OortException as e:
                matched = self.error_handler.input_info_for(e.position) or input_info
                self.error_handler.add(e, matched)
                self.error_handler.report(exit_on_error=False, clear=True)
                raise CompilerError() from None
            return result.host_value

        assert self.args.target == "eval", f"Invalid target {self.args.target}"

        interpreter = ASTInterpreter(self.error_handler)
        interpreter.script_args = tuple(getattr(self.args, "script_args", ()) or ())
        interpreter.script_path = (
            str(input_info.module_path) if input_info.module_path is not None else None
        )
        loader = self.make_module_loader(interpreter, input_info.module_dir)
        interpreter.module_loader = loader
        assert isinstance(ast, nodes.ModuleNode)
        try:
            result = loader.execute_entry(
                ast,
                interpreter.entry_env,
                input_info.module_path,
                dialect_name=dialect.name,
            )
        except OortException as e:
            matched = self.error_handler.input_info_for(e.position) or input_info
            self.error_handler.add(e, matched)
            self.error_handler.report(exit_on_error=False, clear=True)
            raise CompilerError() from None
        if self.error_handler.pending_count:
            self.error_handler.report(exit_on_error=False, clear=True)
        return result.host_value

    def compile_unit_details(self, input_info: InputInfo) -> CompiledUnit | None:
        """Compile one module and return its AST, dialect and static exports."""
        self.error_handler.register_input(input_info)
        if self._entry_dir is None:
            self._entry_dir = input_info.module_dir
        if self._entry_path is None:
            self._entry_path = input_info.module_path
        path = input_info.module_path
        if path is not None:
            cached = self._unit_cache.get(path)
            if cached is not None:
                return cached

        start = self.error_handler.error_count

        dialect = self._resolve_dialect(input_info, exit_on_error=False)
        if dialect is None:
            return None

        parser = self._build_parser(input_info)
        ast = self.build_ast(
            parser,
            input_info,
            dialect=dialect,
            exit_on_error=False,
            summary=False,
            report_errors=False,
        )
        if ast is None or self.error_handler.error_count > start:
            return None

        analyzer = self.make_semantic_analyzer(input_info, dialect)
        ast = self.semantic_analyze(
            ast,
            analyzer,
            exit_on_error=False,
            summary=False,
            report_errors=False,
        )
        if ast is None or self.error_handler.error_count > start:
            return None
        assert isinstance(ast, nodes.ModuleNode)

        exports: tuple[tuple[str, Type], ...] = tuple(getattr(analyzer, "exports", ()))
        unit = CompiledUnit(ast, dialect, exports)
        if path is not None:
            self._unit_cache[path] = unit
        return unit

    def compile_unit(self, input_info: InputInfo) -> nodes.ModuleNode | None:
        """Compile one module without printing or clearing diagnostics."""
        result = self.compile_unit_details(input_info)
        return None if result is None else result.ast

    def make_module_loader(self, interpreter: ASTInterpreter, entry_dir: Path) -> ModuleLoader:
        self._entry_dir = entry_dir.resolve()

        def compile_module(path: Path) -> CompiledModule | None:
            result = self.compile_unit_details(FileInputInfo(path))
            if result is None:
                return None
            return CompiledModule(result.ast, result.dialect.name)

        return ModuleLoader(
            compile_module=compile_module,
            execute_module=interpreter.run_module,
            make_environment=interpreter.create_module_env,
            make_module=interpreter.new_module,
            entry_dir=entry_dir,
            search_paths=self.module_paths,
            native_modules=native_module_factories(interpreter),
        )

    def run_file(self, input_file: os.PathLike) -> Any:
        return self._run_input(FileInputInfo(input_file))

    def run_string(self, input_string: str, name: str = "<string>") -> Any:
        return self._run_input(StringInputInfo(input_string, name=name))

    def _resolve_dialect(
        self, input_info: InputInfo, exit_on_error: bool = True
    ) -> DialectConfig | None:
        """Select the module dialect from its `#lang` directive."""
        directive = parse_lang_directive(input_info.get_source_text())

        if directive.error is not None:
            self._report_dialect_error(
                directive.error, directive, input_info, exit_on_error=exit_on_error
            )
            return None

        if directive.dialect_name is None:
            return DEFAULT_DIALECT

        config = lookup_dialect(directive.dialect_name)
        if config is None:
            known = ", ".join(known_dialect_names())
            self._report_dialect_error(
                f"Unknown dialect {directive.dialect_name!r}. Known dialects: {known}.",
                directive,
                input_info,
                exit_on_error=exit_on_error,
            )
            return None

        if not config.implemented:
            self._report_dialect_error(
                f"The {config.name!r} dialect is not implemented yet.",
                directive,
                input_info,
                exit_on_error=exit_on_error,
            )
            return None

        logging.debug("Using dialect %s", config.name)
        return config

    def _report_dialect_error(
        self,
        message: str,
        directive: LangDirective,
        input_info: InputInfo,
        exit_on_error: bool = True,
    ) -> None:
        position = SourcePosition.from_location(
            directive.line,
            directive.column,
            directive.text,
            filename=input_info.input_filename,
        )
        self.error_handler.add(OortSyntaxError(message, position), input_info)
        if exit_on_error:
            self.error_handler.report(exit_on_error=True, clear=False)

    def prepare_parser(self, input_info: InputInfo) -> tuple[OortParser, TokenizedInput]:
        """Lex and post-process one input, then build its parser.

        The tokenized result carries bracket depth and completeness, which the
        REPL uses to decide whether to keep reading.
        """
        lexer = OortLexer(input_info.get_input_stream())
        tokenized = tokenize(lexer)
        token_stream = CommonTokenStream(ListTokenSource(tokenized.tokens))

        parser = OortParser(token_stream)
        parser.removeErrorListeners()
        parser.addErrorListener(OortErrorListener(self.error_handler, input_info))
        return parser, tokenized

    def _build_parser(self, input_info: InputInfo) -> OortParser:
        """Build parser."""
        return self.prepare_parser(input_info)[0]

    def build_ast(
        self,
        parser: OortParser,
        input_info: InputInfo,
        dialect: DialectConfig = DEFAULT_DIALECT,
        exit_on_error: bool = True,
        summary: bool = True,
        report_errors: bool = True,
    ) -> ASTNode | None:
        start_errors = self.error_handler.error_count
        tree = parser.startRule()

        if report_errors:
            num_errors = self.error_handler.report(exit_on_error=exit_on_error, summary=summary)
        else:
            num_errors = self.error_handler.error_count - start_errors
        if num_errors > 0:
            return None

        # Build AST.
        builder = ASTBuilder(self.error_handler, input_info, dialect=dialect)
        ast = builder.parse(tree)
        logging.debug("AST built successfully")

        if report_errors:
            num_errors = self.error_handler.report(exit_on_error=exit_on_error, summary=summary)
        else:
            num_errors = self.error_handler.error_count - start_errors
        if num_errors > 0:
            return None

        return ast

    def make_semantic_analyzer(
        self,
        input_info: InputInfo,
        dialect: DialectConfig = DEFAULT_DIALECT,
    ) -> SemanticAnalyzer:
        resolver = self._resolve_core_module if dialect.features.type_checking else None
        return create_semantic_analyzer(
            self.error_handler,
            input_info,
            dialect,
            module_resolver=resolver,
        )

    def _resolve_core_module(
        self,
        spec: str,
        importer_dir: Path,
        position: SourcePosition,
    ) -> CoreModuleInfo | None:
        """Resolve and compile one `oort-core` import for static checking."""
        if spec in NATIVE_MODULE_NAMES:
            return CoreModuleInfo(name=spec, dialect_name="native", exports=())

        entry_dir = self._entry_dir or importer_dir
        try:
            path = resolve_module_path(
                spec,
                importer_dir=importer_dir,
                entry_dir=entry_dir,
                search_paths=self.module_paths,
                position=position,
            )
        except OortImportError as error:
            self._add_import_diagnostic(error.msg, position)
            return None

        if path in self._core_compile_stack:
            chain_paths = [
                item
                for item in [self._entry_path, *self._core_compile_stack, path]
                if item is not None
            ]
            chain = " -> ".join(item.name for item in chain_paths)
            self._add_import_diagnostic(f"Circular import detected: {chain}.", position)
            return None

        self._core_compile_stack.append(path)
        try:
            unit = self.compile_unit_details(FileInputInfo(path))
        finally:
            self._core_compile_stack.pop()
        if unit is None:
            return None
        return CoreModuleInfo(
            name=spec,
            dialect_name=unit.dialect.name,
            exports=unit.exports,
        )

    def _add_import_diagnostic(self, message: str, position: SourcePosition) -> None:
        input_info = self.error_handler.input_info_for(position)
        if input_info is not None:
            self.error_handler.add(
                TypeCheckError(message, position),
                input_info,
            )

    def semantic_analyze(
        self,
        ast: ASTNode,
        analyzer: SemanticAnalyzer,
        exit_on_error: bool = True,
        summary: bool = True,
        report_errors: bool = True,
    ) -> ASTNode | None:
        if not ast:
            return None

        start_errors = self.error_handler.error_count
        analyzer.parse(ast)
        logging.debug("Semantic analysis done")

        if report_errors:
            num_errors = self.error_handler.report(exit_on_error=exit_on_error, summary=summary)
        else:
            num_errors = self.error_handler.error_count - start_errors
        if num_errors > 0:
            return None

        return ast
