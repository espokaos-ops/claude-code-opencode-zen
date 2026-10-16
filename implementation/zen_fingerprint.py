#!/usr/bin/env python3
"""Contrato vigente de la puerta free-tier de OpenCode (2026-10-16, live-verificado).

Fuentes:
  - PR #4842 del repo decolua/9router (mergeado a master): implementacion de
    referencia del wire v2 ``/inference/v1`` (UA ``opencode/latest/2.0.26/cli``,
    tools ``read``/``shell`` verbatim, ``Bearer public``, sesion espejo).
  - Sondas propias P1-P6 (16-oct, /tmp/opencode/probes/FINDINGS-FASE1.md):
    ``stream:true`` obligatorio upstream, ``/zen/v1`` cerrado, read/shell
    verbatim obligatorias y aceptadas en forma Anthropic ``input_schema``.
  - Binario opencode 1.19.3 + fuente upstream (identity.ts/app.ts): algoritmo
    de IDs ``ses_``/``msg_`` y forma del User-Agent.

Este modulo NO importa Hermes ni nada del transformer original: es la copia
Python del contrato de wire, stdlib only.

Reglas del gate (todas verificadas):
  1. Endpoint /inference/v1/messages | chat/completions | responses (legacy
     /zen/v1 responde 403 siempre).
  2. ``stream:true`` obligatorio en el body upstream.
  3. UA forma v2 ``opencode/<channel>/<version>/<client>``.
  4. ``x-opencode-session`` + ``x-opencode-session-id`` espejo, ``ses_`` con
     timestamp bajos-48 invertidos y counter 1..16.
  5. ``x-opencode-client: cli``; ``Authorization: Bearer public``.
  6. tools ``read`` y ``shell`` con description+parameters EXACTOS (verbatim);
     nunca ``tool_choice: "none"``.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import threading
import time
import urllib.error
import urllib.request
from typing import Any

ZEN_INFERENCE_BASE = "https://opencode.ai/inference/v1"
ZEN_MESSAGES_PATH = "/messages"
ZEN_RESPONSES_PATH = "/responses"
ZEN_CHAT_PATH = "/chat/completions"
ZEN_MODELS_PATH = "/models"

# Forma v2 verificada en vivo; override por env para el dia que rote.
OPENCODE_UA = os.environ.get("CLAUDE_GATEWAY_ZEN_UA") or "opencode/latest/2.0.26/cli"
OPENCODE_CLIENT = "cli"
ZEN_AUTHORIZATION = "Bearer public"
ANTHROPIC_VERSION = "2023-06-01"

FINGERPRINT_TOOLS = ("read", "shell")

# Nombre que el cliente Claude Code espera para los placeholders cuando el
# modelo los invoca igual (P2d): read -> Read, shell -> Bash.
PLACEHOLDER_CLIENT_NAMES = {"read": "Read", "shell": "Bash"}

# ---------------------------------------------------------------------------
# Definiciones verbatim (open opcode v2.0.26 CLI; NO reformatear ni reescribir:
# el upstream compara description + parameters y responde 403 si difieren).
# ---------------------------------------------------------------------------

FINGERPRINT_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "read": {
        "description": (
            "Read the contents of a file or directory. Supports text files, images, and PDFs. "
            "Images and PDFs are presented directly to the model. Each text line is prefixed "
            "by its 1-based line number as <line>: <content>. The prefix is for reference and "
            "is not part of the file content. Directory entries are returned one per line. "
            "Use offset and limit to read large files or directories in sections. Prefer one "
            "larger read over many small slices, and use grep to find specific content in "
            "large files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory to read"},
                "offset": {"type": "integer", "minimum": 0,
                           "description": "The line or directory entry to start reading from (1-based)"},
                "limit": {"type": "integer", "minimum": 0,
                          "description": "The maximum number of lines or directory entries to read (defaults to and capped at 2000)"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    "shell": {
        "description": (
            "Execute a shell command and return its output. Commands run on Linux using bash. "
            "Quote file paths containing spaces or special characters. Prefer dedicated tools "
            "over shell commands when possible. When output is large, the full result is saved "
            "to a file and a truncated preview is returned. Rely on automatic truncation "
            "unless filtering the output is more useful. Commands accept an optional timeout, "
            "background commands have no timeout by default. Background commands return "
            "immediately, and you will be notified when they complete."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command string to execute"},
                "workdir": {"type": "string",
                            "description": "Working directory to execute the command in. Defaults to the current working directory. When possible, avoid changing directories in the command and set the working directory here instead."},
                "timeout": {"type": "integer", "minimum": 0,
                            "description": "Timeout in milliseconds. Set to 0 to disable the timeout. Defaults to 120000 for foreground commands. Background commands have no timeout by default."},
                "background": {"type": "boolean",
                               "description": "Run the command in the background and return immediately (useful for dev servers and long-running builds). You do not need to use '&' at the end of the command when using this parameter. You will be notified when it completes. DO NOT poll for completion."},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}


def _canon(d: Any) -> str:
    """JSON canonico estilo JSON.stringify (sin espacios, orden de insercion)."""
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def tool_name_of(tool: Any) -> str:
    """Nombre en forma flat {name} o chat {function:{name}}."""
    if not isinstance(tool, dict):
        return ""
    if isinstance(tool.get("name"), str):
        return tool["name"]
    fn = tool.get("function")
    if isinstance(fn, dict) and isinstance(fn.get("name"), str):
        return fn["name"]
    return ""


def _definition_of(tool: dict) -> tuple[Any, Any]:
    """(description, parameters) del tool en forma flat/chat/anthropic."""
    fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
    desc = fn.get("description")
    params = fn.get("parameters", fn.get("input_schema"))
    return desc, params


def is_fingerprint_definition(tool: Any, key: str) -> bool:
    """True si el tool ya trae la definicion EXACTA de opencode para `key`."""
    if not isinstance(tool, dict) or key not in FINGERPRINT_TOOL_DEFINITIONS:
        return False
    want = FINGERPRINT_TOOL_DEFINITIONS[key]
    desc, params = _definition_of(tool)
    return desc == want["description"] and _canon(params) == _canon(want["parameters"])


def anthropic_tool_def(key: str) -> dict:
    """Forma Anthropic Messages: {name, description, input_schema}."""
    want = FINGERPRINT_TOOL_DEFINITIONS[key]
    return {"name": key, "description": want["description"],
            "input_schema": json.loads(_canon(want["parameters"]))}


def flat_tool_def(key: str) -> dict:
    """Forma Responses (flat): {type:function, name, description, parameters}."""
    want = FINGERPRINT_TOOL_DEFINITIONS[key]
    return {"type": "function", "name": key, "description": want["description"],
            "parameters": json.loads(_canon(want["parameters"])), "strict": False}


def chat_tool_def(key: str) -> dict:
    """Forma OpenAI chat: {type:function, function:{name, description, parameters}}."""
    want = FINGERPRINT_TOOL_DEFINITIONS[key]
    return {"type": "function", "function": {
        "name": key, "description": want["description"],
        "parameters": json.loads(_canon(want["parameters"]))}}


def fingerprint_tool_key(name: Any) -> str:
    """La clave de fingerprint si el nombre coincide exacto; "" si no."""
    trimmed = str(name or "").strip()
    return trimmed if trimmed in FINGERPRINT_TOOL_DEFINITIONS else ""


def conceal_fingerprint_tool_names(tools: Any) -> tuple[list, dict[str, str]]:
    """Mueve tools del cliente FUERA de los nombres fingerprint cuando su
    definicion difiere, y devuelve (tools, mapa alias->nombre original).

    Igual que la referencia: los nombres se comparan exactos (case-sensitive),
    asi ``Read``/``Bash`` de Claude Code pasan intactos; un ``read``/``shell``
    del cliente con otra definicion viaja como ``read_client``/``shell_client``
    y el lado respuesta restaura el nombre original.
    """
    if not isinstance(tools, list) or not tools:
        return (tools if isinstance(tools, list) else []), {}
    taken = {tool_name_of(t) for t in tools}
    seen: set[str] = set()
    out: list = []
    amap: dict[str, str] = {}
    for tool in tools:
        if not isinstance(tool, dict) or isinstance(tool, list):
            out.append(tool)
            continue
        key = fingerprint_tool_key(tool_name_of(tool))
        if not key:
            out.append(tool)
            continue
        if key in seen:  # duplicado exacto: el upstream lo rechaza, conserva el primero
            continue
        seen.add(key)
        if is_fingerprint_definition(tool, key):
            out.append(tool)
            continue
        alias = f"{key}_client"
        i = 2
        while alias in taken:
            alias = f"{key}_client{i}"
            i += 1
        taken.add(alias)
        amap[alias] = key
        renamed = json.loads(_canon(tool))
        fn = renamed.get("function")
        if isinstance(fn, dict):
            fn["name"] = alias
        else:
            renamed["name"] = alias
        out.append(renamed)
    return out, amap


def append_missing_fingerprint_tools(tools: list, style: str = "anthropic") -> list[str]:
    """Agrega las definiciones verbatim faltantes; devuelve los nombres agregados.

    style: "anthropic" ({name, description, input_schema}),
           "flat" (Responses), "chat" (OpenAI).
    """
    appended: list[str] = []
    if not isinstance(tools, list):
        return appended
    present = {fingerprint_tool_key(tool_name_of(t)) for t in tools}
    for name in FINGERPRINT_TOOLS:
        if name in present:
            continue
        if style == "anthropic":
            tools.append(anthropic_tool_def(name))
        elif style == "flat":
            tools.append(flat_tool_def(name))
        else:
            tools.append(chat_tool_def(name))
        appended.append(name)
    return appended


def retarget_tool_choice(body: dict, amap: dict[str, str]) -> None:
    """Reapunta un tool_choice explicito al alias del tool ocultado."""
    if not amap:
        return
    choice = body.get("tool_choice")
    if choice is None:
        return
    if isinstance(choice, str):
        # Anthropic no usa strings; chat usa "auto"/"none"/"required". Nunca "none".
        if choice == "none":
            body["tool_choice"] = "auto"
        return
    if not isinstance(choice, dict):
        return
    by_original = {orig: alias for alias, orig in amap.items()}
    name = choice.get("name")
    if isinstance(name, str) and name.strip() in by_original:
        choice["name"] = by_original[name.strip()]
        return
    fn = choice.get("function")
    if isinstance(fn, dict) and isinstance(fn.get("name"), str) and fn["name"].strip() in by_original:
        fn["name"] = by_original[fn["name"].strip()]


def alias_history_anthropic(messages: Any, amap: dict[str, str]) -> None:
    """Renombra en el historial los tool_use del cliente al alias usado en el wire."""
    if not amap or not isinstance(messages, list):
        return
    by_original = {orig: alias for alias, orig in amap.items()}
    for m in messages:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                nm = str(block.get("name") or "").strip()
                if nm in by_original:
                    block["name"] = by_original[nm]


def alias_history_flat(body: dict, amap: dict[str, str]) -> None:
    """Responses/chat: reapunta function_call historicos al alias (referencia)."""
    if not amap or not isinstance(body, dict):
        return
    by_original = {orig: alias for alias, orig in amap.items()}
    inp = body.get("input")
    if isinstance(inp, list):
        for item in inp:
            if isinstance(item, dict) and item.get("type") == "function_call":
                nm = str(item.get("name") or "").strip()
                if nm in by_original:
                    item["name"] = by_original[nm]
    msgs = body.get("messages")
    if isinstance(msgs, list):
        for msg in msgs:
            if not isinstance(msg, dict) or not isinstance(msg.get("tool_calls"), list):
                continue
            for call in msg["tool_calls"]:
                fn = call.get("function") if isinstance(call, dict) else None
                if isinstance(fn, dict) and str(fn.get("name") or "").strip() in by_original:
                    fn["name"] = by_original[str(fn.get("name")).strip()]


def placeholder_note(names: list[str]) -> str:
    """La nota anti-placeholder de la referencia (wording exacto)."""
    quoted = [f"`{n}`" for n in names]
    listing = " or ".join(quoted)
    if len(names) > 1:
        return (f"Do not call the {listing} tools; they are placeholders that do nothing. "
                f"Use the other tools you have been given instead.")
    return (f"Do not call the {listing} tool; it is a placeholder that does nothing. "
            f"Use the other tools you have been given instead.")


def note_unavailable_tools(body: dict, names: list[str], style: str = "anthropic") -> None:
    """Avisa al modelo que los placeholders no se usan (el gate no mira el texto)."""
    if not names:
        return
    note = placeholder_note(names)
    if style == "flat":
        instr = body.get("instructions")
        body["instructions"] = (instr + "\n\n" + note) if isinstance(instr, str) and instr.strip() else note
        return
    if style == "anthropic":
        system = body.get("system")
        if system is None:
            body["system"] = note
        elif isinstance(system, str):
            body["system"] = system + "\n\n" + note if system.strip() else note
        elif isinstance(system, list):
            system.append({"type": "text", "text": note})
        else:
            body["system"] = str(system) + "\n\n" + note
        return
    # chat: solo cuerpos OpenAI con messages (docs de la referencia)
    msgs = body.get("messages")
    if not isinstance(msgs, list) or body.get("system") is not None:
        return
    first = msgs[0] if msgs else None
    if isinstance(first, dict) and first.get("role") == "system" and isinstance(first.get("content"), str):
        msgs[0] = {**first, "content": f"{first['content']}\n\n{note}"}
    else:
        msgs.insert(0, {"role": "system", "content": note})


def force_stream(body: dict) -> None:
    """``stream:true`` upstream es obligatorio (stream:false -> 403)."""
    body["stream"] = True


def _message_texts(content: Any) -> list[str]:
    """Bloques de texto de un content Anthropic (str o lista de bloques)."""
    if isinstance(content, str):
        return [content] if content else []
    texts: list[str] = []
    if isinstance(content, list):
        for blk in content:
            if isinstance(blk, str):
                texts.append(blk)
            elif isinstance(blk, dict) and blk.get("type") in (None, "text"):
                t = blk.get("text")
                if isinstance(t, str):
                    texts.append(t)
    return texts


def _as_blocks(content: Any) -> list[dict]:
    """Normaliza el content de un mensaje a lista de bloques."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b if isinstance(b, dict) else {"type": "text", "text": str(b)}
                for b in content]
    if isinstance(content, dict):
        return [content]
    return []


