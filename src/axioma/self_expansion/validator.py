"""Three-stage validator for generated AXIOMA-tool modules.

Stages:
    1. Syntax — ``compile(source, filename, "exec")``.
    2. Structure — AST walk: confirm a ``GeneratedServer`` class with an
       ``ALL_TOOLS`` attribute, an async ``_dispatch`` method, and an
       ``__init__``; reject forbidden builtins / imports / attribute access.
    3. Dry-run import — write to a temp file, import, instantiate, verify
       ``ALL_TOOLS`` and ``_dispatch`` are present and callable.

Two entry points:
    validate(source, filename)        — runs all three stages.
    validate_static(source, filename) — runs only stages 1+2 (the loader
                                        does stage-3 work implicitly).

This is *static analysis plus a dry-run import*, not a sandbox. The threat
model assumes the coding LLM is trusted (operator's own Ollama, operator's
own prompt). For untrusted code, add subprocess isolation or
seccomp/landlock.

Port of /home/ubuntu/thea/nbc/self_extention/validator.py.
"""
from __future__ import annotations

import ast
import importlib.util
import logging
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


_FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__"})
_FORBIDDEN_IMPORTS = frozenset({"subprocess", "shlex"})
_FORBIDDEN_ATTRS: dict[str, frozenset[str]] = {
    "os": frozenset({
        "system", "popen", "execv", "execve", "execvp", "execvpe",
        "spawn", "spawnl", "spawnle", "spawnlp", "spawnlpe",
        "spawnv", "spawnve", "spawnvp", "spawnvpe",
    }),
}
MAX_SOURCE_BYTES = 50 * 1024


@dataclass
class ValidationResult:
    ok: bool
    stage: int = 0  # 1, 2, or 3
    error: str = ""
    tools: list[str] = field(default_factory=list)


# ── Stage 1 — syntax ────────────────────────────────────────────────────


def _stage1_syntax(source: str, filename: str) -> ValidationResult:
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return ValidationResult(
            ok=False, stage=1,
            error=f"Source exceeds {MAX_SOURCE_BYTES} bytes",
        )
    try:
        compile(source, filename, "exec")
    except SyntaxError as e:
        return ValidationResult(
            ok=False, stage=1,
            error=f"SyntaxError at line {e.lineno}: {e.msg}",
        )
    return ValidationResult(ok=True, stage=1)


# ── Stage 2 — AST structure + forbidden constructs ──────────────────────


class _StructureWalker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.has_class = False
        self.has_all_tools = False
        self.has_dispatch_async = False
        self.has_init = False
        self.tool_names: list[str] = []
        self.errors: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name != "GeneratedServer":
            self.generic_visit(node)
            return
        self.has_class = True
        for child in node.body:
            if isinstance(child, ast.Assign):
                for tgt in child.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "ALL_TOOLS":
                        self.has_all_tools = True
                        self._collect_tool_names(child.value)
            elif isinstance(child, ast.AnnAssign):
                if isinstance(child.target, ast.Name) and child.target.id == "ALL_TOOLS":
                    self.has_all_tools = True
                    if child.value is not None:
                        self._collect_tool_names(child.value)
            elif isinstance(child, ast.FunctionDef):
                if child.name == "__init__":
                    self.has_init = True
                if child.name == "_dispatch":
                    self.errors.append("_dispatch must be async (`async def`)")
            elif isinstance(child, ast.AsyncFunctionDef):
                if child.name == "_dispatch":
                    self.has_dispatch_async = True
                elif child.name == "__init__":
                    self.errors.append("__init__ must be a regular `def`, not async")
        self.generic_visit(node)

    def _collect_tool_names(self, value: ast.AST) -> None:
        if isinstance(value, ast.List):
            for elt in value.elts:
                if isinstance(elt, ast.Call):
                    for kw in elt.keywords:
                        if kw.arg == "name" and isinstance(kw.value, ast.Constant) \
                                and isinstance(kw.value.value, str):
                            self.tool_names.append(kw.value.value)


