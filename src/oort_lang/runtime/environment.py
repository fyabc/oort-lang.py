#! /usr/bin/env python

from __future__ import annotations

import dataclasses
import logging
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .objects import OortObject
    from .type_system import OortType

GLOBAL_ENV_NAME = "<global>"


@dataclasses.dataclass
class Entry:
    value: OortObject
    mutable: bool = True


class DefineResult(Enum):
    OK = 1
    REDEFINED = 2


class AssignResult(Enum):
    OK = 1
    NOT_FOUND = 2
    IMMUTABLE = 3


@dataclasses.dataclass(frozen=True)
class ExtensionMatch:
    """One extension method candidate."""

    target: OortType  # The MRO type the extension was defined on.
    func: OortObject


@dataclasses.dataclass(frozen=True)
class ExtensionLookup:
    """Result of an extension lookup: one match, ambiguity, or nothing."""

    match: ExtensionMatch | None = None
    ambiguous: tuple[ExtensionMatch, ...] = ()


class Environment:
    """Oort environment in AST interpreter."""

    def __init__(
        self,
        outer: Environment | None = None,
        name: str = GLOBAL_ENV_NAME,
        *,
        allow_redefine: bool | None = None,
        is_module_root: bool = False,
    ):
        self.values: dict[str, Entry] = {}
        self.outer: Environment | None = outer
        self.name = name
        # Only the outermost scope of a compilation unit (the entry module or
        # a loaded module) allows top-level redefinition. Class bodies, blocks
        # and call frames keep rejecting duplicates.
        self.allow_redefine = (outer is None) if allow_redefine is None else allow_redefine
        # `module_root` is the environment that owns `Binding.depth is None`.
        # It cannot be derived from `outer is None` alone: module roots have a
        # shared builtins environment as their outer scope.
        if is_module_root or outer is None:
            self.module_root: Environment = self
        else:
            self.module_root = outer.module_root

        # Extension methods and operators are not values; they live in their
        # own per-scope tables and are looked up lexically at the use site.
        self.extensions: dict[tuple[OortType, str], OortObject] = {}
        self.extension_operators: dict[tuple[OortType, str, int], OortObject] = {}
        # Modules imported by this scope whose top-level extensions are active.
        # Only the source scope's local tables are consulted, never its own
        # imported scopes: imports are not transitive.
        self.imported_extension_scopes: list[Environment] = []

    def _ancestor(self, depth: int) -> Environment:
        env: Environment | None = self
        for _ in range(depth):
            assert env is not None
            env = env.outer
        assert env is not None
        return env

    def get(self, name: str) -> Entry | None:
        """Search name from current env and outer env."""
        value = self.values.get(name, None)
        if value is None and self.outer is not None:
            value = self.outer.get(name)
        else:
            logging.debug(f"Get {name!r} from {self.name}.")
        return value

    def get_at(self, name: str, depth: int) -> Entry | None:
        env = self._ancestor(depth)
        logging.debug(f"Get {name!r} from {env.name} (depth = {depth}).")
        return env.values.get(name, None)

    def define(self, name: str, value: OortObject, mutable: bool = False) -> DefineResult:
        """Define a new name to value."""
        if name in self.values and not self.allow_redefine:
            return DefineResult.REDEFINED
        mut_s = "(mut) " if mutable else ""
        logging.debug(f"Define {name!r} to {mut_s}{value}.")
        self.values[name] = Entry(value, mutable)
        return DefineResult.OK

    def assign(self, name: str, value: OortObject) -> AssignResult:
        """Assign a value to a name."""
        env: Environment | None = self
        while env is not None and name not in env.values:
            env = env.outer
        if env is None:
            return AssignResult.NOT_FOUND
        entry = env.values[name]
        if not entry.mutable:
            return AssignResult.IMMUTABLE
        entry.value = value
        return AssignResult.OK

    def assign_at(self, name: str, value: OortObject, depth: int) -> AssignResult:
        env = self._ancestor(depth)
        if name not in env.values:
            return AssignResult.NOT_FOUND
        entry = env.values[name]
        if not entry.mutable:
            return AssignResult.IMMUTABLE
        entry.value = value
        return AssignResult.OK

    def register_extension(
        self, target_type: OortType, name: str, func: OortObject
    ) -> DefineResult:
        """Register a local extension method in this scope."""
        return self._register_extension_in(self.extensions, (target_type, name), func)

    def register_extension_operator(
        self,
        target_type: OortType,
        symbol: str,
        operand_count: int,
        func: OortObject,
    ) -> DefineResult:
        """Register a local extension operator in this scope."""
        return self._register_extension_in(
            self.extension_operators, (target_type, symbol, operand_count), func
        )

    def _register_extension_in(
        self, table: dict[Any, OortObject], key: tuple[Any, ...], func: OortObject
    ) -> DefineResult:
        if key in table and not self.allow_redefine:
            return DefineResult.REDEFINED
        table[key] = func
        return DefineResult.OK

    def add_imported_extension_scope(self, source: Environment) -> None:
        """Activate the top-level extensions defined by an imported module."""
        if not any(scope is source for scope in self.imported_extension_scopes):
            self.imported_extension_scopes.append(source)

    def lookup_extension(self, receiver_type: OortType, name: str) -> ExtensionLookup:
        """Find an extension method visible from this scope."""
        return self._lookup_extension(receiver_type, (name,), operators=False)

    def lookup_extension_operator(
        self, receiver_type: OortType, symbol: str, operand_count: int
    ) -> ExtensionLookup:
        """Find an extension operator visible from this scope."""
        return self._lookup_extension(receiver_type, (symbol, operand_count), operators=True)

    @staticmethod
    def _nearest_in(
        table: Mapping[Any, OortObject], receiver_type: OortType, suffix: tuple[Any, ...]
    ) -> tuple[int, ExtensionMatch] | None:
        """Return the most specific match and its MRO distance."""
        for index, mro_type in enumerate(receiver_type.mro()):
            func = table.get((mro_type, *suffix))
            if func is not None:
                return index, ExtensionMatch(mro_type, func)
        return None

    def _lookup_extension(
        self, receiver_type: OortType, suffix: tuple[Any, ...], *, operators: bool
    ) -> ExtensionLookup:
        """Walk the lexical scope chain with local-before-imported sub-tiers."""
        env: Environment | None = self
        while env is not None:
            table = env.extension_operators if operators else env.extensions

            # Local extensions in this scope win unconditionally, even when an
            # imported extension would match a more derived type.
            local = self._nearest_in(table, receiver_type, suffix)
            if local is not None:
                return ExtensionLookup(match=local[1])

            # Imported scopes form one candidate pool compared by MRO distance.
            best_index: int | None = None
            candidates: list[ExtensionMatch] = []
            for scope in env.imported_extension_scopes:
                imported = scope.extension_operators if operators else scope.extensions
                found = self._nearest_in(imported, receiver_type, suffix)
                if found is None:
                    continue
                index, match = found
                if best_index is None or index < best_index:
                    best_index, candidates = index, [match]
                elif index == best_index:
                    candidates.append(match)

            if candidates:
                # Importing the same module under several aliases must not
                # create a false ambiguity.
                unique = list({id(match.func): match for match in candidates}.values())
                if len(unique) == 1:
                    return ExtensionLookup(match=unique[0])
                return ExtensionLookup(ambiguous=tuple(unique))

            env = env.outer
        return ExtensionLookup()

    def pprint(self):
        """Pretty print current environment."""
        env_chain: list[Environment] = []
        current: Environment | None = self
        while current is not None:
            env_chain.append(current)
            current = current.outer
        for env in reversed(env_chain):
            print(f"{env.name}:")
            for name, entry in env.values.items():
                mut_s = "(mut) " if entry.mutable else ""
                print(f"  {name!r}: {mut_s}{entry.value}")