def hoist_system_messages(body: dict) -> dict:
    """Sanea ``messages`` para la API Anthropic (roles user|assistant).

    CC 2.1.299 puede enviar mensajes con ``role:"system"`` dentro de la
    conversacion (visto en vivo contra el free tier: el gate responde
    "each message needs role user|assistant"). Su texto se mueve al campo
    ``system`` de nivel superior; roles desconocidos se degradan a user; los
    mensajes adyacentes del mismo rol se fusionan.

    Opera in-place sobre ``body`` (el gateway ya trabaja sobre copia).
    Devuelve stats ``{"hoisted", "coerced", "merged"}``.
    """
    msgs = body.get("messages")
    if not isinstance(msgs, list):
        return {"hoisted": 0, "coerced": 0, "merged": 0}
    hoisted = coerced = 0
    hoisted_texts: list[str] = []
    kept: list[dict] = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        if role == "system":
            hoisted_texts.extend(_message_texts(m.get("content")))
            hoisted += 1
            continue
        if role not in ("user", "assistant"):
            m = {**m, "role": "user"}
            coerced += 1
        kept.append(m)
    if hoisted_texts:
        blocks = [{"type": "text", "text": t} for t in hoisted_texts]
        system = body.get("system")
        if system is None:
            body["system"] = blocks
        elif isinstance(system, str):
            body["system"] = ([{"type": "text", "text": system}] if system else []) + blocks
        elif isinstance(system, list):
            body["system"] = list(system) + blocks
        else:
            body["system"] = [{"type": "text", "text": str(system)}] + blocks
    merged = 0
    merged_msgs: list[dict] = []
    for m in kept:
        if merged_msgs and merged_msgs[-1].get("role") == m.get("role"):
            prev = merged_msgs[-1]
            merged_msgs[-1] = {**prev,
                               "content": (_as_blocks(prev.get("content"))
                                           + _as_blocks(m.get("content")))}
            merged += 1
            continue
        merged_msgs.append(m)
    body["messages"] = merged_msgs
    return {"hoisted": hoisted, "coerced": coerced, "merged": merged}


