#!/usr/bin/env python3
"""Tests del contrato v2 (zen_fingerprint): IDs, pase de request y SSE.

Sin red. Los hashes verbatim anclan las definiciones read/shell al contrato
live-verificado 2026-10-16 (probe P2b): si alguien edita una coma, falla.
"""
import hashlib
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import zen_fingerprint as zf  # noqa: E402


def frames_of(raw: str) -> list[bytes]:
    return zf.split_sse_frames(raw.encode())


def chunks_text(chunks: list[bytes]) -> str:
    return b"".join(chunks).decode()


class VerbatimCase(unittest.TestCase):
    """Las definiciones deben ser byte-exactas al contrato (P2b/9router)."""

    EXPECTED = {
        "read": (
            "e6ecb6c162129bb9af6662e49fe1bf8c717fe73fce0b70231426355f364a0fc8",
            "957f3d1e6e1d7599fcb041546e76a86408faf56c7cf42c198cd33a891cf5c104",
        ),
        "shell": (
            "bfffd5c105ef6460d76c72105b3f257f5d97fded792a83c27ac0c5389a0ff6db",
            "e57865231606bd2f85cd2030df37c88262c762732ee5e92ce2886e4b0b066b24",
        ),
    }

    def test_hashes(self):
        for key, (dhash, phash) in self.EXPECTED.items():
            defn = zf.FINGERPRINT_TOOL_DEFINITIONS[key]
            self.assertEqual(hashlib.sha256(defn["description"].encode()).hexdigest(),
                             dhash, key)
            self.assertEqual(hashlib.sha256(zf._canon(defn["parameters"]).encode()).hexdigest(),
                             phash, key)

    def test_shapes(self):
        a = zf.anthropic_tool_def("read")
        self.assertEqual(set(a), {"name", "description", "input_schema"})
        self.assertEqual(a["input_schema"]["required"], ["path"])
        self.assertFalse(a["input_schema"]["additionalProperties"])
        f = zf.flat_tool_def("shell")
        self.assertEqual(f["type"], "function")
        self.assertFalse(f["strict"])
        self.assertEqual(f["parameters"]["required"], ["command"])

    def test_is_fingerprint_definition(self):
        self.assertTrue(zf.is_fingerprint_definition(zf.anthropic_tool_def("read"), "read"))
        self.assertTrue(zf.is_fingerprint_definition(zf.flat_tool_def("shell"), "shell"))
        fake = {"name": "read", "description": "x", "input_schema": {"type": "object"}}
        self.assertFalse(zf.is_fingerprint_definition(fake, "read"))
        self.assertFalse(zf.is_fingerprint_definition({"name": "Read"}, "read"))


class SessionIdCase(unittest.TestCase):
    def test_shape_and_counter(self):
        sid = zf.new_opencode_id("ses")
        self.assertRegex(sid, r"^ses_[0-9a-f]{12}[0-9A-Za-z]{14}$")
        counter = zf.id_counter_of(sid)
        self.assertGreaterEqual(counter, 1)
        self.assertLessEqual(counter, 16)
        self.assertNotEqual(sid, zf.new_opencode_id("ses"))

    def test_counter_decodes_back_timestamp(self):
        import time
        ms_before = int(time.time() * 1000)
        sid = zf.new_opencode_id("ses")
        ms_after = int(time.time() * 1000)
        hex_part = sid.split("_", 1)[1][:12]
        value = (~int(hex_part, 16)) & ((1 << 48) - 1)
        ms_mod = value >> 12  # low-48 bits de ms<<12+counter: quedan 36 bits de ms
        mask36 = (1 << 36) - 1
        now_mod = ms_before & mask36
        # tolera cruce de frontera de ms entre las dos lecturas
        self.assertTrue(ms_mod in (now_mod, (ms_before + 5) & mask36, (ms_after) & mask36),
                        (ms_mod, now_mod))

    def test_session_stable_per_scope(self):
        a = zf.session_for_scope("scope-unit-1")
        b = zf.session_for_scope("scope-unit-1")
        c = zf.session_for_scope("scope-unit-2")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_headers_shape(self):
        h = zf.zen_headers("scope-headers")
        self.assertEqual(h["user-agent"].split("/")[0], "opencode")
        self.assertEqual(len(h["user-agent"].split("/")), 4)  # v2: channel/version/client
        self.assertEqual(h["x-opencode-client"], "cli")
        self.assertEqual(h["authorization"], "Bearer public")
        self.assertEqual(h["x-opencode-session"], h["x-opencode-session-id"])
        self.assertNotIn("x-opencode-request", h)


