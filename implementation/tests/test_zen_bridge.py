#!/usr/bin/env python3
"""Tests del port Freya-Hermes -> Claude-Code (stdlib unittest, sin red externa).

Cubre: freya_wire (IDs, sesion estable, headers), freya_tools (6 core,
fingerprint), zen_bridge (Messages<->Responses, parse SSE) y gateway upstream
zen contra un Zen Responses falso en loopback (valida huella + tools).

Sin credenciales, sin Hermes imports, sin tocar el original.
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

urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))

HERE = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, HERE)

import freya_wire
import freya_tools
import zen_bridge
import zen_fingerprint
from gateway import build_server


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
            return e.code, {"raw": raw[:500].decode("utf-8", "replace")}


# ---------------------------------------------------------------- wire

class WireCase(unittest.TestCase):
    def test_new_id_shape(self):
        a = freya_wire.new_opencode_id("ses")
        b = freya_wire.new_opencode_id("ses")
        self.assertRegex(a, r"^ses_[0-9a-f]{12}[0-9A-Za-z]{14}$")
        self.assertNotEqual(a, b)
        c = freya_wire.new_opencode_id("msg")
        self.assertTrue(c.startswith("msg_"))

    def test_session_stable_per_scope(self):
        s1 = freya_wire.free_session_for_scope("unit-scope-A")
        s2 = freya_wire.free_session_for_scope("unit-scope-A")
        s3 = freya_wire.free_session_for_scope("unit-scope-B")
        self.assertEqual(s1, s2)
        self.assertNotEqual(s1, s3)
        self.assertTrue(s1.startswith("ses_"))

    def test_conversation_scope_stable(self):
        b1 = {"model": "muse-spark-1.3-contributor-free",
              "messages": [{"role": "user", "content": "hola scope"}]}
        b2 = {"model": "muse-spark-1.3-contributor-free",
              "messages": [{"role": "user", "content": "hola scope"},
                            {"role": "assistant", "content": "hi"},
                            {"role": "user", "content": "segundo turno"}]}
        b3 = {"model": "muse-spark-1.3-contributor-free",
              "messages": [{"role": "user", "content": "otra conversacion"}]}
        self.assertEqual(freya_wire.conversation_scope(b1),
                         freya_wire.conversation_scope(b2))
        self.assertNotEqual(freya_wire.conversation_scope(b1),
                            freya_wire.conversation_scope(b3))

    def test_zen_model_mapping(self):
        self.assertEqual(freya_wire.zen_model_for_request(
            "muse-spark-1.3-contributor-free"),
            "muse-spark-1.3-contributor-free")
        self.assertEqual(freya_wire.zen_model_for_request(
            "opencode-zen/muse-spark-1.3-contributor-free"),
            "muse-spark-1.3-contributor-free")
        self.assertEqual(freya_wire.zen_model_for_request(
            "claude-free-muse-spark-1.3-contributor-free"),
            "muse-spark-1.3-contributor-free")
        self.assertEqual(freya_wire.zen_model_for_request("claude-free-beam-free"),
                         "beam-free")
        # big-pickle es free y debe conservarse (no sustituirse por muse)
        self.assertEqual(freya_wire.zen_model_for_request("big-pickle"),
                         "big-pickle")
        # Modelo no-free -> error explicito (nunca sustitucion silenciosa)
        with self.assertRaises(ValueError):
            freya_wire.zen_model_for_request("mock:claude-sonnet")

    def test_headers_shape(self):
        h = freya_wire.free_wire_headers("unit-scope-headers")
        self.assertEqual(h["User-Agent"], "opencode/1.19.0")
        self.assertRegex(h["x-opencode-session"], r"^ses_")
        self.assertRegex(h["x-opencode-request"], r"^msg_")
        self.assertEqual(h["x-opencode-client"], "cli")
        self.assertEqual(h["x-opencode-project"], "global")
        # Request fresco por llamada
        h2 = freya_wire.free_wire_headers("unit-scope-headers")
        self.assertEqual(h["x-opencode-session"], h2["x-opencode-session"])
        self.assertNotEqual(h["x-opencode-request"], h2["x-opencode-request"])


# ---------------------------------------------------------------- tools

class ToolsCase(unittest.TestCase):
    def test_six_core_exact(self):
        tools = freya_tools.responses_core_tools()
        self.assertEqual([t["name"] for t in tools],
                         ["bash", "edit", "glob", "grep", "read", "write"])
        for t in tools:
            self.assertEqual(t["type"], "function")
            self.assertIn("parameters", t)

    def test_ensure_idempotent_and_super(self):
        base = freya_tools.responses_core_tools()
        again = freya_tools.ensure_core_tools(base)
        self.assertEqual(len(again), 6)
        partial = [freya_tools.OPENCODE_TOOL_DEFINITIONS["read"].copy()]
        full = freya_tools.ensure_core_tools(partial)
        self.assertEqual(len(full), 6)
        names = {t["name"] for t in full}
        self.assertEqual(names, set(freya_tools.OPENCODE_CORE_TOOLS))

    def test_anthropic_conversion_keeps_fingerprint(self):
        anth = [{"name": "Read", "description": "r",
                 "input_schema": {"type": "object", "properties": {}}}]
        conv = freya_tools.anthropic_to_responses_tools(anth)
        names = {t["name"] for t in conv}
        for core in freya_tools.OPENCODE_CORE_TOOLS:
            self.assertIn(core, names)
        # La tool de Claude viaja con su nombre + fingerprint
        self.assertIn("Read", names)


# ---------------------------------------------------------------- bridge

class BridgeCase(unittest.TestCase):
    def test_text_input(self):
        items = zen_bridge.anthropic_messages_to_responses_input(
            [{"role": "user", "content": "hola"}])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["role"], "user")

    def test_tool_roundtrip_input(self):
        msgs = [
            {"role": "user", "content": "call read"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "voy"},
                {"type": "tool_use", "id": "toolu_abc123",
                 "name": "read", "input": {"filePath": "/tmp/x"}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_abc123",
                 "content": "MARKER-ZEN-1"}]},
        ]
        items = zen_bridge.anthropic_messages_to_responses_input(msgs)
        kinds = [i["type"] for i in items]
        self.assertIn("function_call", kinds)
        self.assertIn("function_call_output", kinds)
        fc = next(i for i in items if i["type"] == "function_call")
        fco = next(i for i in items if i["type"] == "function_call_output")
        self.assertEqual(fc["call_id"], "toolu_abc123")
        self.assertEqual(fco["call_id"], "toolu_abc123")
        self.assertEqual(fc["name"], "read")

    def test_body_has_gate(self):
        body = {"model": "muse-spark-1.3-contributor-free", "max_tokens": 64,
                "system": "sys", "messages": [{"role": "user", "content": "hi"}],
                "tools": []}
        rbody, scope, amap = zen_bridge.anthropic_to_responses_body(body)
        self.assertEqual(amap, {})
        self.assertEqual(rbody["model"], "muse-spark-1.3-contributor-free")
        self.assertTrue(rbody["stream"])
        self.assertFalse(rbody["store"])
        self.assertIn("sys", rbody["instructions"])
        self.assertIn("placeholders", rbody["instructions"])  # nota anti-placeholder
        self.assertEqual(rbody["tool_choice"], "auto")
        self.assertTrue(scope.startswith("conv-"))
        tools = {t["name"]: t for t in rbody["tools"]}
        for key in ("read", "shell"):
            self.assertIn(key, tools)
            self.assertTrue(zen_fingerprint.is_fingerprint_definition(tools[key], key))

    def test_parse_sse_text_and_call(self):
        sse = (
            'event: response.output_text.delta\n'
            'data: {"type":"response.output_text.delta","delta":"hola "}\n\n'
            'event: response.output_text.delta\n'
            'data: {"type":"response.output_text.delta","delta":"mundo"}\n\n'
            'event: response.output_item.done\n'
            'data: {"type":"response.output_item.done","item":'
            '{"type":"function_call","call_id":"call_xyz1","name":"read",'
            '"arguments":"{\\"filePath\\":\\"/tmp/a\\"}"}}\n\n'
            'event: response.completed\n'
            'data: {"type":"response.completed","response":{"id":"resp_1",'
            '"output":[{"type":"message","content":[{"type":"output_text","text":"hola mundo"}]}],'
            '"usage":{"input_tokens":10,"output_tokens":5}}}\n\n'
        ).encode()
        parsed = zen_bridge.parse_responses_payload(sse, "text/event-stream")
        self.assertIn("hola", parsed["text"])
        self.assertTrue(parsed["saw_done"])
        self.assertTrue(any(c["name"] == "read" for c in parsed["tool_calls"]))
        call = next(c for c in parsed["tool_calls"] if c["name"] == "read")
        self.assertEqual(call["arguments"]["filePath"], "/tmp/a")

    def test_parse_without_completed_not_done(self):
        sse = ('event: response.output_text.delta\n'
               'data: {"type":"response.output_text.delta","delta":"cor"}\n\n'
               ).encode()
        parsed = zen_bridge.parse_responses_payload(sse, "text/event-stream")
        self.assertFalse(parsed["saw_done"])

    def test_alias_restored_in_responses_to_anthropic(self):
        parsed = {"text": "", "tool_calls": [
            {"id": "c1", "name": "read_client", "arguments": {"pattern": "x"}}],
            "usage": {}, "response_id": "r1"}
        msg = zen_bridge.responses_to_anthropic(
            "muse-spark-1.3-contributor-free", parsed,
            alias_map={"read_client": "read"})
        tool = msg["content"][0]
        self.assertEqual(tool["name"], "read")
        self.assertEqual(tool["input"], {"pattern": "x"})

    def test_responses_to_anthropic(self):
        parsed = {"text": "listo MARKER-ZEN-1",
                  "tool_calls": [], "usage": {"input_tokens": 3, "output_tokens": 4}}
        msg = zen_bridge.responses_to_anthropic("muse-spark-1.3-contributor-free",
                                                parsed)
        self.assertEqual(msg["stop_reason"], "end_turn")
        self.assertIn("MARKER-ZEN-1", msg["content"][0]["text"])
        parsed2 = {"text": "", "tool_calls": [
            {"id": "call_1", "name": "read", "arguments": {"filePath": "/tmp/a"}}],
            "usage": {}}
        msg2 = zen_bridge.responses_to_anthropic("muse-spark-1.3-contributor-free",
                                                 parsed2)
        self.assertEqual(msg2["stop_reason"], "tool_use")
        self.assertEqual(len([b for b in msg2["content"] if b["type"] == "tool_use"]), 1)


# ---------------------------------------------------------------- gateway zen vs fake Zen

class FakeZenHandler(BaseHTTPRequestHandler):
    """Mimica Zen /inference/v1 (contrato v2): valida huella + read/shell verbatim."""
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

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            return self._send(400, b'{"error":"bad json"}')
        FakeZenHandler.last_request = {
            "headers": dict(self.headers),
            "body": body,
            "path": self.path,
        }
        # Gate v2 (live-verificado 2026-10-16): Bearer public OBLIGATORIO, UA v2,
        # sesion espejo, stream:true y read/shell VERBATIM en tools (flat).
        # x-opencode-request ausente en la replica (el oficial lo manda y pasa).
        def _h(name):
            for k, v in dict(self.headers).items():
                if str(k).lower() == name:
                    return v
            return ""
        auth = _h("authorization")
        ua = _h("user-agent")
        ses = _h("x-opencode-session")
        sid = _h("x-opencode-session-id")
        if auth != "Bearer public":
            return self._send(403, json.dumps({"type": "error", "error": {
                "type": "FreeTierError", "message": "auth"}}).encode())
        if ua != zen_fingerprint.OPENCODE_UA:
            return self._send(403, json.dumps({"type": "error", "error": {
                "type": "FreeTierError", "message": "UA"}}).encode())
        if not sid or sid != ses:
            return self._send(403, json.dumps({"type": "error", "error": {
                "type": "FreeTierError", "message": "session-id"}}).encode())
        if not re.match(r"^ses_", ses):
            return self._send(403, json.dumps({"type": "error", "error": {
                "type": "FreeTierError", "message": "ids"}}).encode())
        if body.get("stream") is not True:
            return self._send(403, json.dumps({"type": "error", "error": {
                "type": "FreeTierError", "message": "stream"}}).encode())
        tools = {t.get("name"): t for t in body.get("tools") or []
                 if isinstance(t, dict)}
        for key in ("read", "shell"):
            if key not in tools or not zen_fingerprint.is_fingerprint_definition(tools[key], key):
                return self._send(403, json.dumps({"type": "error", "error": {
                    "type": "FreeTierError", "message": f"tools:{key}"}}).encode())
        if body.get("tool_choice") == "none":
            return self._send(403, json.dumps({"type": "error", "error": {
                "type": "FreeTierError", "message": "tool_choice"}}).encode())
        # Decide por el input: si hay function_call_output con marcador, final con eco
        inp = json.dumps(body.get("input") or "")
        if "MARKER-ZEN-1" in inp:
            text = "consumed tool result: MARKER-ZEN-1"
            sse = (
                'event: response.output_text.delta\n'
                f'data: {json.dumps({"type": "response.output_text.delta", "delta": text})}\n\n'
                'event: response.completed\n'
                f'data: {json.dumps({"type": "response.completed", "response": {"id": "resp_fake2", "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}], "usage": {"input_tokens": 7, "output_tokens": 4}}})}\n\n'
            ).encode()
            return self._send(200, sse, "text/event-stream")
        # Si el ultimo user pide call, devuelve un function_call read
        if "call:read" in inp:
            sse = (
                'event: response.output_text.delta\n'
                f'data: {json.dumps({"type": "response.output_text.delta", "delta": "calling read"})}\n\n'
                'event: response.output_item.done\n'
                f'data: {json.dumps({"type": "response.output_item.done", "item": {"type": "function_call", "call_id": "call_fake1", "name": "read", "arguments": json.dumps({"filePath": "/tmp/fake-marker.txt"})}})}\n\n'
                'event: response.completed\n'
                f'data: {json.dumps({"type": "response.completed", "response": {"id": "resp_fake1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "calling read"}]}, {"type": "function_call", "call_id": "call_fake1", "name": "read", "arguments": json.dumps({"filePath": "/tmp/fake-marker.txt"})}], "usage": {"input_tokens": 5, "output_tokens": 6}}})}\n\n'
            ).encode()
            return self._send(200, sse, "text/event-stream")
        text = "fake zen reply"
        sse = (
            'event: response.output_text.delta\n'
            f'data: {json.dumps({"type": "response.output_text.delta", "delta": text})}\n\n'
            'event: response.completed\n'
            f'data: {json.dumps({"type": "response.completed", "response": {"id": "resp_fake0", "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}], "usage": {"input_tokens": 4, "output_tokens": 3}}})}\n\n'
        ).encode()
        return self._send(200, sse, "text/event-stream")


class GatewayZenCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeZenHandler)
        cls.fake.daemon_threads = True
        cls.fake_port = cls.fake.server_address[1]
        cls.fake_thread = threading.Thread(target=cls.fake.serve_forever, daemon=True)
        cls.fake_thread.start()
        fake_base = f"http://127.0.0.1:{cls.fake_port}"
        cls.server = build_server(0, "zen", fake_base, "")
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.fake.shutdown()
        cls.fake.server_close()

    def test_zen_text(self):
        s, o = post(self.base, "/v1/messages",
                    {"model": "muse-spark-1.3-contributor-free", "max_tokens": 64,
                     "messages": [{"role": "user", "content": "hola zen"}]})
        self.assertEqual(s, 200, o)
        texts = [b.get("text", "") for b in o.get("content", []) if b.get("type") == "text"]
        self.assertTrue(any("fake zen reply" in t for t in texts), texts)
        # El fake valido la huella v2: si hubiera faltado, 403
        last = FakeZenHandler.last_request
        low = {str(k).lower(): v for k, v in last["headers"].items()}
        self.assertEqual(str(low.get("user-agent", "")), zen_fingerprint.OPENCODE_UA)
        self.assertRegex(str(low.get("x-opencode-session", "")), r"^ses_")
        self.assertEqual(str(low.get("x-opencode-session-id", "")),
                          str(low.get("x-opencode-session", "")))
        self.assertEqual(str(low.get("authorization", "")), "Bearer public")
        self.assertNotIn("x-opencode-request", low)
        self.assertTrue(last["body"].get("stream"))
        self.assertTrue(last["path"].endswith("/responses"))

    def test_zen_tool_roundtrip_marker(self):
        s, o = post(self.base, "/v1/messages",
                    {"model": "muse-spark-1.3-contributor-free", "max_tokens": 64,
                     "messages": [{"role": "user", "content": "call:read x"}]})
        self.assertEqual(s, 200, o)
        uses = [b for b in o.get("content", []) if b.get("type") == "tool_use"]
        self.assertEqual(len(uses), 1)
        self.assertEqual(uses[0]["name"], "Read")  # placeholder normalizado a CC
        self.assertEqual(uses[0]["input"], {"file_path": "/tmp/fake-marker.txt"})
        hist = [{"role": "user", "content": "call:read x"},
                {"role": "assistant", "content": o["content"]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": uses[0]["id"],
                     "content": "MARKER-ZEN-1"}]}]
        s2, o2 = post(self.base, "/v1/messages",
                      {"model": "muse-spark-1.3-contributor-free",
                       "max_tokens": 64, "messages": hist})
        self.assertEqual(s2, 200, o2)
        final = " ".join(b.get("text", "") for b in o2.get("content", [])
                         if b.get("type") == "text")
        self.assertIn("MARKER-ZEN-1", final)

    def test_zen_rejects_bad_passthrough_guard(self):
        # build_server debe rechazar passthrough directo a Zen
        with self.assertRaises(SystemExit):
            build_server(0, "passthrough", "https://opencode.ai/zen/v1", "k")


if __name__ == "__main__":
    unittest.main(verbosity=2)
