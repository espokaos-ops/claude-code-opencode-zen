# Implementation Plan — Ruta B (adaptador)

> **Nada de este plan está implementado.** Es el diseño de componentes, dependencias y secuencia. La ejecución requiere autorización explícita para las pruebas contra el proveedor (ver `TEST-PLAN.md`). Claude Code **no se modifica**: toda la configuración es por variables de entorno.

## 1. Principio de diseño

- **Cero parches a Claude Code.** Solo `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_*_MODEL`, `ANTHROPIC_CUSTOM_HEADERS` y `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY`.
- **Cero dependencias externas obligatorias.** El MVP usa el runtime estándar (Node ≥ 18 con `fetch`/`ReadableStream`, o Python 3.11 stdlib). Las dependencias de desarrollo (test runner, lint) son opcionales.
- **Sin persistencia de prompts.** Logs estructurados con redacción por defecto.

## 2. Componentes

```
adaptador/
├── server.(m)js            # HTTP local (127.0.0.1:8787): 4 endpoints
├── routes/
│   ├── messages.(m)js      # POST /v1/messages (+?beta=true) → SSE Anthropic
│   ├── count_tokens.(m)js  # POST /v1/messages/count_tokens → estimación local
│   ├── cache_touch.(m)js   # POST /v1/messages/cache_touch → 200 {}
│   └── models.(m)js        # GET /v1/models → ids claude-free-<zen>
├── translate/
│   ├── request.(m)js       # Anthropic Messages → OpenAI Chat Completions
│   ├── stream.(m)js        # SSE OpenAI → SSE Anthropic
│   └── errors.(m)js        # errores OpenAI → errores Anthropic
├── gate/
│   ├── session-id.(m)js    # generador ses_* (algoritmo invertido, ver §3.1)
│   ├── tool-names.(m)js    # normalización a [bash, edit, glob, grep, read, write] + mapa inverso
│   └── upstream.(m)js      # cliente Zen: Bearer, UA, sesión, reintentos
├── model-map.(m)js         # claude-free-<zen> ↔ <zen>, defaults haiku/fondo
└── config.(m)js            # PORT, ZEN_BASE_URL, ZEN_API_KEY (opcional), modelos por defecto
```

### 2.1 Endpoints que expone el adaptador (contrato con Claude Code)

| Método | Ruta | Respuesta | Notas |
|---|---|---|---|
| POST | `/v1/messages` (+`?beta=true`) | SSE Anthropic | `stream:true` siempre desde CC; soportar también no-stream por completitud |
| POST | `/v1/messages/count_tokens` | `{input_tokens: number}` | estimación local (CC tiene fallback si falla) |
| POST | `/v1/messages/cache_touch` | `200 {}` | no-op; el keepalive de CC no debe romper la sesión |
| GET | `/v1/models` | `{data:[{id:"claude-free-…", display_name, description}]}` | para `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`; el filtro de CC es `/claude\|anthropic/i` |

### 2.2 Traducciones (puras, testeables sin red)

- **Petición:** `system` (string/bloques) → mensaje system; `messages` (text/tool_use/tool_result/image/thinking) → roles OpenAI; `tools[].input_schema` → `parameters`; `tool_choice` (`auto|any|tool`) → `auto|required|function`; `stop_sequences` → `stop`; eliminar `cache_control`; descartar `thinking`.
- **Respuesta:** chunks `delta.content` → `content_block_delta.text_delta`; `delta.tool_calls` → bloque `tool_use` + `input_json_delta`; `[DONE]`/`finish_reason` → `message_delta` + `message_stop`; `stop`→`end_turn`, `tool_calls`→`tool_use`, `length`→`max_tokens`; usage `prompt_/completion_tokens` → `input_/output_tokens`.
- **Errores:** `{"error":{…}}` OpenAI → `{"type":"error","error":{…}}` Anthropic con status mapeado (401, 403, 404, 429, 500, 529).

### 2.3 Puerta FreeTier (salida hacia Zen)

- Cabeceras obligatorias en cada petición upstream: `User-Agent: opencode/<versión>` (p. ej. `opencode/1.19.3`), `x-opencode-session: ses_<valor válido>`, `Authorization: Bearer public` (o clave del usuario).
- `tools` normalizadas a minúsculas dentro del set OpenCode; el set por defecto de CC mapea 1:1 (`Bash, Read, Edit, Glob, Grep, Write` → las 6 exigidas), de modo que la condición 3 queda garantizada.
- Keepalive: el adaptador puede renovar el `ses_*` según `IY(true)`/`Bce()` (algoritmo de §3.1) y mantener la misma sesión durante la conversación.