def apply_fingerprint_tools(body: dict, style: str = "anthropic") -> dict[str, str]:
    """Pase completo request-side: alias de colisiones, tools verbatim y nota.

    Devuelve el mapa alias->nombre original para el lado respuesta.
    """
    if not isinstance(body, dict):
        return {}
    tools, amap = conceal_fingerprint_tool_names(body.get("tools"))
    body["tools"] = tools
    appended = append_missing_fingerprint_tools(tools, style)
    retarget_tool_choice(body, amap)
    if style == "anthropic":
        alias_history_anthropic(body.get("messages"), amap)
        if body.get("tool_choice") in ("none", {"type": "none"}):
            body["tool_choice"] = {"type": "auto"}
    else:
        alias_history_flat(body, amap)
        if body.get("tool_choice") in ("none", {"type": "none"}):
            body["tool_choice"] = "auto"
        if body.get("tool_choice") is None and style == "flat":
            body["tool_choice"] = "auto"
    if appended:
        note_unavailable_tools(body, appended, style)
    return amap


RESPONSES_MODEL_PREFIXES = ("muse-spark",)
RESPONSES_MODELS = {"big-pickle"}  # 400 en /messages, 200 en /responses (Fase 5)
MESSAGES_MODELS = {"space-bunny-free"}  # unico con /messages 200 verificado (P2/P4)


