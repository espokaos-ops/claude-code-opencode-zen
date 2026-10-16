"""Traduccion Anthropic Messages <-> NVIDIA NIM (API compatible con OpenAI).

NVIDIA NIM (base por defecto https://integrate.api.nvidia.com/v1):
  POST /chat/completions
  Cuerpo: {model, messages[{role,content}], max_tokens, stream,
          tools[{type:function,function:{name,description,parameters}}], tool_choice}
  Auth: Authorization: Bearer <NVIDIA_API_KEY>
  Respuesta OpenAI: {id, model, choices[{index,finish_reason,
      message:{role,content,tool_calls[{id,type:function,function:{name,arguments}}]
  }}], usage}

Este modulo NO lee claves: la API key se inyecta desde el entorno por quien
hace la peticion HTTP (gateway.py lee NVIDIA_API_KEY de os.environ).
Nunca se escriben secretos en este archivo ni en registros derivados de el.
"""

from __future__ import annotations

import json
import os
import uuid
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"


def default_model() -> str:
    """Modelo NVIDIA a usar si no se establece NVIDIA_MODEL en el entorno."""
    return os.environ.get("NVIDIA_MODEL", DEFAULT_MODEL)


def _flatten_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            t = str(block.get("text", ""))
            if t:
                parts.append(t)
    return "\n".join(p for p in parts if p)


def _tool_result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [
            str(b.get("text", ""))
            for b in c
            if isinstance(b, dict) and b.get("type") == "text" and str(b.get("text", ""))
        ]
        return "\n".join(parts)
    return str(c) if c is not None else ""


def _user_content_and_tools(content: Any):
    """Contenido OpenAI para un mensaje de usuario y mensajes role=tool
    separados para los bloques tool_result (OpenAI no los admite dentro de user)."""
    texts = []
    images = []
    tool_msgs = []
    if isinstance(content, str):
        return content, []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            t = str(block.get("text", ""))
            if t:
                texts.append(t)
        elif btype == "image":
            source = block.get("source") or {}
            if source.get("type") == "base64":
                media = source.get("media_type") or "image/png"
                data = source.get("data") or ""
                images.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media};base64,{data}"},
                    }
                )
        elif btype == "tool_result":
            tool_msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": str(block.get("tool_use_id") or ""),
                    "content": _tool_result_text(block),
                }
            )
    parts = []
    if texts:
        parts.append({"type": "text", "text": "\n".join(texts)})
    parts.extend(images)
    if not parts:
        content_out = ""
    elif len(parts) == 1 and parts[0]["type"] == "text":
        content_out = parts[0]["text"]
    else:
        content_out = parts
    return content_out, tool_msgs


def _assistant_content_and_calls(content: Any):
    """(texto_o_None, tool_calls[]) para un mensaje assistant de Anthropic."""
    texts = []
    calls = []
    if isinstance(content, str):
        return content, []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            t = str(block.get("text", ""))
            if t:
                texts.append(t)
        elif btype == "tool_use":
            calls.append(
                {
                    "id": str(block.get("id") or ""),
                    "type": "function",
                    "function": {
                        "name": str(block.get("name") or ""),
                        "arguments": json.dumps(block.get("input") or {}),
                    },
                }
            )
    text_out = "\n".join(p for p in texts if p) if texts else None
    return text_out, calls


def anthropic_to_nim(body: dict, model_id: str) -> dict:
    """Convierte cuerpo Anthropic POST /v1/messages a cuerpo NVIDIA
    POST /chat/completions listo para enviar (sin incluir la API key)."""
    model = model_id or default_model()
    messages = []
    system_parts = []
    for m in body.get("messages") or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role == "system":
            t = _flatten_text(content)
            if t:
                system_parts.append(t)
            continue
        if role == "user":
            oai_content, tool_msgs = _user_content_and_tools(content)
            messages.append({"role": "user", "content": oai_content})
            messages.extend(tool_msgs)
            continue
        if role == "assistant":
            text, calls = _assistant_content_and_calls(content)
            entry: dict[str, Any] = {"role": "assistant"}
            entry["content"] = text
            if calls:
                entry["tool_calls"] = calls
            messages.append(entry)
            continue
        messages.append({"role": role, "content": _flatten_text(content)})
    if system_parts:
        messages.insert(0, {"role": "system", "content": "\n".join(system_parts)})
    nim: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    mt = body.get("max_tokens")
    if isinstance(mt, int) and mt > 0:
        nim["max_tokens"] = mt
    tools = body.get("tools")
    if isinstance(tools, list):
        oai_tools = []
        for t in tools:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            oai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.get("name"),
                        "description": t.get("description") or "",
                        "parameters": t.get("input_schema") or {},
                    },
                }
            )
        if oai_tools:
            nim["tools"] = oai_tools
            tc = body.get("tool_choice")
            if tc in ("required", "none", "auto"):
                nim["tool_choice"] = tc
    return nim