class ToolPatchCase(unittest.TestCase):
    def test_appends_when_missing_with_note(self):
        body = {"model": "m", "messages": [{"role": "user", "content": "hi"}],
                "system": "base", "tools": [{"name": "Read",
                                             "description": "cc", "input_schema": {"type": "object"}}]}
        amap = zf.apply_fingerprint_tools(body, style="anthropic")
        self.assertEqual(amap, {})
        names = [t["name"] for t in body["tools"]]
        self.assertIn("read", names)
        self.assertIn("shell", names)
        self.assertTrue(zf.is_fingerprint_definition(
            next(t for t in body["tools"] if t["name"] == "read"), "read"))
        self.assertIn("placeholders", body["system"])
        self.assertIn("`read` or `shell`", body["system"])

    def test_no_duplicate_when_verbatim_present(self):
        body = {"model": "m", "messages": [],
                "tools": [zf.anthropic_tool_def("read")]}
        zf.apply_fingerprint_tools(body, style="anthropic")
        names = [t["name"] for t in body["tools"]]
        self.assertEqual(names.count("read"), 1)
        self.assertIn("shell", names)
        self.assertIn("`shell`", body.get("system", ""))

    def test_note_single_placeholder_wording(self):
        body = {"model": "m", "messages": [], "system": None,
                "tools": [zf.anthropic_tool_def("read")]}
        zf.apply_fingerprint_tools(body, style="anthropic")
        self.assertIn("`shell` tool; it is a placeholder", body["system"])

    def test_alias_conflicting_client_tool(self):
        body = {"model": "m",
                "messages": [{"role": "user", "content": "hi"},
                             {"role": "assistant", "content": [
                                 {"type": "tool_use", "id": "tu_1", "name": "read",
                                  "input": {"file": "x"}}]}],
                "tools": [{"name": "read", "description": "client own read",
                           "input_schema": {"type": "object"}}],
                "tool_choice": {"type": "tool", "name": "read"}}
        amap = zf.apply_fingerprint_tools(body, style="anthropic")
        self.assertEqual(amap, {"read_client": "read"})
        names = [t["name"] for t in body["tools"]]
        self.assertIn("read_client", names)
        self.assertIn("read", names)
        self.assertEqual(body["tool_choice"]["name"], "read_client")
        hist_call = body["messages"][1]["content"][0]
        self.assertEqual(hist_call["name"], "read_client")

    def test_tool_choice_none_never(self):
        for tc in ("none", {"type": "none"}):
            body = {"model": "m", "messages": [], "tools": [], "tool_choice": tc}
            zf.apply_fingerprint_tools(body, style="anthropic")
            self.assertNotEqual(body["tool_choice"], "none")
            self.assertNotEqual(body["tool_choice"], {"type": "none"})

    def test_flat_style_sets_auto_and_instructions_note(self):
        body = {"model": "muse-spark-1.3-contributor-free", "input": [],
                "tools": [], "instructions": "sys"}
        zf.apply_fingerprint_tools(body, style="flat")
        self.assertEqual(body["tool_choice"], "auto")
        self.assertIn("placeholders", body["instructions"])
        names = [t["name"] for t in body["tools"]]
        self.assertEqual(names, ["read", "shell"])
        self.assertTrue(zf.is_fingerprint_definition(body["tools"][0], "read"))

    def test_force_stream(self):
        body = {"stream": False}
        zf.force_stream(body)
        self.assertTrue(body["stream"])


