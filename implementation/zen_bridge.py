#!/usr/bin/env python3
"""Puente Anthropic Messages <-> OpenCode Zen Responses (stdlib only).

Reutiliza zen_fingerprint (contrato v2) y freya_tools (conversion).
No importa Hermes. No ejecuta tools: solo traduce wire.

Flujo (solo modelos Responses, p.ej. muse-spark-*):
  Claude-Code POST /v1/messages
    -> anthropic_to_responses_body (instructions + input + read/shell verbatim
       + nota anti-placeholder + tool_choice auto + stream:true)
    -> POST https://opencode.ai/inference/v1/responses (wire v2, Bearer public)
    -> parse_responses_sse (texto + function_call + usage)
    -> responses_to_anthropic (message + tool_use + usage estimado si falta)

Los modelos con /messages nativo ya no pasan por aqui: el gateway usa el relay
fino de ``gateway._handle_zen_messages``. V1: el gateway pide siempre
stream:true a Zen (exigido por el gate) y, para responder streaming Anthropic
al cliente, re-emite desde el mensaje completo (igual orden SSE que el mock).
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any

from freya_wire import (
    conversation_scope,
    resolve_zen_model,
)
from freya_tools import (
    anthropic_to_responses_tools,
    clamp_call_id,
    coerce_arguments,
)
from zen_fingerprint import (
    PLACEHOLDER_CLIENT_NAMES,
    ZEN_INFERENCE_BASE,
    ZEN_RESPONSES_PATH,
    apply_fingerprint_tools,
    hoist_system_messages,
    normalize_placeholder_args,
    zen_headers,
)


def flatten_anthropic_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(str(b.get("text", "")))
    return "\n".join(parts)


def flatten_anthropic_system(system: Any) -> str:
    if system is None:
        return ""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        bits = []
        for b in system:
            if isinstance(b, dict) and b.get("type") == "text":
                bits.append(str(b.get("text", "")))
            elif isinstance(b, str):
                bits.append(b)
        return "\n".join(bits)
    return str(system)


def tool_result_to_string(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits = []
        for sub in content:
            if isinstance(sub, dict):
                if sub.get("type") == "text":
                    bits.append(str(sub.get("text", "")))
                elif "text" in sub:
                    bits.append(str(sub.get("text", "")))
                else:
                    bits.append(json.dumps(sub, ensure_ascii=False))
            else:
                bits.append(str(sub))
        return "\n".join(bits)
    if content is None:
        return ""
    return str(content)


def anthropic_messages_to_responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convierte historial Anthropic a input Responses (port simplificado de
    _chat_messages_to_responses_input para el subset user/assistant/tool_result)."""
    items: list[dict[str, Any]] = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role == "user":
            if isinstance(content, str):
                if content.strip():
                    items.append({"type": "message", "role": "user", "content": content})
                continue
            # content en bloques: separa texto y tool_result
            texts = []
            for b in content or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    texts.append(str(b.get("text", "")))
                elif b.get("type") == "tool_result":
                    tid = str(b.get("tool_use_id", ""))
                    if not tid:
                        continue
                    out = tool_result_to_string(b.get("content"))
                    items.append({
                        "type": "function_call_output",
                        "call_id": clamp_call_id(tid),
                        "output": out,
                    })
            txt = "\n".join(t for t in texts if t).strip()
            if txt:
                # Texto como item message. En la practica Claude manda tool_result
                # sin texto mezclado; si hay mezcla, el orden texto/output no es
                # critico siempre que call_id empareje (DEMOSTRADO FASE 4/5).
                items.append({"type": "message", "role": "user", "content": txt})
        elif role == "assistant":
            if isinstance(content, str):
                if content.strip():
                    items.append({"type": "message", "role": "assistant", "content": content})
                continue
            texts = []
            for b in content or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    texts.append(str(b.get("text", "")))
                elif b.get("type") == "tool_use":
                    tid = str(b.get("id", ""))
                    name = str(b.get("name", ""))
                    inp = b.get("input", {})
                    if not tid or not name:
                        continue
                    items.append({
                        "type": "function_call",
                        "call_id": clamp_call_id(tid),
                        "name": name,
                        "arguments": coerce_arguments(inp),
                    })
            txt = "\n".join(t for t in texts if t).strip()
            if txt:
                # El texto del asistente precede a sus calls en el mismo turno
                # (igual que Hermes emite follower + tool_items en orden).
                # Como los calls ya se emitieron arriba, reordenamos: texto primero.
                # Quitamos los calls recien anadidos y los re-emitimos tras el texto.
                # Simple: buscar cuantos function_call se anadieron en este turno.
                n_calls = 0
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        n_calls += 1
                if n_calls:
                    calls = items[-n_calls:]
                    items = items[:-n_calls]
                    items.append({"type": "message", "role": "assistant", "content": txt})
                    items.extend(calls)
                else:
                    items.append({"type": "message", "role": "assistant", "content": txt})
        # system/otros roles se ignoran aqui (system va a instructions)
    return items