def bare_model_id(model: Any) -> str:
    return str(model or "").strip().rsplit("/", 1)[-1].lower()


def is_responses_model(model: Any) -> bool:
    """muse-spark* y big-pickle viven solo en /responses (400 en /messages)."""
    bare = bare_model_id(model)
    return bare in RESPONSES_MODELS or bare.startswith(RESPONSES_MODEL_PREFIXES)


def is_chat_model(model: Any) -> bool:
    """El resto de los modelos free viven en /chat/completions (Fase 5)."""
    bare = bare_model_id(model)
    if not bare:
        return False
    return not is_responses_model(bare) and bare not in MESSAGES_MODELS


# ---------------------------------------------------------------------------
# IDs de sesion/requests (forma opencode: 12 hex bajos-48 invertidos + 14 b62)
# ---------------------------------------------------------------------------

_ID_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_ID_LOCK = threading.RLock()
_ID_COUNTER = 0
_ID_COUNTER_MS = 0
_ID_COUNTER_MAX = 16  # gate: 0..16 pasan, >=100 fallan

_SESSION_CACHE: dict[str, str] = {}
_SESSION_LOCK = threading.RLock()


def new_opencode_id(prefix: str) -> str:
    """ID fiel al cliente opencode v2 (counter acotado 1..16)."""
    global _ID_COUNTER, _ID_COUNTER_MS
    with _ID_LOCK:
        ms = int(time.time() * 1000)
        if ms != _ID_COUNTER_MS:
            _ID_COUNTER_MS = ms
            _ID_COUNTER = 0
        _ID_COUNTER += 1
        if _ID_COUNTER > _ID_COUNTER_MAX:
            _ID_COUNTER = 1
        n = ms * 0x1000 + _ID_COUNTER
        low48 = (~n) & ((1 << 48) - 1)
    hex_part = f"{low48:012x}"
    rand_part = "".join(secrets.choice(_ID_ALPHABET) for _ in range(14))
    return f"{prefix}_{hex_part}{rand_part}"


