# Port Freya-Hermes → Claude-Code: cambios y activación (2026-10-15)

> NOTA (2026-10-16): este documento es historico (fases 0.2.x). El estado
> operativo actual (0.4.0: wire v2 aceptado, routing de 3 protocolos y E2E
> con Claude Code real) esta en README.md §7-8 y /tmp/opencode/probes/PHASE5-MATRIX.md.

## 0. Resumen honesto

* `DEMOSTRADO`: port completo del transformer Freya-Hermes a Claude-Code como
  upstream `zen` (Messages↔Responses + wire free-tier + 6 core), con suite
  **24/24 OK** (8 preexistentes intactos + 16 nuevos) y daemon verificado.
* `DEMOSTRADO`: el wire emitido es fiel al original (mismos headers, mismos IDs
  `ses_*`/`msg_*`, mismas 6 tools, `stream:true`, `Bearer public`).
* `DEMOSTRADO` (bloqueo del proveedor, no del código): hoy 2026-10-15 tanto el
  port como **el transformer original de Hermes** reciben
  `HTTP 403 FreeTierError "can only be used from within OpenCode"` ante
  `POST https://opencode.ai/zen/v1/responses` con `muse-spark-1.3-contributor-free`.
  El gateway devuelve ese 403 sin modificar. Operativo end-to-end contra
  endpoint Responses compatible (fake local en tests); **bloqueado en vivo por
  el proveedor**, igual que Hermes hoy.
* No se modificó el transformer original. Solo se leyó. Todo el trabajo vive en
  `~/workspace/Transformers/Claude-Code/`.

## 1. Origen (solo lectura, sin modificar)

| Pieza Hermes | Ruta real | Qué se reutilizó |
|---|---|---|
| Wire free-tier | `~/.hermes/hermes-agent/agent/opencode_affinity.py` (líneas ~153-308: `_OPENCODE_FREE_MODELS`, `_OPENCODE_CLI_VERSION=1.18.31`, `_new_opencode_id`, `_free_session_for_scope`, `_is_opencode_free_wire_target`, `_opencode_free_wire_headers`, `merge_opencode_free_wire_headers`) | Generador `ses_/msg_` con bits invertidos, sesión estable por scope, 5 headers, set de modelos free |
| Hook kwargs | `agent/chat_completion_helpers.py:1544-1568` (`build_api_kwargs`: inyecta 6 core **antes** del builder + aplica headers) | Orden: fingerprint en `tools` antes de convertir; headers en cada request |
| Hook transporte | `agent/transports/codex.py:878-890` (refresca `msg_*` por request) | `msg_*` fresco por request, `ses_*` estable |
| Adapter 6 core | `agent/opencode_tool_adapter.py` (completo: `OPENCODE_CORE_TOOLS`, `OPENCODE_TOOL_DEFINITIONS`, `free_route_definitions`, `translate_opencode_tool_call`, validación) | Las 6 definiciones exactas + `ensure` idempotente; traducción de args como referencia (aquí no se ejecuta, solo se traduce wire) |
| Routing | `hermes_cli/models.py:2549-2570` (`_OPENCODE_API_MODE_PREFIXES`, `opencode_model_api_mode`: `muse-spark` → `codex_responses`) | `muse-spark-*` es Responses-only; `POST /zen/v1/responses` |
| Formato Responses | `agent/codex_responses_adapter.py` (`_responses_tools`, `_chat_messages_to_responses_input`, `function_call`/`function_call_output` con `call_id`, cap 64) | `function_call{call_id,name,arguments:json-string}`, `function_call_output{call_id,output:string}`, `call_id` preservado para round-trip exacto (FASE 4/5) |

## 2. Qué se creó (nuevo, en `Claude-Code/`)

* `freya_wire.py` — port vendored sin imports Hermes: `new_opencode_id`,
  `free_session_for_scope`, `normalize_model_id`, `is_free_model`,
  `zen_model_for_request` (pide free conocido o default
  `muse-spark-1.3-contributor-free`), `conversation_scope` (deriva scope estable
  del primer texto user + modelo; equivale al ROOT de Hermes pero stateless),
  `free_wire_headers` / `zen_request_headers` (5 headers + `Bearer public`).
