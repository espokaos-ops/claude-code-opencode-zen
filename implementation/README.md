# Transformer Claude-Code (gateway local multi-protocolo Zen free; E2E activo 2026-10-16)

Objetivo: Claude Code + `muse-spark-1.3-contributor-free` con tools.
Investigación previa ( §§1–4 intactos ) + gateway mock/passthrough ( §5 ) +
port del transformer Freya-Hermes como upstream `zen` ( §6 nuevo, 2026-10-15 ).
El gateway NO evade el bloqueo del proveedor (propaga el 403 tal cual).

## 1. Lo auditado `DEMOSTRADO` (solo lectura)

* Transformer y adapter de Freya-Hermes (sección 3 de `../Freya-Hermes/README.md`):
  in-process de Hermes (kwargs/SDK), no un servidor reutilizable por otro CLI.
* Claude Code 2.1.299 instalado en `~/.local/bin/claude`; `settings.json` solo
  `theme:dark`, sin managed settings ni `env`. Config intacta.
* OpenCode `opencode.jsonc` mínimo; `auth.json` local solo guarda clave `nvidia`
  (Zen free no necesita clave almacenada: keyless `public`).

## 2. Incompatibilidad central `DEMOSTRADO`

* Claude Code habla **Anthropic Messages** (`POST /v1/messages` vía
  `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`): docs gateway de Anthropic
  (formato por variable, `/v1/messages`, `anthropic-version`, `count_tokens`).
* Zen sirve `muse-spark-*` **Responses-only** (`POST /zen/v1/responses`,
  `api_mode codex_responses`): `hermes_cli/models.py`, `_OPENCODE_API_MODE_PREFIXES`.
  Los modelos Anthropic-wire en Zen son otros (`claude-*/minimax/qwen`), no muse-spark.
* Conclusión `INFERIDO`: apuntar `ANTHROPIC_BASE_URL=https://opencode.ai/zen/v1`
  no puede funcionar sin un traductor Messages↔Responses en medio. Los hooks de
  OpenCode no son copiables sin más (generan kwargs Hermes, no HTTP Anthropic).

## 3. Prueba viva mínima `DEMOSTRADO` (1 request, sin cambios)

```sh
POST https://opencode.ai/zen/v1/messages
model=muse-spark-1.3-contributor-free, max_tokens=1, Bearer public (vía Privoxy)
→ HTTP 403 {"type":"error","error":{"type":"FreeTierError",
  "message":"OpenCode's free tier can only be used from within OpenCode..."}}
```

Sin huella de cliente el relay rechaza incluso la ruta Messages. Con huella
haría falta además: UA `opencode/*`, `ses_*` estable + `msg_*` fresco por request
(imposible con `ANTHROPIC_CUSTOM_HEADERS` estáticos), las 6 core en el wire
Responses y traducción de `tool_use`↔`function_call` + SSE con `call_id` exactos.

## 4. Estado y qué falta (nada implementado)

* BLOQUEADO en: gateway local Anthropic→Zen (headers dinámicos + tools + streaming).
  Alcance estimado: proceso nuevo con puerto local, secreto local, logs sin fugas,
  revalidación FASE 1–6 tras cada cambio. Riesgo alto, fuera de “mínimo viable”.
* NO se tocó: transformer original, configs de Claude/OpenCode, WARP/Privoxy,
  SSH, credenciales. Archivos modificados por esta investigación: NINGUNO
  (solo este doc y el índice).
* Arranque/petición/tools de Claude+muse-spark: `NO DEMOSTRADO` (no intentado al
  estar bloqueado el transporte). Límites gratuitos (429) en esta ruta: `NO
  DEMOSTRADO`. Alternativa válida hoy: usar Hermes (Freya) para muse-spark, o en
  Claude Code otro modelo Anthropic-wire ya soportado por Zen —pero eso sustituye
  el modelo y queda fuera de este objetivo.

## 5. Implementación 2026-10-14: gateway local (desacoplado, sin suplantación)

* `DEMOSTRADO`: `gateway.py` (stdlib, sin imports Hermes, bind 127.0.0.1:8479)
  habla Anthropic Messages (`/v1/messages` + SSE, `count_tokens`, `/health`)
  con upstreams `mock` (determinista) y `passthrough` (clave propia).
  Rechaza upstreams `opencode.ai`/`zen` al arrancar y no falsifica huella
  OpenCode; errores del proveedor se devuelven sin modificar.
* `DEMOSTRADO`: `bin/claude-gateway {start|stop|status|logs|doctor}` y
  `bin/claude-with-gateway` (env solo-hijo, `settings.json` intacto).
* `DEMOSTRADO`: suite `tests/test_gateway.py` **8/8 OK** (texto, 1 tool +
  round-trip con marcador, multi-tool, SSE, errores, continuidad 3 turnos,
  interrupción). Detalle en `TESTS.md`.