def parse_nim_payload(raw: bytes, content_type: str | None = None) -> dict:
    """Partea la respuesta JSON de NVIDIA NIM a campos neutrales."""
    try:
        obj = json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:
        raise ValueError(f"respuesta NVIDIA NIM no es JSON valido: {e}")
    if isinstance(obj, dict) and isinstance(obj.get("error"), dict):
        err = obj["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise ValueError(f"NVIDIA NIM devolvio error: {msg}")
    choices = obj.get("choices") or []
    if not isinstance(choices, list) or not choices:
        raise ValueError("NVIDIA NIM sin choices en la respuesta")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError("choice invalido en la respuesta de NVIDIA NIM")
    message = choice.get("message") or {}
    if not isinstance(message, dict):
        message = {}
    content = message.get("content")
    tool_calls = message.get("tool_calls") or []
    blocks = []
    if isinstance(content, str) and content:
        blocks.append({"type": "text", "text": content})
    for tc in tool_calls or []:
        if not isinstance(tc, dict) or tc.get("type") != "function":
            continue
        fn = tc.get("function") or {}
        if not isinstance(fn, dict):
            fn = {}
        arguments = fn.get("arguments") or "{}"
        try:
            input_obj = json.loads(arguments)
        except Exception:
            input_obj = {"_raw_arguments": arguments}
        blocks.append(
            {
                "type": "tool_use",
                "id": str(tc.get("id") or ""),
                "name": str(fn.get("name") or ""),
                "input": input_obj,
            }
        )
    finish = choice.get("finish_reason") or "stop"
    stop_reason = "tool_use" if finish == "tool_calls" else "end_turn"
    return {
        "model": str(obj.get("model") or ""),
        "blocks": blocks,
        "stop_reason": stop_reason,
        "finish_reason": str(finish),
        "id": str(obj.get("id") or ""),
        "usage": obj.get("usage") if isinstance(obj.get("usage"), dict) else {},
    }


def _msg_id() -> str:
    return "msg_nim_" + uuid.uuid4().hex[:24]


def _estimate_usage(text: str, usage: dict) -> dict:
    if usage:
        return {
            "input_tokens": int(usage.get("prompt_tokens") or 0) or 1,
            "output_tokens": int(usage.get("completion_tokens") or 0) or 1,
            "total_tokens": int(usage.get("total_tokens") or 0),
        }
    return {
        "input_tokens": max(1, len(text) // 4),
        "output_tokens": max(1, len(text) // 4),
    }


def nim_to_anthropic(model: str, parsed: dict, max_tokens: int = 1024) -> dict:
    """Convierte la respuesta parseada de NVIDIA al formato message de
    Anthropic (listo para enviar al cliente, stream o no)."""
    text_parts = [
        b.get("text", "") for b in parsed.get("blocks", []) if b.get("type") == "text"
    ]
    text = "\n".join(p for p in text_parts if p)
    usage = _estimate_usage(text, parsed.get("usage") or {})
    return {
        "id": _msg_id(),
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": parsed.get("blocks", []),
        "stop_reason": parsed.get("stop_reason") or "end_turn",
        "usage": usage,
    }


def post_nim(body: dict, api_key: str, base_url: str,
             timeout: int = 120) -> tuple[int, bytes, dict]:
    """Peticion HTTP a NVIDIA NIM /chat/completions con Bearer auth.

    Devuelve (status, raw_body, headers). Los errores de red devuelven
    (502, cuerpo_json_error, {}) sin lanzar.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(body).encode("utf-8")
    headers = {"content-type": "application/json",
               "accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})
    except Exception as e:  # connectivity, DNS, proxy refusal...
        payload = json.dumps({"type": "error", "error": {
            "type": "api_error", "message": f"upstream unreachable: {e}"}}).encode()
        return 502, payload, {"content-type": "application/json"}