## 3. Piezas críticas

### 3.1 Generador de `ses_*` (reutilizar el diseño de la misión previa)

- Puerto fiel del algoritmo del cliente OpenCode: `n = BigInt(ms)*0x1000n + BigInt(contador)`, id = forma oficial con los **12 hex = 48 bits bajos de `~n`** y sufijo base62.
- La misión previa ya implementó y probó esta pieza (`_new_opencode_id`, tests 6/6 en verde; ver `artifacts/reports/INFORME-TRANSFORMER-OPENCODE-ZEN.md` §5). El adaptador la reutiliza como módulo aislado con sus tests.
- IDs oficiales capturados (válidos por valor) funcionaron como control positivo; los "frescos sin invertir" dieron 403 (evidencia de validación por valor).

### 3.2 Enrutado de modelos

- Id externo (lo que ve CC): `claude-free-<zen-id>` (contiene `claude` → pasa el filtro del discovery).
- `ANTHROPIC_MODEL=claude-free-space-bunny-free` para el modelo principal; `ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-free-glm-5.3-flash-free` para tareas de fondo (títulos, resúmenes).
- `muse-spark-1.3-contributor-free` queda fuera del mapa por defecto (Responses-only); si se quiere soportar, añadir una ruta de traducción extra a `/openai/v1/responses` (fase posterior).

### 3.3 Flujo de datos interno

```
POST /v1/messages
   → parsear cuerpo Anthropic
   → resolver modelo (claude-free-* → zen-id) y rechazar desconocidos con error Anthropic 404
   → traducir a OpenAI (incluye normalización de tools)
   → POST {ZEN}/chat/completions (stream) con puerta inyectada
   → transformar SSE chunk a chunk
   → cerrar con message_delta + message_stop
```

## 4. Dependencias y entorno

| Elemento | Decisión | Motivo |
|---|---|---|
| Runtime | Node ≥ 18 **o** Python 3.11 | stdlib suficiente (HTTP + SSE + fetch) |
| Dependencias npm/pip | **Ninguna** para el MVP | menú mínimo, superficie de fallo mínima |
| Red saliente | Solo `opencode.ai` | por diseño |
| Puertos | 127.0.0.1:8787 (configurable) | solo loopback; nunca exponer |
| Secretos | `ZEN_API_KEY` opcional (tier de pago); para el gratuito `public` | el tier gratuito no requiere credencial |
| Claude Code | Sin cambios; solo env | restricción de la investigación |

## 5. Secuencia propuesta

| Fase | Entregable | Validación | Requiere red |
|---|---|---|---|
| 0 | Estructura + config + esqueletos | lint/unit vacíos | No |
| 1 | `gate/session-id` portado de Freya | tests unitarios (forma, timestamp, inversión) | No |
| 2 | `translate/*` (puras) | tests con fixtures JSON documentados (Anthropic ↔ OpenAI) | No |
| 3 | `server` + rutas con upstream simulado (fixture local SSE) | smoke test E2E local: CC (o curl imitando a CC) contra el adaptador | No |
| 4 | `gate/upstream` real + ruta `/v1/messages` | **1 petición** a `space-bunny-free` (requiere autorización) | Sí (mínima) |
| 5 | Claude Code 2.1.299 con HOME aislado | 1 conversación corta (2 turnos) | Sí |
| 6 | Discovery + selector | `/model` lista `claude-free-*`; cambio de modelo sin `unrecognized_model` | Sí |
| 7 | Tool loop completo | test de una llamada de herramienta ida/vuelta (p. ej. `Read`) | Sí |
| 8 | Multi-modelo + haiku de fondo + errores (429/529) | matriz de `TEST-PLAN.md` | Sí |

Criterio de parada temprana: cualquier 403/400 inesperado en fase 4 → detener y re-evaluar antes de tocar Claude Code (minimiza coste/cuota).

## 6. Riesgos y mitigaciones

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| La puerta cambia de algoritmo (`ses_*`) | Media | módulo aislado con tests; control positivo con sesión oficial capturada |
| El servidor no acepta la conversación traducida (calidad de tool-loop) | Media | empezar con `deepseek-v4.1-flash-free` / `space-bunny-free`; matriz progresiva |
| Deriva de protocolo (OpenAI SSE imperfecto) | Media | tolerancia a chunks parciales; tests de stream con fixtures reales mínimo-coste |
| Límites de rate/uso del tier gratuito | Media | reintentos con backoff respetando 429; una petición por prueba |
| Términos de uso de Zen | — | revisar antes de publicar/uso continuado; el adaptador replica el cliente oficial |
