# Findings — hallazgos detallados

> **Regla de este documento:** cada afirmación lleva su clasificación (`DEMOSTRADO` / `DOCUMENTADO` / `INFERIDO` / `NO DEMOSTRADO`) y se distingue siempre **análisis estático** (código del artefacto) de **prueba real contra el proveedor** (captura HTTP). Los dos puntos pendientes se mantienen como **NO DEMOSTRADO** en todo el documento.

## 0. Metodología

- **Análisis estático (REA/Ghidra)** sobre:
  - Claude Code 2.1.299 — `/home/kaos/.local/share/claude/versions/2.1.299` (bun bytecode → 2376 módulos JS).
  - OpenCode 1.19.3 — `/home/kaos/.opencode/bin/opencode` (345 módulos JS).
- **Pruebas reales contra el proveedor (misión previa, documentadas):** validación de la puerta FreeTier y de la superficie Anthropic unificada con `curl` y con dos harnesses (Freya). Fuente: `artifacts/reports/INFORME-TRANSFORMER-OPENCODE-ZEN.md`.
- **Consultas sin autenticación:** `GET /inference/v1/models` (catálogo público) y sondas de disponibilidad que devolvieron `403 FreeTierError`.
- **Restricciones:** sin peticiones de prueba nuevas al proveedor, sin instalaciones, sin modificar Claude Code.

## 1. Claude Code 2.1.299 — hallazgos de código

### F-01 · Concatenación `baseURL + path` (chunk `gmq0qwep.js`)

`buildURL(r,n,s){ … new URL(h+(h.endsWith("/")&&r.startsWith("/")?r.slice(1):r)) … }` concatena la base sin normalizar con el path del endpoint. Los paths del SDK son `/v1/messages`, `/v1/messages?beta=true`, `/v1/messages/count_tokens`, `/v1/messages/batches`, `/v1/messages/cache_touch`.

**Implicación:** `ANTHROPIC_BASE_URL` no debe terminar en `/v1`:

| Configuración | POST resultante |
|---|---|
| `https://opencode.ai/inference` | `https://opencode.ai/inference/v1/messages` ✅ (superficie unificada) |
| `https://opencode.ai/inference/anthropic` | `https://opencode.ai/inference/anthropic/v1/messages` ✅ (superficie documentada) |
| `https://opencode.ai/inference/v1` | `https://opencode.ai/inference/v1/v1/messages` ❌ (duplicado) |

- `DEMOSTRADO` (estático): la concatenación y los paths — extractos `CC-01`, `CC-06`, `CC-15`.
- `INFERIDO`: que la configuración del 13-oct (`…/inference/v1`) habría producido `…/v1/v1/messages`. Esa configuración **nunca llegó al cable** con Claude Code (el cliente bloqueó antes por el ID de modelo en 2.1.296); las pruebas de protocolo de esa fecha fueron `curl` directo a `/inference/v1/messages`.

### F-02 · Fusión de `ANTHROPIC_CUSTOM_HEADERS` después de `Nl()` (chunk `gmq0qwep.js`)

- El constructor del SDK parsea `ANTHROPIC_CUSTOM_HEADERS` (`ive()`/`$Mt()`) y las usa como base de `defaultHeaders`.
- La factory `jF` ensambla: `ee = {...Nl(), ...te, ...n$(), …}` donde `te = $Mt()` (custom headers) y `Nl()` = `{"x-app":…, "User-Agent": $0(), "X-Claude-Code-Session-Id": …}`.
- Como `te` se extiende **después** de `Nl()`, un `User-Agent` en custom headers **sobrescribe** el UA de Claude Code (`$0()` = `claude-cli/2.1.299 (external, cli)`). Igualmente se pueden inyectar cabeceras arbitrarias, incluidas `x-opencode-session`, `x-session-id` o `x-session-affinity`.
- `$Mt()` aplica política: ignora `anthropic-beta` custom si las betas experimentales están deshabilitadas por política de organización; extrae `Authorization` con tratamiento especial.

**Implicación:** la Ruta A puede satisfacer a mano las condiciones 1 y 2 de la puerta (UA + sesión). `DEMOSTRADO` (estático) — extractos `CC-02`, `CC-03`, `CC-04`, `CC-07`. La verificación en el cable de que el UA llega efectivamente sobrescrito: `NO DEMOSTRADO`.

### F-03 · `mZe()` / `dHe()` — validación de modelo omitida (chunk `1qwezzd3.js`)