def anthropic_to_responses_body(body: dict) -> tuple[dict, str, dict[str, str]]:
    """Body Responses + scope + mapa alias->nombre original (para respuestas)."""
    hoist_system_messages(body)
    scope = conversation_scope(body)
    zen_model = resolve_zen_model(body.get("model"))
    instructions = flatten_anthropic_system(body.get("system"))
    messages = body.get("messages") or []
    resp_input = anthropic_messages_to_responses_input(messages)
    tools = anthropic_to_responses_tools(body.get("tools"), ensure_core=False)
    rbody: dict[str, Any] = {
        "model": zen_model,
        "input": resp_input,
        "tools": tools,
        "parallel_tool_calls": True,
        "stream": True,
        "store": False,
    }
    if instructions.strip():
        rbody["instructions"] = instructions
    mt = body.get("max_tokens")
    if isinstance(mt, int) and mt > 0:
        rbody["max_output_tokens"] = mt
    # Fingerprint v2 (estilo Responses): alias de colisiones, read/shell
    # verbatim, tool_choice auto y nota anti-placeholder en instructions.
    amap = apply_fingerprint_tools(rbody, style="flat")
    return rbody, scope, amap


# ---------------------------------------------------------------- parse Zen SSE

def _split_sse(raw: bytes) -> list[tuple[str, Any]]:
    """Parsea SSE (event:/data:) a lista de (event, json|str). Tolerante."""
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return []
    events: list[tuple[str, Any]] = []
    # Los frames se separan por linea en blanco
    for frame in text.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        ev = "message"
        datas: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                ev = line.split(":", 1)[1].strip() or "message"
            elif line.startswith("data:"):
                datas.append(line.split(":", 1)[1].strip())
            elif line.startswith(":"):
                continue
            elif line.strip() == "[DONE]":
                events.append(("done", "[DONE]"))
            elif datas is not None and line.strip():
                # Continuacion de data sin prefijo (raro)
                datas.append(line.strip())
        if not datas:
            continue
        payload = "\n".join(datas)
        if payload == "[DONE]":
            events.append(("done", "[DONE]"))
            continue
        try:
            events.append((ev, json.loads(payload)))
        except Exception:
            events.append((ev, payload))
    return events


