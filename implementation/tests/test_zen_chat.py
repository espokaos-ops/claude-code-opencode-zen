"""Tests del puente chat.completions (zen_chat, Fase 5)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import zen_chat  # noqa: E402
from zen_fingerprint import is_fingerprint_definition  # noqa: E402


class ChatConversionCase(unittest.TestCase):
    def cc_body(self, messages=None):
        return {"model": "beam-free", "max_tokens": 128,
                "system": [{"type": "text", "text": "eres CC"}],
                "messages": messages or [{"role": "user", "content": "hola"}],
                "tools": [{"name": "Read", "description": "cc",
                           "input_schema": {"type": "object"}},
                          {"name": "Bash", "description": "cc",
                           "input_schema": {"type": "object"}}]}

    def test_body_chat_shape_with_fingerprint(self):
        cbody, scope = zen_chat.anthropic_to_chat_body(self.cc_body())
        self.assertTrue(scope)
        self.assertTrue(cbody["stream"])
        self.assertEqual(cbody["max_tokens"], 128)
        self.assertEqual(cbody["messages"][0]["role"], "system")
        self.assertIn("eres CC", cbody["messages"][0]["content"])
        # nota anti-placeholder del fingerprint (read/shell se agregaron)
        self.assertIn("Do not call", cbody["messages"][0]["content"])
        by = {((t or {}).get("function") or {}).get("name"): t
              for t in cbody["tools"]}
        self.assertTrue(is_fingerprint_definition(by["read"], "read"))
        self.assertTrue(is_fingerprint_definition(by["shell"], "shell"))
        self.assertIn("Read", by)  # tool del cliente intacta

    def test_history_tool_result_split_to_role_tool(self):
        messages = [
            {"role": "user", "content": "lee /tmp/x"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "leo"},
                {"type": "tool_use", "id": "tu_1", "name": "Read",
                 "input": {"file_path": "/tmp/x"}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tu_1",
                 "content": [{"type": "text", "text": "contenido X"}]},
                {"type": "text", "text": "gracias"}]},
        ]
        out = zen_chat.anthropic_messages_to_chat(messages)
        roles = [m["role"] for m in out]
        self.assertEqual(roles, ["user", "assistant", "tool", "user"])
        call = out[1]["tool_calls"][0]
        self.assertEqual(call["function"]["name"], "Read")
        self.assertEqual(json.loads(call["function"]["arguments"]),
                         {"file_path": "/tmp/x"})
        self.assertEqual(out[2]["tool_call_id"], "tu_1")
        self.assertEqual(out[2]["content"], "contenido X")
        self.assertEqual(out[3]["content"], "gracias")

    def test_parse_chat_sse_accumulates_arguments(self):
        sse = (
            'data: {"id":"c1","choices":[{"index":0,"delta":{"role":"assistant"}}],"usage":null}\n\n'
            'data: {"id":"c1","choices":[{"index":0,"delta":{"content":"ho"}}],"usage":null}\n\n'
            'data: {"id":"c1","choices":[{"index":0,"delta":{"content":"la"}}],"usage":null}\n\n'
            'data: {"id":"c1","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_1",'
            '"function":{"name":"read","arguments":"{\\"path\\": "}}]}}],"usage":null}\n\n'
            'data: {"id":"c1","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,'
            '"function":{"arguments":"\\"/tmp/y\\"}"}}]},"finish_reason":"tool_calls"}],"usage":null}\n\n'
            'data: {"id":"c1","choices":[],"usage":{"prompt_tokens":5,"completion_tokens":6}}\n\n'
            "data: [DONE]\n\n"
        ).encode()
        parsed = zen_chat.parse_chat_payload(sse, "text/event-stream")
        self.assertEqual(parsed["text"], "hola")
        self.assertEqual(parsed["response_id"], "c1")
        self.assertEqual(parsed["finish_reason"], "tool_calls")
        call = parsed["tool_calls"][0]
        self.assertEqual(call["id"], "call_1")
        self.assertEqual(call["name"], "read")
        self.assertEqual(call["arguments"], {"path": "/tmp/y"})
        self.assertEqual(parsed["usage"]["prompt_tokens"], 5)

    def test_to_anthropic_restores_placeholder_names(self):
        parsed = {"text": "", "tool_calls": [
            {"id": "call_1", "name": "read",
             "arguments": {"path": "/tmp/z"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3},
            "finish_reason": "tool_calls", "response_id": "c1"}
        msg = zen_chat.chat_to_anthropic("beam-free", parsed)
        self.assertEqual(msg["stop_reason"], "tool_use")
        tool = msg["content"][0]
        self.assertEqual(tool["name"], "Read")
        self.assertEqual(tool["input"], {"file_path": "/tmp/z"})
        self.assertEqual(msg["usage"], {"input_tokens": 2, "output_tokens": 3})

    def test_error_json_passthrough(self):
        raw = json.dumps({"type": "error", "error": {
            "type": "FreeTierError", "message": "no"}}).encode()
        parsed = zen_chat.parse_chat_payload(raw, "application/json")
        self.assertEqual(parsed["error"]["type"], "FreeTierError")

    def test_full_json_response_parse(self):
        raw = json.dumps({"id": "c9", "choices": [{"index": 0, "message": {
            "role": "assistant", "content": "ok",
            "tool_calls": [{"id": "call_9", "type": "function",
                            "function": {"name": "shell",
                                         "arguments": "{\"command\": \"ls\"}"}}]},
            "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2}}).encode()
        parsed = zen_chat.parse_chat_payload(raw, "application/json")
        self.assertEqual(parsed["text"], "ok")
        self.assertEqual(parsed["tool_calls"][0]["name"], "shell")
        self.assertEqual(parsed["tool_calls"][0]["arguments"], {"command": "ls"})


if __name__ == "__main__":
    unittest.main()