* `NO DEMOSTRADO`: extremo a extremo con Muse Spark Free — el proveedor lo
  rechaza (403 verificado) y el gateway no lo evade. Sin petición aceptada,
  no se afirma.
* Docs: `ARCHITECTURE.md`, `INSTALL.md`, `USAGE.md`, `TESTS.md`,
  `TROUBLESHOOTING.md`. Producción (Hermes, CLIs, WARP) intacta.

## 6. Port 2026-10-15: upstream `zen` (Freya-Hermes vendored, sin tocar original)

* `DEMOSTRADO`: `freya_wire.py` (IDs `ses_/msg_*`, sesión estable por
  conversación, 5 headers, `Bearer public`), `freya_tools.py` (las 6 core
  exactas + `ensure` idempotente + conversión `input_schema`→`parameters`),
  `zen_bridge.py` (Messages↔Responses, `stream:true` siempre, `call_id` exacto,
  parse SSE `output_text.delta`/`function_call`/`completed`, errores sin modificar).
  Origen solo-lectura en `CAMBIOS-Y-ACTIVACION.md` §1; original intacto.
* `DEMOSTRADO`: `gateway.py 0.2.0` con `--upstream zen` (default
  `https://opencode.ai/zen/v1`), `bin/claude-gateway`/`claude-with-gateway`
  (en `zen`, modelo default `muse-spark-1.3-contributor-free`). `passthrough`
  directo a Zen sigue rechazado (usar `zen`).
* `DEMOSTRADO`: suite **24/24 OK** (8 previos + 16 nuevos: wire, 6 core, bridge,
  gateway-zen contra fake Zen con huella validada + round-trip `MARKER-ZEN-1`).
  Daemon `zen` verificado (`start/status/stop`, `/health` con `upstream:zen`).
* `DEMOSTRADO` (bloqueo vivo, no del código): hoy Zen da `403 FreeTierError`
  tanto al port como al Hermes original (comprobado `hermes --provider
  opencode-zen` → mismo 403; `config.yaml` restaurado). El gateway lo devuelve
  sin modificar. Operativo contra Responses compatible (fake); bloqueado en vivo
  por el proveedor. Activación y pruebas en `CAMBIOS-Y-ACTIVACION.md`.
* Opción 1 (2026-10-15, gateway `0.2.1`): wire 1.19.0 (UA `1.19.0`, sin `Bearer
  public`, `x-opencode-session-id`); 24/24 OK; en vivo sigue 403 incluso con
  title-preface y con IDs reales. Gate = firma/estado del cliente real, no
  forma. Bisección parada ahí (ver `CAMBIOS-Y-ACTIVACION.md` §5).


## 7. Fases 4–5 (2026-10-16): gateway 0.4.0 operativo contra Zen free

* `DEMOSTRADO`: wire v2 aceptado en vivo (`/inference/v1/messages`, UA
  `opencode/latest/2.0.26/cli`, `Bearer public`, sesión `ses_...` fresca,
  tools `read`/`shell` verbatim obligatorias en `/messages` y
  `/chat/completions`; `stream:true` obligatorio). Ver `zen_fingerprint.py`
  (sin Hermes).
* `DEMOSTRADO`: matriz de protocolos por modelo (Fase 5 + re-verificación
  2026-10-16):
  * `/messages` → `space-bunny-free` (único verificado en esta vía).
  * `/responses` → `muse-spark-1.2-contributor-free` y
    `muse-spark-1.3-contributor-free`. Nota: `muse-spark-1.3-contributor-free`
    respondió 200 en `/responses` (Fase 5 y sonda directa), pero hoy el free
    tier devuelve 429 en esta ruta; reintentar más tarde.
  * `/chat/completions` → `beam-free`, `deepseek-v4.1-flash-free`,
    `glm-5.3-flash-free`, `nemotron-3.5-lightning-free`,
    `nemotron-3.5-super-vl-free`, `mimo-v2.6-flash-free`,
    `longcat-2.5-preview-free`, `ll-alpha-free` (+`space-bunny-free`),
    **y `big-pickle`** (en Fase 5 midió 200 en `/responses`, pero hoy responde
    en `/chat/completions` y rechaza `/responses` con 400 `ModelProtocolUnsupported`;
    el routing del gateway se actualizó en consecuencia).
  * `jev-1.13-free`: 400 `ModelProtocolUnsupported` en las tres (inutilizable).
  Routing automático en el gateway: `is_responses_model` / `is_chat_model`
  (`zen_fingerprint.py`), bridges `zen_bridge.py` y `zen_chat.py` (nuevo).
* `DEMOSTRADO` (E2E Claude Code 2.1.299 con marcador `ZEN-E2E-MARKER-4242`,
  tool Read + respuesta final; modelo solicitado = modelo que respondió, eco
  verificado por el gateway): `space-bunny-free` (messages) y `beam-free`
  (chat). Evidencia en `/tmp/opencode/probes/` (`phase4_*`,
  `phase5_cc_*.json`, `p6_*`).
