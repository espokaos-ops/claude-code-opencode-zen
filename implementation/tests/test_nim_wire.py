#!/usr/bin/env python3
"""Pruebas unitarias de nim_wire (traduccion Anthropic <-> NVIDIA NIM).

Sin red, sin credenciales, sin imports de Hermes.
"""
import json
import os
import unittest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import nim_wire  # noqa: E402

MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"


class TestAnthropicToNIM(unittest.TestCase):
    def test_texto_simple(self):
        body = {"model": MODEL, "max_tokens": 64,
                "messages": [{"role": "user", "content": "hola"}]}
        nim = nim_wire.anthropic_to_nim(body, MODEL)
        self.assertEqual(nim["model"], MODEL)
        self.assertEqual(nim["stream"], False)
        self.assertEqual(nim["max_tokens"], 64)
        self.assertEqual(nim["messages"], [{"role": "user", "content": "hola"}])
        self.assertNotIn("tools", nim)

    def test_system_se_hoistea(self):
        body = {"model": MODEL, "max_tokens": 64,
                "messages": [{"role": "system", "content": "Eres util"},
                             {"role": "user", "content": "dime algo"}]}
        nim = nim_wire.anthropic_to_nim(body, MODEL)
        self.assertEqual(nim["messages"][0],
                         {"role": "system", "content": "Eres util"})
        self.assertEqual(nim["messages"][1], {"role": "user", "content": "dime algo"})

    def test_tools_se_convierten_a_funciones(self):
        body = {"model": MODEL, "max_tokens": 64,
                "messages": [{"role": "user", "content": "lee"}],
                "tools": [{"name": "read", "description": "leer archivo",
                           "input_schema": {"type": "object",
                                            "properties": {"path": {}}}}],
                "tool_choice": "required"}
        nim = nim_wire.anthropic_to_nim(body, MODEL)
        self.assertEqual(len(nim["tools"]), 1)
        f = nim["tools"][0]["function"]
        self.assertEqual(f["name"], "read")
        self.assertEqual(f["description"], "leer archivo")
        self.assertEqual(f["parameters"], {"type": "object",
                                           "properties": {"path": {}}})
        self.assertEqual(nim["tool_choice"], "required")

    def test_tool_result_de_usuario_se_separa_en_role_tool(self):
        body = {"model": MODEL, "max_tokens": 64,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "procesalo"},
                    {"type": "tool_result", "tool_use_id": "call_1",
                     "content": "resultado-a"},
                ]}]}
        nim = nim_wire.anthropic_to_nim(body, MODEL)
        self.assertEqual(nim["messages"][0], {"role": "user",
                                              "content": "procesalo"})
        self.assertEqual(nim["messages"][1],
                         {"role": "tool", "tool_call_id": "call_1",
                          "content": "resultado-a"})

    def test_bloque_de_imagen_se_convierte_a_data_uri(self):
        body = {"model": MODEL, "max_tokens": 64,
                "messages": [{"role": "user", "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png",
                        "data": "abc123"}},
                    {"type": "text", "text": "dime"},
                ]}]}
        nim = nim_wire.anthropic_to_nim(body, MODEL)
        content = nim["messages"][0]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "dime"})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertEqual(content[1]["image_url"]["url"],
                         "data:image/png;base64,abc123")

    def test_assistant_con_tool_use_se_convierte_a_tool_calls(self):
        body = {"model": MODEL, "max_tokens": 64,
                "messages": [{"role": "assistant", "content": [
                    {"type": "text", "text": "voy a leer"},
                    {"type": "tool_use", "id": "tu_1", "name": "read",
                     "input": {"filePath": "/tmp/x.txt"}},
                ]}]}
        nim = nim_wire.anthropic_to_nim(body, MODEL)
        msg = nim["messages"][0]
        self.assertEqual(msg["content"], "voy a leer")
        self.assertEqual(len(msg["tool_calls"]), 1)
        tc = msg["tool_calls"][0]
        self.assertEqual(tc["id"], "tu_1")
        self.assertEqual(tc["type"], "function")
        self.assertEqual(tc["function"]["name"], "read")
        self.assertEqual(json.loads(tc["function"]["arguments"]),
                         {"filePath": "/tmp/x.txt"})


