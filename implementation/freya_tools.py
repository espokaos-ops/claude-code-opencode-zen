#!/usr/bin/env python3
"""Definiciones de las 6 core + mapeo, port para Claude-Code (stdlib only).

Origen (solo lectura, NO modificado):
  ~/.hermes/hermes-agent/agent/opencode_tool_adapter.py
    - OPENCODE_CORE_TOOLS, OPENCODE_TO_HERMES_TOOL, OPENCODE_TOOL_DEFINITIONS
    - free_route_definitions (inyecta las 6 si faltan, idempotente)
    - translate_opencode_tool_call (bash/edit/glob/grep/read/write)

Adaptacion para Claude-Code (Anthropic Messages <-> Responses):
  - Hermes mapea OpenCode->Hermes (terminal/patch/search_files/read_file/write_file)
    para ejecutar en su runtime. Claude-Code ejecuta sus propias tools en el CLI,
    asi que aqui NO se ejecuta nada: solo se garantiza el fingerprint (las 6 en el
    wire Responses) y se traducen nombres/args entre formatos para que el round-trip
    preserve call_ids.
  - Anthropic tools usan {"name", "input_schema"}; Responses usa
    {"type":"function","name","description","parameters"}. La conversion es mecanica.
"""

from __future__ import annotations

import copy
import json
from typing import Any

OPENCODE_CORE_TOOLS = ("bash", "edit", "glob", "grep", "read", "write")

# Copia exacta (valores) de OPENCODE_TOOL_DEFINITIONS en opencode_tool_adapter.py.
OPENCODE_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "bash": {
        "type": "function",
        "name": "bash",
        "description": "Execute a shell command. Returns stdout, stderr, and exit code. Supports background execution and notifications.",
        "strict": False,
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in milliseconds", "default": 120000},
                "workdir": {"type": "string", "description": "Working directory for the command"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    "edit": {
        "type": "function",
        "name": "edit",
        "description": "Make a surgical edit to a file by replacing a specific string. Requires reading the file first.",
        "strict": False,
        "parameters": {
            "type": "object",
            "properties": {
                "filePath": {"type": "string", "description": "Path to the file to edit"},
                "oldString": {"type": "string", "description": "The exact string to replace"},
                "newString": {"type": "string", "description": "The replacement string"},
                "replaceAll": {"type": "boolean", "description": "Replace all occurrences", "default": False},
            },
            "required": ["filePath", "oldString", "newString"],
            "additionalProperties": False,
        },
    },
    "glob": {
        "type": "function",
        "name": "glob",
        "description": "Find files matching a glob pattern.",
        "strict": False,
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "The glob pattern to match"},
                "path": {"type": "string", "description": "Base directory for the search"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    "grep": {
        "type": "function",
        "name": "grep",
        "description": "Search for a pattern in files using ripgrep.",
        "strict": False,
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "The regex pattern to search for"},
                "path": {"type": "string", "description": "Base directory for the search"},
                "include": {"type": "string", "description": "File pattern to include (e.g. *.py)"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    "read": {
        "type": "function",
        "name": "read",
        "description": "Read a file with optional offset and limit (2000 lines default).",
        "strict": False,
        "parameters": {
            "type": "object",
            "properties": {
                "filePath": {"type": "string", "description": "Path to the file to read"},
                "offset": {"type": "integer", "description": "1-indexed line offset", "default": 1},
                "limit": {"type": "integer", "description": "Maximum number of lines to read", "default": 2000},
            },
            "required": ["filePath"],
            "additionalProperties": False,
        },
    },
    "write": {
        "type": "function",
        "name": "write",
        "description": "Write content to a file, creating it if it doesn't exist.",
        "strict": False,
        "parameters": {
            "type": "object",
            "properties": {
                "filePath": {"type": "string", "description": "Path to the file to write"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["filePath", "content"],
            "additionalProperties": False,
        },
    },
}


def responses_core_tools() -> list[dict[str, Any]]:
    """Las 6 en forma Responses (port de get_all_opencode_core_definitions)."""
    return [copy.deepcopy(OPENCODE_TOOL_DEFINITIONS[n]) for n in OPENCODE_CORE_TOOLS]


def ensure_core_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Asegura las 6 core en la lista Responses (port de free_route_definitions).

    Idempotente: no duplica. Superconjunto tolerado por Zen (DEMOSTRADO en FASE 2).
    tools entrante en forma Responses {"type":"function","name":...}.
    """
    base = list(tools) if isinstance(tools, list) else []
    existing = set()
    for t in base:
        if isinstance(t, dict):
            name = t.get("name")
            if isinstance(name, str):
                existing.add(name)
            fn = t.get("function")
            if isinstance(fn, dict) and isinstance(fn.get("name"), str):
                existing.add(fn["name"])
    for name in OPENCODE_CORE_TOOLS:
        if name not in existing:
            base.append(copy.deepcopy(OPENCODE_TOOL_DEFINITIONS[name]))
    return base


def anthropic_to_responses_tools(anthropic_tools: list[dict[str, Any]] | None,
                                 ensure_core: bool = True) -> list[dict[str, Any]]:
    """Convierte tools Anthropic [{name, description?, input_schema}] a Responses.

    Los nombres se preservan tal cual (Claude declara p.ej. Bash/Read; el wire
    Responses los lleva igual). Con ``ensure_core`` (compat wire 1.x) agrega las
    6 core; el contrato v2 usa ``ensure_core=False`` y agrega las verbatim
    read/shell via ``zen_fingerprint.apply_fingerprint_tools``.
    """
    converted: list[dict[str, Any]] = []
    for t in anthropic_tools or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        name = str(t["name"])
        schema = t.get("input_schema") or t.get("inputSchema") or {"type": "object", "properties": {}}
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        converted.append({
            "type": "function",
            "name": name,
            "description": str(t.get("description", "")),
            "strict": False,
            "parameters": schema,
        })
    if not ensure_core:
        return converted
    return ensure_core_tools(converted) if converted else responses_core_tools()


def clamp_call_id(call_id: str, limit: int = 64) -> str:
    """Port de _clamp_responses_call_id: respeta el cap de 64 de Responses."""
    import hashlib as _hl
    s = str(call_id or "")
    if len(s) <= limit:
        return s
    return "call_" + _hl.sha256(s.encode("utf-8", errors="replace")).hexdigest()[:32]


def coerce_arguments(arguments: Any) -> str:
    """Responses exige arguments como string JSON (port de _coerce_arguments)."""
    if isinstance(arguments, str):
        try:
            json.loads(arguments)
            return arguments
        except Exception:
            return json.dumps({"_raw": arguments})
    try:
        return json.dumps(arguments if isinstance(arguments, (dict, list)) else {"_raw": arguments})
    except Exception:
        return "{}"
