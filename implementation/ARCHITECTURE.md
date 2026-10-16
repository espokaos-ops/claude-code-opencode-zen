# ARCHITECTURE — claude-code-local-gateway

## Rol

Adaptador HTTP en loopback entre Claude Code (Anthropic Messages) y un upstream
permitido. No es un transformer in-process: es un proceso independiente, sin
imports de Hermes, sin hooks, sin tocar el transformer original.

```text
claude (ANTHROPIC_BASE_URL=http://127.0.0.1:8479, child env only)
  → POST /v1/messages (+ SSE) → gateway.py (valida, enruta)
      → mock (determinista, sin red)        [tests, demos]
      → passthrough → UPSTREAM_URL (clave propia del usuario)  [uso real]
      → zen → routing por modelo (zen_fingerprint.is_responses_model/is_chat_model)
              → /inference/v1/messages    (relay fino: space-bunny-free)
              → zen_bridge → /inference/v1/responses  (muse-spark*, big-pickle)
              → zen_chat   → /inference/v1/chat/completions  (resto de free)
```

## Endpoints

* `GET /health` → `{"status":"ok", gateway, version, upstream}`.
* `POST /v1/messages` → valida (`model`, `max_tokens>0`, `messages` no vacío,
  roles `user|assistant`, `tools[].name`) y responde en formato Anthropic
  (`msg_*`, `content[]` texto/`tool_use`, `stop_reason`, `usage` estimado) o
  reenvía bytes del upstream sin modificar (errores incluidos, sin envolver,
  como exige Claude Code para su recuperación automática).
* `POST /v1/messages/count_tokens` → estimación `len//4` (suficiente para el
  chequeo opcional del cliente; el upstream real manda `usage` exacto).
* Streaming SSE Anthropic (`message_start → content_block_start →
  content_block_delta[text_delta|input_json_delta] → content_block_stop →
  message_delta → message_stop`). `tool_use.input` se reensambla de deltas
  `input_json_delta`, igual que hace un cliente real.

## Routing por protocolo (Fase 5, 2026-10-16)

| modelo | protocolo upstream | modulo |
|---|---|---|
| space-bunny-free (default) | `POST /inference/v1/messages` (Anthropic SSE, relay) | `zen_fingerprint` |
| muse-spark-1.2/1.3-contributor-free, big-pickle | `POST /inference/v1/responses` | `zen_bridge` |
| beam-free, deepseek-v4.1-flash-free, glm-5.3-flash-free, nemotron-*, mimo-*, longcat-*, ll-alpha-* | `POST /inference/v1/chat/completions` | `zen_chat` |

* Los tres caminos aplican el fingerprint v2 (tools `read`/`shell` verbatim,
  alias de colisiones, nota anti-placeholder, `stream:true`) y normalizan la
  respuesta a Anthropic (`read`→`Read`, `shell`→`Bash`).
* `zen_chat` convierte historial (tool_result→role tool, tool_use→tool_calls),
  acumula deltas de `tool_calls[].function.arguments` y emite `event: error`
  si el upstream corta antes de `[DONE]`/`finish_reason`.
* Errores del proveedor (403/400/401) se propagan sin modificar en los tres.

## Decisiones

* **Upstream `zen` (2026-10-15, port sin tocar original)**: `freya_wire.py`
  (UA `opencode/1.18.31`, `ses_*` estable por conversación + `msg_*` fresco,
  `x-opencode-client/project`, `Bearer public`), `freya_tools.py` (las 6 core
  exactas, `ensure` idempotente) y `zen_bridge.py` (Messages↔Responses,
  `stream:true` siempre a Zen, `call_id` exacto, parse SSE, errores sin
  modificar). Hoy Zen da 403 tanto al port como a Hermes original
  (`CAMBIOS-Y-ACTIVACION.md` §5); el gateway lo propaga tal cual, sin evadirlo.
  `build_server()` solo permite Zen con `upstream==zen`; `passthrough` directo
  a `opencode.ai`/`/zen` sigue rechazado con `SystemExit`.
* **Stateless**: la continuidad de sesión la da el cliente reenviando historial
  (como exige la API Messages). El gateway deriva el “turno” del nº de mensajes
  `user` del request; no guarda estado entre requests (sin fugas entre sesiones).
* **Secretos**: `Authorization`/`x-api-key`/`cookie` se redactan en logs; la clave
  de passthrough viaja solo en memoria del proceso, nunca a disco.
* **Loopback exclusivo**: bind `127.0.0.1`, `ThreadingHTTPServer` + hilos daemon;
  `BrokenPipe`/`ConnectionReset` en streaming se absorben (el servidor sobrevive
  a interrupciones del cliente).
* **Proxy**: el gateway respeta el proxy del entorno para upstreams externos
  (sale por WARP como el resto); loopback jamás va al proxy (como Claude Code).