class TestParseNIM(unittest.TestCase):
    def test_texto(self):
        raw = json.dumps({"id": "cmpl_1", "model": MODEL,
                          "choices": [{"index": 0,
                                       "message": {"role": "assistant",
                                                   "content": "hola mundo"},
                                       "finish_reason": "stop"}],
                          "usage": {"prompt_tokens": 3, "completion_tokens": 2,
                                    "total_tokens": 5}}).encode()
        parsed = nim_wire.parse_nim_payload(raw)
        self.assertEqual(parsed["model"], MODEL)
        self.assertEqual(parsed["blocks"],
                         [{"type": "text", "text": "hola mundo"}])
        self.assertEqual(parsed["stop_reason"], "end_turn")
        self.assertEqual(parsed["finish_reason"], "stop")

    def test_tool_calls(self):
        raw = json.dumps({"id": "cmpl_2", "model": MODEL,
                          "choices": [{"index": 0,
                                       "message": {"role": "assistant",
                                                   "content": None,
                                                   "tool_calls": [
                                                       {"id": "tc_1", "type": "function",
                                                        "function": {
                                                            "name": "read",
                                                            "arguments": '{"path": "/tmp/a"}'}}]},
                                       "finish_reason": "tool_calls"}]}).encode()
        parsed = nim_wire.parse_nim_payload(raw)
        self.assertEqual(parsed["stop_reason"], "tool_use")
        self.assertEqual(len(parsed["blocks"]), 1)
        b = parsed["blocks"][0]
        self.assertEqual(b["type"], "tool_use")
        self.assertEqual(b["id"], "tc_1")
        self.assertEqual(b["name"], "read")
        self.assertEqual(b["input"], {"path": "/tmp/a"})

    def test_error_de_nim_es_valor_invalido(self):
        raw = json.dumps({"error": {"message": "rate limited"}}).encode()
        with self.assertRaises(ValueError):
            nim_wire.parse_nim_payload(raw)

    def test_sin_choices_es_valor_invalido(self):
        raw = json.dumps({"id": "cmpl_3", "model": MODEL,
                          "choices": []}).encode()
        with self.assertRaises(ValueError):
            nim_wire.parse_nim_payload(raw)


class TestNimToAnthropic(unittest.TestCase):
    def test_conversion_completa(self):
        parsed = {"model": MODEL, "blocks": [
            {"type": "text", "text": "respuesta"},
            {"type": "tool_use", "id": "tu_9", "name": "read",
             "input": {"filePath": "/tmp/a"}},
        ], "stop_reason": "tool_use", "finish_reason": "tool_calls",
            "id": "cmpl_x", "usage": {"prompt_tokens": 2, "completion_tokens": 3,
                                      "total_tokens": 5}}
        msg = nim_wire.nim_to_anthropic(MODEL, parsed, max_tokens=128)
        self.assertEqual(msg["type"], "message")
        self.assertEqual(msg["role"], "assistant")
        self.assertEqual(msg["model"], MODEL)
        self.assertEqual(msg["content"], parsed["blocks"])
        self.assertEqual(msg["stop_reason"], "tool_use")
        self.assertEqual(msg["usage"]["input_tokens"], 2)
        self.assertEqual(msg["usage"]["output_tokens"], 3)
        self.assertTrue(msg["id"].startswith("msg_nim_"))

    def test_sin_usage_estima(self):
        parsed = {"model": MODEL, "blocks": [{"type": "text",
                                              "text": "un texto de prueba largo"}],
                  "stop_reason": "end_turn", "finish_reason": "stop"}
        msg = nim_wire.nim_to_anthropic(MODEL, parsed)
        self.assertGreaterEqual(msg["usage"]["input_tokens"], 1)
        self.assertGreaterEqual(msg["usage"]["output_tokens"], 1)


class TestPostNIM(unittest.TestCase):
    def test_inaccesible_devuelve_502_sin_lanzar(self):
        status, raw, hdrs = nim_wire.post_nim({"model": MODEL}, "",
                                              "http://127.0.0.1:1", timeout=2)
        self.assertEqual(status, 502)
        obj = json.loads(raw)
        self.assertEqual(obj["error"]["type"], "api_error")
        self.assertIsInstance(hdrs, dict)
        self.assertIn("content-type", hdrs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
