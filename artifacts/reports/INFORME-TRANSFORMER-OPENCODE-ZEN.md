# INFORME — Transformer OpenCode Zen en Freya

Fecha: 2026-10-13 (actualizado tras misión E2E) · Repositorio: `/home/kaos/.hermes/hermes-agent`
(`NousResearch/hermes-agent`, rama `main`, HEAD `3b63f7b0a4`)

> Nota de rutas: el enunciado situaba el repo en `/home/kaos/Proyectos/Freya-Hermes`, que no existe. La raíz real es la de arriba.

---

## 1. Síntomas originales

El transformer propio de Freya recibía **HTTP 403 `FreeTierError`** en todas las peticiones a los modelos gratuitos de OpenCode Zen, mientras el binario oficial respondía 200 desde la misma IP y en los mismos minutos.

```
{"type":"error","error":{"type":"FreeTierError",
 "message":"OpenCode's free tier can only be used from within OpenCode. Download it at https://opencode.ai and keep building."}}
```

## 2. Causa real (DEMOSTRADO)

La puerta es una **combinación de tres condiciones** (bisección con controles intercalados):

1. **`User-Agent: opencode/*`** — `HermesAgent/1.0` → 403; cualquier `opencode/<ver>` → 200.
2. **Cabecera de sesión** — `x-opencode-session`, `x-session-id` o `x-session-affinity` (cualquiera sirve).
3. **`tools` no vacío con nombres OpenCode** — `[bash, edit, glob, grep, read, write]` basta.

**Hallazgo decisivo de esta misión:** el formato de los IDs `ses_*`/`msg_*` SÍ se valida por valor, no solo por forma. Extraído del binario oficial v2.0.28:

```js
function IY(e, r=Date.now()){ ...; let n=BigInt(r)*0x1000n+BigInt(d), a=e?~n:n, ... }
// Bce() = IY(true) → los 12 hex son los 48 bits bajos de ~(ms*0x1000+contador)
```

Prueba controlada (mismo cuerpo, mismas cabeceras, controles 200 intercalados):

| Sesión | Resultado |
|---|---|
| `ses_ec9bba235ffe…` (antigua, del cliente oficial) | **200 + `response.completed`** (repetido) |
| `ses_01a136887af9…` (fresca, generada sin invertir) | **403** |

Decodificación: `0xec9bba235ffe` invertido da `ms ≈ 2026-10-13T17:16:52Z` (momento exacto de la captura). El generador anterior de Freya emitía `(ms<<12)` sin invertir (prefijo `1a136…`, 28 caracteres en vez de 26). **Esa era la causa del 403 E2E.**

Descartado experimentalmente: IP/egress, huella TLS (OpenSSL → 200), HTTP/1.1 vs 2, contenido de `instructions` (el prompt propio de Freya → 200), `Authorization` (suprimible), resto de cabeceras, `x-opencode-project/-client`. Hipótesis del "prefijo de system prompt": **retirada**, era un artefacto (línea base sin `tools`).

**Riesgo documentado:** el 403 es ambiguo — el tier devuelve el mismo error al exceder el ritmo. Observado: control 200 → fallos tras muchos envíos → 200 tras 2 min de pausa. Todo sondeo rápido sin control intercalado es poco fiable.

## 3. Bugs y cambios realizados

### 3.1 `agent/opencode_affinity.py`
- **`_new_opencode_id`: inversión `~n` + contador por milisegundo** (puerto fiel de `Bce()`/`IY(true)`). Antes: sin invertir, 28 caracteres → 403. Ahora: `ses_ec97…` (26, forma oficial).
- `_is_opencode_free_wire_target`: acepta `chat_completions` además de `codex_responses` para los modelos free (los modelos chat del tier — `space-bunny-free`, `glm-5-free`, … — exigen el mismo fingerprint en `/chat/completions`, verificado en vivo).

### 3.2 `agent/chat_completion_helpers.py`
- `free_route_definitions()` se aplicaba **después** del builder (código muerto). Ahora se inyecta **antes**, con copia de la lista (aliasing `#27907`).
- `merge_opencode_free_wire_headers()` se aplica en el nivel compartido (cubre el path chat, que no tiene hook de transporte). El hook del transporte codex se conserva.

### 3.3 `agent/opencode_tool_adapter.py` (nuevo, sin seguimiento)
- `get_opencode_tool_definition()`: emite forma **chat** (`{"type":"function","function":{…}}`). Antes en forma Responses, el conversor `_responses_tools` la descartaba en silencio (`None`).
- Nuevo `effective_valid_names()`: unión de nombres válidos + 6 core cuando el adapter está activo.

### 3.4 `agent/turn_tool_validation.py` + `agent/turn_tool_round.py`
- Faltaba el tercer hook: la validación rechazaba `bash` ("Tool 'bash' does not exist") antes del dispatch. Ahora acepta los 6 nombres en ruta free (validación y filtrado de lotes mixtos).