def id_counter_of(value: str) -> int:
    """Counter embebido en un id (decode de verificacion/tests)."""
    s = str(value or "")
    if len(s) < 16 or "_" not in s:
        return -1
    try:
        return int((~int(s.split("_", 1)[1][:12], 16)) & 0xFFF)
    except ValueError:
        return -1


def session_for_scope(scope: str) -> str:
    """``ses_`` estable por conversacion (cache en memoria)."""
    key = scope or "oneshot"
    with _SESSION_LOCK:
        if key not in _SESSION_CACHE:
            _SESSION_CACHE[key] = new_opencode_id("ses")
        return _SESSION_CACHE[key]


def zen_headers(scope: str, accept_sse: bool = True) -> dict[str, str]:
    """Headers del wire free-tier v2 hacia /inference/v1/*."""
    ses = session_for_scope(scope)
    headers = {
        "content-type": "application/json",
        "user-agent": OPENCODE_UA,
        "x-opencode-client": OPENCODE_CLIENT,
        "x-opencode-session": ses,
        "x-opencode-session-id": ses,
        "authorization": ZEN_AUTHORIZATION,
        "anthropic-version": ANTHROPIC_VERSION,
    }
    if accept_sse:
        headers["accept"] = "text/event-stream"
    return headers


def post_messages(body: dict, scope: str, base_url: str = ZEN_INFERENCE_BASE,
                  timeout: int = 300):
    """POST /inference/v1/messages. Devuelve (status, response|bytes).

    status 200 -> ``response`` es un HTTPResponse (streaming, cerrar); el resto
    -> ``bytes`` con el body de error del proveedor, sin modificar.
    """
    url = base_url.rstrip("/") + ZEN_MESSAGES_PATH
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=zen_headers(scope),
                                 method="POST")
    try:
        return 200, urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
        except Exception:
            raw = b""
        return e.code, raw
    except Exception as e:
        payload = json.dumps({"type": "error", "error": {
            "type": "api_error", "message": f"zen upstream unreachable: {e}"}}).encode()
        return 502, payload


