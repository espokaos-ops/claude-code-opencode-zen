#!/usr/bin/env python3
"""Claude-Code local gateway: Anthropic Messages API on loopback.

Speaks Anthropic Messages (POST /v1/messages, optional SSE streaming,
POST /v1/messages/count_tokens, GET /health, GET /v1/models) and forwards to an
allowed upstream. Upstreams: ``mock`` (deterministic, no network, for tests),
``passthrough`` (any Anthropic-compatible base URL with the user's own key) and
``zen`` (OpenCode free tier, contrato v2 verificado 2026-10-16).

Upstream ``zen`` tiene dos vias (``zen_fingerprint.py``):
  - Relay fino a ``POST /inference/v1/messages`` (Anthropic nativo): inyecta
    headers del wire free-tier, ``stream:true``, tools ``read``/``shell``
    verbatim y la nota anti-placeholder; reenvia el SSE normalizando la
    respuesta (``read``->``Read``, ``shell``->``Bash``, aliases) y ensambla
    JSON si el cliente pidio stream:false.
  - Modelos muse-spark (solo Responses): puente Anthropic<->Responses de
    ``zen_bridge.py`` (port Freya-Hermes) hacia ``/inference/v1/responses``.

Los errores del proveedor (403 FreeTierError incluido) se devuelven sin
transformar. Ver README §5-§6, CAMBIOS-Y-ACTIVACION.md y FINDINGS-FASE1.md.

Stdlib only. No Hermes imports (port copiado, original intacto).
Binds 127.0.0.1 exclusively.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GATEWAY_NAME = "claude-code-local-gateway"
GATEWAY_VERSION = "0.4.0"
DEFAULT_PORT = 8479
ANTHROPIC_VERSION = "2023-06-01"
from zen_fingerprint import ZEN_INFERENCE_BASE as ZEN_DEFAULT_BASE  # noqa: E402
ZEN_DEFAULT_MODEL = "space-bunny-free"
ZEN_MODELS_CACHE_TTL = 600.0

_msg_counter = itertools.count(1)
_tool_counter = itertools.count(1)
_lock = threading.Lock()


def _new_id(prefix: str, counter: itertools.count) -> str:
    with _lock:
        n = next(counter)
    return f"{prefix}{n:06d}{int(time.time() * 1000) % 1000000:06d}"


def redact_headers(headers) -> dict:
    out = {}
    for k, v in dict(headers).items():
        lk = k.lower()
        if lk in ("authorization", "x-api-key", "cookie", "proxy-authorization"):
            out[k] = "[REDACTED]"
        else:
            out[k] = v
    return out


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def flatten_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(parts)


def user_turn_count(messages) -> int:
    return sum(1 for m in messages or [] if isinstance(m, dict) and m.get("role") == "user")


def tool_results_text(messages) -> list[str]:
    texts = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        blocks = content if isinstance(content, list) else []
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                c = b.get("content")
                if isinstance(c, str):
                    texts.append(c)
                elif isinstance(c, list):
                    for sub in c:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            texts.append(str(sub.get("text", "")))
    return texts


# ---------------------------------------------------------------- mock upstream

def mock_respond(body: dict) -> tuple[int, dict]:
    """Deterministic mock. Returns (http_status, anthropic_response_or_error)."""
    messages = body.get("messages") or []
    last_user = ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_user = flatten_text(m.get("content"))
            break
    turn = user_turn_count(messages)
    model = str(body.get("model") or "mock:claude-sonnet")

    if "error:" in last_user:
        code = 500
        mm = re.search(r"error:(\d{3})", last_user)
        if mm:
            try:
                code = int(mm.group(1))
            except ValueError:
                code = 500
        return code, {"type": "error", "error": {"type": "api_error",
                      "message": f"mock upstream error ({last_user.strip()[:80]})"}}

    if "call:multi" in last_user:
        t1 = _new_id("toolu_mock", _tool_counter)
        t2 = _new_id("toolu_mock", _tool_counter)
        return 200, _message(model, [
            {"type": "text", "text": f"turn {turn}: two tool calls queued"},
            {"type": "tool_use", "id": t1, "name": "read",
             "input": {"filePath": "/tmp/mock-a.txt"}},
            {"type": "tool_use", "id": t2, "name": "glob",
             "input": {"pattern": "**/*.py"}},
        ], "tool_use")

    if "call:" in last_user:
        target = last_user.split("call:", 1)[1].strip().split()[0]
        name = "read"
        arg = {"filePath": target if target.startswith("/") else "/tmp/" + target}
        tid = _new_id("toolu_mock", _tool_counter)
        return 200, _message(model, [
            {"type": "text", "text": f"turn {turn}: calling {name}"},
            {"type": "tool_use", "id": tid, "name": name, "input": arg},
        ], "tool_use")

    results = tool_results_text(messages)
    if results:
        shown = " | ".join(r.strip()[:200] for r in results)
        return 200, _message(model, [
            {"type": "text", "text": f"turn {turn}: consumed tool result: {shown}"},
        ], "end_turn")

    if last_user.startswith("stop:"):
        chunks = " ".join(f"chunk{i}" for i in range(50))
        return 200, _message(model, [
            {"type": "text", "text": f"turn {turn}: {chunks}"},
        ], "end_turn")

    return 200, _message(model, [
        {"type": "text", "text": f"turn {turn}: mock reply to: {last_user.strip()[:160]}"},
    ], "end_turn")


def _message(model: str, content: list, stop_reason: str) -> dict:
    text = " ".join(b.get("text", "") for b in content if b.get("type") == "text")
    return {"id": _new_id("msg_mock", _msg_counter), "type": "message",
            "role": "assistant", "model": model, "content": content,
            "stop_reason": stop_reason,
            "usage": {"input_tokens": estimate_tokens(text),
                      "output_tokens": estimate_tokens(text)}}


# ------------------------------------------------------------- validation

def validate_messages_request(body: dict, allow_system_roles: bool = False) -> str | None:
    if not isinstance(body, dict):
        return "body must be a JSON object"
    if not body.get("model") or not isinstance(body.get("model"), str):
        return "field 'model' is required (string)"
    mt = body.get("max_tokens")
    if not isinstance(mt, int) or mt < 1:
        return "field 'max_tokens' is required (positive int)"
    msgs = body.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return "field 'messages' is required (non-empty array)"
    allowed = ("user", "assistant", "system") if allow_system_roles else ("user", "assistant")
    for m in msgs:
        if not isinstance(m, dict) or m.get("role") not in allowed:
            return "each message needs role user|assistant"
        if "content" not in m:
            return "each message needs content"
    tools = body.get("tools")
    if tools is not None:
        if not isinstance(tools, list):
            return "field 'tools' must be an array"
        for t in tools:
            if not isinstance(t, dict) or not t.get("name"):
                return "each tool needs a name"
    return None


def error_envelope(http_status: int, err_type: str, message: str) -> tuple[int, dict]:
    return http_status, {"type": "error", "error": {"type": err_type, "message": message}}


def model_echo_error(expected: str, echoed: str) -> dict | None:
    """Error si el upstream reporta otro modelo que el solicitado.

    Verifica que el modelo pedido sea el que realmente responde (eco del campo
    ``model``); un eco ausente no se puede verificar y no falla.
    """
    from freya_wire import normalize_model_id
    seen = normalize_model_id(echoed)
    if seen and expected and seen != normalize_model_id(expected):
        return {"type": "error", "error": {
            "type": "api_error",
            "message": f"upstream answered model '{echoed}' for requested "
                       f"model '{expected}'"}}
    return None


# ------------------------------------------------------------- passthrough

def passthrough(base_url: str, api_key: str, body: dict, stream: bool,
                extra_headers: dict) -> tuple[int, bytes, dict]:
    url = base_url.rstrip("/") + "/v1/messages"
    data = json.dumps(body).encode()
    headers = {"content-type": "application/json",
               "anthropic-version": extra_headers.get("anthropic-version", ANTHROPIC_VERSION)}
    if api_key:
        if api_key.startswith("sk-ant-") or len(api_key) > 20:
            headers["x-api-key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"
    for k in ("anthropic-beta",):
        if extra_headers.get(k):
            headers[k] = extra_headers[k]
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})
    except Exception as e:  # connectivity, DNS, proxy refusal...
        payload = json.dumps({"type": "error", "error": {
            "type": "api_error", "message": f"upstream unreachable: {e}"}}).encode()
        return 502, payload, {"content-type": "application/json"}


# ------------------------------------------------------------- HTTP handler

class Handler(BaseHTTPRequestHandler):
    server_version = GATEWAY_NAME + "/" + GATEWAY_VERSION

    def log_message(self, fmt, *args):  # quieter + redacted
        pass

    def _send_json(self, status: int, obj: dict):
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json(self):
        try:
            length = int(self.headers.get("content-length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > 4_000_000:
            return None, "empty or oversized body"
        try:
            return json.loads(self.rfile.read(length) or b"{}"), None
        except Exception:
            return None, "invalid JSON body"

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            self._send_json(200, {"status": "ok", "gateway": GATEWAY_NAME,
                                  "version": GATEWAY_VERSION,
                                  "upstream": self.server.config["upstream"]})
        elif path == "/v1/models":
            return self._handle_models()
        else:
            self._send_json(404, {"type": "error", "error": {
                "type": "not_found", "message": f"unknown path {self.path}"}})

    def _handle_models(self):
        """GET /v1/models: catalogo vivo de Zen (cache 10 min)."""
        cfg = self.server.config
        if cfg["upstream"] == "mock":
            return self._send_json(200, {"data": [
                {"type": "model", "id": "mock:claude-sonnet",
                 "display_name": "mock:claude-sonnet"}], "object": "list"})
        if cfg["upstream"] == "zen":
            from freya_wire import OPENCODE_FREE_MODELS, model_alias, resolve_zen_model
            from zen_fingerprint import fetch_models
            cache = cfg.setdefault("models_cache", {})
            now = time.time()
            if cache.get("data") and (now - cache.get("ts", 0)) < ZEN_MODELS_CACHE_TTL:
                return self._send_json(200, cache["data"])
            status, obj = fetch_models(cfg.get("upstream_url") or ZEN_DEFAULT_BASE)
            if status != 200 or not isinstance(obj, dict):
                if cache.get("data"):  # stale-on-error
                    return self._send_json(200, cache["data"])
                s, o = error_envelope(502, "api_error",
                                      f"zen models fetch failed (HTTP {status})")
                return self._send_json(s, o)
            # Solo los free verificados, servidos como alias de selector
            # (claude-free-<id>): asi el selector de CC los muestra y el
            # gateway los vuelve a mapear al slug real. Los ids de pago no se
            # anuncian porque el wire publico los rechaza.
            catalog = obj.get("data") if isinstance(obj.get("data"), list) else obj.get("models") or []
            models = []
            seen: set[str] = set()
            for m in catalog:
                mid = str(m.get("id") if isinstance(m, dict) else m or "")
                if not mid:
                    continue
                try:
                    bare = resolve_zen_model(mid)
                except ValueError:
                    continue
                if bare in seen:
                    continue
                seen.add(bare)
                models.append({"type": "model", "id": model_alias(bare),
                               "display_name": bare})
            if not models:
                models = [{"type": "model", "id": model_alias(bare),
                           "display_name": bare}
                          for bare in sorted(OPENCODE_FREE_MODELS)]
            data = {"data": models, "object": "list"}
            cfg["models_cache"] = {"data": data, "ts": now}
            return self._send_json(200, data)
        self._send_json(404, {"type": "error", "error": {
            "type": "not_found", "message": "models listing not available"}})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/v1/messages/count_tokens":
            body, err = self._read_json()
            if err:
                s, o = error_envelope(400, "invalid_request_error", err)
                return self._send_json(s, o)
            msgs = body.get("messages") or []
            total = sum(estimate_tokens(flatten_text(m.get("content"))) for m in msgs
                        if isinstance(m, dict))
            return self._send_json(200, {"input_tokens": total})
        if path != "/v1/messages":
            return self._send_json(404, {"type": "error", "error": {
                "type": "not_found", "message": f"unknown path {self.path}"}})

        body, err = self._read_json()
        if err:
            s, o = error_envelope(400, "invalid_request_error", err)
            return self._send_json(s, o)
        cfg = self.server.config
        # zen: CC 2.1.299 manda role:"system" dentro de messages; el relay lo
        # sanea (hoist_system_messages), asi que aqui se admite.
        problem = validate_messages_request(body,
                                            allow_system_roles=(cfg["upstream"] == "zen"))
        if problem:
            s, o = error_envelope(400, "invalid_request_error", problem)
            return self._send_json(s, o)

        stream = bool(body.get("stream"))
        if cfg["upstream"] == "mock":
            status, obj = mock_respond(body)
            if stream and status == 200:
                return self._stream_anthropic(obj)
            return self._send_json(status, obj)

        if cfg["upstream"] == "zen":
            from freya_wire import resolve_zen_model
            from zen_fingerprint import is_chat_model, is_responses_model
            try:
                body["model"] = resolve_zen_model(body.get("model"))
            except ValueError as e:
                s, o = error_envelope(400, "invalid_request_error", str(e))
                return self._send_json(s, o)
            bare = body["model"]
            if is_responses_model(bare):
                return self._handle_zen_responses(body, stream)
            if is_chat_model(bare):
                return self._handle_zen_chat(body, stream)
            return self._handle_zen_messages(body, stream)

        # passthrough: forward bytes unmodified (errors included, unmodified)
        api_key = cfg.get("api_key", "")
        status, raw, _hdrs = passthrough(cfg["upstream_url"], api_key, body, stream,
                                         {"anthropic-version":
                                          self.headers.get("anthropic-version",
                                                           ANTHROPIC_VERSION),
                                          "anthropic-beta":
                                          self.headers.get("anthropic-beta", "")})
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---- Anthropic SSE for a complete mock message
    def _stream_anthropic(self, msg: dict):
        self.close_connection = True
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "close")
        self.end_headers()

        def emit(event: str, data: dict) -> bool:
            try:
                self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError):
                return False

        head = {k: v for k, v in msg.items() if k != "content"} | {
            "content": [], "stop_reason": None}
        if not emit("message_start", {"type": "message_start",
                                      "message": head}):
            return
        for i, block in enumerate(msg.get("content", [])):
            btype = block.get("type")
            start_block = dict(block)
            if btype == "text":
                # igual que Anthropic: start con texto vacio, contenido por deltas
                start_block["text"] = ""
            elif btype == "tool_use":
                # igual que Anthropic: start con input {} y deltas input_json_delta
                start_block["input"] = {}
            if not emit("content_block_start", {"type": "content_block_start",
                                                "index": i,
                                                "content_block": start_block}):
                return
            if btype == "text":
                text = block.get("text", "")
                for j in range(0, len(text), 60):
                    time.sleep(0.002)
                    if not emit("content_block_delta", {"type": "content_block_delta",
                                                        "index": i, "delta": {
                                                            "type": "text_delta",
                                                            "text": text[j:j + 60]}}):
                        return
            elif btype == "tool_use":
                blob = json.dumps(block.get("input", {}))
                for j in range(0, len(blob), 40):
                    time.sleep(0.002)
                    if not emit("content_block_delta", {"type": "content_block_delta",
                                                        "index": i, "delta": {
                                                            "type": "input_json_delta",
                                                            "partial_json": blob[j:j + 40]}}):
                        return
            if not emit("content_block_stop", {"type": "content_block_stop", "index": i}):
                return
        emit("message_delta", {"type": "message_delta",
                               "delta": {"stop_reason": msg.get("stop_reason")},
                               "usage": msg.get("usage", {})})
        emit("message_stop", {"type": "message_stop"})

    def _stream_error_event(self, err: dict):
        """SSE con un unico ``event: error`` (corte upstream a mitad de stream)."""
        self.close_connection = True
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "close")
        self.end_headers()
        try:
            self.wfile.write(b"event: error\ndata: "
                             + json.dumps(err, separators=(",", ":")).encode()
                             + b"\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---- Zen v2 thin relay: Messages -> /inference/v1/messages -> Messages
    def _handle_zen_messages(self, body: dict, stream: bool):
        """Relay fino con fingerprint v2 (zen_fingerprint).

        El body Anthropic viaja casi intacto: se agregan los tools verbatim
        read/shell (o se renombran colisiones), se fuerza stream:true upstream y
        la respuesta se normaliza (read->Read, shell->Bash, aliases).
        """
        try:
            from zen_fingerprint import (
                AnthropicSSENormalizer,
                apply_fingerprint_tools,
                assemble_message,
                force_stream,
                hoist_system_messages,
                post_messages,
                split_sse_frames,
            )
            from freya_wire import conversation_scope
        except Exception as e:
            s, o = error_envelope(502, "api_error", f"zen fingerprint unavailable: {e}")
            return self._send_json(s, o)
        patched = json.loads(json.dumps(body))
        try:
            hoist_system_messages(patched)
            amap = apply_fingerprint_tools(patched, style="anthropic")
            force_stream(patched)
        except Exception as e:
            s, o = error_envelope(400, "invalid_request_error",
                                  f"zen translation failed: {e}")
            return self._send_json(s, o)
        cfg = self.server.config
        base_url = cfg.get("upstream_url") or ZEN_DEFAULT_BASE
        scope = conversation_scope(patched)
        try:
            status, obj = post_messages(patched, scope, base_url=base_url,
                                        timeout=300)
        except Exception as e:
            s, o = error_envelope(502, "api_error", f"zen messages failed: {e}")
            return self._send_json(s, o)
        if status != 200:
            return self._send_zen_error(status, obj)
        resp = obj
        expected = str(patched.get("model") or "")
        try:
            if stream:
                return self._relay_anthropic_stream(resp, amap, expected)
            raw = resp.read()
            chunks: list[bytes] = []
            norm = AnthropicSSENormalizer(alias_map=amap)
            for frame in split_sse_frames(raw):
                chunks.extend(norm.feed_frame(frame))
            chunks.extend(norm.finish())
            msg = assemble_message(chunks)
            if "_error" in msg:
                return self._send_json(502, msg["_error"])
            if not norm.saw_message_stop:
                return self._send_json(502, {
                    "type": "error", "error": {
                        "type": "api_error",
                        "message": "upstream stream ended before message_stop "
                                   "(truncated by provider)"}})
            mismatch = model_echo_error(expected, norm.model_name or msg.get("model", ""))
            if mismatch:
                return self._send_json(502, mismatch)
            return self._send_json(200, msg)
        finally:
            try:
                resp.close()
            except Exception:
                pass

    def _send_zen_error(self, status: int, raw):
        """Errores del proveedor sin transformar (403 FreeTierError incluido)."""
        try:
            obj = json.loads(raw.decode("utf-8", errors="replace") or "{}")
        except Exception:
            text = raw[:500].decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)[:500]
            obj = {"type": "error", "error": {"type": "api_error",
                                              "message": text or f"zen HTTP {status}"}}
        if not isinstance(obj, dict) or obj.get("type") != "error":
            obj = {"type": "error", "error": {"type": "api_error",
                                              "message": json.dumps(obj)[:500]}}
        return self._send_json(status, obj)

    def _relay_anthropic_stream(self, resp, amap: dict, expected_model: str = ""):
        """Reenvia el SSE de Zen normalizando frames placeholder.

        Si el upstream cierra sin ``message_stop`` (corte a mitad de stream,
        observado en el free tier) o el eco de modelo no coincide, se emite un
        ``event: error`` para que el cliente reintente en vez de aceptar una
        respuesta incompleta o de otro modelo.
        """
        from zen_fingerprint import AnthropicSSENormalizer
        self.close_connection = True
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "close")
        self.end_headers()
        norm = AnthropicSSENormalizer(alias_map=amap)
        try:
            for line in resp:
                for chunk in norm.feed_line(line):
                    self.wfile.write(chunk + b"\n")  # separador de frame
                    self.wfile.flush()
            for chunk in norm.finish():
                self.wfile.write(chunk + b"\n")
            if not norm.saw_message_stop:
                err = {
                    "type": "error",
                    "error": {
                        "type": "api_error",
                        "message": "upstream stream ended before message_stop (truncated by provider)",
                    },
                }
                self.wfile.write(
                    b"event: error\ndata: "
                    + json.dumps(err, separators=(",", ":")).encode()
                    + b"\n\n"
                )
            else:
                mismatch = model_echo_error(expected_model, norm.model_name)
                if mismatch:
                    self.wfile.write(
                        b"event: error\ndata: "
                        + json.dumps(mismatch, separators=(",", ":")).encode()
                        + b"\n\n"
                    )
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---- Zen Responses (Freya-Hermes port): Messages -> Responses -> Messages
    def _handle_zen_responses(self, body: dict, stream: bool):
        try:
            from zen_bridge import (
                anthropic_to_responses_body,
                parse_responses_payload,
                responses_to_anthropic,
                zen_post,
            )
            from freya_wire import conversation_scope
        except Exception as e:
            s, o = error_envelope(502, "api_error",
                                  f"zen bridge unavailable: {e}")
            return self._send_json(s, o)
        try:
            rbody, scope, amap = anthropic_to_responses_body(body)
        except Exception as e:
            s, o = error_envelope(400, "invalid_request_error",
                                  f"zen translation failed: {e}")
            return self._send_json(s, o)
        cfg = self.server.config
        base_url = cfg.get("upstream_url") or ZEN_DEFAULT_BASE
        status, raw, _ctype = zen_post(rbody, scope, timeout=120,
                                       base_url=base_url)
        if status != 200:
            # Errores del proveedor se devuelven sin modificar (status + body).
            try:
                obj = json.loads(raw.decode("utf-8", errors="replace") or "{}")
                if not isinstance(obj, dict) or obj.get("type") != "error":
                    obj = {"type": "error", "error": {
                        "type": "api_error",
                        "message": (raw[:500].decode("utf-8", "replace") or f"zen HTTP {status}")}}
            except Exception:
                obj = {"type": "error", "error": {
                    "type": "api_error",
                    "message": f"zen HTTP {status}"}}
            return self._send_json(status, obj)
        try:
            parsed = parse_responses_payload(raw, _ctype)
        except Exception as e:
            s, o = error_envelope(502, "api_error",
                                  f"zen parse failed: {e}")
            return self._send_json(s, o)
        if isinstance(parsed.get("error"), dict):
            err = parsed["error"]
            if isinstance(err, dict) and err.get("type") == "error":
                return self._send_json(502, err)
            s, o = error_envelope(502, "api_error", str(err)[:500])
            return self._send_json(s, o)
        mismatch = model_echo_error(str(body.get("model") or ""),
                                    str(parsed.get("model_name") or ""))
        if mismatch:
            return self._send_json(502, mismatch)
        if not parsed.get("saw_done"):
            err = {"type": "error", "error": {
                "type": "api_error",
                "message": "upstream stream ended before response.completed "
                           "(truncated by provider)"}}
            if stream:
                return self._stream_error_event(err)
            return self._send_json(502, err)
        model = str(body.get("model") or ZEN_DEFAULT_MODEL)
        try:
            mt = body.get("max_tokens")
            mt = mt if isinstance(mt, int) and mt > 0 else 1024
            msg = responses_to_anthropic(model, parsed, max_tokens=mt,
                                         alias_map=amap)
        except Exception as e:
            s, o = error_envelope(502, "api_error",
                                  f"zen to-anthropic failed: {e}")
            return self._send_json(s, o)
        if stream:
            return self._stream_anthropic(msg)
        return self._send_json(200, msg)

    # ---- Zen v2 chat bridge: Messages -> /chat/completions -> Messages
    def _handle_zen_chat(self, body: dict, stream: bool):
        """Modelos free que solo hablan chat.completions (Fase 5: beam-free,
        deepseek-v4.1-flash-free, glm-5.3-flash-free, nemotron-*, mimo-*,
        longcat-*, ll-alpha-*). Misma traduccion + fingerprint v2 chat."""
        try:
            from zen_chat import (anthropic_to_chat_body, chat_to_anthropic,
                                  parse_chat_payload, zen_post_chat)
        except Exception as e:
            s, o = error_envelope(502, "api_error",
                                  f"zen chat bridge unavailable: {e}")
            return self._send_json(s, o)
        try:
            cbody, scope, amap = anthropic_to_chat_body(body)
        except Exception as e:
            s, o = error_envelope(400, "invalid_request_error",
                                  f"zen translation failed: {e}")
            return self._send_json(s, o)
        cfg = self.server.config
        base_url = cfg.get("upstream_url") or ZEN_DEFAULT_BASE
        status, raw, _ctype = zen_post_chat(cbody, scope, timeout=120,
                                            base_url=base_url)
        if status != 200:
            # Errores del proveedor se devuelven sin modificar (status + body).
            try:
                obj = json.loads(raw.decode("utf-8", errors="replace") or "{}")
                if not isinstance(obj, dict) or obj.get("type") != "error":
                    obj = {"type": "error", "error": {
                        "type": "api_error",
                        "message": (raw[:500].decode("utf-8", "replace")
                                    or f"zen HTTP {status}")}}
            except Exception:
                obj = {"type": "error", "error": {
                    "type": "api_error", "message": f"zen HTTP {status}"}}
            return self._send_json(status, obj)
        try:
            parsed = parse_chat_payload(raw, _ctype)
        except Exception as e:
            s, o = error_envelope(502, "api_error", f"zen parse failed: {e}")
            return self._send_json(s, o)
        if isinstance(parsed.get("error"), dict):
            return self._send_json(502, {"type": "error",
                                         "error": parsed["error"]})
        if not parsed.get("saw_done") and not parsed.get("finish_reason"):
            # Corte a mitad de stream del free tier (observado): avisar al
            # cliente para que reintente en vez de aceptar una respuesta vacia.
            err = {"type": "error", "error": {
                "type": "api_error",
                "message": "upstream stream ended before completion "
                           "(truncated by provider)"}}
            if stream:
                return self._stream_error_event(err)
            return self._send_json(502, err)
        mismatch = model_echo_error(str(body.get("model") or ""),
                                    str(parsed.get("model_name") or ""))
        if mismatch:
            if stream:
                return self._stream_error_event(mismatch)
            return self._send_json(502, mismatch)
        model = str(body.get("model") or ZEN_DEFAULT_MODEL)
        try:
            mt = body.get("max_tokens")
            mt = mt if isinstance(mt, int) and mt > 0 else 1024
            msg = chat_to_anthropic(model, parsed, max_tokens=mt,
                                    alias_map=amap)
        except Exception as e:
            s, o = error_envelope(502, "api_error",
                                  f"zen to-anthropic failed: {e}")
            return self._send_json(s, o)
        if stream:
            return self._stream_anthropic(msg)
        return self._send_json(200, msg)


def build_server(port: int, upstream: str, upstream_url: str, api_key: str
                 ) -> ThreadingHTTPServer:
    if upstream == "zen":
        # Upstream zen explícito: relay v2 + fingerprint (zen_fingerprint).
        # El base por defecto es /inference/v1; se permite override solo para
        # tests con servidor local (127.0.0.1). Un passthrough hacia Zen sigue
        # rechazado: debe pasar por el fingerprint, no directo.
        low = (upstream_url or "").lower()
        is_loopback_test = ("127.0.0.1" in low) or ("localhost" in low)
        is_zen = ("opencode.ai" in low) or (low in ("", "zen"))
        if not (is_zen or is_loopback_test):
            raise SystemExit(
                f"zen upstream needs a Zen base URL (got {upstream_url!r}); "
                f"default {ZEN_DEFAULT_BASE}")
        if not upstream_url or upstream_url == "https://api.anthropic.com":
            upstream_url = ZEN_DEFAULT_BASE
    else:
        if "opencode.ai" in (upstream_url or "").lower():
            raise SystemExit(
                f"refusing upstream {upstream_url!r} for '{upstream}': use "
                "--upstream zen (relay /inference/v1 + fingerprint v2) en vez de "
                "passthrough directo; el tier free exige el wire con huella "
                "(403 FreeTierError si falta).")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.config = {"upstream": upstream, "upstream_url": upstream_url, "api_key": api_key}
    server.daemon_threads = True
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description="Claude-Code local Anthropic gateway")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--upstream", choices=["mock", "passthrough", "zen"], default="mock")
    ap.add_argument("--upstream-url", default="https://api.anthropic.com")
    ap.add_argument("--api-key", default="")
    args = ap.parse_args()
    if args.upstream == "zen" and args.upstream_url == "https://api.anthropic.com":
        args.upstream_url = ZEN_DEFAULT_BASE
    server = build_server(args.port, args.upstream, args.upstream_url, args.api_key)
    print(f"{GATEWAY_NAME} {GATEWAY_VERSION} on 127.0.0.1:"
          f"{server.server_address[1]} upstream={args.upstream}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