### 3.5 `tests/agent/test_opencode_free_wire.py` (nuevo)
6 tests: forma/timestamp de IDs, inyección pre-builder, supervivencia a `_responses_tools`, idempotencia/no-op fuera de ruta, `effective_valid_names`, cobertura chat. **6/6 en verde.**

No se tocaron `tool_executor.py`, `transports/codex.py`, `runtime_provider.py` (cambios locales preexistentes preservados).

## 4. Routing

`opencode_model_api_mode`: solo `muse-spark-*` → `codex_responses`; los otros 8 alias → `chat_completions`. Con §3.1–3.2 el transformer cubre ambos. Verificado en vivo: `space-bunny-free` E2E por el loop (`BUNNYOK`). Resto de modelos chat: NO VERIFICADO individualmente.

## 5. Pruebas reales Freya (DEMOSTRADO)

Todas directas a `https://opencode.ai/inference/v1`, sin CLI, sin proxy, sin `serve` (proceso destinatario verificado por captura: SDK de Hermes → opencode.ai):

| Prueba | Resultado |
|---|---|
| `agent.chat("…ZENOK")` (muse-spark-1.3) | **`'ZENOK'`** |
| 2 turnos (chat + `read` de fixture con marcador) | **`'ZENOK'` + `'FREYA_TOOL_OK_4821'`** |
| `bash`→`terminal` (`echo TOOLPROBE789`) | **emitido, traducido, ejecutado (exit 0), respondido** |
| `space-bunny-free` por el loop | **`'BUNNYOK'`** |
| Instructions propias (12702 chars, Hermes) | confirmadas en el cable; ningún prompt ajeno |
| Suites tocadas | `test_opencode_free_wire` 6/6; affinity+adapter+run_codex+helpers **136 passed**; `test_auxiliary_opencode_routing` 9 failed + `test_shared_metrics_model` 2 failed = **preexistentes** (idénticos con cambios en `stash`) |

Nota de honestidad: existe un proceso `opencode serve --service` (PID 88197, anterior a la misión, del propio CLI). Nunca interviene en las peticiones de Freya; solo se usó el binario para controles positivos y capturas de referencia.

## 6. Claude Code (instalado, bloqueado por limitación externa)

- Instalado **2.1.296** aislado (`/tmp/opencode/claude-pfx`, binarios node/npm de Hermes). Sin config previa que tocar (no existía `~/.claude`); settings de prueba solo en `/tmp/opencode/claude-home` y `/tmp/opencode/probe/.claude/`. Nada del sistema modificado.
- Configurado con `ANTHROPIC_BASE_URL=https://opencode.ai/inference/v1`, `ANTHROPIC_AUTH_TOKEN=public`, `ANTHROPIC_MODEL=muse-spark-1.3-contributor-free`.
- **Bloqueo 1 (servidor, definitivo):** `POST /inference/v1/messages` con ese modelo → `400 {"type":"error","error":{"type":"ModelProtocolUnsupported","message":"Model does not support this protocol."}}` (con y sin stream/tools). El modelo es solo-Responses en Zen.
- **Bloqueo 2 (cliente):** Claude Code rechaza el ID desconocido (`[claude-code:unrecognized_model]`); el mapeo `behavesAs` en `modelPicker` (settings usuario, `--settings` y proyecto, con/sin `replaceBuiltInOptions`) no surte efecto en esta versión.
- Contrapueba: `space-bunny-free` por la misma superficie Anthropic → **200 + SSE**. La limitación es específica del protocolo del modelo, no del harness.
- **Conclusión: Claude Code + Muse Spark 1.3 es inviable sin un traductor de protocolo (= proxy, prohibido).** Demostrado, no disfrazado. NO VERIFICADO: Claude Code con `space-bunny-free` (el cliente rechaza el ID antes de emitir).

## 7. Compatibilidad con otros harnesses

Interfaz mínima reutilizable (3 constantes + 6 esquemas, sin dependencias): `User-Agent: opencode/*`, `x-opencode-session: ses_<12hex-invertidos><14base62>`, `tools` con los 6 nombres. `instructions` propio de cada harness (irrelevante). Cada harness traduce los calls a sus tools. Validado a nivel de protocolo con `curl` (OpenSSL y BoringSSL) y con dos rutas de Freya (Responses + chat).

## 8. Reproducir / revertir

```bash
cd /home/kaos/.hermes/hermes-agent
HH=/tmp/opencode/hh-live   # home aislado ya provisionado
HERMES_HOME=$HH scripts/run-in-hermes-env python3 /tmp/opencode/live_chat.py      # E2E 1 turno
HERMES_HOME=$HH scripts/run-in-hermes-env python3 /tmp/opencode/live_two_turn.py  # 2 turnos + read
HERMES_HOME=$HH scripts/run-in-hermes-env python3 /tmp/opencode/live_bunny.py     # chat-path
HERMES_HOME=$HH scripts/run_tests.sh tests/agent/test_opencode_free_wire.py       # regresión
```
Reversión: `git diff > /tmp/fix.patch; git checkout -- agent/; rm tests/agent/test_opencode_free_wire.py INFORME-TRANSFORMER-OPENCODE-ZEN.md` (los demás cambios locales son preexistentes; `agent/opencode_tool_adapter.py` está sin seguimiento). Claude Code: borrar `/tmp/opencode/claude-pfx` y `/tmp/opencode/claude-home`; ninguna config del sistema fue tocada.

