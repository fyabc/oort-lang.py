#! /usr/bin/env python

"""Module resolution, loading and caching for the runtime backends."""

from __future__ import annotations

import dataclasses
from enum import Enum, auto
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from ..diagnostics.runtime_errors import OortImportError
from ..parser.dialect import DEFAULT_DIALECT_NAME

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from ..ast import nodes
    from ..source.source_position import SourcePosition
    from .environment import Environment
    from .objects import OortModule, OortObject


def _split_spec(spec: str) -> PurePosixPath:
    """Normalize module separators without touching the host filesystem."""
    return PurePosixPath(spec.replace("\\", "/"))


def _with_extension(spec: str, position: SourcePosition) -> str:
    """Return the module filename, appending `.ort` only when it is omitted."""
    suffix = _split_spec(spec).suffix
    if suffix and suffix.lower() != ".ort":
        raise OortImportError(
            f"Module path {spec!r} must use the .ort extension or none.", position
        )
    return spec if suffix else spec + ".ort"


def _is_relative_spec(spec: str) -> bool:
    normalized = spec.replace("\\", "/")
    return normalized.startswith(("./", "../"))


def resolve_module_path(
    spec: str,
    *,
    importer_dir: Path,
    entry_dir: Path,
    search_paths: Sequence[Path],
    position: SourcePosition,
) -> Path:
    """Resolve an import specifier to a canonical `.ort` file path."""
    if not spec:
        raise OortImportError("Module path cannot be empty.", position)
    if Path(spec).is_absolute() or _split_spec(spec).is_absolute():
        raise OortImportError(
            f"Absolute module paths are not supported: {spec!r}. "
            "Use a relative path or add a search directory with --module-path.",
            position,
        )

    filename = _with_extension(spec, position)

    if _is_relative_spec(spec):
        candidates = [importer_dir / filename]
    else:
        candidates = [entry_dir / filename]
        candidates.extend(root / filename for root in search_paths)

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_dir():
            raise OortImportError(f"Directory modules are not supported: {candidate}.", position)
        if candidate.is_file():
            return candidate

    searched = ", ".join(str(candidate.resolve()) for candidate in candidates)
    raise OortImportError(f"Cannot find module {spec!r}. Searched: {searched}.", position)


def derive_binding_name(spec: str, position: SourcePosition) -> str:
    """Derive the default local name for `import "<spec>"`."""
    name = _split_spec(spec).name
    if name.lower().endswith(".ort"):
        name = name[: -len(".ort")]
    if not name.isidentifier():
        raise OortImportError(
            f"Cannot derive a binding name from module path {spec!r}; "
            "use 'as <name>' to choose one.",
            position,
        )
    return name


class ModuleState(Enum):
    LOADING = auto()
    LOADED = auto()
    FAILED = auto()


@dataclasses.dataclass(frozen=True)
class CompiledModule:
    """A compiled module AST together with the dialect it resolved."""

    ast: nodes.ModuleNode
    dialect_name: str


@dataclasses.dataclass
class ModuleRecord:
    path: Path
    env: Environment
    module: OortModule | None = None
    state: ModuleState = ModuleState.LOADING


@dataclasses.dataclass
class ImportFrame:
    path: Path | None
    directory: Path
    display: str
    dialect_name: str = DEFAULT_DIALECT_NAME


