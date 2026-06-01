"""FileSystemServer — static tool server for scoped file I/O.

Read/write access is scoped to an *allowlist of root directories* set at
construction time. By default AXIOMA gets:

  - read access to her project root (so she can read her own source code,
    configs, and design docs),
  - write access ONLY to her runtime data directory (snapshots, JSONL,
    generated modules).

This gives her enough rope to author and run her own generated tool modules
without giving her free rein over the operator's filesystem.

Tools:
  - file_read   — read a UTF-8 text file
  - file_write  — create-or-overwrite a UTF-8 text file
  - file_append — append text to a file
  - file_list   — list directory contents (optionally recursive, glob filter)
  - file_exists — boolean existence check
  - file_stat   — size + mtime + type + read/write scope info
  - file_mkdir  — create directory + parents
  - file_delete — delete a file or *empty* directory
  - path_resolve — resolve a path and report read/write scope

Each tool returns either the answer (as text) or a clear `[ERROR] ...`
message. `_dispatch` never raises.

Port of /home/ubuntu/thea/nbc/self_extention/filesystem.py.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiofiles

from ..types import TextContent, Tool

log = logging.getLogger(__name__)


def _ok(data: Any) -> list[TextContent]:
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _err(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=f"[ERROR] {msg}")]


def _resolve(path: str | os.PathLike) -> Path:
    """Expand ~, resolve symlinks where possible, return an absolute Path."""
    p = Path(path).expanduser()
    try:
        return p.resolve()
    except OSError:
        return p.absolute()


def _under_any(p: Path, roots: Iterable[Path]) -> bool:
    """True if p is equal to or inside any of the given roots."""
    p_resolved = _resolve(p)
    for root in roots:
        root_resolved = _resolve(root)
        try:
            p_resolved.relative_to(root_resolved)
            return True
        except ValueError:
            continue
    return False


_TOOLS: list[Tool] = [
    Tool(
        name="file_read",
        description=(
            "Read a UTF-8 text file. Use this to inspect your own prompts, "
            "configuration, source code, or any file inside your read-allowed "
            "roots. Returns the file contents as text. Use the optional "
            "offset/limit args to read part of a large file."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path":   {"type": "string", "description": "Absolute or ~-relative path."},
                "offset": {"type": "integer", "description": "0-indexed start line.", "default": 0},
                "limit":  {"type": "integer", "description": "Max lines to return.", "default": 0},
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="file_write",
        description=(
            "Create or overwrite a UTF-8 text file at `path`. Restricted to "
            "your write-allowed roots. Parent directories are created "
            "automatically. Returns the absolute path written and byte count."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path":    {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    ),
    Tool(
        name="file_append",
        description=(
            "Append text to a file (creating it if needed). Restricted to "
            "write-allowed roots. Returns the new total byte count."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path":    {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    ),
    Tool(
        name="file_list",
        description=(
            "List directory contents. Returns a JSON array of "
            "{name, path, type, size, modified}. `recursive` walks "
            "subdirectories. `pattern` is a glob (e.g. \"*.py\")."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path":      {"type": "string"},
                "recursive": {"type": "boolean", "default": False},
                "pattern":   {"type": "string", "description": "Optional glob filter."},
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="file_exists",
        description="Return whether a path exists. Returns 'true' or 'false'.",
        inputSchema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    ),
    Tool(
        name="file_stat",
        description=(
            "Return path metadata as JSON: {exists, type (file|dir|other), "
            "size, modified, readable, writable, in_read_scope, in_write_scope}."
        ),
        inputSchema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    ),
    Tool(
        name="file_mkdir",
        description=(
            "Create a directory and any missing parents. Restricted to "
            "write-allowed roots."
        ),
        inputSchema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    ),
    Tool(
        name="file_delete",
        description=(
            "Delete a file or *empty* directory. Restricted to write-allowed "
            "roots. Refuses non-empty directories."
        ),
        inputSchema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    ),
    Tool(
        name="path_resolve",
        description=(
            "Resolve a path and report whether it is readable and writable "
            "for you. Returns {absolute, exists, in_read_scope, in_write_scope}."
        ),
        inputSchema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    ),
]


class FileSystemServer:
    """Scoped-root filesystem tool server."""

    ALL_TOOLS = _TOOLS

    def __init__(
        self,
        read_roots: list[Path] | None = None,
        write_roots: list[Path] | None = None,
    ) -> None:
        self.read_roots: list[Path] = [
            _resolve(p) for p in (read_roots or [Path.cwd()])
        ]
        self.write_roots: list[Path] = [
            _resolve(p) for p in (write_roots or [])
        ]
        # Write roots are implicitly readable.
        for w in self.write_roots:
            if w not in self.read_roots:
                self.read_roots.append(w)

    # ── Scope checks ────────────────────────────────────────────────────

    def _check_read(self, path: Path) -> str | None:
        if not _under_any(path, self.read_roots):
            return f"Path outside read scope: {path}"
        return None

    def _check_write(self, path: Path) -> str | None:
        if not _under_any(path, self.write_roots):
            return f"Path outside write scope: {path}"
        return None

    # ── Dispatch ────────────────────────────────────────────────────────

    async def _dispatch(self, name: str, args: dict) -> list[TextContent]:
        try:
            if name == "file_read":    return await self._read(args)
            if name == "file_write":   return await self._write(args)
            if name == "file_append":  return await self._append(args)
            if name == "file_list":    return self._list(args)
            if name == "file_exists":  return self._exists(args)
            if name == "file_stat":    return self._stat(args)
            if name == "file_mkdir":   return self._mkdir(args)
            if name == "file_delete":  return self._delete(args)
            if name == "path_resolve": return self._path_resolve(args)
            return _err(f"Unknown tool: {name}")
        except Exception as e:
            log.exception("[FileSystemServer] %s raised", name)
            return _err(f"{name} failed: {type(e).__name__}: {e}")

    # ── Handlers ────────────────────────────────────────────────────────

    async def _read(self, args: dict) -> list[TextContent]:
        path = _resolve(args["path"])
        err = self._check_read(path)
        if err:
            return _err(err)
        if not path.exists():
            return _err(f"File not found: {path}")
        if not path.is_file():
            return _err(f"Not a regular file: {path}")
        try:
            async with aiofiles.open(path, encoding="utf-8") as f:
                text = await f.read()
        except UnicodeDecodeError:
            return _err(f"File is not valid UTF-8: {path}")
        offset = max(0, int(args.get("offset", 0) or 0))
        limit = int(args.get("limit", 0) or 0)
        if offset or limit:
            lines = text.splitlines(keepends=True)
            sliced = lines[offset:offset + limit] if limit > 0 else lines[offset:]
            text = "".join(sliced)
        return _ok(text)

    async def _write(self, args: dict) -> list[TextContent]:
        path = _resolve(args["path"])
        err = self._check_write(path)
        if err:
            return _err(err)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = args["content"]
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(content)
        return _ok({
            "path": str(path),
            "bytes": len(content.encode("utf-8")),
            "wrote": True,
        })

    async def _append(self, args: dict) -> list[TextContent]:
        path = _resolve(args["path"])
        err = self._check_write(path)
        if err:
            return _err(err)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = args["content"]
        async with aiofiles.open(path, "a", encoding="utf-8") as f:
            await f.write(content)
        return _ok({
            "path": str(path),
            "appended_bytes": len(content.encode("utf-8")),
            "total_bytes": path.stat().st_size,
        })

    def _list(self, args: dict) -> list[TextContent]:
        path = _resolve(args["path"])
        err = self._check_read(path)
        if err:
            return _err(err)
        if not path.exists():
            return _err(f"Path not found: {path}")
        if not path.is_dir():
            return _err(f"Not a directory: {path}")
        recursive = bool(args.get("recursive", False))
        pattern = args.get("pattern") or "*"
        try:
            entries = path.rglob(pattern) if recursive else path.glob(pattern)
            results: list[dict] = []
            for entry in sorted(entries):
                if not _under_any(entry, self.read_roots):
                    continue
                kind = "dir" if entry.is_dir() else (
                    "file" if entry.is_file() else "other"
                )
                try:
                    st = entry.stat()
                    size = st.st_size
                    mtime = datetime.fromtimestamp(
                        st.st_mtime, tz=UTC,
                    ).isoformat()
                except OSError:
                    size, mtime = 0, ""
                results.append({
                    "name": entry.name,
                    "path": str(entry),
                    "type": kind,
                    "size": size,
                    "modified": mtime,
                })
        except OSError as e:
            return _err(f"List failed: {e}")
        return _ok(results)

    def _exists(self, args: dict) -> list[TextContent]:
        path = _resolve(args["path"])
        err = self._check_read(path)
        if err:
            return _err(err)
        return _ok("true" if path.exists() else "false")

    def _stat(self, args: dict) -> list[TextContent]:
        path = _resolve(args["path"])
        err = self._check_read(path)
        if err:
            return _err(err)
        if not path.exists():
            return _ok({
                "path": str(path),
                "exists": False,
                "in_read_scope": True,
                "in_write_scope": _under_any(path, self.write_roots),
            })
        try:
            st = path.stat()
        except OSError as e:
            return _err(f"stat failed: {e}")
        kind = "dir" if path.is_dir() else (
            "file" if path.is_file() else "other"
        )
        return _ok({
            "path": str(path),
            "exists": True,
            "type": kind,
            "size": st.st_size,
            "modified": datetime.fromtimestamp(
                st.st_mtime, tz=UTC,
            ).isoformat(),
            "readable": os.access(path, os.R_OK),
            "writable": os.access(path, os.W_OK),
            "in_read_scope": True,
            "in_write_scope": _under_any(path, self.write_roots),
        })

    def _mkdir(self, args: dict) -> list[TextContent]:
        path = _resolve(args["path"])
        err = self._check_write(path)
        if err:
            return _err(err)
        path.mkdir(parents=True, exist_ok=True)
        return _ok({"path": str(path), "exists": True, "type": "dir"})

    def _delete(self, args: dict) -> list[TextContent]:
        path = _resolve(args["path"])
        err = self._check_write(path)
        if err:
            return _err(err)
        if not path.exists():
            return _err(f"Path not found: {path}")
        if path.is_dir():
            try:
                path.rmdir()
            except OSError as e:
                return _err(f"Directory not empty (or rmdir failed): {e}")
            return _ok({"path": str(path), "deleted": True, "type": "dir"})
        try:
            path.unlink()
        except OSError as e:
            return _err(f"unlink failed: {e}")
        return _ok({"path": str(path), "deleted": True, "type": "file"})

    def _path_resolve(self, args: dict) -> list[TextContent]:
        path = _resolve(args["path"])
        return _ok({
            "absolute": str(path),
            "exists": path.exists(),
            "in_read_scope": _under_any(path, self.read_roots),
            "in_write_scope": _under_any(path, self.write_roots),
        })


__all__ = ["FileSystemServer"]