* `freya_tools.py` — las 6 definiciones exactas + `responses_core_tools()`,
  `ensure_core_tools()` (port de `free_route_definitions`),
  `anthropic_to_responses_tools()` (convierte `input_schema`→`parameters` y
  garantiza las 6), `clamp_call_id` (cap 64), `coerce_arguments`.
* `zen_bridge.py` — `anthropic_messages_to_responses_input()` (user→message,
  assistant `tool_use`→`function_call`, user `tool_result`→`function_call_output`
  con mismo `call_id`; texto preservado y reordenado texto-antes-que-calls),
  `anthropic_to_responses_body()` (siempre `stream:true`, `store:false`,
  `tool_choice:auto`, `parallel_tool_calls:true`, `instructions` desde `system`,
  `max_output_tokens` desde `max_tokens`), `parse_responses_payload()` (SSE
  `output_text.delta` + `function_call_arguments.delta` + `output_item.done` +
  `response.completed` y JSON directo/errores), `responses_to_anthropic()`
  (texto + `tool_use` + `usage` o estimado `len//4`),
  `zen_post()` (POST a `/zen/v1/responses` con wire).
* `tests/test_zen_bridge.py` — 16 tests nuevos (wire, tools, bridge, gateway-zen
  contra fake Zen que valida huella + 6 core + `stream:true`).

## 3. Qué se modificó (solo en `Claude-Code/`, original intacto)

* `gateway.py` (`0.1.0`→`0.2.0`): nuevo upstream `zen` (`--upstream zen`).
  Rama `_handle_zen()` (Messages→Responses→Zen→Messages; en `stream:true` del
  cliente re-emite SSE Anthropic desde el mensaje completo, mismo orden que el
  mock). `build_server()` ahora **permite** Zen solo con `upstream==zen`
  (default `https://opencode.ai/zen/v1`, override loopback para tests) y
  **sigue rechazando** `passthrough` directo a `opencode.ai`/`/zen` (debe pasar
  por el traductor + fingerprint). Errores del proveedor se devuelven con
  mismo status + body, sin envolver. `GET /health` reporta `upstream:zen`.
* `bin/claude-gateway`: default URL por upstream (`zen`→Zen, resto→Anthropic);
  `start|stop|status|logs|doctor` sin cambios.
* `bin/claude-with-gateway`: si `CLAUDE_GATEWAY_UPSTREAM=zen` y no hay
  `ANTHROPIC_MODEL`, usa `muse-spark-1.3-contributor-free`; si hay, lo respeta.

## 4. Activación

```sh
cd ~/workspace/Transformers/Claude-Code
python3 -m py_compile gateway.py freya_wire.py freya_tools.py zen_bridge.py && echo compile-ok
python3 -m unittest discover -s tests 2>&1 | tail -n 3   # 24 OK esperado

# 1) Mock (demos sin red, sin credenciales) — como antes
./bin/claude-gateway start
./bin/claude-with-gateway -p "hola"

# 2) Zen Muse Spark Free (port Freya-Hermes)
CLAUDE_GATEWAY_UPSTREAM=zen ./bin/claude-gateway start
./bin/claude-gateway status   # {"status":"ok","upstream":"zen",...}
CLAUDE_GATEWAY_UPSTREAM=zen ./bin/claude-with-gateway -p "hola"
# o explícito:
# ANTHROPIC_MODEL=muse-spark-1.3-contributor-free ./bin/claude-with-gateway

# 3) Passthrough con clave propia (sin cambios)
CLAUDE_GATEWAY_UPSTREAM=passthrough \
CLAUDE_GATEWAY_UPSTREAM_URL=https://api.anthropic.com \
./bin/claude-gateway start

./bin/claude-gateway stop
```

Variables: `CLAUDE_GATEWAY_PORT` (8479), `CLAUDE_GATEWAY_UPSTREAM`
(`mock|passthrough|zen`), `CLAUDE_GATEWAY_UPSTREAM_URL`
(default según upstream), `ANTHROPIC_MODEL` (en `zen` default
`muse-spark-1.3-contributor-free`; el gateway mapea a Zen cualquier modelo no-free).

## 5. Pruebas (2026-10-15, `DEMOSTRADO`)