class ModuleLoader:
    """Load and cache Oort modules for one interpreter session."""

    def __init__(
        self,
        *,
        compile_module: Callable[[Path], CompiledModule | None],
        execute_module: Callable[[nodes.ModuleNode, Environment], OortObject],
        make_environment: Callable[[str], Environment],
        make_module: Callable[[str, Environment], OortModule],
        entry_dir: Path,
        search_paths: Sequence[Path] = (),
        native_modules: Mapping[str, Callable[[], OortModule]] | None = None,
    ):
        self._compile_module = compile_module
        self._execute_module = execute_module
        self._make_environment = make_environment
        self._make_module = make_module
        self.entry_dir = entry_dir.resolve()
        self.search_paths = tuple(path.resolve() for path in search_paths)
        self._native_modules = dict(native_modules or {})
        self._native_cache: dict[str, OortModule] = {}
        self._records: dict[Path, ModuleRecord] = {}
        self._frames: list[ImportFrame] = []

    def execute_entry(
        self,
        ast: nodes.ModuleNode,
        env: Environment,
        path: Path | None = None,
        dialect_name: str = DEFAULT_DIALECT_NAME,
    ) -> OortObject:
        """Execute the entry module, registering it for cycle diagnostics."""
        key = path.resolve() if path is not None else None
        if key is not None:
            self._records[key] = ModuleRecord(path=key, env=env)

        frame = ImportFrame(
            path=key,
            directory=key.parent if key is not None else self.entry_dir,
            display=self._display(key) if key is not None else "<entry>",
            dialect_name=dialect_name,
        )
        self._frames.append(frame)
        try:
            result = self._execute_module(ast, env)
        except BaseException:
            if key is not None:
                self._records.pop(key, None)
            raise
        else:
            if key is not None:
                self._records[key].state = ModuleState.LOADED
            return result
        finally:
            self._frames.pop()

    def import_module(self, spec: str, position: SourcePosition) -> OortModule:
        """Resolve, load and return a module, executing it at most once."""
        factory = self._native_modules.get(spec)
        if factory is not None:
            module = self._native_cache.get(spec)
            if module is None:
                module = factory()
                self._native_cache[spec] = module
            return module

        importer_frame = self._frames[-1] if self._frames else None
        importer_dir = importer_frame.directory if importer_frame else self.entry_dir
        importer_dialect = importer_frame.dialect_name if importer_frame else DEFAULT_DIALECT_NAME
        path = resolve_module_path(
            spec,
            importer_dir=importer_dir,
            entry_dir=self.entry_dir,
            search_paths=self.search_paths,
            position=position,
        )

        record = self._records.get(path)
        if record is not None:
            if record.state is ModuleState.LOADING:
                raise OortImportError(self._cycle_message(path), position)
            if record.state is ModuleState.FAILED:
                raise OortImportError(f"Module {spec!r} failed to initialize.", position)
            assert record.module is not None
            return record.module

        env = self._make_environment(self._module_name(path))
        record = ModuleRecord(path=path, env=env)
        self._records[path] = record

        frame = ImportFrame(
            path=path,
            directory=path.parent,
            display=self._display(path),
            dialect_name=importer_dialect,
        )
        self._frames.append(frame)
        try:
            self._initialize_module(record, spec, position, frame)
        except KeyboardInterrupt:
            # The user aborted initialization; drop the half-built record so a
            # retry (notably from the REPL) can load the module again.
            self._records.pop(path, None)
            raise
        except BaseException:
            record.state = ModuleState.FAILED
            raise
        else:
            record.module = self._make_module(self._module_name(path), env)
            record.state = ModuleState.LOADED
            return record.module
        finally:
            self._frames.pop()

    def _initialize_module(
        self,
        record: ModuleRecord,
        spec: str,
        position: SourcePosition,
        frame: ImportFrame,
    ) -> None:
        """Compile and execute a module body, or raise an import diagnostic."""
        compiled = self._compile_module(record.path)
        if compiled is None:
            raise OortImportError(
                f"Failed to import module {spec!r}: compilation failed.", position
            )
        if compiled.dialect_name != frame.dialect_name:
            raise OortImportError(
                f"Cannot import a {compiled.dialect_name!r} module from an "
                f"{frame.dialect_name!r} module; cross-dialect imports require "
                f"an explicit FFI boundary.",
                position,
            )
        frame.dialect_name = compiled.dialect_name
        self._execute_module(compiled.ast, record.env)

    def import_names(
        self,
        spec: str,
        names: Iterable[str],
        position: SourcePosition,
    ) -> tuple[OortModule, dict[str, OortObject]]:
        """Load a module and return it with the requested exported values."""
        module = self.import_module(spec, position)
        requested = list(names)
        missing = [name for name in requested if not module.has(name)]
        if missing:
            joined = ", ".join(repr(name) for name in missing)
            raise OortImportError(f"Module {spec!r} does not export {joined}.", position)

        values: dict[str, OortObject] = {}
        for name in requested:
            value = module.get(name)
            assert value is not None
            values[name] = value
        return module, values

    def binding_name(self, spec: str, position: SourcePosition) -> str:
        return derive_binding_name(spec, position)

    def _module_name(self, path: Path) -> str:
        relative = self._relative(path)
        if relative.lower().endswith(".ort"):
            relative = relative[: -len(".ort")]
        return relative

    def _display(self, path: Path) -> str:
        return self._relative(path)

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.entry_dir).as_posix()
        except ValueError:
            return path.name

    def _cycle_message(self, target: Path) -> str:
        start = next(
            (index for index, frame in enumerate(self._frames) if frame.path == target),
            0,
        )
        chain = [frame.display for frame in self._frames[start:]]
        chain.append(self._display(target))
        return "Circular import detected: " + " -> ".join(chain) + "."