class HoistCase(unittest.TestCase):
    """CC 2.1.299 manda role:"system" dentro de messages; se mueve a system."""

    def test_midstream_system_hoisted_to_system_field(self):
        body = {"model": "m",
                "system": [{"type": "text", "text": "base"}],
                "messages": [{"role": "user", "content": "hi"},
                             {"role": "system", "content": [
                                 {"type": "text", "text": "ENV PROMPT"}]},
                             {"role": "assistant", "content": "ok"}]}
        stats = zf.hoist_system_messages(body)
        self.assertEqual(stats, {"hoisted": 1, "coerced": 0, "merged": 0})
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles, ["user", "assistant"])
        texts = [b["text"] for b in body["system"]]
        self.assertEqual(texts[-1], "ENV PROMPT")

    def test_string_system_and_coercion_and_merge(self):
        body = {"model": "m", "system": "base",
                "messages": [{"role": "user", "content": "a"},
                             {"role": "system", "content": "S"},
                             {"role": "tool", "content": "b"},
                             {"role": "user", "content": "c"}]}
        stats = zf.hoist_system_messages(body)
        self.assertEqual(stats["hoisted"], 1)
        self.assertEqual(stats["coerced"], 1)
        # tool->user se fusiona con el user siguiente; luego "a"+"b"+"c"
        self.assertEqual(stats["merged"], 2)
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles, ["user"])
        self.assertEqual(body["system"], [{"type": "text", "text": "base"},
                                          {"type": "text", "text": "S"}])
        merged = body["messages"][0]["content"]
        self.assertEqual([b["text"] for b in merged], ["a", "b", "c"])

    def test_no_system_message_is_noop(self):
        body = {"model": "m", "messages": [
            {"role": "user", "content": "x"},
            {"role": "assistant", "content": "y"}]}
        stats = zf.hoist_system_messages(body)
        self.assertEqual(stats, {"hoisted": 0, "coerced": 0, "merged": 0})
        self.assertEqual([m["role"] for m in body["messages"]], ["user", "assistant"])


