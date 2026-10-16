# USAGE — claude-code-local-gateway

## Zen free: modelos y protocolos (Fase 5)

```sh
cd ~/workspace/Transformers/Claude-Code
CLAUDE_GATEWAY_UPSTREAM=zen ./bin/claude-gateway start   # 127.0.0.1:8479

# E2E por familia (ANTHROPIC_MODEL = id free; el gateway enruta solo):
ANTHROPIC_MODEL=space-bunny-free          # /messages (default del gateway)
ANTHROPIC_MODEL=muse-spark-1.2-contributor-free   # /responses
ANTHROPIC_MODEL=big-pickle                # /responses
ANTHROPIC_MODEL=beam-free                 # /chat/completions
ANTHROPIC_MODEL=deepseek-v4.1-flash-free  # /chat/completions
# ...gemelo para el resto de ids free (ver README §7).
```

Claude Code avisa `[claude-code:unrecognized_model]` para ids desconocidos:
es inofensivo, la peticion sale igual por el gateway. `jev-1.13-free` no
acepta ningun protocolo (no usar).

## Lanzar Claude Code contra el gateway (mock, sin credenciales)

```sh
cd ~/workspace/Transformers/Claude-Code
./bin/claude-gateway start
./bin/claude-with-gateway
# dentro de claude: /status muestra ANTHROPIC_BASE_URL http://127.0.0.1:8479
```

`claude-with-gateway` solo exporta en el hijo: `ANTHROPIC_BASE_URL`,
`ANTHROPIC_AUTH_TOKEN=dummy-local-gateway`, `ANTHROPIC_MODEL` (defecto
`mock:claude-sonnet`) y des-setea `ANTHROPIC_API_KEY` para que no compita.
Acepta args: `./bin/claude-with-gateway -p "hola"`.

## Upstream real (passthrough, clave propia)

```sh
CLAUDE_GATEWAY_UPSTREAM=passthrough \
CLAUDE_GATEWAY_UPSTREAM_URL=https://api.anthropic.com \
./bin/claude-gateway start
ANTHROPIC_MODEL=claude-sonnet-4-6 ./bin/claude-with-gateway
```

El gateway reenvía el body intacto y devuelve la respuesta/error del upstream
sin modificar (Claude Code casa sus recuperaciones con el texto del error).

## Comportamientos del mock (deterministas, para demos y tests)

* `hola...` → texto `turn N: mock reply to: ...` (N = nº de mensajes user).
* `call:read:/ruta` → `tool_use read {filePath}`; al devolver el `tool_result`
  con el historial, la respuesta final cita el contenido (`consumed tool result`).
* `call:multi` → dos `tool_use` (`read` + `glob`) en un turno; dos `tool_result`
  → final con ambos marcadores.
* `stop:...` → texto largo (50 chunks) para probar streaming/interrupción.
* `error:NNN` → HTTP NNN `{"type":"error","error":{"type":"api_error",...}}`.

## Upstream zen (port Freya-Hermes → Muse Spark Free)

```sh
CLAUDE_GATEWAY_UPSTREAM=zen ./bin/claude-gateway start
CLAUDE_GATEWAY_UPSTREAM=zen ./bin/claude-with-gateway -p "hola"
# modelo por defecto en zen: muse-spark-1.3-contributor-free
```

Traduce Messages↔Responses, inyecta el wire (UA `opencode/*`, `ses_*/msg_*`,
6 core, `stream:true`, `Bearer public`) y devuelve errores del proveedor sin
modificar. Detalle y estado vivo en `CAMBIOS-Y-ACTIVACION.md`.

## Límites honestos (2026-10-15)

* En vivo Zen hoy responde `403 FreeTierError` tanto al port como al Hermes
  original (ver `CAMBIOS-Y-ACTIVACION.md` §5); el gateway lo propaga tal cual,
  sin evadirlo. Operativo end-to-end contra endpoint Responses compatible
  (fake local en tests).
* `count_tokens` y `usage` del mock son estimaciones `len//4`; en passthrough
  y en `zen` valen los del upstream cuando los trae.