def parse_responses_payload(raw: bytes, content_type: str = "") -> dict[str, Any]:
    """Extrae {text, tool_calls[{id,name,arguments:dict}], usage, response_id, raw_error?}.

    Soporta SSE de Responses y JSON directo (respuesta no-stream o error).
    tool_calls preserva call_id del wire para el round-trip exacto (FASE 4/5).
    """
    if not raw:
        return {"text": "", "tool_calls": [], "usage": {}, "response_id": "",
                "saw_done": False}
    # JSON directo (error o respuesta completa sin SSE)
    stripped = raw.strip()[:1]
    if stripped in (b"{", b"["):
        try:
            obj = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            obj = None
        if isinstance(obj, dict) and obj.get("type") == "error" and "error" in obj:
            return {"text": "", "tool_calls": [], "usage": {}, "response_id": "",
                    "saw_done": False, "error": obj, "error_status": None}
        if isinstance(obj, dict) and ("output" in obj or "output_text" in obj):
            return _from_completed_response(obj)
        # Si parece JSON pero no es Responses, devuelve vacio (el llamante decide)
        if isinstance(obj, dict):
            return {"text": "", "tool_calls": [], "usage": {}, "response_id": "",
                    "saw_done": False, "unknown_json": obj}
    # SSE
    events = _split_sse(raw)
    text_deltas: list[str] = []
    arg_deltas: dict[str, list[str]] = {}
    call_meta: dict[str, dict[str, str]] = {}
    done_calls: list[dict[str, Any]] = []
    completed_obj: dict[str, Any] | None = None
    response_id = ""
    usage: dict[str, Any] = {}

    for ev, data in events:
        if ev == "done":
            continue
        if not isinstance(data, dict):
            continue
        dtype = str(data.get("type", ""))
        # Texto
        if dtype in ("response.output_text.delta", "response.text.delta"):
            d = data.get("delta", "")
            if isinstance(d, str):
                text_deltas.append(d)
            elif isinstance(d, dict) and isinstance(d.get("text"), str):
                text_deltas.append(d["text"])
        elif dtype == "response.output_text.done":
            t = data.get("text", "")
            if isinstance(t, str) and t and not text_deltas:
                text_deltas.append(t)
        # function_call args por deltas
        elif dtype in ("response.function_call_arguments.delta",):
            cid = str(data.get("call_id", "") or data.get("item_id", "") or "")
            d = data.get("delta", "")
            if cid and isinstance(d, str):
                arg_deltas.setdefault(cid, []).append(d)
                if data.get("name"):
                    call_meta.setdefault(cid, {})["name"] = str(data["name"])
        # item done con function_call completo
        elif dtype in ("response.output_item.done", "response.function_call_arguments.done"):
            item = data.get("item") if isinstance(data.get("item"), dict) else data
            if isinstance(item, dict) and item.get("type") == "function_call":
                cid = str(item.get("call_id", "") or item.get("id", "") or "")
                name = str(item.get("name", "") or "")
                args = item.get("arguments", "{}")
                if cid and name:
                    done_calls.append({"call_id": cid, "name": name, "arguments": args})
            elif isinstance(item, dict) and dtype == "response.function_call_arguments.done":
                cid = str(item.get("call_id", "") or item.get("item_id", "") or "")
                name = str(item.get("name", "") or call_meta.get(cid, {}).get("name", ""))
                args = item.get("arguments", "".join(arg_deltas.get(cid, [])))
                if cid and name:
                    done_calls.append({"call_id": cid, "name": name, "arguments": args})
        # output_text en item done generico
        elif dtype == "response.content_part.done":
            part = data.get("part", {})
            if isinstance(part, dict) and part.get("type") == "output_text":
                t = part.get("text", "")
                if isinstance(t, str) and t:
                    text_deltas.append(t)
        # completed con response completa
        elif dtype in ("response.completed", "response.done"):
            resp = data.get("response") if isinstance(data.get("response"), dict) else data
            if isinstance(resp, dict):
                completed_obj = resp
        # Errores en stream
        elif dtype in ("response.failed", "error"):
            completed_obj = {"_stream_error": data}

    if completed_obj is not None:
        if "_stream_error" in completed_obj:
            return {"text": "".join(text_deltas), "tool_calls": done_calls,
                    "usage": usage, "response_id": response_id,
                    "saw_done": False,
                    "error": completed_obj["_stream_error"], "error_status": None}
        parsed = _from_completed_response(completed_obj)
        # Fusiona deltas si el completed no trae texto pero los deltas si
        if not parsed.get("text") and text_deltas:
            parsed["text"] = "".join(text_deltas)
        if not parsed.get("tool_calls") and done_calls:
            parsed["tool_calls"] = _normalize_done_calls(done_calls)
        if not parsed.get("response_id"):
            parsed["response_id"] = response_id
        if usage and not parsed.get("usage"):
            parsed["usage"] = usage
        return parsed

    # Sin completed: arma desde deltas + done_calls + arg_deltas pendientes
    for cid, chunks in arg_deltas.items():
        if any(c.get("call_id") == cid for c in done_calls):
            continue
        name = call_meta.get(cid, {}).get("name", "")
        if cid and name:
            done_calls.append({"call_id": cid, "name": name,
                               "arguments": "".join(chunks)})
    return {
        "text": "".join(text_deltas),
        "tool_calls": _normalize_done_calls(done_calls),
        "usage": usage,
        "response_id": response_id,
        "saw_done": False,
    }


def _normalize_done_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in calls:
        try:
            args_raw = c.get("arguments", "{}")
            if isinstance(args_raw, dict):
                args = args_raw
            else:
                args = json.loads(args_raw or "{}")
                if not isinstance(args, dict):
                    args = {"_raw": args_raw}
        except Exception:
            args = {"_raw": c.get("arguments", "")}
        out.append({"id": str(c.get("call_id", "")), "name": str(c.get("name", "")),
                    "arguments": args})
    return out


