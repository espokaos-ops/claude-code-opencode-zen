# TESTS — claude-code-local-gateway

Suite: `tests/test_gateway.py` + `tests/test_zen_bridge.py` +
`tests/test_fingerprint.py` + `tests/test_zen_chat.py`, stdlib `unittest`
(sin pytest), loopback, sin credenciales, sin red externa salvo probe vivo
documentado. Arranque: `python3 -m unittest discover -s tests`.

| # | test | qué prueba | resultado 2026-10-15 |
|---|---|---|---|
| 1 | `test_health` | `GET /health` → 200 `status ok` | OK |
| 2 | `test_text_conversation` | texto + `stop_reason end_turn` + turno | OK |
| 3 | `test_single_tool_roundtrip` | `tool_use read` (id `toolu_*`) → `tool_result MARKER-ABC-123` → final cita el marcador | OK |
| 4 | `test_multi_tool` | 2 `tool_use` (ids distintos, `read`+`glob`) → 2 results → final con `A-1`+`B-2` | OK |
| 5 | `test_streaming_sequence` | orden SSE + reensamblado `input_json` con `filePath` | OK |
| 6 | `test_error_mapping` | `error:500` → HTTP 500 envelope `api_error`; request inválido → 400 `invalid_request_error` | OK |
| 7 | `test_session_continuity` | 3 turnos con historial (turn 1→2→3) + sesión B independiente en 1 | OK |
| 8 | `test_interruption_server_survives` | cierre mid-stream + `/health` sigue 200 | OK |
| 9-13 | wire/tools/bridge | IDs `ses_/msg_`, sesión/scope estables, 6 core exactas, input round-trip, body con gate, parse SSE, `responses_to_anthropic` | OK (13/13 en `test_zen_bridge` sin gateway) |
| 14-16 | gateway-zen vs fake Zen | texto + huella validada; `tool_use read` → `MARKER-ZEN-1` → final; guard rechaza passthrough→Zen | OK |

Total 2026-10-16: **66/66 OK** (`Ran 66 tests ... OK`).

| # | test (Fase 4/5) | qué prueba | resultado |
|---|---|---|---|
| 17-24 | gateway-zen relay v2 | normalizacion, hoist system, nonstream, alias collision, 403 sin transformar, /v1/models, truncamiento→`event: error`, muse SSE bien formado | OK |
| 25-30 | `test_fingerprint` | contrato v2, `saw_message_stop`, sesion/headers, ensamblado | OK |
| 31-42 | `test_zen_bridge` | wire, 6 core, bridge Responses, parseo SSE | OK |
| 43-49 | `test_zen_chat` (nuevo) | conversion chat (tools/role tool/nota), parser de deltas, placeholder, JSON completo | OK |
| 50-66 | gateway chat (nuevo) | routing beam-free→`/chat/completions`, roundtrip Read, nonstream, 403, truncamiento chat | OK |


Hallazgo de entorno (resuelto): el shell hereda `HTTP_PROXY` sin `NO_PROXY`,
y urllib mandaba el loopback a Privoxy (`500 Internal Privoxy Error`). Fix solo
en nuestro código: opener sin proxy en el proceso de tests y
`curl --noproxy '*'` en `bin/claude-gateway` (loopback jamás al proxy, como
Claude Code). WARP/Privoxy intactos.

Comandos de daemon verificados: `start` (health-poll OK, pid), `status`,
`doctor` (python/claude/warp/proxy/puertos/health), `stop` (puerto liberado).
`~/.claude/settings.json` intacto (`theme:dark`), WARP `Connected` antes y después.

Vivo contra Zen real (2026-10-15, documentado): tanto el port como Hermes
original dan `403 FreeTierError`; el gateway-zen lo propaga sin modificar
(ver `CAMBIOS-Y-ACTIVACION.md` §5). End-to-end operativo contra fake Zen
Responses compatible (huella + 6 core + `MARKER-ZEN-1`).