```javascript
function mZe(){return Boolean(ic()!==void 0||a.ANTHROPIC_MODEL||a.ANTHROPIC_DEFAULT_FABLE_MODEL||a.ANTHROPIC_DEFAULT_OPUS_MODEL||a.ANTHROPIC_DEFAULT_SONNET_MODEL||a.ANTHROPIC_DEFAULT_HAIKU_MODEL||aBe()||!su())}
async function dHe(e,r,o,…){if(mZe())return; …}
```

- En 2.1.296 el cliente rechazaba el ID desconocido (`[claude-code:unrecognized_model]`; `behavesAs` en el model picker no surtía efecto).
- En 2.1.299, con `ANTHROPIC_MODEL` (o `ANTHROPIC_DEFAULT_*_MODEL`) definidos, la ruta de validación `dHe()` retorna inmediatamente.
- `DEMOSTRADO` (estático) — extracto `CC-08`.
- `NO DEMOSTRADO`: que 2.1.299 emita realmente peticiones con un ID arbitrario de Zen **en el cable** (nunca ejecutado contra el proveedor).

### F-04 · Gateway model discovery (chunk `xywp7esx.js`)

- Condiciones: `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, proveedor `firstParty` (una `ANTHROPIC_BASE_URL` custom mantiene firstParty), `ANTHROPIC_BASE_URL` definido y alguna credencial.
- Petición: `GET {base sin barras finales}/v1/models?limit=1000` con `Authorization`/`x-api-key` + `anthropic-version` + UA; **los custom headers se aplican después y eliminan duplicados** (override case-insensitive).
- Filtro de ids: regex **`/claude|anthropic/i`**. Los ids que no lo pasan no aparecen en el selector. Cache: `gateway-models.json`.

**Implicación:** un adaptador (Ruta B) debe exponer ids con `claude` (p. ej. `claude-free-<zen-id>`) para aparecer en `/model`. `DEMOSTRADO` (estático) — extracto `CC-09`.

### F-05 · Validación al cambiar de modelo (chunk `jtbwa3j2.js`)

`opn(e,n)` bloquea en la superficie `model_switch` los ids no reconocidos (devuelve error con sugerencia). Los ids del discovery se asumen reconocidos (registro). `DEMOSTRADO` (estático) el bloqueo; `INFERIDO` que los ids del discovery pasan.

### F-06 · Telemetría `unrecognized_model` (chunk `84yp45y8.js`)

`IIo="[claude-code:unrecognized_model]"`; `sge()` emite `tengu_api_unrecognized_model` una vez por sesión. Es **señal de telemetría**, no bloqueo duro. `DEMOSTRADO` (estático; REA de ese chunk es parcial, solo facts estáticos) — extracto `CC-13`.

### F-07 · Endpoints auxiliares (chunks `gmq0qwep.js`, `84yp45y8.js`)

- `POST /v1/messages/count_tokens` (`?beta=true`): hay **fallback local** si falla — no es dependencia dura. `DEMOSTRADO` (estático).
- `POST /v1/messages/cache_touch`: keepalive (beta `cache-keepalive-2026-09-03`), cada ~30 s. `DEMOSTRADO` (estático) el uso; su comportamiento contra Zen: `NO DEMOSTRADO`.
- `POST /v1/messages/batches`: existe en el SDK; irrelevante para este caso.

### F-08 · Credenciales y cabeceras base

- Sin credencial → `throw K6e` (hay que definir `ANTHROPIC_API_KEY` o `ANTHROPIC_AUTH_TOKEN`, aunque sea placeholder). El mapeo es `apiKey → x-api-key`, `authToken → Authorization: Bearer`. `DEMOSTRADO` (estático) — extractos `CC-05`, `CC-16`.
- Cabeceras por petición: `Nl()` = `x-app`, `User-Agent: $0()` (`claude-cli/2.1.299 (external, cli)`), `X-Claude-Code-Session-Id`. `DEMOSTRADO` (estático).
- Betas: allowlist; base URL custom mantiene `firstParty` → betas normales se mantienen. `INFERIDO` (estático detallado en misión previa).

## 2. Lado OpenCode (cliente legítimo de Zen) — hallazgos de código

### F-09 · `@ai-sdk/openai-compatible` y credencial "public" (v1.19.3)

- Proveedor `openai-compatible`: `Authorization: Bearer ${apiKey}` y URL `${baseURL}${path}` → `POST {baseURL}/chat/completions`. `DEMOSTRADO` (estático) — extracto `OC-01`.
- Provider opencode sin credencial: se usa `apiKey:"public"` y **se eliminan del catálogo los modelos con coste > 0** (solo quedan gratuitos). Explica por qué el tier gratuito funciona dentro de OpenCode y por qué las sondas externas reciben `403 FreeTierError`. `DEMOSTRADO` (estático) — extracto `OC-02`.

## 3. Superficies de Zen y puerta FreeTier

### F-10 · Superficies

| Superficie | URL | Protocolo | Estado |
|---|---|---|---|
| OpenAI-compatible chat | `/inference/openai/v1/chat/completions` | OpenAI | `DOCUMENTADO` (gratuitos) |
| OpenAI Responses | `/inference/openai/v1/responses` | Responses | `DOCUMENTADO` (muse) |
| Anthropic (pagos) | `/inference/anthropic/v1/messages` | Anthropic | `DOCUMENTADO` (Claude/Qwen) |
| **Unificada Anthropic** | `/inference/v1/messages` | Anthropic | `DEMOSTRADO`: `space-bunny-free` → 200+SSE con puerta (curl, misión previa); `muse` → 400 `ModelProtocolUnsupported` |
| Catálogo público | `GET /inference/v1/models` | JSON | `DEMOSTRADO` |

### F-11 · Puerta FreeTier (DEMOSTRADO, misión previa)

Tres condiciones (cualquier otra combinación → `403 FreeTierError`):
1. `User-Agent: opencode/*` (cualquier versión).
2. Cabecera de sesión entre `x-opencode-session` / `x-session-id` / `x-session-affinity`, con valor `ses_*` **validado por valor**: 12 hex = 48 bits bajos de `~(ms*0x1000+contador)` (`IY(true)`, `Bce()`); IDs sin invertir → 403.
3. `tools` no vacío con nombres OpenCode `[bash, edit, glob, grep, read, write]`.

Descartados experimentalmente: IP/egress, huella TLS, HTTP/1.1 vs 2, `instructions`, `Authorization` (suprimible), resto de cabeceras.

### F-12 · Sondas anónimas de disponibilidad (16-oct)

Tres modelos gratuitos, petición anónima → `HTTP/2 403` + `{"type":"error","error":{"type":"FreeTierError",…}}`. Evidencia en `artifacts/probes/`. (`DEMOSTRADO`, endpoint exacto de la sonda no conservado.)

## 4. Traducción de protocolo Anthropic Messages ↔ OpenAI (diseño, Ruta B)

Diferencias estructurales que el adaptador debe cubrir (`DISEÑO`; detalles de mapeo en `ARCHITECTURE.md` §5):

| Aspecto | Anthropic Messages | OpenAI Chat Completions |
|---|---|---|
| System prompt | Campo `system` de primer nivel (string o bloques) | Mensaje `role:"system"` |
| Contenido | Lista de bloques (`text`, `image`, `tool_use`, `tool_result`, `thinking`) | String o lista de partes; `assistant.tool_calls`; `role:"tool"` |
| Herramientas | `tools[{name, description, input_schema}]` | `tools[{type:"function", function:{name, description, parameters}}]` |
| Resultado de tool | Bloque `tool_result` (`tool_use_id`) | Mensaje `role:"tool"` (`tool_call_id`) |
| Streaming | SSE tipado (`message_start`, `content_block_delta` con `text_delta`/`input_json_delta`, `message_delta`, `message_stop`) | SSE de chunks (`choices[].delta`, `tool_calls`) + `[DONE]` |
| `stop_reason` | `end_turn`, `tool_use`, `max_tokens` | `finish_reason`: `stop`, `tool_calls`, `length` |
| Usage | `input_tokens`, `output_tokens`, campos de caché | `prompt_tokens`, `completion_tokens` |
| `max_tokens` | Obligatorio | Opcional |
| Cache | `cache_control` en bloques | No existe |
| Conteo tokens | `POST /v1/messages/count_tokens` | No existe |
| Errores | `{"type":"error","error":{…}}` | `{"error":{…}}` |

El adaptador debe además: (a) normalizar nombres de tools a minúsculas del set OpenCode y revertir en la respuesta; (b) generar la cabecera de sesión `ses_*` válida (reutilizando el algoritmo invertido documentado en la misión previa); (c) inyectar UA `opencode/*`; (d) aplanar `cache_control` y descartar `thinking`; (e) mapear imágenes base64 a `image_url` con data-URI.

## 5. Rutas de integración

### Ruta A — Directa (solo variables de entorno)

```bash
export ANTHROPIC_BASE_URL=https://opencode.ai/inference        # sin /v1 (F-01)
export ANTHROPIC_AUTH_TOKEN=public
export ANTHROPIC_MODEL=space-bunny-free
export ANTHROPIC_DEFAULT_HAIKU_MODEL=glm-5.3-flash-free
export ANTHROPIC_CUSTOM_HEADERS="User-Agent: opencode/1.19.3
x-opencode-session: ses_<12hex-invertidos>…"
```

**Ventajas:** cero componentes nuevos; usa los mecanismos propios de 2.1.299 (custom headers, `mZe()`); sin proceso extra.

**Limitaciones:**
- Condición 3 de la puerta: CC envía sus tools con nombres capitalizados (`Bash`, `Read`, …); la puerta se demostró con minúsculas. **NO DEMOSTRADO** que los nombres capitalizados pasen (si es case-sensitive → 403).
- Aceptación por modelo en la superficie unificada: solo `space-bunny-free` demostrado. **NO DEMOSTRADO** el resto.
- `count_tokens`/`cache_touch` contra Zen: **NO DEMOSTRADO** (el fallback local de count_tokens está demostrado en código; cache_touch es no-fatal probablemente).
- Comportamiento real en el cable de 2.1.299: **NO DEMOSTRADO**.

### Ruta B — Adaptador local (preferida)

**Ventajas:**
- Controla la puerta al 100 % (UA, sesión, tools minúsculas) → elimina la incertidumbre de la condición 3.
- Homologa protocolos: soporta cualquier gratuito chat aunque no hable Anthropic (Zen traduce server-side o el modelo es OpenAI-only).
- Proporciona `count_tokens`, `cache_touch` y `/v1/models` (selector con ids `claude-free-*`).
- Observabilidad local (logs de traducción) y posibilidad de enrutar distintos modelos por tipo de tarea.

**Limitaciones:**
- Componente nuevo a mantener; latencia mínima añadida; hay que revisar los términos de uso de Zen (el adaptador replica el comportamiento del cliente OpenCode legítimo).
- **NO DEMOSTRADO**: todo el flujo E2E (no implementado, no probado).

## 6. Los dos puntos pendientes (mantener como NO DEMOSTRADO)

1. **Herramientas con nombres capitalizados.** CC envía `Bash`, `Read`, `Edit`, `Glob`, `Grep`, `Write`; la puerta se demostró con `[bash, edit, glob, grep, read, write]`. No se sabe si el servidor compara case-sensitive. Resolvería con una única petición controlada (o directamente con Ruta B, donde el adaptador normaliza).
2. **Comportamiento real de Claude Code 2.1.299 en el cable.** Está demostrado estáticamente (`mZe()`, custom headers, concatenación de URL), pero nunca se ha observado una petición real de 2.1.299 contra Zen. Ambas rutas dependen de esto para poder afirmar funcionamiento E2E.

Otros desconocidos: aceptación por-modelo individual en la superficie unificada; comportamiento de `count_tokens`/`cache_touch` en Zen; endpoint exacto de las sondas `403`.

## 7. Recomendación (separada de los hechos y de las alternativas)

- **Hechos:** protocolo y puerta demostrados; ni Ruta A ni Ruta B han funcionado de extremo a extremo con Claude Code (nunca probado).
- **Recomendación técnica preliminar:** implementar la **Ruta B** si se decide seguir; es la única que neutraliza los dos pendientes sin depender de comportamiento no verificado del servidor (nombres de tools y aceptación de IDs quedan bajo control del adaptador). La Ruta A puede probarse primero como validación barata de una sola petición si se autoriza.
- **Modelo:** empezar por `space-bunny-free` (único con 200+SSE demostrado en la superficie Anthropic unificada); candidato principal para agente de código `deepseek-v4.1-flash-free`; tareas de fondo con `glm-5.3-flash-free` o `longcat-2.5-preview-free`; evitar `muse-spark-1.3-contributor-free` (Responses-only).
- **Alternativas:** cualquier otro gratuito con `tools=True` del catálogo (`artifacts/catalogs/models.dev-opencode-provider.json`); o usar OpenCode como harness (ya funciona con gratuitos) si no se necesitan las funciones específicas de Claude Code.

La recomendación es una **opinión de diseño**, no un hecho demostrado; la validación requiere `TEST-PLAN.md` con autorización explícita.