def _from_completed_response(resp: dict) -> dict[str, Any]:
    texts: list[str] = []
    calls: list[dict[str, Any]] = []
    for item in resp.get("output") or []:
        if not isinstance(item, dict):
            continue
        itype = item.get("type")
        if itype == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") in ("output_text", "text"):
                    t = part.get("text", "")
                    if isinstance(t, str) and t:
                        texts.append(t)
        elif itype == "function_call":
            cid = str(item.get("call_id", "") or item.get("id", "") or "")
            name = str(item.get("name", "") or "")
            if cid and name:
                try:
                    a = item.get("arguments", "{}")
                    args = json.loads(a) if isinstance(a, str) else (a if isinstance(a, dict) else {})
                    if not isinstance(args, dict):
                        args = {"_raw": a}
                except Exception:
                    args = {"_raw": item.get("arguments", "")}
                calls.append({"id": cid, "name": name, "arguments": args})
    # output_text plano (algunos relays lo duplican arriba)
    ot = resp.get("output_text", "")
    if isinstance(ot, str) and ot.strip() and not texts:
        texts.append(ot)
    usage = resp.get("usage") if isinstance(resp.get("usage"), dict) else {}
    rid = str(resp.get("id", "") or "")
    return {"text": "".join(texts), "tool_calls": calls, "usage": usage,
            "response_id": rid, "saw_done": True,
            "model_name": str(resp.get("model", "") or "")}


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def responses_to_anthropic(model: str, parsed: dict[str, Any],
                           max_tokens: int = 1024,
                           alias_map: dict[str, str] | None = None) -> dict[str, Any]:
    """Convierte el parseado Responses a mensaje Anthropic."""
    import itertools as _it
    import time as _time
    alias_map = alias_map or {}
    text = parsed.get("text", "") or ""
    calls = parsed.get("tool_calls") or []
    content: list[dict[str, Any]] = []
    if text.strip():
        content.append({"type": "text", "text": text})
    for c in calls:
        name = str(c.get("name"))
        args = c.get("arguments") if isinstance(c.get("arguments"), dict) else {}
        if name in alias_map:  # tool del cliente ocultado: restaura su nombre
            name = alias_map[name]
        elif name in PLACEHOLDER_CLIENT_NAMES:  # read->Read, shell->Bash (P2d)
            args = normalize_placeholder_args(name, args)
            name = PLACEHOLDER_CLIENT_NAMES[name]
        content.append({"type": "tool_use", "id": str(c.get("id")),
                        "name": name, "input": args})
    if not content:
        content.append({"type": "text", "text": ""})
    stop = "tool_use" if calls else "end_turn"
    usage = parsed.get("usage") or {}
    # Normaliza usage Responses (input_tokens/output_tokens o prompt_tokens/...) a Anthropic
    try:
        it = int(usage.get("input_tokens", usage.get("prompt_tokens", usage.get("inputTokens", 0))) or 0)
        ot = int(usage.get("output_tokens", usage.get("completion_tokens", usage.get("outputTokens", 0))) or 0)
    except Exception:
        it, ot = 0, 0
    if not it and not ot:
        it, ot = estimate_tokens(text), estimate_tokens(text)
    msg_id = "msg_zen%06d%06d" % (1, int(_time.time() * 1000) % 1000000)
    return {"id": msg_id, "type": "message", "role": "assistant", "model": model,
            "content": content, "stop_reason": stop,
            "usage": {"input_tokens": it, "output_tokens": ot}}


# ---------------------------------------------------------------- POST a Zen

def zen_post(responses_body: dict, scope: str, timeout: int = 120,
             base_url: str = ZEN_INFERENCE_BASE) -> tuple[int, bytes, str]:
    """POST a /inference/v1/responses con el wire free-tier v2. (status, raw, ctype)."""
    url = base_url.rstrip("/") + ZEN_RESPONSES_PATH
    data = json.dumps(responses_body).encode()
    headers = zen_headers(scope)
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.headers.get("content-type", "")
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
        except Exception:
            raw = b""
        try:
            ctype = (e.headers or {}).get("content-type", "") if e.headers else ""
        except Exception:
            ctype = ""
        return e.code, raw, ctype
    except Exception as e:
        payload = json.dumps({"type": "error", "error": {
            "type": "api_error", "message": f"zen upstream unreachable: {e}"}}).encode()
        return 502, payload, "application/json"
