"""Puente Anthropic Messages <-> OpenCode Zen /chat/completions (chat OpenAI).

Los modelos free que no hablan /messages ni /responses (beam-free, ll-alpha-*,
deepseek-v4.1-*, glm-5.3-*, nemotron-*, mimo-*, longcat-*, ...) viven en el
endpoint chat.completions (Fase 5, DEMOSTRADO por sonda directa). Este modulo
convierte el body Anthropic al shape chat, aplica el fingerprint v2 (read/shell
verbatim, aliases y nota) y parsea SSE/JSON de vuelta a un mensaje Anthropic.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from freya_wire import conversation_scope, zen_model_for_request
from zen_bridge import estimate_tokens, flatten_anthropic_system
from zen_fingerprint import (
    PLACEHOLDER_CLIENT_NAMES,
    ZEN_INFERENCE_BASE,
    apply_fingerprint_tools,
    hoist_system_messages,
    normalize_placeholder_args,
    zen_headers,
)

ZEN_CHAT_PATH = "/chat/completions"


# ------------------------------------------------------- Anthropic -> chat

def anthropic_tools_to_chat(tools: Any) -> list[dict[str, Any]]:
    """Tools Anthropic {name, description, input_schema} -> chat functions."""
    out: list[dict[str, Any]] = []
    if not isinstance(tools, list):
        return out
    for t in tools:
        if isinstance(t, list):
            # server-tool (web_search, ...): chat free-tier no lo soporta; omitir
            continue
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        schema = t.get("input_schema")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        out.append({"type": "function", "function": {
            "name": name,
            "description": str(t.get("description") or ""),
            "parameters": schema}})
    return out


def _tool_result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    bits: list[str] = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                bits.append(str(b.get("text", "")))
            elif isinstance(b, str):
                bits.append(b)
    return "\n".join(bits)


def anthropic_messages_to_chat(messages: Any) -> list[dict[str, Any]]:
    """Convierte el historial Anthropic a mensajes chat (tool_result -> role tool)."""
    out: list[dict[str, Any]] = []
    if not isinstance(messages, list):
        return out
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role == "assistant":
            text_bits: list[str] = []
            calls: list[dict[str, Any]] = []
            if isinstance(content, str):
                text_bits.append(content)
            elif isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        text_bits.append(str(b.get("text", "")))
                    elif b.get("type") == "tool_use":
                        calls.append({
                            "id": str(b.get("id") or ""), "type": "function",
                            "function": {"name": str(b.get("name") or ""),
                                         "arguments": json.dumps(b.get("input") or {})}})
            text = "\n".join(x for x in text_bits if x)
            if not text and not calls:
                continue
            msg: dict[str, Any] = {"role": "assistant", "content": text}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
            continue
        # user (o inesperado): separa tool_result (role tool) del texto (role user)
        tool_msgs: list[dict[str, Any]] = []
        text_bits = []
        if isinstance(content, str):
            text_bits.append(content)
        elif isinstance(content, list):
            for b in content:
                if isinstance(b, str):
                    text_bits.append(b)
                    continue
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "tool_result":
                    tool_msgs.append({"role": "tool",
                                      "tool_call_id": str(b.get("tool_use_id") or ""),
                                      "content": _tool_result_text(b) or "(no output)"})
                elif bt == "text":
                    text_bits.append(str(b.get("text", "")))
                # image/document: el chat free-tier no acepta bloques multimodales
                # (NO DEMOSTRADO); se omiten del wire chat.
        out.extend(tool_msgs)
        text = "\n".join(x for x in text_bits if x)
        if text:
            out.append({"role": "user", "content": text})
    return out


def anthropic_to_chat_body(body: dict) -> tuple[dict[str, Any], str]:
    """Body chat.completions + scope. Fingerprint v2 estilo chat."""
    if not isinstance(body, dict):
        raise ValueError("body must be an object")
    hoist_system_messages(body)
    scope = conversation_scope(body)
    model = zen_model_for_request(body.get("model"))
    system = flatten_anthropic_system(body.get("system"))
    messages: list[dict[str, Any]] = []
    if system.strip():
        messages.append({"role": "system", "content": system})
    messages.extend(anthropic_messages_to_chat(body.get("messages")))
    if not messages:
        raise ValueError("no user messages to send")
    cbody: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": anthropic_tools_to_chat(body.get("tools")),
        "stream": True,
    }
    mt = body.get("max_tokens")
    cbody["max_tokens"] = mt if isinstance(mt, int) and mt > 0 else 1024
    # Fingerprint v2 chat: alias de colisiones, read/shell verbatim, nota
    # anti-placeholder y tool_choice nunca "none" (apply_fingerprint_tools).
    apply_fingerprint_tools(cbody, style="chat")
    return cbody, scope


# ------------------------------------------------------- parse Zen chat SSE

def _arguments_value(raw_arguments: str) -> Any:
    if not raw_arguments:
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except Exception:
        return {"_raw_arguments": raw_arguments}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def _absorb_full(result: dict[str, Any], obj: dict) -> None:
    choices = obj.get("choices") or []
    if choices and isinstance(choices[0], dict):
        ch = choices[0]
        msg = ch.get("message") or {}
        if isinstance(msg.get("content"), str):
            result["text"] = msg["content"]
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            result["tool_calls"].append({
                "id": str(tc.get("id") or ""),
                "name": str(fn.get("name") or ""),
                "arguments": _arguments_value(str(fn.get("arguments") or "")),
                "_raw_arguments": str(fn.get("arguments") or "")})
        if ch.get("finish_reason"):
            result["finish_reason"] = str(ch["finish_reason"])


def parse_chat_payload(raw: bytes, content_type: str = "") -> dict[str, Any]:
    """Extrae {text, tool_calls[{id,name,arguments}], usage, response_id,
    finish_reason} de SSE o JSON directo (error incluido)."""
    result: dict[str, Any] = {"text": "", "tool_calls": [], "usage": {},
                              "response_id": "", "finish_reason": "",
                              "saw_done": False}
    if not raw:
        return result
    if raw.strip()[:1] in (b"{", b"["):
        try:
            obj = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            obj = None
        if isinstance(obj, dict) and obj.get("error"):
            result["error"] = obj["error"]
            return result
        if isinstance(obj, dict) and obj.get("choices") is not None:
            if obj.get("id"):
                result["response_id"] = str(obj["id"])
            if isinstance(obj.get("usage"), dict):
                result["usage"] = obj["usage"]
            _absorb_full(result, obj)
        return result
    acc: dict[int, dict[str, str]] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        if payload == "[DONE]":
            result["saw_done"] = True
            continue
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if isinstance(obj.get("error"), dict):
            result["error"] = obj["error"]
            continue
        if obj.get("id") and not result["response_id"]:
            result["response_id"] = str(obj["id"])
        usage = obj.get("usage")
        if isinstance(usage, dict) and usage:
            merged = dict(result["usage"])
            merged.update(usage)
            result["usage"] = merged
        for ch in obj.get("choices") or []:
            if not isinstance(ch, dict):
                continue
            if ch.get("finish_reason"):
                result["finish_reason"] = str(ch["finish_reason"])
            delta = ch.get("delta") or {}
            if isinstance(delta.get("content"), str):
                result["text"] += delta["content"]
            for tc in delta.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                try:
                    idx = int(tc.get("index", 0) or 0)
                except Exception:
                    idx = 0
                slot = acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    slot["id"] = str(tc["id"])
                fn = tc.get("function") or {}
                name = str(fn.get("name") or "")
                if name:
                    if not slot["name"]:
                        slot["name"] = name
                    elif name != slot["name"] and not slot["name"].endswith(name):
                        slot["name"] += name
                if fn.get("arguments"):
                    slot["arguments"] += str(fn["arguments"])
    for idx in sorted(acc):
        slot = acc[idx]
        result["tool_calls"].append({
            "id": slot["id"],
            "name": slot["name"],
            "arguments": _arguments_value(slot["arguments"]),
            "_raw_arguments": slot["arguments"]})
    return result


# ------------------------------------------------------- chat -> Anthropic

def chat_to_anthropic(model: str, parsed: dict[str, Any],
                      max_tokens: int = 1024) -> dict[str, Any]:
    """Convierte el parseado chat a mensaje Anthropic (mismo patron que responses)."""
    text = str(parsed.get("text") or "")
    calls = parsed.get("tool_calls") or []
    content: list[dict[str, Any]] = []
    if text.strip():
        content.append({"type": "text", "text": text})
    for c in calls:
        name = str(c.get("name") or "")
        args = c.get("arguments") if isinstance(c.get("arguments"), dict) else {}
        if name in PLACEHOLDER_CLIENT_NAMES:  # read->Read, shell->Bash (P2d)
            args = normalize_placeholder_args(name, args)
            name = PLACEHOLDER_CLIENT_NAMES[name]
        content.append({"type": "tool_use", "id": str(c.get("id") or ""),
                        "name": name, "input": args})
    if not content:
        content.append({"type": "text", "text": ""})
    finish = str(parsed.get("finish_reason") or "")
    stop = "tool_use" if calls else ("max_tokens" if finish == "length" else "end_turn")
    usage = parsed.get("usage") or {}
    try:
        it = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
        ot = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    except Exception:
        it, ot = 0, 0
    if not it and not ot:
        it, ot = estimate_tokens(text), estimate_tokens(text)
    msg_id = "msg_zenchat%06d" % (int(time.time() * 1000) % 1000000,)
    return {"id": msg_id, "type": "message", "role": "assistant", "model": model,
            "content": content, "stop_reason": stop,
            "usage": {"input_tokens": it, "output_tokens": ot}}


# ------------------------------------------------------- POST a Zen chat

def zen_post_chat(chat_body: dict, scope: str, timeout: int = 120,
                  base_url: str = ZEN_INFERENCE_BASE) -> tuple[int, bytes, str]:
    """POST a /inference/v1/chat/completions con el wire free-tier v2."""
    url = base_url.rstrip("/") + ZEN_CHAT_PATH
    data = json.dumps(chat_body).encode()
    headers = zen_headers(scope)
    # Extras que usa la referencia para el wire chat (baratos e inocuos en
    # /messages; Fase 5 los requirio en las sondas 200).
    headers["x-session-affinity"] = headers.get("x-opencode-session-id", "")
    headers["x-session-id"] = headers.get("x-opencode-session-id", "")
    headers["x-opencode-project"] = "global"
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
