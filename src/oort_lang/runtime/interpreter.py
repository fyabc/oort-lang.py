#! /usr/bin/env python

"""AST interpreter."""

from collections.abc import Iterable
from typing import TYPE_CHECKING

from ..ast import nodes
from ..ast.ast_visitor import ASTVisitor
from ..diagnostics import OortException, OortSyntaxError, UnsupportedSyntax
from ..diagnostics.error_handler import CompilerErrorHandler
from ..diagnostics.runtime_errors import (
    OortAttributeError,
    OortImportError,
    OortNameError,
    OortRuntimeError,
    OortTypeError,
)
from ..source.source_position import SourcePosition
from .builtins import setup_builtins
from .call_args import ArgumentBindingError, EvaluatedArgument
from .control_flow_exceptions import OortBreak, OortContinue, OortReturn
from .dispatch import (
    _bind_extension_method,
    _get_operator_from_cls,
    find_callable_class_member,
)
from .environment import (
    AssignResult,
    DefineResult,
    Entry,
    Environment,
    ExtensionLookup,
)
from .functions import (
    OortCallableMixin,
    OortFunction,
    OortIterator,
    OortMethod,
    OortNativeFunction,
    OortNativeMethod,
    OortVMInvokable,
)
from .native import NativeMode
from .objects import (
    OortADT,
    OortBool,
    OortDict,
    OortFloat,
    OortInstance,
    OortInt,
    OortList,
    OortModule,
    OortNull,
    OortObject,
    OortSet,
    OortSlice,
    OortString,
    OortSuperProxy,
    OortTuple,
)
from .type_system import OortType, Runtime, SlotDefinition

if TYPE_CHECKING:
    from .modules import ModuleLoader

_AUG_OPS = {
    "+=": "+",
    "-=": "-",
    "*=": "*",
    "/=": "/",
    "//=": "//",
    "%=": "%",
    "**=": "**",
    "<<=": "<<",
    ">>=": ">>",
    "&=": "&",
    "^=": "^",
    "|=": "|",
}


def _is_truthy(value: OortObject) -> bool:
    # Truthy check: same as Python.
    # TODO: Replace this simple check with complex `__bool__` call.
    return bool(value.host_value)