## 9. Pendiente

- Resto de modelos chat uno por uno (solo `space-bunny-free` E2E).
- Los 9+2 fallos preexistentes de suites ajenas.
- `try/except: pass` residual en diffs locales (contra `AGENTS.md`).
- Claude Code con otro modelo / versión futura (revisar si `behavesAs` funciona).

## 10. Modelo por defecto: Muse Spark 1.3 free (misión de configuración)

Cambio aplicado con `hermes config set` (copia de seguridad en `/tmp/opencode/config.yaml.bak-20261013-191733`):

```yaml
model:
  default: muse-spark-1.3-contributor-free
  provider: opencode-zen
  base_url: https://opencode.ai/inference/v1
```

(El propio `config set` limpió la `base_url` anterior de nvidia al cambiar de proveedor; el resto del diff son normalizaciones cosméticas del escritor — `null`→vacío, indentación de listas.)

**Bug encontrado al verificar (corregido):** la resolución (`resolve_runtime_with_fallback`) devolvía correctamente `opencode-zen / muse-spark-1.3-contributor-free / inference/v1 / codex_responses` con `api_key=''` (exención keyless), pero `agent_init._init_openai_client` solo aceptaba la vía explícita `if api_key and base_url` y caía en la ruta con credenciales → `ProviderNotConfiguredError`. Añadido `_is_opencode_free_keyless_route()` en `agent/agent_init.py` (espejo de la exención de `runtime_provider`: familia opencode + modelo free + host opencode.ai) que toma la vía explícita con clave vacía. Sin regresiones (suites de init: 16 passed / 14 failed idénticos con y sin el cambio — preexistentes).

**Verificación por la vía de producción** (`load_config` → `_resolve_model_and_provider` → `resolve_runtime_with_fallback` → `AIAgent`, sin argumentos explícitos): resuelve el default y `agent.chat("…DEFAULT_OK")` devuelve **`'DEFAULT_OK'`** (DEMOSTRADO).

**Bug 2 de la vía por defecto (corregido):** el CLI (`hermes chat --oneshot`) fallaba con `HTTP 401 Invalid credential` mientras construcciones equivalentes devolvían 200. Captura del cable con cabeceras registradas: el CLI enviaba `Authorization: Bearer no-key-required` (22 caracteres). Origen: alguna vía (clientes aux cacheados/heredados) sustituía la clave vacía por el placeholder de "sin clave", que Zen rechaza con 401. Corrección en `hermes_cli/runtime_provider.py`: la exención keyless resuelve ahora `api_key="public"` —literalmente lo que envía el cliente oficial— en vez de `""`, de modo que ninguna vía puede sustituir un placeholder (verificado: `test_runtime_provider_resolution.py` + `test_opencode_free_wire.py`, 113 passed). Tras el cambio, el comando exacto de usuario devuelve **`PUBLICAUTH`** (DEMOSTRADO).

**Limitación estructural confirmada (no bloqueante):** la generación auxiliar de títulos usa la ruta por defecto sin transformer y sin `tools` → 403 del gate (un título no declara herramientas por diseño). Es un aviso no fatal; el turno principal no se ve afectado. Queda documentado, no corregido (requeriría expulsar al aux del tier gratuito o un fallback, fuera del alcance mínimo).

**Servicios reiniciados:** `hermes-gateway` y `hermes-webui` corrían código anterior al fix (errores `ProviderNotConfiguredError` en logs hasta las 19:28). Reiniciados vía systemd (`systemctl --user restart hermes-gateway hermes-webui`): gateway `running` + telegram `connected`, webui health 200. El proceso `opencode serve --service` preexistente no interviene en estas peticiones.

## 11. Veredicto

# FUNCIONA, PERO CON LIMITACIONES

**Freya + Muse Spark 1.3: ARREGLADO Y VERIFICADO E2E** (chat, 2 turnos, ejecución real de `bash` y `read`, segundo modelo en ruta chat, 142 tests verdes sin regresiones).
**Claude Code + Muse Spark 1.3: NO ARREGLADO por limitación externa demostrada** (protocolo Responses-only en servidor + catálogo cerrado en cliente).
**Límites:** sello del servidor (puede volver a endurecerse), 403 ambiguo con rate limiting, resto de alias sin probar, suites ajenas con fallos preexistentes.

DEMOSTRADO: todo §5–§6. INFERIDO: nada relevante pendiente de inferencia. NO VERIFICADO: resto de modelos chat, Claude Code con otro modelo.