* `python3 -m unittest discover -s tests` → **24 tests OK**
  (8 `test_gateway.py` preexistentes intactos + 16 nuevos: IDs `ses_/msg_`,
  sesión estable, scope estable, mapeo de modelo, 6 core exactas, idempotencia,
  conversión Anthropic→Responses, body con gate, parse SSE texto+call,
  `responses_to_anthropic`, gateway-zen texto + round-trip con marcador
  `MARKER-ZEN-1` + guard que rechaza passthrough→Zen).
* Daemon: `CLAUDE_GATEWAY_UPSTREAM=zen ./bin/claude-gateway start/status/stop`
  → `started ... upstream=zen`, `/health` 200 `upstream:zen`, puerto liberado.
* Fake Zen local (valida `Bearer public`, `UA opencode/*`, `ses_/msg_`,
  `stream:true`, 6 core): texto + `tool_use read` → `tool_result MARKER-ZEN-1`
  → final cita el marcador. `DEMOSTRADO` end-to-end contra endpoint Responses
  compatible.
* Vivo contra Zen real (vía proxy del entorno, sin secretos):
  `POST /zen/v1/responses` con wire porteado → `HTTP 403 FreeTierError`
  (igual con `UA 1.18.31` y `1.19.0`, con/sin `instructions`, `include`,
  `max_output_tokens`, `prompt_cache_key`). Vía gateway-zen:
  `POST 127.0.0.1:8479/v1/messages` → `HTTP 403` mismo body, sin modificar.
  **Hermes original hoy da el mismo 403** (`hermes -z ... --provider
  opencode-zen` → `HTTP 403: ... can only be used from within OpenCode`),
  así que el port es fiel y el bloqueo es del proveedor, no del código.
  (`~/.hermes/config.yaml` se restauró a `false` tras la comprobación.)
* Opción 1 (2026-10-15, `DEMOSTRADO`, gateway `0.2.1`): wire alineado al
  binario 1.19.0 — UA `1.19.0`, SIN `Bearer public` (literal ausente en el
  binario; el cliente real no lo manda), `x-opencode-session-id` (= sessionID)
  más `x-opencode-parent-session-id` solo con padre. Suite **24/24 OK** con el
  fake actualizado (que ahora 403 la receta Sept con `Bearer public`).
  En vivo: `403` también con el wire 1.19.0 sin auth, y `403+403` en variante
  title-preface (title pequeña + build en la misma sesión, como el log real).
  Probado además: IDs reales de sesión del cliente, paths `/responses`,
  `/chat/completions`, `/messages`, stacks Python y Node. El cliente real
  1.19.0 sigue en 200 sin cuenta. Conclusión: el gate ya no valida forma sino
  firma/estado del cliente real (probablemente TLS de Bun o sesión encadenada
  servidor-side). Se para aquí: sin captura MITM del wire real no hay más
  bisección barata. Ver `README.md` §6.

## 6. Límites y no-objetivos

* Sin ejecución de tools en el gateway (Claude Code ejecuta sus tools; aquí
  solo traducción + fingerprint, igual que `free_route_definitions` anuncia
  pero `dispatch` aquí no aplica).
* Streaming V1 bufferizado: a Zen siempre `stream:true` (exigido); al cliente
  Anthropic se le re-emite SSE desde el mensaje completo (mismo orden, 2 ms
  por chunk como el mock). No es traducción incremental evento-a-evento.
* `count_tokens`/`usage` del mock y del fallback son `len//4`; en `zen` valen
  los de Zen si los trae.
* No se falsifica nada más allá del wire documentado de Hermes; no hay
  bypass: el 403 se propaga tal cual. Si el proveedor endurece el gate (como
  hizo entre 2026-09-17 y hoy), este port lo hereda igual que Hermes.
* Producción intacta: Hermes, `~/.claude/settings.json`, WARP/Privoxy, SSH,
  credenciales. Archivos tocados solo bajo `Claude-Code/`.

## 7. Archivos (estado final en `Claude-Code/`)

Nuevos: `freya_wire.py`, `freya_tools.py`, `zen_bridge.py`,
`tests/test_zen_bridge.py`, `CAMBIOS-Y-ACTIVACION.md` (este doc).
Modificados: `gateway.py`, `bin/claude-gateway`, `bin/claude-with-gateway`,
`README.md` (§6), `USAGE.md`, `INSTALL.md`, `TESTS.md`, `TROUBLESHOOTING.md`
(punteros a `zen`; sin cambiar comportamiento `mock`/`passthrough`).