* `DEMOSTRADO` a nivel HTTP a través del gateway (eco verificado por el propio
  gateway, HTTP 200): `deepseek-v4.1-flash-free` (chat), `big-pickle`
  (chat). E2E completo de Claude Code con estos dos y con
  `muse-spark-1.3-contributor-free` (responses) queda pendiente por agotarse
  la cuota free hoy (ver §9 para el comando exacto).
* `DEMOSTRADO`: multimodal por `/messages` (bloque `image` base64: el modelo
  la ve; `phase5_img_messages.sse`). Por chat `image_url`: 422/400 → el bridge
  deja una nota visible (`IMAGE_OMITTED_NOTE`) en vez de descartar en silencio.
* `DEMOSTRADO`: `count_tokens` no existe upstream (404); el gateway sirve su
  estimador local (`len//4`) y CC funciona sin el endpoint real.
* `DEMOSTRADO`: guard de truncamiento (upstream corta sin `message_stop`/
  `[DONE]` → `event: error` para que CC reintente en vez de colgar), `_stream_anthropic`
  corregido (sin duplicar input/texto), `connection: close`.
* `DEMOSTRADO`: resolución estricta de modelo (sin sustitución silenciosa:
  modelo desconocido → 400 `invalid_request_error` con la lista de free);
  guard de eco de modelo: mismatch → 502 (no-stream) / `event: error` (stream).
* `DEMOSTRADO`: suite **82/82 OK** (`test_gateway.py`, `test_fingerprint.py`,
  `test_zen_bridge.py`, `test_zen_chat.py`).

## 8. Limites actuales (NO DEMOSTRADO / DOCUMENTADO)

* `jev-1.13-free` listado pero sin protocolo que lo acepte (NO DEMOSTRADO).
* Imagenes en la vía chat (bridge deja nota visible; upstream 422/400) y tool
  roundtrip de los chats restantes (ll-alpha, mimo, longcat, glm, nemotron):
  NO DEMOSTRADO.
* Rate limit/429 del free tier: observable hoy (2026-10-16) en varias rutas;
  DOCUMENTADO por el proveedor, reintentar tras pausa.
* `claude` emite `[claude-code:unrecognized_model]` con algunos ids: inofensivo,
  no bloquea.
* `x-opencode-request` solo existe en el wire v1 viejo; el v2 no lo necesita
  (P2b/P4).

## 9. Quickstart: Claude Code + modelo free de Zen vía el gateway (copia-pega)

Prerrequisitos: Python 3.11+, `claude` (Claude Code 2.1.299) en PATH,
y el repo en `~/workspace/Transformers/Claude-Code` (o ajustar la ruta).

```sh
# 0) variables de entorno del gateway (una sola vez)
export CLAUDE_GATEWAY_UPSTREAM=zen
export REPO=~/workspace/Transformers/Claude-Code

# 1) iniciar el gateway local en 127.0.0.1:8479 (upstream Zen)
cd "$REPO"
./bin/claude-gateway stop 2>/dev/null || true
./bin/claude-gateway start </dev/null
curl -s --noproxy '*' http://127.0.0.1:8479/health   # {"status":"ok","upstream":"zen",...}
curl -s --noproxy '*' http://127.0.0.1:8479/v1/models | head -c 400   # lista modelos free

# 2) ejecutar Claude Code con un modelo free (ejemplo: beam-free, vía /chat/completions)
export ANTHROPIC_BASE_URL=http://127.0.0.1:8479
export ANTHROPIC_AUTH_TOKEN=public
export ANTHROPIC_MODEL=beam-free            # alias equivalente: claude-free-beam-free
echo "ZEN-E2E-MARKER-4242" > /tmp/zen-marker.txt
claude -p "Usa la herramienta Read para leer /tmp/zen-marker.txt y devuelve su contenido exacto y nada más" \
  --output-format json --dangerously-skip-permissions
# Comprobar: "model":"beam-free" y el texto final contiene ZEN-E2E-MARKER-4242
# (otra opción válida: ANTHROPIC_MODEL=big-pickle, que el gateway rota a /chat/completions)

# 3) detener el gateway cuando termine
./bin/claude-gateway stop
```

Diagnóstico rápido:
* `403 FreeTierError`: el provider exige huella de cliente real; el gateway lo propaga sin modificar (no es configuración local).
* `400 invalid_request_error`: modelo no está en la lista free (`/v1/models`).
* `502` / `event: error`: el upstream respondió un modelo distinto al pedido (el gateway no sustituye silenciosamente).
* `429`: cuota free agotada; esperar y reintentar.

Nota: `bin/claude-with-gateway` ya define `ANTHROPIC_MODEL=space-bunny-free` cuando el upstream es `zen`; basta con ejecutarlo con `ANTHROPIC_BASE_URL=http://127.0.0.1:8479 ANTHROPIC_AUTH_TOKEN=public`.