class ASTInterpreter(ASTVisitor[OortObject]):
    def __init__(
        self,
        error_handler: CompilerErrorHandler,
        module_loader: "ModuleLoader | None" = None,
    ):
        self.error_handler = error_handler
        self._current_method = None
        # Guards against `on_missing` re-entering itself for the same receiver.
        self._missing_hook_receivers: set[int] = set()
        # Process-level context for the `os` native module. The compiler sets
        # these for file/-c runs; REPL and embedded interpreters keep defaults.
        self.script_args: tuple[str, ...] = ()
        self.script_path: str | None = None

        # Every interpreter owns one runtime and one shared builtins scope.
        # Modules are separate roots whose outer scope is this builtins scope.
        self.runtime = Runtime()
        self.builtins_env = Environment(name="<builtins>", allow_redefine=False)
        with self.runtime.activate():
            setup_builtins(self.runtime, self.builtins_env)

        self.entry_env = self.create_module_env("<global>")
        self.env = self.entry_env
        self.module_loader = module_loader

    def create_module_env(self, name: str) -> Environment:
        """Create an isolated top-level scope for one module."""
        return Environment(
            outer=self.builtins_env,
            name=name,
            allow_redefine=True,
            is_module_root=True,
        )

    def new_module(self, name: str, env: Environment) -> OortModule:
        """Create a module value under this interpreter's runtime."""
        with self.runtime.activate():
            return OortModule(name, env)

    def run(self, node: nodes.ASTNode) -> OortObject:
        with self.runtime.activate():
            result = node.accept(self)
            return self.runtime.null if result is None else result

    def run_module(self, node: nodes.ModuleNode, env: Environment) -> OortObject:
        """Execute a module body in its own top-level environment."""
        prev = self.env
        try:
            self.env = env
            return self.run(node)
        finally:
            self.env = prev

    def run_block(self, statements: Iterable[nodes.ASTNode], env: Environment) -> OortObject:
        """Run the block with given environment.

        Used in function execution.
        """
        prev = self.env
        try:
            self.env = env
            result = OortNull.get_null_value()
            for stmt in statements:
                result = stmt.accept(self)
            return result
        finally:
            self.env = prev

    @staticmethod
    def _builtin_position() -> SourcePosition:
        return SourcePosition.from_location(1, 0, "<builtin>", filename="<builtin>")

    def is_truthy(self, value: OortObject) -> bool:
        return _is_truthy(value)

    def open_iterator(self, value: OortObject, position=None) -> OortObject:
        """Call `__iter__` and return the callable iterator."""
        error_position = position or self._builtin_position()
        if isinstance(value, OortType):
            raise OortTypeError(f"Class {value.name!r} is not iterable", error_position)
        if isinstance(value, OortModule):
            raise OortTypeError(f"Module {value.module_name!r} is not iterable", error_position)

        method = value.get("__iter__")
        if method is None:
            raise OortTypeError(f"Type {value.type.name!r} is not iterable", error_position)
        if not isinstance(method, OortCallableMixin):
            raise OortTypeError(
                f"Type {value.type.name!r} has a non-callable '__iter__'",
                error_position,
            )

        iterator = self.call_value(method, [], error_position)
        if not isinstance(iterator, OortCallableMixin):
            raise OortTypeError(
                f"__iter__() must return a callable iterator, got {iterator.type.name!r}",
                error_position,
            )
        return iterator

    def iterator_next(self, iterator: OortObject, position=None) -> tuple[OortObject | None, bool]:
        """Fetch one `(value, valid)` step from an iterator."""
        error_position = position or self._builtin_position()
        if isinstance(iterator, OortIterator):
            return iterator.next_value()

        step = self.call_value(iterator, [], error_position)
        if not isinstance(step, OortTuple):
            raise OortTypeError(
                f"Iterator must return a Tuple, got {step.type.name!r}",
                error_position,
            )
        if len(step.value) != 2:
            raise OortTypeError(
                "Iterator must return a 2-element Tuple (value, valid), "
                f"got {len(step.value)} element(s)",
                error_position,
            )

        value, valid = step.value
        if not isinstance(valid, OortBool):
            raise OortTypeError(
                f"Iterator 'valid' flag must be a Bool, got {valid.type.name!r}",
                error_position,
            )
        return value, valid.value

    def iter_values(self, value: OortObject, position=None) -> list[OortObject]:
        """Drain an iterable into a list for eager helpers."""
        iterator = self.open_iterator(value, position)
        if isinstance(iterator, OortIterator):
            return iterator.take_remaining()

        result: list[OortObject] = []
        while True:
            item, valid = self.iterator_next(iterator, position)
            if not valid:
                break
            assert item is not None
            result.append(item)
        return result

    def call_value(self, func, args, position=None) -> OortObject:
        """Call any Oort callable with already-evaluated positional values."""
        error_position = position or self._builtin_position()
        if isinstance(func, (OortNativeFunction, OortNativeMethod, OortVMInvokable)):
            try:
                return func(self, args, position)
            except OortException:
                raise
            except ArgumentBindingError as e:
                raise OortTypeError(str(e), error_position) from e
            except TypeError as e:
                raise OortTypeError(str(e), error_position) from e
            except Exception as e:
                raise OortRuntimeError(str(e), error_position) from e

        if isinstance(func, (OortFunction, OortMethod, OortType)):
            try:
                return func(self, args)
            except OortException:
                raise
            except ArgumentBindingError as e:
                raise OortTypeError(str(e), error_position) from e

        raise OortTypeError(f"{func.type.name} object is not callable", error_position)

    def apply_operator(self, symbol: str, lhs: OortObject, rhs: OortObject, position=None):
        """Apply a binary Oort operator to already-evaluated operands."""
        error_position = position or self._builtin_position()
        method = self._find_operator(lhs, symbol, 2, error_position)
        if method is None:
            raise OortTypeError(
                f"Type {lhs.type.name!r} does not support operator {symbol!r}",
                error_position,
            )
        return self._invoke_operator(method, [rhs], symbol, error_position)

    def values_equal(
        self,
        lhs: OortObject,
        rhs: OortObject,
        position: SourcePosition | None = None,
    ) -> bool:
        """Recursive Oort value equality (OP 0016)."""
        return self._values_equal(lhs, rhs, set(), position)

    def _values_equal(
        self,
        lhs: OortObject,
        rhs: OortObject,
        memo: set[tuple[int, int]],
        position: SourcePosition | None = None,
    ) -> bool:
        if lhs is rhs:
            return True

        if isinstance(lhs, (OortList, OortTuple)) or isinstance(rhs, (OortList, OortTuple)):
            if type(lhs) is not type(rhs):
                return False
            assert isinstance(lhs, (OortList, OortTuple))
            assert isinstance(rhs, (OortList, OortTuple))
            pair = (id(lhs), id(rhs))
            if pair in memo:
                return True
            memo.add(pair)
            if len(lhs.value) != len(rhs.value):
                return False
            return all(
                self._values_equal(left, right, memo, position)
                for left, right in zip(lhs.value, rhs.value, strict=True)
            )

        if isinstance(lhs, OortDict) or isinstance(rhs, OortDict):
            if not isinstance(lhs, OortDict) or not isinstance(rhs, OortDict):
                return False
            pair = (id(lhs), id(rhs))
            if pair in memo:
                return True
            memo.add(pair)
            if len(lhs.value) != len(rhs.value):
                return False
            for key, value in lhs.value.items():
                # Python dict lookup uses the Oort key protocol (Bool/Int
                # strict, Int/Float distinct, identity for instances).
                if key not in rhs.value:
                    return False
                if not self._values_equal(value, rhs.value[key], memo, position):
                    return False
            return True

        if isinstance(lhs, OortSet) or isinstance(rhs, OortSet):
            return isinstance(lhs, OortSet) and isinstance(rhs, OortSet) and lhs.value == rhs.value

        if isinstance(lhs, OortBool) or isinstance(rhs, OortBool):
            return (
                isinstance(lhs, OortBool) and isinstance(rhs, OortBool) and lhs.value == rhs.value
            )

        if isinstance(lhs, (OortInt, OortFloat)) or isinstance(rhs, (OortInt, OortFloat)):
            if isinstance(lhs, (OortInt, OortFloat)) and isinstance(rhs, (OortInt, OortFloat)):
                return lhs.value == rhs.value
            return False

        if isinstance(lhs, OortNull) or isinstance(rhs, OortNull):
            return isinstance(lhs, OortNull) and isinstance(rhs, OortNull)

        if isinstance(lhs, OortString) or isinstance(rhs, OortString):
            return (
                isinstance(lhs, OortString)
                and isinstance(rhs, OortString)
                and lhs.value == rhs.value
            )

        result = self.apply_operator("==", lhs, rhs, position or self._builtin_position())
        return _is_truthy(result)

    def sequence_contains(
        self,
        container: OortObject,
        item: OortObject,
        position: SourcePosition | None = None,
    ) -> bool:
        """Sequence membership with Oort value equality."""
        assert isinstance(container, (OortList, OortTuple))
        for element in container.value:
            if element is item or self._values_equal(element, item, set(), position):
                return True
        return False

    def visit_module(self, node: nodes.ModuleNode) -> OortObject:
        # Static imports are hoisted: dependencies are initialized before the
        # rest of the module body, in source order (ES module / Go style).
        statements = list(node.body.statements)
        imports = [
            stmt
            for stmt in statements
            if isinstance(stmt, (nodes.ImportStmt, nodes.ImportFromStmt))
        ]
        others = [
            stmt
            for stmt in statements
            if not isinstance(stmt, (nodes.ImportStmt, nodes.ImportFromStmt))
        ]

        result: OortObject = OortNull.get_null_value()
        for stmt in imports + others:
            result = stmt.accept(self)
        return result

    def visit_import_stmt(self, node: nodes.ImportStmt) -> OortObject:
        loader = self.module_loader
        if loader is None:
            raise OortImportError(
                "Module imports are not available in this context.", node.position
            )
        module = loader.import_module(node.module_path, node.position)
        name = node.alias or loader.binding_name(node.module_path, node.position)
        if self.env.define(name, module, mutable=False) == DefineResult.REDEFINED:
            raise OortNameError(f"Name {name!r} is already defined", node.position)
        # Importing a module activates its top-level extensions in this scope.
        self.env.add_imported_extension_scope(module.env)
        return OortNull.get_null_value()

    def visit_import_from_stmt(self, node: nodes.ImportFromStmt) -> OortObject:
        loader = self.module_loader
        if loader is None:
            raise OortImportError(
                "Module imports are not available in this context.", node.position
            )
        module, values = loader.import_names(node.module_path, list(node.names), node.position)
        for src, dst in node.names.items():
            name = dst or src
            if self.env.define(name, values[src], mutable=False) == DefineResult.REDEFINED:
                raise OortNameError(f"Name {name!r} is already defined", node.position)
        self.env.add_imported_extension_scope(module.env)
        return OortNull.get_null_value()

    def visit_block_expr(self, node: nodes.BlockExpr) -> OortObject:
        block_env = Environment(outer=self.env, name="<block>")
        return self.run_block(node.statements, block_env)

    def visit_var_decl(self, node: nodes.VarDecl) -> OortObject:
        if node.init_value is None:
            raise OortSyntaxError("Variable declaration requires an initializer", node.position)
        init_value = node.init_value.accept(self)

        targets = node.decl_targets
        if len(targets) == 1:
            values = [init_value]
        else:
            # Multiple declaration targets are unpacked from a tuple/list.
            if isinstance(init_value, (OortTuple, OortList)):
                values = list(init_value.value)
            else:
                raise OortTypeError(
                    "Multiple declaration targets require a tuple or list initializer",
                    node.init_value.position,
                )
            if len(values) != len(targets):
                raise OortTypeError(
                    f"Cannot unpack {len(values)} value(s) into {len(targets)} target(s)",
                    node.init_value.position,
                )

        for decl_target, value in zip(targets, values, strict=True):
            define_result = self.env.define(decl_target.name, value, mutable=node.mutable)
            if define_result == DefineResult.REDEFINED:
                raise OortSyntaxError(
                    f"Name {decl_target.name!r} is already defined", decl_target.position
                )
        return OortNull.get_null_value()

    def _read_lvalue(self, lhs: nodes.ASTNode) -> OortObject:
        """Read the current value of an assignment target."""
        if isinstance(lhs, nodes.Name):
            entry = self.lookup_variable(lhs.id, lhs)
            if entry is None:
                raise OortNameError(f"Name {lhs.id!r} is not defined", lhs.position)
            return entry.value
        if isinstance(lhs, nodes.Attribute):
            return lhs.accept(self)
        if isinstance(lhs, nodes.Subscript):
            return lhs.accept(self)
        raise OortSyntaxError("Cannot assign to expression here.", lhs.position)

    def visit_assignment(self, node: nodes.Assignment) -> OortObject:
        if not isinstance(node.lhs, (nodes.LValue, nodes.TupleLiteral)):
            raise OortSyntaxError("Cannot assign to expression here.", node.lhs.position)

        if node.op.text == "=":
            rhs = node.rhs.accept(self)
        else:
            base_op = _AUG_OPS.get(node.op.text)
            if base_op is None:
                raise UnsupportedSyntax(
                    f"Unsupported assignment operator {node.op.text!r}",
                    SourcePosition.from_token(node.op),
                )
            current = self._read_lvalue(node.lhs)
            rhs_value = node.rhs.accept(self)
            rhs = self._apply_binary(base_op, current, rhs_value, node.op)

        self._assign(node.lhs, rhs)
        return OortNull.get_null_value()

    def _assign(self, lhs: nodes.ASTNode, rhs: OortObject):
        if isinstance(lhs, nodes.TupleLiteral):
            if isinstance(rhs, (OortTuple, OortList)):
                values = list(rhs.value)
            else:
                raise OortTypeError("Cannot unpack a non-tuple value in assignment", lhs.position)
            if len(values) != len(lhs.elements):
                raise OortTypeError(
                    f"Cannot unpack {len(values)} value(s) into "
                    f"{len(lhs.elements)} assignment target(s)",
                    lhs.position,
                )
            for target, value in zip(lhs.elements, values, strict=True):
                self._assign(target, value)
            return

        if isinstance(lhs, nodes.Name):
            binding = lhs.binding
            assert binding is not None and binding.name == lhs.id
            if binding.depth is None:
                assign_result = self.env.module_root.assign(lhs.id, rhs)
            else:
                assign_result = self.env.assign_at(lhs.id, rhs, binding.depth)
            if assign_result == AssignResult.NOT_FOUND:
                raise OortNameError(f"Name {lhs.id!r} is not defined", lhs.position)
            elif assign_result == AssignResult.IMMUTABLE:
                raise OortSyntaxError(f"Cannot assign to immutable {lhs.id!r}", lhs.position)
        elif isinstance(lhs, nodes.Subscript):
            value = lhs.value.accept(self)
            index = lhs.index.accept(self)
            self.set_item(value, index, rhs, lhs.position)
        else:
            assert isinstance(lhs, nodes.Attribute)
            assert lhs.ctx == nodes.LValueContext.STORE
            value = lhs.value.accept(self)
            self.set_attribute(value, lhs.attribute, rhs, lhs.position)

    def set_attribute(
        self,
        value: OortObject,
        name: str,
        new_value: OortObject,
        position: SourcePosition,
    ) -> None:
        """Assign an attribute on an already-evaluated receiver."""
        if value.is_native:
            raise OortTypeError(f"Cannot set attribute {name!r} to native object", position)
        if not isinstance(value, OortInstance):
            raise OortTypeError(
                f"Cannot set attribute {name!r} on {value.type.name!r} object",
                position,
            )

        if isinstance(value, OortType):
            # Writing through a class object must not replace methods or
            # class methods inherited from the class/metaclass MRO.
            if find_callable_class_member(name, value) is not None:
                raise OortAttributeError(
                    f"Cannot shadow method {name!r} with a class attribute",
                    position,
                )
        elif find_callable_class_member(name, value.type) is not None:
            raise OortAttributeError(
                f"Cannot shadow method {name!r} with an instance field",
                position,
            )

        if value.type.static_layout and not isinstance(value, OortType):
            slot = value.type.find_slot(name)
            if slot is None:
                raise OortAttributeError(
                    f"Class {value.type.name!r} has no slot {name!r}",
                    position,
                )
            if not slot.mutable:
                current_method = self._current_method
                is_initializer = getattr(current_method, "is_initializer", False)
                if not (is_initializer and name not in value.fields):
                    raise OortAttributeError(
                        f"Cannot assign to read-only slot {name!r}",
                        position,
                    )
        value.set(name, new_value)

    def get_attribute(
        self,
        value: OortObject,
        name: str,
        position: SourcePosition,
        *,
        env: Environment | None = None,
    ) -> OortObject:
        """Resolve an attribute on an already-evaluated value."""
        result = value.get(name)
        if result is not None:
            return result

        # `super` searches class members only; extensions are never a fallback.
        if isinstance(value, OortSuperProxy):
            raise OortAttributeError(
                f"Type {value.receiver.type.name!r} has no super attribute {name!r}",
                position,
            )

        if (
            isinstance(value, OortInstance)
            and not isinstance(value, OortType)
            and value.type.static_layout
        ):
            slot = value.type.find_slot(name)
            if slot is not None and name not in value.fields:
                raise OortAttributeError(f"Slot {name!r} is not initialized", position)

        lookup = (env or self.env).lookup_extension(value.type, name)
        if lookup.ambiguous:
            raise OortAttributeError(self._ambiguous_extension_message(lookup), position)
        if lookup.match is not None:
            return _bind_extension_method(value, lookup.match.func, lookup.match.target)

        if isinstance(value, OortInstance) and not isinstance(value, OortType):
            receiver_id = id(value)
            if receiver_id not in self._missing_hook_receivers:
                hook = value.get("on_missing")
                if isinstance(hook, OortCallableMixin):
                    self._missing_hook_receivers.add(receiver_id)
                    try:
                        return self.call_value(
                            hook,
                            [OortString(name)],
                            position,
                        )
                    finally:
                        self._missing_hook_receivers.discard(receiver_id)

        raise OortAttributeError(f"{value.type.name!r} object has no attribute {name!r}", position)

    def visit_attribute(self, node: nodes.Attribute) -> OortObject:
        value = node.value.accept(self)
        return self.get_attribute(value, node.attribute, node.position)

    @staticmethod
    def _ambiguous_extension_message(
        lookup: ExtensionLookup, kind: str = "method", symbol: str | None = None
    ) -> str:
        def origin(func: OortObject) -> str:
            closure = getattr(func, "closure", None)
            if closure is not None:
                return str(closure.module_root.name)
            env = getattr(func, "env", None)
            if env is not None:
                return str(env.module_root.name)
            return "<vm>"

        def label_of(func: OortObject) -> str:
            proto = getattr(func, "proto", None)
            if proto is not None:
                return str(proto.name)
            return str(getattr(func, "name", "<function>"))

        names = sorted({origin(match.func) for match in lookup.ambiguous})
        target = lookup.ambiguous[0].target.name
        label = symbol if symbol is not None else label_of(lookup.ambiguous[0].func)
        origins = " and ".join(repr(origin) for origin in names)
        return (
            f"Ambiguous extension {kind} {label!r} for type {target!r}: candidates from {origins}."
        )

    def get_item(
        self,
        value: OortObject,
        index: OortObject,
        position: SourcePosition,
        *,
        env: Environment | None = None,
    ) -> OortObject:
        """Read `value[index]`, honouring user `operator "[]"` methods."""
        if isinstance(value, OortInstance) and not isinstance(value, OortType):
            method = self._find_operator(value, "[]", 2, position, env=env)
            if method is None:
                raise OortTypeError(
                    f"Type {value.type.name!r} does not support subscripting "
                    '(define `operator "[]"`).',
                    position,
                )
            return self._invoke_operator(method, [index], "[]", position)

        try:
            return value[index]
        except Exception as e:
            raise OortRuntimeError(f"{e}", position) from e

    def set_item(
        self,
        value: OortObject,
        index: OortObject,
        item: OortObject,
        position: SourcePosition,
        *,
        env: Environment | None = None,
    ) -> None:
        """Write `value[index] = item`, honouring user `operator "[]="` methods."""
        if isinstance(value, OortInstance) and not isinstance(value, OortType):
            method = self._find_operator(value, "[]=", 3, position, env=env)
            if method is None:
                raise OortTypeError(
                    f"Type {value.type.name!r} does not support subscript "
                    'assignment (define `operator "[]="`).',
                    position,
                )
            self._invoke_operator(method, [index, item], "[]=", position)
            return

        try:
            value[index] = item
        except Exception as e:
            raise OortRuntimeError(f"{e}", position) from e

    def visit_subscript(self, node: nodes.Subscript) -> OortObject:
        value = node.value.accept(self)
        index = node.index.accept(self)
        return self.get_item(value, index, node.position)

    def visit_call(self, node: nodes.Call) -> OortObject:
        func = node.func.accept(self)

        # Evaluate every argument exactly once, in source order. Keyword and
        # trailing-block metadata is carried into the binder.
        evaluated = [
            EvaluatedArgument(
                value=arg.accept(self),
                keyword=arg.keyword,
                kind=arg.kind,
            )
            for arg in node.args
        ]

        if isinstance(func, (OortNativeFunction, OortNativeMethod)):
            # Native functions have no parameter names; keywords are rejected.
            if any(arg.keyword is not None for arg in evaluated):
                raise OortTypeError(
                    f"Built-in function {func.name!r} does not accept keyword arguments",
                    node.position,
                )
            values = [arg.value for arg in evaluated]
            try:
                return func(self, values, node.position)
            except OortException:
                raise
            except TypeError as e:
                raise OortTypeError(f"{e}", node.position)
            except Exception as e:
                raise OortRuntimeError(f"{e}", node.position)
        elif isinstance(func, (OortFunction, OortMethod, OortType)):
            try:
                return func(self, evaluated)
            except ArgumentBindingError as e:
                raise OortTypeError(str(e), node.position) from e
        else:
            assert isinstance(func, OortObject)
            raise OortTypeError(f"{func.type.name} object is not callable", node.func.position)

    def _find_operator(
        self,
        receiver: OortObject,
        symbol: str,
        operand_count: int,
        position: SourcePosition,
        *,
        env: Environment | None = None,
    ):
        """Find an operator method for `receiver`, then an extension operator."""
        method = _get_operator_from_cls(symbol, operand_count, receiver.type, receiver)
        if method is not None:
            return method

        lookup = (env or self.env).lookup_extension_operator(receiver.type, symbol, operand_count)
        if lookup.ambiguous:
            raise OortTypeError(
                self._ambiguous_extension_message(lookup, "operator", symbol),
                position,
            )
        if lookup.match is not None:
            return _bind_extension_method(receiver, lookup.match.func, lookup.match.target)
        return None

    def _invoke_operator(self, method, args: list[OortObject], symbol: str, position):
        try:
            if isinstance(method, OortNativeMethod):
                result = method(self, args, position)
            else:
                result = method(self, args)
        except OortException:
            raise
        except TypeError as e:
            raise OortTypeError(
                f"Operator {symbol!r} is not supported for these operands: {e}", position
            ) from e
        except Exception as e:
            raise OortRuntimeError(f"{e}", position) from e
        return result

    def apply_binary(
        self,
        op_text: str,
        lhs: OortObject,
        rhs: OortObject,
        position: SourcePosition | None = None,
        *,
        env: Environment | None = None,
    ) -> OortObject:
        """Apply a binary operator using an already-resolved source position."""
        position = position or self._builtin_position()

        # Identity is not overloadable.
        if op_text == "is":
            return OortBool.get_bool_value(lhs is rhs)
        if op_text == "!is":
            return OortBool.get_bool_value(lhs is not rhs)

        # Membership dispatches to the container (the right operand).
        if op_text in ("in", "!in"):
            method = self._find_operator(rhs, op_text, 2, position, env=env)
            if method is None and op_text == "!in":
                method = self._find_operator(rhs, "in", 2, position, env=env)
                if method is not None:
                    result = self._invoke_operator(method, [lhs], "in", position)
                    return OortBool.get_bool_value(not _is_truthy(result))
            if method is None:
                raise OortTypeError(
                    f"Type {rhs.type.name!r} does not support operator {op_text!r}", position
                )
            result = self._invoke_operator(method, [lhs], op_text, position)
            return OortBool.get_bool_value(_is_truthy(result))

        method = self._find_operator(lhs, op_text, 2, position, env=env)
        if method is None and op_text == "!=":
            # `!=` defaults to the negation of `==`.
            method = self._find_operator(lhs, "==", 2, position, env=env)
            if method is not None:
                result = self._invoke_operator(method, [rhs], "==", position)
                return OortBool.get_bool_value(not _is_truthy(result))
        if method is None:
            raise OortTypeError(
                f"Type {lhs.type.name!r} does not support operator {op_text!r}", position
            )
        return self._invoke_operator(method, [rhs], op_text, position)

    def _apply_binary(self, op_text: str, lhs: OortObject, rhs: OortObject, op_token):
        return self.apply_binary(op_text, lhs, rhs, SourcePosition.from_token(op_token))

    def visit_binary_expr(self, node: nodes.BinaryExpr) -> OortObject:
        lhs = node.lhs.accept(self)
        rhs = node.rhs.accept(self)
        return self._apply_binary(node.op.text, lhs, rhs, node.op)

    def apply_unary(
        self,
        op_text: str,
        operand: OortObject,
        position: SourcePosition | None = None,
        *,
        env: Environment | None = None,
    ) -> OortObject:
        """Apply a unary operator using an already-resolved source position."""
        position = position or self._builtin_position()
        if op_text == "not":
            return OortBool.get_bool_value(not _is_truthy(operand))

        method = self._find_operator(operand, op_text, 1, position, env=env)
        if method is None:
            raise OortTypeError(
                f"Type {operand.type.name!r} does not support operator {op_text!r}", position
            )
        return self._invoke_operator(method, [], op_text, position)

    def _apply_unary(self, op_text: str, operand: OortObject, op_token) -> OortObject:
        return self.apply_unary(op_text, operand, SourcePosition.from_token(op_token))

    def visit_unary_expr(self, node: nodes.UnaryExpr) -> OortObject:
        operand = node.operand.accept(self)
        return self._apply_unary(node.op.text, operand, node.op)

    def visit_and_expr(self, node: nodes.AndExpr) -> OortObject:
        lhs = node.lhs.accept(self)
        if _is_truthy(lhs):
            return node.rhs.accept(self)
        else:
            return lhs

    def visit_or_expr(self, node: nodes.OrExpr) -> OortObject:
        lhs = node.lhs.accept(self)
        if _is_truthy(lhs):
            return lhs
        else:
            return node.rhs.accept(self)

    def visit_return_expr(self, node: nodes.ReturnExpr) -> None:
        if node.value is None:
            raise OortReturn(OortNull.get_null_value())
        else:
            raise OortReturn(node.value.accept(self))

    def visit_continue_expr(self, node: nodes.ContinueExpr) -> None:
        raise OortContinue()

    def visit_break_expr(self, node: nodes.BreakExpr) -> None:
        value = OortNull.get_null_value() if node.value is None else node.value.accept(self)
        raise OortBreak(value)

    def visit_implicit_super_expr(self, node: nodes.ImplicitSuperExpr) -> OortSuperProxy:
        entry = self.lookup_variable("this", node)
        if entry is None:
            raise OortNameError("Cannot find receiver for 'super' call", node.position)
        receiver = entry.value

        # `super` must resume after the class that *defines* the currently
        # executing method, not after the receiver's dynamic type.
        defining_type = getattr(self._current_method, "defining_type", None)
        if defining_type is None or not (
            isinstance(receiver, OortObject) and defining_type in receiver.type.mro()
        ):
            defining_type = receiver.type
        return OortSuperProxy(defining_type, receiver)

    @staticmethod
    def _is_reserved_method_name(name: str) -> bool:
        """Dunder-style names the runtime does not dispatch to user code."""
        return len(name) > 4 and name.startswith("__") and name.endswith("__")

    def initialize_instance_slots(self, instance: "OortInstance", class_type: "OortType"):
        """Evaluate declared slot initializers for a fresh instance."""
        for slot in class_type.slot_definitions():
            if slot.initializer_callable is not None:
                value = self.call_value(slot.initializer_callable, [], slot.position)
            elif slot.initializer is not None:
                previous_env = self.env
                self.env = slot.closure
                try:
                    value = slot.initializer.accept(self)
                finally:
                    self.env = previous_env
            else:
                continue
            instance.fields[slot.name] = value

    def check_instance_slots(self, instance: "OortInstance", class_type: "OortType"):
        """Fail if the constructor left any declared slot uninitialized."""
        missing = [
            slot
            for slot in class_type.slot_definitions()
            if (
                slot.initializer is None
                and slot.initializer_callable is None
                and slot.name not in instance.fields
            )
        ]
        if missing:
            names = ", ".join(slot.name for slot in missing)
            raise OortTypeError(
                f"Class {class_type.name!r} did not initialize slot(s): {names}.",
                missing[0].position,
            )

    def visit_class_def(self, node: nodes.ClassDef) -> OortType:
        # Visit base classes and metaclasses.
        bases = []
        for base_node in node.bases:
            base = base_node.accept(self)
            if not isinstance(base, OortType):
                raise OortTypeError(f"{base.type.name!r} object is not a class", base_node.position)
            bases.append(base)

        metaclass: OortType | None = None
        if node.meta is not None:
            metaclass_value = node.meta.accept(self)
            if not isinstance(metaclass_value, OortType):
                raise OortTypeError(
                    f"{metaclass_value.type.name!r} object is not a class", node.meta.position
                )
            if not metaclass_value.is_metaclass:
                raise OortTypeError(
                    f"{metaclass_value.type.name!r} object is not a metaclass", node.meta.position
                )
            metaclass = metaclass_value

        # Define class name (visible in class body).
        try:
            cls = OortType.create_type_object(node.name, bases=bases, metaclass=metaclass)
        except TypeError as e:
            raise OortTypeError(f"{e}", node.name_position)

        self.env.define(node.name, cls, mutable=False)

        # Visit class body.
        class_env = Environment(outer=self.env, name=node.name)
        prev = self.env
        try:
            self.env = class_env
            for stmt in node.body.statements:
                if isinstance(stmt, nodes.VarDecl):
                    self._define_slot(cls, stmt, class_env)
                    continue

                result = stmt.accept(self)

                if isinstance(stmt, nodes.FunctionDef) and not stmt.is_lambda:
                    # Dunder methods are only honoured where the runtime
                    # actually calls them; silently storing the rest would
                    # look like a working overload that is never used.
                    if self._is_reserved_method_name(stmt.name) and (
                        stmt.is_class_method or stmt.name not in ("__init__", "__iter__")
                    ):
                        raise OortTypeError(
                            f"Special method {stmt.name!r} is not supported.",
                            stmt.name_position,
                        )
                    # Method definition.
                    if stmt.is_operator:
                        cls.set_operator(stmt.operator_symbol, stmt.operator_operand_count, result)
                    elif stmt.is_class_method:
                        cls.set_class_field(stmt.name, result)
                    else:
                        cls.set(stmt.name, result)
                else:
                    # Allow any type of statement in class body.
                    # TODO: Add compiler options to control this.
                    pass
        finally:
            self.env = prev
        return cls

    def _define_slot(self, cls: OortType, node: nodes.VarDecl, class_env: Environment):
        if len(node.decl_targets) != 1:
            raise OortSyntaxError(
                "Class-body slot declarations require a single target.", node.position
            )
        target = node.decl_targets[0]
        if target.name in cls.slots:
            raise OortSyntaxError(f"Slot {target.name!r} is already declared.", target.position)
        cls.slots[target.name] = SlotDefinition(
            name=target.name,
            mutable=node.mutable,
            initializer=node.init_value,
            closure=class_env,
            position=target.position,
        )
        cls.static_layout = True

    def visit_enum_def(self, node: nodes.EnumDef) -> OortType:
        enum_type = OortType.create_type_object(node.name, bases=[self.runtime.types.object_type])
        enum_type.adt_variants = {
            constructor.name: len(constructor.fields) for constructor in node.constructors
        }

        for constructor in node.constructors:
            arity = len(constructor.fields)
            if arity == 0:
                value: OortObject = OortADT(enum_type, constructor.name)
            else:

                def construct(
                    *values: OortObject,
                    _name: str = constructor.name,
                    _arity: int = arity,
                ) -> OortADT:
                    if len(values) != _arity:
                        raise TypeError(
                            f"Constructor {_name!r} expects {_arity} argument(s), got {len(values)}"
                        )
                    return OortADT(enum_type, _name, values)

                value = OortNativeFunction(
                    construct,
                    name=constructor.name,
                    mode=NativeMode.VALUE,
                )
            if self.env.define(constructor.name, value, mutable=False) == DefineResult.REDEFINED:
                raise OortSyntaxError(
                    f"Constructor {constructor.name!r} is already defined.",
                    constructor.position,
                )
        return enum_type

    def visit_match_expr(self, node: nodes.MatchExpr) -> OortObject:
        value = node.scrutinee.accept(self)
        for arm in node.arms:
            bindings: dict[str, OortObject] = {}
            if not self._match_pattern(arm.pattern, value, bindings):
                continue

            arm_env = Environment(outer=self.env, name="<match-arm>")
            for name, bound in bindings.items():
                arm_env.define(name, bound, mutable=False)
            prev = self.env
            try:
                self.env = arm_env
                return arm.body.accept(self)
            finally:
                self.env = prev

        raise OortRuntimeError(
            f"No match arm matched value {value!r}.",
            node.position,
        )

    def _match_pattern(
        self,
        pattern: nodes.Pattern,
        value: OortObject,
        bindings: dict[str, OortObject],
    ) -> bool:
        if isinstance(pattern, nodes.WildcardPattern):
            return True
        if isinstance(pattern, nodes.NamePattern):
            if isinstance(value, OortADT) and value.type.adt_variants is not None:
                arity = value.type.adt_variants.get(pattern.name)
                if arity is not None:
                    if arity != 0:
                        raise OortTypeError(
                            f"Constructor {pattern.name!r} expects {arity} argument(s).",
                            pattern.position,
                        )
                    if value.variant != pattern.name:
                        return False
                    bindings[pattern.name] = value
                    return True
            bindings[pattern.name] = value
            return True
        if isinstance(pattern, nodes.ConstructorPattern):
            if not isinstance(value, OortADT) or value.variant != pattern.name:
                return False
            if len(value.values) != len(pattern.args):
                raise OortTypeError(
                    f"Constructor {pattern.name!r} expects {len(value.values)} "
                    f"argument(s), got {len(pattern.args)}.",
                    pattern.position,
                )
            for subpattern, payload in zip(pattern.args, value.values):
                if not self._match_pattern(subpattern, payload, bindings):
                    return False
            return True
        return False

    def visit_function_def(self, node: nodes.FunctionDef) -> OortFunction:
        func = OortFunction(node, closure=self.env)
        if node.is_extension:
            receiver_name = node.extension_receiver
            assert receiver_name is not None
            entry = self.env.get(receiver_name)
            if entry is None:
                raise OortNameError(
                    f"Extension receiver {receiver_name!r} is not defined.",
                    node.name_position,
                )
            receiver = entry.value
            if not isinstance(receiver, OortType):
                raise OortTypeError(
                    f"Extension receiver {receiver_name!r} is not a type.",
                    node.name_position,
                )
            if node.is_operator:
                assert node.operator_symbol is not None
                assert node.operator_operand_count is not None
                result = self.env.register_extension_operator(
                    receiver,
                    node.operator_symbol,
                    node.operator_operand_count,
                    func,
                )
                duplicate_message = (
                    f"Extension operator {node.operator_symbol!r} for "
                    f"{receiver.name!r} is already defined in this scope."
                )
            else:
                result = self.env.register_extension(receiver, node.name, func)
                duplicate_message = (
                    f"Extension method {receiver.name!r}.{node.name} is already "
                    f"defined in this scope."
                )
            if result == DefineResult.REDEFINED:
                raise OortSyntaxError(duplicate_message, node.name_position)
            return func

        self.env.define(node.name, func, mutable=False)
        return func

    def visit_if_expr(self, node: nodes.IfExpr) -> OortObject:
        cond_value = node.condition.accept(self)

        if _is_truthy(cond_value):
            return node.if_block.accept(self)
        elif node.else_block is not None:
            return node.else_block.accept(self)
        else:
            return OortNull.get_null_value()

    def visit_while_expr(self, node: nodes.WhileExpr) -> OortObject:
        result = OortNull.get_null_value()
        while _is_truthy(node.condition.accept(self)):
            try:
                node.body.accept(self)
            except OortContinue:
                continue
            except OortBreak as e:
                result = OortNull.get_null_value() if e.value is None else e.value
                break
        return result

    def visit_for_expr(self, node: nodes.ForExpr) -> OortObject:
        iterable = node.iterator.accept(self)
        position = node.iterator.position
        iterator = self.open_iterator(iterable, position)

        result = OortNull.get_null_value()
        while True:
            item, valid = self.iterator_next(iterator, position)
            if not valid:
                break

            # A fresh environment per iteration gives each captured loop
            # variable its own binding (like JavaScript `let`/C# `foreach`,
            # not Python's shared loop variable).
            loop_env = Environment(outer=self.env, name="<for>")
            prev = self.env
            try:
                self.env = loop_env
                assert item is not None
                if len(node.vars) == 1:
                    self.env.define(node.vars[0].name, item)
                else:
                    if isinstance(item, (OortTuple, OortList)):
                        values = list(item.value)
                    else:
                        raise OortTypeError("Cannot unpack a non-tuple value in for loop", position)
                    if len(values) != len(node.vars):
                        raise OortTypeError(
                            f"Cannot unpack {len(values)} value(s) into {len(node.vars)} "
                            f"loop variable(s)",
                            position,
                        )
                    for var, value in zip(node.vars, values, strict=True):
                        self.env.define(var.name, value)

                try:
                    node.body.accept(self)
                except OortContinue:
                    continue
                except OortBreak as e:
                    result = OortNull.get_null_value() if e.value is None else e.value
                    break
            finally:
                self.env = prev

        return result

    def visit_list_literal(self, node: nodes.ListLiteral) -> OortList:
        return OortList([item.accept(self) for item in node.elements])

    def visit_tuple_literal(self, node: nodes.TupleLiteral) -> OortTuple:
        return OortTuple(tuple(item.accept(self) for item in node.elements))

    def visit_set_literal(self, node: nodes.SetLiteral) -> OortSet:
        return OortSet({item.accept(self) for item in node.elements})

    def visit_dict_literal(self, node: nodes.DictLiteral) -> OortDict:
        items = {}
        for key_node, value_node in node.items:
            if key_node is None:
                raise UnsupportedSyntax("Dictionary unpacking is not supported yet.", node.position)
            items[key_node.accept(self)] = value_node.accept(self)
        return OortDict(items)

    def visit_slice_literal(self, node: nodes.SliceLiteral) -> OortSlice:
        return OortSlice(
            None if node.start is None else node.start.accept(self),
            None if node.stop is None else node.stop.accept(self),
            None if node.step is None else node.step.accept(self),
        )

    def visit_int_constant(self, node: nodes.IntConstant) -> OortInt:
        assert isinstance(node.value, int)
        return OortInt(node.value)

    def visit_float_constant(self, node: nodes.FloatConstant) -> OortFloat:
        assert isinstance(node.value, float)
        return OortFloat(node.value)

    def visit_string_constant(self, node: nodes.StringConstant) -> OortString:
        assert isinstance(node.value, str)
        return OortString(node.value)

    def visit_boolean_constant(self, node: nodes.BooleanConstant) -> OortBool:
        assert isinstance(node.value, bool)
        return OortBool.get_bool_value(node.value)

    def visit_null_constant(self, node: nodes.NullConstant) -> OortNull:
        return OortNull.get_null_value()

    def visit_name(self, node: nodes.Name) -> OortObject:
        if node.ctx == nodes.LValueContext.LOAD:
            entry = self.lookup_variable(node.id, node)
            if entry is None:
                raise OortNameError(f"Name {node.id!r} is not defined", node.position)
            return entry.value
        else:
            # Store & delete will be processed in assignment node.
            raise AssertionError("Unreachable code")

    def lookup_variable(self, name: str, node: nodes.ASTNode) -> Entry | None:
        """Lookup a variable through the binding attached by pass 1."""
        binding = node.binding
        assert binding is not None and binding.name == name, "Name node was not resolved"
        if binding.depth is None:
            return self.env.module_root.get(name)
        return self.env.get_at(name, binding.depth)