class NormalizerCase(unittest.TestCase):
    def _upstream_read_block(self, args_json: str, name: str = "read") -> list[bytes]:
        raw = (
            "event: content_block_start\n"
            f'data: {json.dumps({"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "tu_1", "name": name, "input": {}}})}\n\n'
            "event: content_block_delta\n"
            f'data: {json.dumps({"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": args_json}})}\n\n'
            "event: content_block_stop\n"
            f'data: {json.dumps({"type": "content_block_stop", "index": 0})}\n\n'
        )
        return frames_of(raw)

    def _forwarded(self, out: list[bytes]) -> list[tuple[str, dict]]:
        parsed = []
        for c in out:
            ev, data = zf._parse_frame(c)
            parsed.append((ev, data))
        return parsed

    def test_read_becomes_Read_with_file_path(self):
        norm = zf.AnthropicSSENormalizer()
        out: list[bytes] = []
        for f in self._upstream_read_block('{"path": "/etc", "limit": 10}'):
            out.extend(norm.feed_frame(f))
        out.extend(norm.finish())
        events = self._forwarded(out)
        self.assertEqual([e for e, _ in events],
                         ["content_block_start", "content_block_delta",
                          "content_block_stop"])
        self.assertEqual(events[0][1]["content_block"]["name"], "Read")
        args = json.loads(events[1][1]["delta"]["partial_json"])
        self.assertEqual(args, {"file_path": "/etc", "limit": 10})

    def test_shell_becomes_Bash(self):
        norm = zf.AnthropicSSENormalizer()
        args = '{"command": "ls", "workdir": "/tmp", "background": true, "timeout": 0}'
        out = []
        for f in self._upstream_read_block(args, name="shell"):
            out.extend(norm.feed_frame(f))
        events = self._forwarded(out)
        self.assertEqual(events[0][1]["content_block"]["name"], "Bash")
        args_norm = json.loads(events[1][1]["delta"]["partial_json"])
        self.assertEqual(args_norm["command"], "cd /tmp && ls")
        self.assertTrue(args_norm["run_in_background"])
        self.assertNotIn("timeout", args_norm)  # timeout 0 se descarta

    def test_alias_restores_client_name(self):
        norm = zf.AnthropicSSENormalizer(alias_map={"read_client": "read"})
        out = []
        for f in self._upstream_read_block('{"x": 1}', name="read_client"):
            out.extend(norm.feed_frame(f))
        text = chunks_text(out)
        self.assertIn('"name":"read"', text)
        self.assertIn('"partial_json"', text)  # deltas del cliente pasan intactos

    def test_saw_message_stop_flag(self):
        norm = zf.AnthropicSSENormalizer()
        norm.feed_frame(b'event: message_start\ndata: {"type":"message_start"}')
        self.assertFalse(norm.saw_message_stop)
        norm.feed_frame(b'event: message_stop\ndata: {"type":"message_stop"}')
        self.assertTrue(norm.saw_message_stop)

    def test_text_and_ping_passthrough(self):
        raw = (
            "event: content_block_start\n"
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
            "event: content_block_delta\n"
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hola"}}\n\n'
            "event: ping\n"
            'data: {"type":"ping"}\n\n'
        )
        norm = zf.AnthropicSSENormalizer()
        out = []
        for f in frames_of(raw):
            out.extend(norm.feed_frame(f))
        text = chunks_text(out)
        self.assertIn("text_delta", text)
        self.assertIn("ping", text)

    def test_assemble_message(self):
        raw = (
            "event: message_start\n"
            'data: {"type":"message_start","message":{"id":"msg_1","type":"message","role":"assistant","model":"m","content":[],"usage":{"input_tokens":5}}}\n\n'
            + ""
            "event: content_block_start\n"
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
            "event: content_block_delta\n"
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hola"}}\n\n'
            "event: content_block_stop\n"
            'data: {"type":"content_block_stop","index":0}\n\n'
            "event: content_block_start\n"
            'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"tu_2","name":"Read","input":{}}}\n\n'
            "event: content_block_delta\n"
            'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"file_path\\": \\"/tmp/a\\"}"}}\n\n'
            "event: content_block_stop\n"
            'data: {"type":"content_block_stop","index":1}\n\n'
            "event: message_delta\n"
            'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":7}}\n\n'
        )
        norm = zf.AnthropicSSENormalizer()
        chunks = []
        for f in frames_of(raw):
            chunks.extend(norm.feed_frame(f))
        msg = zf.assemble_message(chunks)
        self.assertEqual(msg["id"], "msg_1")
        self.assertEqual(msg["stop_reason"], "tool_use")
        self.assertEqual(msg["content"][0]["text"], "hola")
        self.assertEqual(msg["content"][1]["name"], "Read")
        self.assertEqual(msg["content"][1]["input"], {"file_path": "/tmp/a"})
        self.assertEqual(msg["usage"]["output_tokens"], 7)

    def test_feed_line_stream(self):
        raw = (
            "event: message_start\n"
            'data: {"type":"message_start","message":{"id":"msg_9","role":"assistant","content":[]}}\n\n'
            "event: message_stop\n"
            'data: {"type":"message_stop"}\n\n'
        )
        norm = zf.AnthropicSSENormalizer()
        out = []
        for line in raw.encode().splitlines(keepends=True):
            out.extend(norm.feed_line(line))
        self.assertIn('"message_stop"', chunks_text(out))


if __name__ == "__main__":
    unittest.main(verbosity=2)