def _check_forbidden(tree: ast.AST) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _FORBIDDEN_CALLS:
                return f"Forbidden call: {func.id}()"
        if isinstance(node, ast.Import):
            for n in node.names:
                root = n.name.split(".", 1)[0]
                if root in _FORBIDDEN_IMPORTS:
                    return f"Forbidden import: {n.name}"
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".", 1)[0]
            if mod in _FORBIDDEN_IMPORTS:
                return f"Forbidden import: from {node.module}"
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            blocked = _FORBIDDEN_ATTRS.get(node.value.id)
            if blocked and node.attr in blocked:
                return f"Forbidden attribute access: {node.value.id}.{node.attr}"
    return None


def _stage2_structure(source: str, filename: str) -> ValidationResult:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        # Should have been caught by stage 1, but defensively:
        return ValidationResult(ok=False, stage=2,
                                error=f"AST parse failed: {e}")

    forbidden = _check_forbidden(tree)
    if forbidden:
        return ValidationResult(ok=False, stage=2, error=forbidden)

    walker = _StructureWalker()
    walker.visit(tree)

    if not walker.has_class:
        return ValidationResult(
            ok=False, stage=2,
            error="Module must define a class named `GeneratedServer`",
        )
    if not walker.has_all_tools:
        return ValidationResult(
            ok=False, stage=2,
            error="GeneratedServer must define a class-level ALL_TOOLS list",
        )
    if not walker.has_dispatch_async:
        return ValidationResult(
            ok=False, stage=2,
            error="GeneratedServer must define `async def _dispatch(self, name, args)`",
        )
    if not walker.has_init:
        return ValidationResult(
            ok=False, stage=2,
            error="GeneratedServer must define `def __init__(self) -> None`",
        )
    if walker.errors:
        return ValidationResult(ok=False, stage=2,
                                error="; ".join(walker.errors))

    return ValidationResult(ok=True, stage=2, tools=list(walker.tool_names))


# ── Stage 3 — dry-run import ────────────────────────────────────────────


def _stage3_import(source: str, filename: str) -> ValidationResult:
    tmp_dir = Path(tempfile.mkdtemp(prefix="axioma_validate_"))
    tmp_file = tmp_dir / f"_validate_{uuid.uuid4().hex[:8]}.py"
    module_name = f"_axioma_validate_{uuid.uuid4().hex[:8]}"
    try:
        tmp_file.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(module_name, str(tmp_file))
        if spec is None or spec.loader is None:
            return ValidationResult(ok=False, stage=3,
                                    error="Could not create import spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            return ValidationResult(
                ok=False, stage=3,
                error=f"Module top-level execution raised: "
                      f"{type(e).__name__}: {e}",
            )

        if not hasattr(module, "GeneratedServer"):
            return ValidationResult(
                ok=False, stage=3,
                error="GeneratedServer class not exported",
            )
        try:
            server = module.GeneratedServer()
        except Exception as e:
            return ValidationResult(
                ok=False, stage=3,
                error=f"GeneratedServer() raised: {type(e).__name__}: {e}",
            )
        all_tools = getattr(server, "ALL_TOOLS", None)
        if not isinstance(all_tools, list) or not all_tools:
            return ValidationResult(
                ok=False, stage=3,
                error="ALL_TOOLS must be a non-empty list",
            )
        if not callable(getattr(server, "_dispatch", None)):
            return ValidationResult(
                ok=False, stage=3,
                error="_dispatch is not callable",
            )

        names: list[str] = []
        for t in all_tools:
            n = getattr(t, "name", None)
            if isinstance(n, str):
                names.append(n)
        return ValidationResult(ok=True, stage=3, tools=names)
    finally:
        sys.modules.pop(module_name, None)
        try:
            tmp_file.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            tmp_dir.rmdir()
        except Exception:
            pass


# ── Entry points ────────────────────────────────────────────────────────


def validate(source: str, filename: str) -> ValidationResult:
    """Run all three stages. Used by the generator (after each LLM call)."""
    r = _stage1_syntax(source, filename)
    if not r.ok:
        return r
    r = _stage2_structure(source, filename)
    if not r.ok:
        return r
    return _stage3_import(source, filename)


def validate_static(source: str, filename: str) -> ValidationResult:
    """Run only stages 1+2. Used by the loader (which is about to import)."""
    r = _stage1_syntax(source, filename)
    if not r.ok:
        return r
    return _stage2_structure(source, filename)


__all__ = ["ValidationResult", "validate", "validate_static"]