def fetch_models(base_url: str = ZEN_INFERENCE_BASE, timeout: int = 30):
    """GET /inference/v1/models (publico). Devuelve (status, dict|bytes)."""
    url = base_url.rstrip("/") + ZEN_MODELS_PATH
    req = urllib.request.Request(url, headers={
        "user-agent": OPENCODE_UA, "accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:
        return 502, json.dumps({"type": "error", "error": {
            "type": "api_error", "message": f"zen models unreachable: {e}"}}).encode()


# ---------------------------------------------------------------------------
# SSE Anthropic: normalizacion de respuesta (read->Read, shell->Bash, aliases)
# ---------------------------------------------------------------------------

_SAFE_WORKDIR = re.compile(r"^[A-Za-z0-9_@%+=:,~./ -]{1,240}$")


def normalize_placeholder_args(key: str, args: Any) -> dict:
    """Traduce los args que el modelo manda al placeholder a la tool de CC."""
    if not isinstance(args, dict):
        return {}
    if key == "read":
        out: dict[str, Any] = {}
        fp = args.get("file_path") or args.get("filePath") or args.get("path")
        if isinstance(fp, str) and fp:
            out["file_path"] = fp
        for k in ("offset", "limit"):
            v = args.get(k)
            if isinstance(v, int) and v >= 0:
                out[k] = v
        return out
    if key == "shell":
        out = {}
        cmd = args.get("command")
        if isinstance(cmd, str):
            out["command"] = cmd
        wd = args.get("workdir")
        if isinstance(wd, str) and wd.strip() and isinstance(cmd, str):
            if _SAFE_WORKDIR.match(wd) and not cmd.strip().startswith("cd "):
                out["command"] = f"cd {shlex.quote(wd)} && {cmd}"
        t = args.get("timeout")
        if isinstance(t, (int, float)) and t > 0:
            out["timeout"] = min(int(t), 600000)
        bg = args.get("background")
        if isinstance(bg, bool):
            out["run_in_background"] = bg
        return out if "command" in out else (args if cmd is None else {})
    return dict(args)


def _sse_frame(event: str, data: dict) -> bytes:
    """Frame SSE sin la linea en blanco separadora (la agrega el transporte)."""
    return (f"event: {event}\n".encode()
            + b"data: " + _canon(data).encode() + b"\n")


def split_sse_frames(raw: bytes) -> list[bytes]:
    """Divide un stream SSE completo en frames SIN la linea en blanco final."""
    if b"\r\n" in raw:
        raw = raw.replace(b"\r\n", b"\n")
    frames = []
    for part in raw.split(b"\n\n"):
        if part.strip():
            frames.append(part.rstrip(b"\n") + b"\n")
    return frames


def _parse_frame(frame: bytes) -> tuple[str, Any]:
    """(event, data) de un frame SSE; data puede ser dict o str crudo."""
    event = "message"
    datas: list[str] = []
    for line in frame.decode("utf-8", "replace").splitlines():
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip() or "message"
        elif line.startswith("data:"):
            datas.append(line.split(":", 1)[1].strip())
    payload = "\n".join(datas)
    if not payload:
        return event, None
    try:
        return event, json.loads(payload)
    except Exception:
        return event, payload


class AnthropicSSENormalizer:
    """Renombra tool_use read->Read / shell->Bash, restaura aliases y traduce
    los args de placeholder al esquema de la tool de Claude Code.

    Uso streaming: ``feed_line`` por linea cruda del upstream; lo que devuelve
    (lista de chunks de bytes) se reenvia al cliente. Los bloques placeholder
    se bufferizan (sus ``input_json_delta``) y se re-emiten de una sola pieza en
    el ``content_block_stop`` con los args normalizados.
    """

    def __init__(self, alias_map: dict[str, str] | None = None):
        self.alias_map = dict(alias_map or {})
        self._buf: dict[int, dict[str, Any]] = {}
        self._lines: list[bytes] = []
        self.saw_message_stop = False

    # -- API por lineas (streaming)
    def feed_line(self, raw: bytes) -> list[bytes]:
        if raw in (b"", b"\n", b"\r\n"):
            return self._flush()  # linea en blanco: fin de frame
        self._lines.append(raw)
        return []

    def finish(self) -> list[bytes]:
        """Flush final (upstream cerro sin blank final)."""
        return self._flush()

    def _flush(self) -> list[bytes]:
        if not self._lines:
            return []
        frame = b"".join(self._lines)
        self._lines = []
        return self.feed_frame(frame)

    # -- API por frames (tests / no-stream)
    def feed_frame(self, frame: bytes) -> list[bytes]:
        event, data = _parse_frame(frame)
        if not isinstance(data, dict):
            return [frame]  # no-JSON: pasa crudo
        etype = str(data.get("type") or event)
        if etype == "content_block_start":
            return self._on_start(data)
        if etype == "content_block_delta":
            return self._on_delta(data)
        if etype == "content_block_stop":
            return self._on_stop(data)
        if etype == "message_stop":
            self.saw_message_stop = True
        return [frame]

    def _on_start(self, data: dict) -> list[bytes]:
        block = data.get("content_block")
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            return [_sse_frame("content_block_start", data)]
        name = str(block.get("name") or "")
        if name in self.alias_map:  # tool del cliente ocultado: restaura su nombre
            block["name"] = self.alias_map[name]
            return [_sse_frame("content_block_start", data)]
        if name in PLACEHOLDER_CLIENT_NAMES:
            index = int(data.get("index") or 0)
            self._buf[index] = {"key": name, "parts": [],
                                "start_input": block.get("input") or {}}
            block["name"] = PLACEHOLDER_CLIENT_NAMES[name]
            return [_sse_frame("content_block_start", data)]
        return [_sse_frame("content_block_start", data)]

    def _on_delta(self, data: dict) -> list[bytes]:
        index = int(data.get("index") or 0)
        delta = data.get("delta") if isinstance(data.get("delta"), dict) else {}
        if index in self._buf and delta.get("type") == "input_json_delta":
            part = delta.get("partial_json", "")
            if isinstance(part, str):
                self._buf[index]["parts"].append(part)
            return []  # se re-emite normalizado en el stop
        return [_sse_frame("content_block_delta", data)]

    def _on_stop(self, data: dict) -> list[bytes]:
        index = int(data.get("index") or 0)
        entry = self._buf.pop(index, None)
        if entry is None:
            return [_sse_frame("content_block_stop", data)]
        blob = "".join(entry["parts"]) or _canon(entry.get("start_input") or {})
        try:
            args = json.loads(blob)
        except Exception:
            args = {"_raw": blob}
        norm = normalize_placeholder_args(entry["key"], args)
        out = []
        if norm:
            out.append(_sse_frame("content_block_delta", {
                "type": "content_block_delta", "index": index,
                "delta": {"type": "input_json_delta", "partial_json": _canon(norm)}}))
        out.append(_sse_frame("content_block_stop", data))
        return out


def assemble_message(chunks: list[bytes]) -> dict:
    """Ensambla el mensaje Anthropic completo desde frames SSE ya normalizados.

    Devuelve el dict ``message`` o ``{"_error": {...}}`` si el stream trae error.
    """
    message: dict | None = None
    blocks: dict[int, dict] = {}
    json_parts: dict[int, list[str]] = {}
    stop_reason = None
    for frame in chunks:
        event, data = _parse_frame(frame)
        if not isinstance(data, dict):
            continue
        etype = str(data.get("type") or event)
        if etype == "error":
            return {"_error": data}
        if etype == "message_start":
            message = json.loads(_canon(data.get("message") or {}))
            message["content"] = []
        elif etype == "content_block_start":
            index = int(data.get("index") or 0)
            block = json.loads(_canon(data.get("content_block") or {}))
            block.setdefault("input", {})
            blocks[index] = block
        elif etype == "content_block_delta":
            index = int(data.get("index") or 0)
            delta = data.get("delta") if isinstance(data.get("delta"), dict) else {}
            block = blocks.get(index)
            if block is None:
                continue
            if delta.get("type") == "text_delta":
                block["text"] = block.get("text", "") + str(delta.get("text", ""))
            elif delta.get("type") == "input_json_delta":
                json_parts.setdefault(index, []).append(str(delta.get("partial_json", "")))
        elif etype == "content_block_stop":
            index = int(data.get("index") or 0)
            block = blocks.get(index)
            if block is None:
                continue
            if block.get("type") == "tool_use":
                blob = "".join(json_parts.pop(index, []))
                try:
                    block["input"] = json.loads(blob) if blob else (block.get("input") or {})
                except Exception:
                    block["input"] = {"_raw": blob}
        elif etype in ("message_delta", "message_delta_stop"):
            delta = data.get("delta") if isinstance(data.get("delta"), dict) else {}
            if delta.get("stop_reason"):
                stop_reason = delta["stop_reason"]
            usage = data.get("usage")
            if isinstance(usage, dict) and message is not None:
                message.setdefault("usage", {}).update(usage)
    if message is None:
        return {"_error": {"type": "error", "error": {
            "type": "api_error", "message": "upstream stream ended without message_start"}}}
    message["content"] = [blocks[i] for i in sorted(blocks)]
    if stop_reason:
        message["stop_reason"] = stop_reason
    else:
        message.setdefault("stop_reason", "end_turn")
    message.setdefault("usage", {})
    return message
