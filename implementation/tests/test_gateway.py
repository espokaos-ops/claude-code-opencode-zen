#!/usr/bin/env python3
"""Reproducible gateway tests (stdlib unittest, loopback only, no credentials).

Starts gateway.py in-process on an ephemeral 127.0.0.1 port with the mock
upstream, then exercises: health, text, single tool_use round-trip, multi
tool_use, SSE streaming order, error mapping, session continuity and client
interruption. Also exercises the zen v2 relay (FakeZenMessages) and /v1/models.
No network beyond loopback. No Hermes imports.
"""
import json
import re
import threading
import unittest
import urllib.request
import urllib.error
import sys
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Loopback must never go through the session proxy (mirrors Claude Code, which
# never proxies localhost/127.0.0.0/8). The ambient shell may export HTTP_PROXY
# without NO_PROXY; force a proxy-bypassing opener for this test process only.
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gateway import build_server  # noqa: E402  (same directory, not Hermes)
import freya_wire  # noqa: E402
import zen_fingerprint  # noqa: E402


def post(base, path, obj, headers=None, timeout=15):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(base + path, data=data,
                                 headers={"content-type": "application/json",
                                          "anthropic-version": "2023-06-01",
                                          **(headers or {})}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw[:200].decode("utf-8", "replace")}


def read_sse(base, obj, timeout=20, max_events=400,
             stop_at_message_stop=True):
    """POST with stream:true, return list of (event, data)."""
    data = json.dumps({**obj, "stream": True}).encode()
    req = urllib.request.Request(base + "/v1/messages", data=data,
                                 headers={"content-type": "application/json",
                                          "anthropic-version": "2023-06-01"},
                                 method="POST")
    events = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        buf = b""
        while len(events) < max_events:
            chunk = r.read(1)
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                frame, buf = buf.split(b"\n\n", 1)
                lines = frame.decode("utf-8", "replace").splitlines()
                ev, payload = "message", "{}"
                for ln in lines:
                    if ln.startswith("event:"):
                        ev = ln.split(":", 1)[1].strip()
                    elif ln.startswith("data:"):
                        payload = ln.split(":", 1)[1].strip()
                try:
                    events.append((ev, json.loads(payload)))
                except Exception:
                    pass
                if stop_at_message_stop and ev == "message_stop":
                    return events
    return events


class GatewayCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = build_server(0, "mock", "https://api.anthropic.com", "")
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def base_msg(self, text, **kw):
        body = {"model": "mock:claude-sonnet", "max_tokens": 256,
                "messages": [{"role": "user", "content": text}]}
        body.update(kw)
        return body

    def test_health(self):
        with urllib.request.urlopen(self.base + "/health", timeout=5) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(json.loads(r.read())["status"], "ok")

    def test_text_conversation(self):
        s, o = post(self.base, "/v1/messages", self.base_msg("hello world"))
        self.assertEqual(s, 200)
        self.assertEqual(o["stop_reason"], "end_turn")
        texts = [b["text"] for b in o["content"] if b["type"] == "text"]
        self.assertTrue(any("turn 1" in t for t in texts), texts)

    def test_single_tool_roundtrip(self):
        s, o = post(self.base, "/v1/messages",
                    self.base_msg("call:read:/tmp/mock-marker.txt",
                                  tools=[{"name": "read",
                                          "input_schema": {"type": "object"}}]))
        self.assertEqual(s, 200)
        self.assertEqual(o["stop_reason"], "tool_use")
        uses = [b for b in o["content"] if b["type"] == "tool_use"]
        self.assertEqual(len(uses), 1)
        self.assertRegex(uses[0]["id"], r"^toolu_")
        # client executes tool, sends result back with full history
        hist = [{"role": "user", "content": "call:read:/tmp/mock-marker.txt"},
                {"role": "assistant", "content": o["content"]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": uses[0]["id"],
                     "content": "MARKER-ABC-123"}]}]
        s2, o2 = post(self.base, "/v1/messages",
                      {"model": "mock:claude-sonnet", "max_tokens": 256, "messages": hist})
        self.assertEqual(s2, 200)
        final = " ".join(b.get("text", "") for b in o2["content"] if b["type"] == "text")
        self.assertIn("MARKER-ABC-123", final)

    def test_multi_tool(self):
        s, o = post(self.base, "/v1/messages", self.base_msg("call:multi"))
        self.assertEqual(s, 200)
        uses = [b for b in o["content"] if b["type"] == "tool_use"]
        self.assertEqual(len(uses), 2)
        self.assertNotEqual(uses[0]["id"], uses[1]["id"])
        self.assertEqual({u["name"] for u in uses}, {"read", "glob"})
        hist = [{"role": "user", "content": "call:multi"},
                {"role": "assistant", "content": o["content"]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": uses[0]["id"], "content": "A-1"},
                    {"type": "tool_result", "tool_use_id": uses[1]["id"], "content": "B-2"}]}]
        s2, o2 = post(self.base, "/v1/messages",
                      {"model": "mock:claude-sonnet", "max_tokens": 256, "messages": hist})
        final = " ".join(b.get("text", "") for b in o2["content"] if b["type"] == "text")
        self.assertIn("A-1", final)
        self.assertIn("B-2", final)

    def test_streaming_sequence(self):
        events = read_sse(self.base, self.base_msg("call:read:/tmp/x.txt"))
        kinds = [e for e, _ in events]
        self.assertEqual(kinds[0], "message_start")
        self.assertEqual(kinds[-1], "message_stop")
        self.assertIn("content_block_start", kinds)
        self.assertIn("content_block_stop", kinds)
        self.assertIn("message_delta", kinds)
        # reassemble tool_use input JSON from deltas
        partials = []
        for e, d in events:
            if e == "content_block_delta" and d.get("delta", {}).get("type") == "input_json_delta":
                partials.append(d["delta"]["partial_json"])
        if partials:
            blob = json.loads("".join(partials))
            self.assertIn("filePath", blob)

    def test_error_mapping(self):
        s, o = post(self.base, "/v1/messages", self.base_msg("error:500 boom"))
        self.assertEqual(s, 500)
        self.assertEqual(o.get("type"), "error")
        s2, o2 = post(self.base, "/v1/messages", {"model": "x", "max_tokens": 1,
                                                  "messages": []})
        self.assertEqual(s2, 400)
        self.assertEqual(o2["error"]["type"], "invalid_request_error")

    def test_session_continuity(self):
        hist = []
        for turn in (1, 2, 3):
            hist.append({"role": "user", "content": f"turn-{turn}"})
            s, o = post(self.base, "/v1/messages",
                        {"model": "mock:claude-sonnet", "max_tokens": 64, "messages": hist})
            self.assertEqual(s, 200)
            txt = " ".join(b.get("text", "") for b in o["content"] if b["type"] == "text")
            self.assertIn(f"turn {turn}", txt)
            hist.append({"role": "assistant", "content": o["content"]})
        # independent session B starts at turn 1 again (no server-side leak)
        s, o = post(self.base, "/v1/messages", self.base_msg("fresh"))
        txt = " ".join(b.get("text", "") for b in o["content"] if b["type"] == "text")
        self.assertIn("turn 1", txt)

    def test_interruption_server_survives(self):
        data = json.dumps({**self.base_msg("stop:long-stream"), "stream": True}).encode()
        req = urllib.request.Request(self.base + "/v1/messages", data=data,
                                     headers={"content-type": "application/json",
                                              "anthropic-version": "2023-06-01"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            self.assertEqual(r.status, 200)
            r.read(200)  # read partial, then abandon (close)
        with urllib.request.urlopen(self.base + "/health", timeout=5) as r2:
            self.assertEqual(r2.status, 200)


# ---------------------------------------------------------------- zen v2 relay

class FakeZenMessagesHandler(BaseHTTPRequestHandler):
    """Mimica /inference/v1/messages (Anthropic SSE) con el gate v2 completo."""
    last_request: dict = {}

    def log_message(self, *a):
        pass

    def _send(self, status, raw, ctype="application/json"):
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _gate_error(self, why):
        return self._send(403, json.dumps({"type": "error", "error": {
            "type": "FreeTierError", "message": why}}).encode())

    def do_GET(self):
        models = {"data": [{"id": "beam-free", "name": "Beam"},
                           {"id": "paid-model-not-free"}]}
        self._send(200, json.dumps(models).encode())

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            return self._send(400, b'{"error":"bad json"}')
        FakeZenMessagesHandler.last_request = {
            "headers": dict(self.headers), "body": body, "path": self.path}

        if self.path.rstrip("/").endswith("/responses"):
            req_model = str(body.get("model") or "")
            if body.get("max_output_tokens") == 76:
                resp = {"id": "resp_fake2", "model": "wrong-model-free",
                        "output": [{"type": "message", "role": "assistant",
                                    "content": [{"type": "output_text",
                                                 "text": "hola"}]}],
                        "usage": {"input_tokens": 1, "output_tokens": 1}}
                return self._send(200, json.dumps(resp).encode())
            if body.get("max_output_tokens") == 75:
                trunc = (
                    'event: response.created\n'
                    'data: {"type":"response.created","response":'
                    '{"id":"resp_trunc","model":"muse-spark-1.3-contributor-free",'
                    '"output":[]}}\n\n'
                ).encode()
                return self._send(200, trunc, "text/event-stream")
            resp = {"id": "resp_fake1", "model": req_model, "output": [
                {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "hola muse"}]},
                {"type": "function_call", "name": "read", "call_id": "call_fake1",
                 "arguments": "{\"path\": \"/tmp/fake-muse.txt\"}"}],
                "usage": {"input_tokens": 7, "output_tokens": 5}}
            return self._send(200, json.dumps(resp).encode())

        def _h(name):
            for k, v in dict(self.headers).items():
                if str(k).lower() == name:
                    return v
            return ""

        if _h("authorization") != "Bearer public":
            return self._gate_error("auth")
        if _h("user-agent") != zen_fingerprint.OPENCODE_UA:
            return self._gate_error("UA")
        ses = _h("x-opencode-session")
        if not re.match(r"^ses_", ses) or ses != _h("x-opencode-session-id"):
            return self._gate_error("session")
        if body.get("stream") is not True:
            return self._gate_error("stream")

        if self.path.rstrip("/").endswith("/chat/completions"):
            chat_tools = {((t or {}).get("function") or {}).get("name"): t
                          for t in body.get("tools") or []
                          if isinstance(t, dict) and t.get("type") == "function"}
            for key in ("read", "shell"):
                tool = chat_tools.get(key)
                if not tool or not zen_fingerprint.is_fingerprint_definition(
                        tool, key):
                    return self._gate_error(f"chat-tools:{key}")
            if body.get("tool_choice") == "none":
                return self._gate_error("tool_choice")
            for m in body.get("messages") or []:
                if not isinstance(m, dict) or m.get("role") not in (
                        "system", "user", "assistant", "tool"):
                    return self._gate_error("chat-roles")
            if body.get("max_tokens") == 78:
                return self._send(403, json.dumps({"type": "error", "error": {
                    "type": "FreeTierError", "message": "forced chat"}}).encode())
            if body.get("max_tokens") == 76:
                wrong = (
                    'data: {"id":"chatcmpl_wrong","choices":[{"index":0,'
                    '"delta":{"role":"assistant"}}],"model":"wrong-model-free"}\n\n'
                    'data: {"id":"chatcmpl_wrong","choices":[{"index":0,'
                    '"delta":{"content":"hola"},"finish_reason":"stop"}],'
                    '"model":"wrong-model-free"}\n\n'
                    "data: [DONE]\n\n"
                ).encode()
                return self._send(200, wrong, "text/event-stream")
            if body.get("max_tokens") == 77:
                trunc = (
                    'data: {"id":"chatcmpl_trunc","choices":[{"index":0,'
                    '"delta":{"role":"assistant"}}],"usage":null}\n\n'
                    'data: {"id":"chatcmpl_trunc","choices":[{"index":0,'
                    '"delta":{"content":"cor"}}],"usage":null}\n\n'
                ).encode()
                return self._send(200, trunc, "text/event-stream")
            chat_sse = (
                'data: {"id":"chatcmpl_fake2","object":"chat.completion.chunk",'
                '"created":1,"model":"beam-free","choices":[{"index":0,'
                '"delta":{"role":"assistant"}}],"usage":null}\n\n'
                'data: {"id":"chatcmpl_fake2","object":"chat.completion.chunk",'
                '"created":1,"model":"beam-free","choices":[{"index":0,'
                '"delta":{"content":"hola chat"},"finish_reason":null}],"usage":null}\n\n'
                'data: {"id":"chatcmpl_fake2","object":"chat.completion.chunk",'
                '"created":1,"model":"beam-free","choices":[{"index":0,'
                '"delta":{"tool_calls":[{"index":0,"id":"call_fake2",'
                '"type":"function","function":{"name":"read",'
                '"arguments":"{\\"path\\": \\"/tmp/fake-chat.txt\\"}"}}]},'
                '"finish_reason":null}],"usage":null}\n\n'
                'data: {"id":"chatcmpl_fake2","object":"chat.completion.chunk",'
                '"created":1,"model":"beam-free","choices":[{"index":0,'
                '"delta":{},"finish_reason":"tool_calls"}],"usage":null}\n\n'
                'data: {"id":"chatcmpl_fake2","object":"chat.completion.chunk",'
                '"created":1,"model":"beam-free","choices":[],"usage":'
                '{"prompt_tokens":13,"completion_tokens":7,"total_tokens":20}}\n\n'
                "data: [DONE]\n\n"
            ).encode()
            cm = str(body.get("model") or "beam-free")
            chat_sse = chat_sse.replace(b'"model":"beam-free"',
                                        b'"model":"' + cm.encode() + b'"')
            return self._send(200, chat_sse, "text/event-stream")

        if body.get("max_tokens") == 76:
            wrong = (
                "event: message_start\n"
                'data: {"type":"message_start","message":{"id":"msg_wrong","type":"message",'
                '"role":"assistant","model":"wrong-model-free","content":[],'
                '"usage":{"input_tokens":1}}}\n\n'
                "event: content_block_start\n"
                'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
                "event: content_block_delta\n"
                'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hola"}}\n\n'
                "event: content_block_stop\n"
                'data: {"type":"content_block_stop","index":0}\n\n'
                "event: message_delta\n"
                'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":1}}\n\n'
                "event: message_stop\n"
                'data: {"type":"message_stop"}\n\n'
            ).encode()
            return self._send(200, wrong, "text/event-stream")

        tools = {t.get("name"): t for t in body.get("tools") or []
                 if isinstance(t, dict)}
        for key in ("read", "shell"):
            if key not in tools or not zen_fingerprint.is_fingerprint_definition(tools[key], key):
                return self._gate_error(f"tools:{key}")
        if body.get("tool_choice") == "none":
            return self._gate_error("tool_choice")
        for m in body.get("messages") or []:
            if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
                return self._gate_error("roles")
        if body.get("max_tokens") == 78:
            return self._send(403, json.dumps({"type": "error", "error": {
                "type": "FreeTierError", "message": "forced"}}).encode())
        if body.get("max_tokens") == 77:
            trunc = (
                "event: message_start\n"
                'data: {"type":"message_start","message":{"id":"msg_trunc","type":"message",'
                '"role":"assistant","model":"space-bunny-free","content":[],'
                '"usage":{"input_tokens":11}}}\n\n'
                "event: content_block_start\n"
                'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}\n\n'
                "event: content_block_delta\n"
                'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"cort"}}\n\n'
            ).encode()
            return self._send(200, trunc, "text/event-stream")
        sse = (
            "event: message_start\n"
            'data: {"type":"message_start","message":{"id":"msg_fake1","type":"message",'
            '"role":"assistant","model":"space-bunny-free","content":[],'
            '"usage":{"input_tokens":11}}}\n\n'
            "event: content_block_start\n"
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
            "event: content_block_delta\n"
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hola"}}\n\n'
            "event: content_block_stop\n"
            'data: {"type":"content_block_stop","index":0}\n\n'
            "event: content_block_start\n"
            'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"tu_fake1","name":"read","input":{}}}\n\n'
            "event: content_block_delta\n"
            'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"path\\": \\"/tmp/fake-zen-file.txt\\"}"}}\n\n'
            "event: content_block_stop\n"
            'data: {"type":"content_block_stop","index":1}\n\n'
            "event: message_delta\n"
            'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":9}}\n\n'
            "event: message_stop\n"
            'data: {"type":"message_stop"}\n\n'
        ).encode()
        self._send(200, sse, "text/event-stream")


class GatewayZenMessagesCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeZenMessagesHandler)
        cls.fake.daemon_threads = True
        fake_base = f"http://127.0.0.1:{cls.fake.server_address[1]}/inference/v1"
        cls.fake_thread = threading.Thread(target=cls.fake.serve_forever, daemon=True)
        cls.fake_thread.start()
        cls.server = build_server(0, "zen", fake_base, "")
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.fake.shutdown()
        cls.fake.server_close()

    def cc_body(self, text="hola", tools=None, model="space-bunny-free",
                max_tokens=128):
        return {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": text}],
                "tools": tools if tools is not None else [
                    {"name": "Read", "description": "cc",
                     "input_schema": {"type": "object"}},
                    {"name": "Bash", "description": "cc",
                     "input_schema": {"type": "object"}}]}

    def test_relay_stream_normalizes_placeholder(self):
        events = read_sse(self.base, self.cc_body())
        scenarios = [d for e, d in events if e == "content_block_start"]
        self.assertEqual(scenarios[0]["content_block"]["type"], "text")
        tool_start = next(d for d in scenarios
                          if d["content_block"].get("type") == "tool_use")
        self.assertEqual(tool_start["content_block"]["name"], "Read")
        partials = []
        for e, d in events:
            if e == "content_block_delta" and d.get("delta", {}).get("type") == "input_json_delta":
                partials.append(d["delta"]["partial_json"])
        self.assertEqual(json.loads("".join(partials)),
                         {"file_path": "/tmp/fake-zen-file.txt"})
        self.assertEqual(events[-1][0], "message_stop")
        # el upstream valido el gate v2 completo
        last = FakeZenMessagesHandler.last_request
        low = {str(k).lower(): v for k, v in last["headers"].items()}
        self.assertEqual(low.get("authorization"), "Bearer public")
        self.assertEqual(low.get("user-agent"), zen_fingerprint.OPENCODE_UA)
        self.assertEqual(low.get("x-opencode-client"), "cli")
        self.assertNotIn("x-opencode-request", low)
        self.assertEqual(low.get("x-opencode-session"), low.get("x-opencode-session-id"))
        self.assertTrue(last["path"].endswith("/messages"))
        self.assertTrue(last["body"]["stream"])
        names = [t["name"] for t in last["body"]["tools"]]
        self.assertIn("Read", names)
        self.assertIn("read", names)
        self.assertIn("shell", names)

    def test_relay_hoists_midstream_system_message(self):
        body = self.cc_body()
        body["messages"] = [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {"role": "system", "content": [{"type": "text", "text": "ENV-PROMPT-77"}]},
        ]
        events = read_sse(self.base, body)
        self.assertEqual(events[-1][0], "message_stop")
        sent = FakeZenMessagesHandler.last_request["body"]
        self.assertEqual([m["role"] for m in sent["messages"]], ["user"])
        sys_texts = [b.get("text") for b in sent.get("system") or []]
        self.assertIn("ENV-PROMPT-77", sys_texts)

    def test_relay_nonstream_assembles_message(self):
        s, o = post(self.base, "/v1/messages", self.cc_body())
        self.assertEqual(s, 200, o)
        self.assertEqual(o["id"], "msg_fake1")
        self.assertEqual(o["stop_reason"], "tool_use")
        texts = [b["text"] for b in o["content"] if b["type"] == "text"]
        self.assertIn("hola", texts)
        tool = next(b for b in o["content"] if b["type"] == "tool_use")
        self.assertEqual(tool["name"], "Read")
        self.assertEqual(tool["input"], {"file_path": "/tmp/fake-zen-file.txt"})
        self.assertEqual(o["usage"]["input_tokens"], 11)
        self.assertEqual(o["usage"]["output_tokens"], 9)

    def test_muse_path_streams_well_formed_sse(self):
        events = read_sse(self.base,
                          self.cc_body(model="muse-spark-1.3-contributor-free"))
        self.assertEqual(events[0][0], "message_start")
        self.assertIsNone(events[0][1]["message"].get("stop_reason"))
        starts = [d for e, d in events if e == "content_block_start"]
        txt = next(b for b in starts if b["content_block"]["type"] == "text")
        # el start va vacio: el contenido llega solo por deltas (sin duplicar)
        self.assertEqual(txt["content_block"]["text"], "")
        tool = next(b for b in starts if b["content_block"]["type"] == "tool_use")
        self.assertEqual(tool["content_block"]["input"], {})
        self.assertEqual(tool["content_block"]["name"], "Read")
        deltas = [d for e, d in events if e == "content_block_delta"]
        text = "".join(d["delta"]["text"] for d in deltas
                       if d["delta"]["type"] == "text_delta")
        self.assertEqual(text, "hola muse")
        pj = "".join(d["delta"]["partial_json"] for d in deltas
                     if d["delta"]["type"] == "input_json_delta")
        self.assertEqual(json.loads(pj), {"file_path": "/tmp/fake-muse.txt"})
        stops = [d for e, d in events if e == "content_block_stop"]
        self.assertEqual([s["index"] for s in stops], [0, 1])
        self.assertEqual(events[-1][0], "message_stop")

    def test_chat_model_routes_to_chat_and_roundtrips(self):
        events = read_sse(self.base, self.cc_body(model="beam-free"))
        last = FakeZenMessagesHandler.last_request
        self.assertTrue(last["path"].rstrip("/").endswith("/chat/completions"))
        low = {str(k).lower(): v for k, v in last["headers"].items()}
        self.assertTrue(low.get("x-session-affinity"))
        self.assertEqual(low.get("x-opencode-project"), "global")
        starts = [d for e, d in events if e == "content_block_start"]
        tool = next(b for b in starts if b["content_block"]["type"] == "tool_use")
        self.assertEqual(tool["content_block"]["name"], "Read")
        deltas = [d for e, d in events if e == "content_block_delta"]
        text = "".join(d["delta"]["text"] for d in deltas
                       if d["delta"]["type"] == "text_delta")
        self.assertEqual(text, "hola chat")
        pj = "".join(d["delta"]["partial_json"] for d in deltas
                     if d["delta"]["type"] == "input_json_delta")
        self.assertEqual(json.loads(pj), {"file_path": "/tmp/fake-chat.txt"})
        self.assertEqual(events[-1][0], "message_stop")
        sent = {((t or {}).get("function") or {}).get("name")
                for t in last["body"]["tools"]}
        self.assertIn("read", sent)
        self.assertIn("shell", sent)
        roles = [m.get("role") for m in last["body"]["messages"]]
        self.assertEqual(roles[0], "system")
        self.assertIn("user", roles)

    def test_chat_model_nonstream_assembles_json(self):
        body = self.cc_body(model="beam-free")
        s, o = post(self.base, "/v1/messages", body)
        self.assertEqual(s, 200)
        tool = next(b for b in o["content"] if b["type"] == "tool_use")
        self.assertEqual(tool["name"], "Read")
        self.assertEqual(tool["input"], {"file_path": "/tmp/fake-chat.txt"})
        self.assertEqual(o["stop_reason"], "tool_use")
        self.assertEqual(o["usage"]["input_tokens"], 13)
        self.assertEqual(o["usage"]["output_tokens"], 7)

    def test_chat_error_passthrough_403(self):
        s, o = post(self.base, "/v1/messages",
                    self.cc_body(model="beam-free", max_tokens=78))
        self.assertEqual(s, 403)
        self.assertEqual(o["error"]["type"], "FreeTierError")

    def test_chat_truncated_upstream_emits_error(self):
        events = read_sse(self.base, self.cc_body(model="beam-free",
                                                  max_tokens=77))
        self.assertFalse(any(e == "message_stop" for e, _ in events))
        errs = [d for e, d in events if e == "error"]
        self.assertEqual(len(errs), 1)
        self.assertIn("truncated", errs[0]["error"]["message"])

    def test_relay_alias_collision_roundtrip(self):
        tools = [{"name": "read", "description": "client own",
                  "input_schema": {"type": "object"}},
                 {"name": "Read", "description": "cc",
                  "input_schema": {"type": "object"}}]
        events = read_sse(self.base, self.cc_body(tools=tools))
        sent = [t["name"] for t in FakeZenMessagesHandler.last_request["body"]["tools"]]
        self.assertIn("read_client", sent)
        self.assertIn("read", sent)
        tool_start = next(d for e, d in events if e == "content_block_start"
                          and d["content_block"].get("type") == "tool_use")
        # el upstream devolvio name "read": es el placeholder -> Read
        self.assertEqual(tool_start["content_block"]["name"], "Read")

    def test_error_passthrough_403(self):
        s, o = post(self.base, "/v1/messages",
                    self.cc_body(model="space-bunny-free", max_tokens=78))
        self.assertEqual(s, 403)
        self.assertEqual(o["error"]["type"], "FreeTierError")

    def test_relay_truncated_upstream_emits_error(self):
        events = read_sse(self.base, self.cc_body(model="space-bunny-free",
                                                  max_tokens=77))
        self.assertFalse(any(e == "message_stop" for e, _ in events))
        errs = [d for e, d in events if e == "error"]
        self.assertEqual(len(errs), 1)
        self.assertIn("truncated", errs[0]["error"]["message"])
        deltas = [d for e, d in events
                  if e == "content_block_delta"
                  and d.get("delta", {}).get("type") == "thinking_delta"]
        self.assertTrue(deltas)

    def test_models_endpoint(self):
        with urllib.request.urlopen(self.base + "/v1/models", timeout=5) as r:
            data = json.loads(r.read())
        # solo free verificados, como alias de selector para Claude Code
        self.assertEqual([m["id"] for m in data["data"]], ["claude-free-beam-free"])
        self.assertEqual(data["data"][0]["display_name"], "beam-free")

    def test_unknown_model_rejected_without_substitution(self):
        before = FakeZenMessagesHandler.last_request
        s, o = post(self.base, "/v1/messages",
                    self.cc_body(model="claude-sonnet-4-5"))
        self.assertEqual(s, 400)
        self.assertEqual(o["error"]["type"], "invalid_request_error")
        self.assertIn("free models", o["error"]["message"])
        # ningun request llego al upstream (no hay sustitucion silenciosa)
        self.assertIs(FakeZenMessagesHandler.last_request, before)

    def test_all_free_models_resolve(self):
        for mid in sorted(freya_wire.OPENCODE_FREE_MODELS):
            self.assertEqual(freya_wire.resolve_zen_model(mid), mid)
            self.assertEqual(freya_wire.resolve_zen_model("claude-free-" + mid), mid)
        self.assertEqual(len(freya_wire.OPENCODE_FREE_MODELS), 13)

    def test_selector_alias_routes_to_real_model(self):
        body = self.cc_body(model="claude-free-beam-free")
        s, o = post(self.base, "/v1/messages", body)
        self.assertEqual(s, 200)
        last = FakeZenMessagesHandler.last_request
        self.assertTrue(last["path"].rstrip("/").endswith("/chat/completions"))
        self.assertEqual(last["body"]["model"], "beam-free")

    def test_big_pickle_routes_to_chat_and_preserves_model(self):
        body = self.cc_body(model="big-pickle")
        s, o = post(self.base, "/v1/messages", body)
        self.assertEqual(s, 200, o)
        last = FakeZenMessagesHandler.last_request
        self.assertTrue(last["path"].rstrip("/").endswith("/chat/completions"))
        self.assertEqual(last["body"]["model"], "big-pickle")
        self.assertEqual(o["model"], "big-pickle")

    def test_chat_model_echo_mismatch_errors(self):
        events = read_sse(self.base, self.cc_body(model="beam-free",
                                                  max_tokens=76))
        errs = [d for e, d in events if e == "error"]
        self.assertEqual(len(errs), 1)
        self.assertIn("answered model 'wrong-model-free'",
                      errs[0]["error"]["message"])

    def test_relay_stream_echo_mismatch_appends_error(self):
        events = read_sse(self.base, self.cc_body(model="space-bunny-free",
                                                  max_tokens=76),
                          stop_at_message_stop=False)
        self.assertTrue(any(e == "message_stop" for e, _ in events))
        errs = [d for e, d in events if e == "error"]
        self.assertEqual(len(errs), 1)
        self.assertIn("answered model 'wrong-model-free'",
                      errs[0]["error"]["message"])

    def test_relay_nonstream_truncated_is_502(self):
        s, o = post(self.base, "/v1/messages",
                    self.cc_body(model="space-bunny-free", max_tokens=77))
        self.assertEqual(s, 502)
        self.assertIn("truncated", o["error"]["message"])

    def test_relay_nonstream_echo_mismatch_is_502(self):
        s, o = post(self.base, "/v1/messages",
                    self.cc_body(model="space-bunny-free", max_tokens=76))
        self.assertEqual(s, 502)
        self.assertIn("answered model 'wrong-model-free'", o["error"]["message"])

    def test_responses_echo_mismatch_is_502(self):
        s, o = post(self.base, "/v1/messages",
                    self.cc_body(model="muse-spark-1.3-contributor-free",
                                 max_tokens=76))
        self.assertEqual(s, 502)
        self.assertIn("answered model 'wrong-model-free'", o["error"]["message"])

    def test_responses_truncated_is_502(self):
        s, o = post(self.base, "/v1/messages",
                    self.cc_body(model="muse-spark-1.3-contributor-free",
                                 max_tokens=75))
        self.assertEqual(s, 502)
        self.assertIn("truncated", o["error"]["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
