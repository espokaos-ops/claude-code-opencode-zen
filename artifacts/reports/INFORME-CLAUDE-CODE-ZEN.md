# INFORME — Claude Code × OpenCode Zen

- **Fecha:** 16 oct 2026
- **Objetivo de la misión:** determinar (solo lectura, con REA/Ghidra) si **Claude Code 2.1.299** puede usar los **modelos gratuitos de OpenCode Zen**, conservando selector de modelo y funciones habituales; y **diseñar el adaptador Anthropic↔OpenAI** como componente imprescindible (decisión del usuario: "ampliar diseño con adaptador").
- **Método:** análisis estático REA de los binarios instalados (`~/.opencode/bin/opencode` v1.19.3; `~/.local/share/claude/versions/2.1.299`), `webfetch` de documentación pública, y lectura de los informes locales de la serie Zen.
- **Restricciones respetadas:** sin peticiones de prueba a Zen (no autorizadas), sin instalaciones, sin modificar configs del sistema, sin exponer credenciales. Este informe es **diseño**: el adaptador no se ha construido ni ejecutado.
- **Leyenda de clasificación:** `[DEMOSTRADO]` evidencia directa (código del artefacto, captura o prueba previa documentada) · `[DOCUMENTADO]` doc oficial · `[INFERIDO]` derivado razonado, no verificado en wire · `[NO DEMOSTRADO]` pendiente de verificación empírica.

---

## 1. Resumen ejecutivo

1. **Claude Code 2.1.299 es "Anthropic Messages de principio a fin"**: SDK embebido con path fijo `/v1/messages`, auth flexible (`x-api-key` o `Bearer`) y beta headers. En 2.1.299 **añade discovery de gateways** (`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY`) y **omite la validación de modelo** cuando hay variables `ANTHROPIC_MODEL`/`ANTHROPIC_DEFAULT_*_MODEL` definidas (`mZe()`), lo que corrige el "bloqueo 2" que impedía apuntar 2.1.296 a IDs de Zen. `[DEMOSTRADO]` (estático)
2. **Zen sirve los gratuitos, pero por endpoints OpenAI** (`@ai-sdk/openai-compatible`, `/inference/openai/v1/chat/completions`) según documentación oficial; además existe una **superficie unificada Anthropic** (`/inference/v1/messages`) que sirvió `space-bunny-free` con **200 + SSE** (con la puerta FreeTier satisfecha, probado por curl en misión previa). `muse-spark-1.3-contributor-free` es **Responses-only** → 400 `ModelProtocolUnsupported`. `[DEMOSTRADO]`/`[DOCUMENTADO]`
3. **La puerta FreeTier de Zen** exige 3 condiciones (UA `opencode/*`; cabecera de sesión; `tools` con nombres OpenCode). Claude Code puede inyectar UA y sesión vía `ANTHROPIC_CUSTOM_HEADERS`, pero **los nombres de tools van capitalizados por CC** (`Bash`, `Read`…), dejando la condición 3 en duda. `[DEMOSTRADO]` (mecanismo) + `[NO DEMOSTRADO]` (caso CC real)
4. **Diseño recomendado — Ruta B (adaptador local)**: un pequeño servidor Anthropic Messages → OpenAI chat que traduce protocolo, mapea IDs, inyecta la puerta y ordena los nombres de tools. La **Ruta A directa** (solo variables de entorno, sin intermediario) queda documentada como alternativa frágil y sujeta a los puntos NO DEMOSTRADO.

---

## 2. Superficies de Zen relevantes

| Superficie | URL | Protocolo | Auth | Estado |
|---|---|---|---|---|
| OpenAI-compatible chat | `https://opencode.ai/inference/openai/v1/chat/completions` | OpenAI | `Authorization: Bearer public` (o clave) | `[DOCUMENTADO]` para gratuitos |
| OpenAI Responses (muse) | `https://opencode.ai/inference/openai/v1/responses` | Responses | idem | `[DOCUMENTADO]` |
| Anthropic (pagos, docs) | `https://opencode.ai/inference/anthropic/v1/messages` | Anthropic | idem | `[DOCUMENTADO]` (Claude y Qwen pagos) |
| **Unificada Anthropic** | `https://opencode.ai/inference/v1/messages` | Anthropic | idem | `[DEMOSTRADO]` 200+SSE con `space-bunny-free` (curl, misión previa); muse → 400 `ModelProtocolUnsupported` |
| Lista pública de modelos | `GET https://opencode.ai/inference/v1/models` | `{object:"list",data:[{id,…}]}` | **sin auth** | `[DEMOSTRADO]` (consulta directa esta misión) |

- La puerta FreeTier aplica a todas las superficies: sin las 3 condiciones → `403 FreeTierError` ("OpenCode's free tier can only be used from within OpenCode. Download it at https://opencode.ai and keep building."). Confirmado de nuevo con sondas locales del 16 oct 15:01 UTC (`/tmp/opencode/avail_*.json`, endpoint exacto de la sonda desconocido).
- Ojo: el bloqueo actual de esas sondas (403) **no prueba** que la superficie Anthropic rechace gratuitos; la misión previa demostró 200+SSE a `space-bunny-free` **con** la puerta satisfecha. `[DEMOSTRADO]`
- **12 gratuitos activos** (snapshot `~/.cache/opencode/models.json`; provider `{api:"https://opencode.ai/inference/openai/v1"}`): `longcat-2.5-preview-free`, `space-bunny-free`, `ll-alpha-free`, `mimo-v2.6-flash-free`, `nemotron-3-ultra-free`, `glm-5.3-flash-free`, `nemotron-3.5-lightning-free`, `nemotron-3.5-super-vl-free`, `deepseek-v4.1-flash-free`, `beam-free`, `big-pickle`, `muse-spark-1.3-contributor-free`. Todos `tools=True reasoning=True`; contexto 200k–1M. Los gratuitos con ruta Anthropic (`qwen3.6-plus-free`, `minimax-*-free`) están **deprecados** en el snapshot. `[DEMOSTRADO]` (datos locales)

La puerta FreeTier (de `INFORME-TRANSFORMER-OPENCODE-ZEN.md`, bisectada con curl):
1. `User-Agent: opencode/*` — cualquier versión.
2. Cabecera de sesión: `x-opencode-session`, `x-session-id` o `x-session-affinity` (cualquiera válida). El ID `ses_*` **se valida por valor**: 12 hex = 48 bits bajos de `~(ms*0x1000+contador)` (`IY(e,r=Date.now())`, `Bce()=IY(true)`); IDs frescos "sin invertir" → 403. `[DEMOSTRADO]`
3. `tools` no vacío con nombres OpenCode: `[bash, edit, glob, grep, read, write]` basta.
- `Authorization` es **suprimible** (la puerta no lo exige). `[DEMOSTRADO]`

---

## 3. Claude Code 2.1.299 — comportamiento relevante (hallazgos REA)

Todo lo de esta sección es análisis estático de `claude_js` (2.1.299); los chunks citados viven en `/tmp/opencode/re/claude_js/root/`.

- **Cliente y credenciales** (`chunk-gmq0qwep.js`): factory `jF({apiKey, authToken, …})` construye el cliente SDK. Si no hay `apiKey`, `authToken` (OAuth) ni token de otro origen → `throw K6e` (hay que configurar alguna credencial, aunque sea placeholder). Cabeceras: `apiKey` → `x-api-key`; `authToken` → `Authorization: Bearer`; validación de colisiones en `aCr(...)`. `[DEMOSTRADO]`
- **`ANTHROPIC_CUSTOM_HEADERS`** (`chunk-gmq0qwep.js`): parseado por `ive()`/`$Mt()` (pares `Nombre: Valor`; `anthropic-beta` custom se ignora si la política de betas experimentales está deshabilitada). Se fusiona como `ee = {...Nl(), ...te, ...n$(), …}` — al ir **después** de `Nl()`, un `User-Agent` propio en custom headers **sobrescribe** el UA de CC. `[DEMOSTRADO]` (estático)
- **Cabeceras por defecto de cada petición**: `Nl()` = `{"x-app": "cli"/"cli-bg", "User-Agent": $0(), "X-Claude-Code-Session-Id": q()}` con `$0() = "claude-cli/2.1.299 (external, cli)"` (+ sufijos opcionales agent-sdk/client-app/workload). `kDt="X-Claude-Code-Session-Id"`. `[DEMOSTRADO]`
- **Base URL**: el SDK concatena `baseURL + path` sin normalizar (`buildURL`); paths observados: `/v1/messages`, `/v1/messages?beta=true`, `/v1/messages/count_tokens` (`?beta=true`), `/v1/messages/batches`, `/v1/messages/cache_touch`. Conclusión: **`ANTHROPIC_BASE_URL` no debe terminar en `/v1`** — con `…/inference/v1` el POST saldría a `…/inference/v1/v1/messages`. La config de la misión del 13 oct (`…/inference/v1`) nunca se validó en wire con CC (el cliente bloqueó antes por el ID de modelo); sus pruebas de protocolo fueron curl directo a `/inference/v1/messages`. `[DEMOSTRADO]` (concat) + `[INFERIDO]` (corrección de la config previa)
- **Discovery de modelos** (`chunk-xywp7esx.js`): requiere `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, proveedor firstParty, `ANTHROPIC_BASE_URL` definido y credencial; hace `GET {base sin barras finales}/v1/models?limit=1000` con `Authorization`/`x-api-key` + `anthropic-version` + UA, **custom headers con override** (borra duplicados case-insensitive); filtra los ids con regex **`/claude|anthropic/i`** y cachea en `gateway-models.json`. `[DEMOSTRADO]`
- **Validación de modelo omitida**: `mZe()` en `chunk-1qwezzd3.js` devuelve `true` si `ANTHROPIC_MODEL` o `ANTHROPIC_DEFAULT_{FABLE,OPUS,SONNET,HAIKU}_MODEL` (u otras) están definidos; `dHe(...)` retorna de inmediato cuando `mZe()`. Esto es lo que en 2.1.296 faltaba: allí el cliente rechazó el ID desconocido (`[claude-code:unrecognized_model]`, `behavesAs` no surtía efecto). `[DEMOSTRADO]` (estático)
- **Validación al cambiar de modelo** (`chunk-jtbwa3j2.js`): `opn(e,n)` bloquea IDs no reconocidos en la superficie `model_switch` (error devuelto). Los IDs descubiertos por gateway se asumen "reconocidos" por el registro → un adaptador que sirva `/v1/models` con IDs que pasen el filtro `claude|anthropic` es la vía limpia para el selector. `[DEMOSTRADO]` (bloqueo) + `[INFERIDO]` (reconocidos vía discovery)
- **Telemetría** `unrecognized_model` (`chunk-84yp45y8.js`, REA parcial): `IIo="[claude-code:unrecognized_model]"`, `sge()` emite señal `tengu_api_unrecognized_model` (una vez por sesión) — es señal, no bloqueo. `[DEMOSTRADO]` (estático; cobertura parcial)
- **count_tokens / cache_touch**: CC usa `POST /v1/messages/count_tokens` con **fallback local** si falla (no dependencia dura); `cache_touch` (`/v1/messages/cache_touch`) es keepalive de 30s (beta `cache-keepalive-2026-09-03`). `[DEMOSTRADO]` (estático)
- **Betas**: registry + allowlist; base URL custom mantiene `firstParty` → los betas normales se mantienen; modelo desconocido → solo `claude-code-20250219` probable. `[DEMOSTRADO]`/`[INFERIDO]`
- **Mantle** = "Amazon Bedrock (Mantle)" (`chunk-4jswj7c0.js`) — no aplica a este caso.

---

## 4. Arquitectura de las dos rutas

### Ruta A — Directa (sin intermediario)

```
Claude Code 2.1.299 ──(Anthropic Messages + gate)──▶ https://opencode.ai/inference/v1/messages ──▶ modelo gratuito
```

Configuración mínima (todo por entorno; nada que parchear):

```bash
export ANTHROPIC_BASE_URL=https://opencode.ai/inference        # SIN /v1 (el SDK añade /v1/messages)
export ANTHROPIC_AUTH_TOKEN=public                             # evita el throw K6e; la puerta no lo exige
export ANTHROPIC_MODEL=space-bunny-free                        # o cualquier chat gratuito (ver §2)
export ANTHROPIC_DEFAULT_HAIKU_MODEL=glm-5.3-flash-free        # tareas de fondo
export ANTHROPIC_CUSTOM_HEADERS="User-Agent: opencode/1.19.3
x-opencode-session: ses_<12hex-invertidos>…"                   # UA + sesión válidos (formato del informe previo)
```

- Cubre: el modelo (por `mZe()`), el UA y la sesión de la puerta 1–2.
- **NO DEMOSTRADO (bloqueantes o semibloqueantes):**
  1. **Condición 3 de la puerta**: CC envía sus tools capitalizadas (`Bash`, `Read`, `Edit`, `Glob`, `Grep`, `Write`…). Si la puerta compara nombres case-sensitive contra `[bash, edit, glob, grep, read, write]`, la petición será 403. (Contrapueba de la puerta: satisfecha con nombres minúsculos; caso de CC nunca probado.) Nótese que el mapeo minúsculas de las 6 herramientas de CC **es exactamente** el set exigido — el adaptador lo explota; en directo depende de la sensibilidad a mayúsculas del servidor. `[NO DEMOSTRADO]`
  2. **Aceptación por modelo** en la superficie unificada: solo `space-bunny-free` tiene 200+SSE demostrado; el resto de gratuitos chat, uno por uno, no. `muse` está descartado (Responses-only). `[NO DEMOSTRADO]`
  3. `count_tokens` y `cache_touch` en Zen: comportamiento desconocido (404/handling). El fallback local de CC existe; el keepalive podría fallar de forma no fatal. `[NO DEMOSTRADO]`
  4. Confirmación en wire de que 2.1.299 emite la petición con IDs arbitrarios (estático sí; runtime nunca observado). `[NO DEMOSTRADO]`

### Ruta B — Adaptador local Anthropic↔OpenAI (diseño elegido)

```
Claude Code 2.1.299 ──Anthropic Messages──▶ 127.0.0.1:8787 (adaptador)
                                               │  • mapea ID claude-free-<zen> → <zen>
                                               │  • traduce Anthropic ⇄ OpenAI (SSE)
                                               │  • inyecta puerta: UA opencode/*, ses_*, tools OpenCode
                                               ▼
                              https://opencode.ai/inference/openai/v1/chat/completions ──▶ modelo gratuito
```

**Endpoints que expone el adaptador** (lo que CC pide):

| Ruta local | Función | Respuesta |
|---|---|---|
| `POST /v1/messages` (+`?beta=true`) | petición principal (siempre `stream:true`) | SSE Anthropic traducido |
| `POST /v1/messages/count_tokens` | conteo de tokens | estimación local (`{input_tokens}`) |
| `POST /v1/messages/cache_touch` | keepalive 30s | `200 {}` (no-op) |
| `GET /v1/models` | selector (`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`) | `{data:[{id:"claude-free-<zen>",…}]}` → pasa el filtro `/claude|anthropic/i` |

**Traducción de petición (Anthropic → OpenAI):**

- `system` (string o bloques) → mensaje `system`; se elimina `cache_control`.
- `messages`: `text` → contenido; `tool_use` → `assistant.tool_calls[{id,type:"function",function:{name,arguments:JSON}}]`; `tool_result` → mensaje `role:"tool"` con `tool_call_id`; imagen base64 → `{type:"image_url",image_url:{url:"data:<mime>;base64,…"}}`; bloques `thinking` → descartar.
- `tools[{name,description,input_schema}]` → `[{type:"function",function:{name,description,parameters}}]`, **normalizando nombres a minúsculas** dentro del set OpenCode (`bash, edit, glob, grep, read, write`) y guardando el mapa inverso nombre→original para la respuesta. Las 6 tools por defecto de CC mapean 1:1; tools MCP extra se conservan tal cual.
- `tool_choice` (`auto|any|tool`) → `auto|required|{type:"function",…}`; `max_tokens`, `temperature`, `top_p`, `stop_sequences`→`stop`, `metadata` passthrough.

**Traducción de respuesta (OpenAI SSE → Anthropic SSE):** secuencia que CC consume:

```
message_start {message:{id:"msg_…",role:"assistant",model:<id-pedido>,content:[],usage:{input_tokens,output_tokens:0}}}
content_block_start {index, content_block:{type:"text"|…}} / content_block_delta {text_delta|input_json_delta} / content_block_stop
message_delta {delta:{stop_reason,stop_sequence:null}, usage:{output_tokens}} → message_stop
ping (keepalive opcional)
```

- `finish_reason`: `stop`→`end_turn`; `tool_calls`→`tool_use`; `length`→`max_tokens`.
- Usage: `prompt_tokens`→`input_tokens`; `completion_tokens`→`output_tokens`; campos de caché a 0/ausentes.
- Errores: JSON OpenAI → `{type:"error",error:{type,message}}` con el status mapeado; `429`/`529` reenviados.

**Inyección de la puerta (salida hacia Zen):**

- `Authorization: Bearer public` (o clave del usuario), `User-Agent: opencode/<ver>`, `x-opencode-session: ses_<válido>`.
- Generación del `ses_`: **reutilizar `_new_opencode_id` de Freya** (inversión `~n` + contador por milisegundo; tests 6/6 en verde en `INFORME-TRANSFORMER-OPENCODE-ZEN.md` §5). También vale una sesión oficial capturada (probado 200 en informe previo).
- `tools` minúsculas garantizadas (ver arriba). No se envía `instructions` especial: es irrelevante para la puerta (demostrado en misión previa).

**Configuración de Claude Code para la Ruta B:**

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787      # el SDK pedirá /v1/messages aquí
export ANTHROPIC_AUTH_TOKEN=placeholder               # solo para pasar el chequeo K6e local
export ANTHROPIC_MODEL=claude-free-space-bunny-free
export ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-free-glm-5.3-flash-free
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1   # el selector lista los ids del adaptador
```

**Ventajas frente a Ruta A:** control total de la puerta (UA/sesión/tools), IDs siempre aceptados, protocolo homologado (incluidos `count_tokens`/`cache_touch`), posibilidad de enrutar por modelo, y observabilidad local. **Coste:** proceso extra, latencia mínima, mantenimiento y revisar los términos de uso de Zen (el adaptador replica un cliente OpenCode; es la misma puerta que el CLI oficial usa para el tier gratuito).

---

## 5. Obstáculos y desconocidos (resumen honesto)

1. Condición 3 de la puerta con nombres capitalizados de CC → 403 posible en Ruta A. `[NO DEMOSTRADO]`
2. Aceptación por modelo de la superficie unificada Anthropic (solo `space-bunny-free` demostrado; `muse` rechazado). `[NO DEMOSTRADO]`
3. `count_tokens`/`cache_touch` en Zen (Ruta A). `[NO DEMOSTRADO]`
4. Comportamiento en wire de 2.1.299 con `ANTHROPIC_MODEL` arbitrario (estático: sí por `mZe()`). `[NO DEMOSTRADO]`
5. El "bloqueo 2" de 2.1.296 (`unrecognized_model`) no re-probado en 2.1.299; `mZe()` cubre la ruta de arranque/resume, pero la superficie `model_switch` sin discovery sigue validando. `[DEMOSTRADO]` (código) / `[NO DEMOSTRADO]` (runtime)
6. REA del bundle principal (`chunk-84yp45y8.js`, 4.88 MB) es **parcial** (grafo semántico excedió presupuesto; solo facts estáticos). Cualquier conclusión que dependa de ese chunk es estática.
7. Endpoint exacto de las sondas `403` del 16 oct desconocido (solo se conservaron respuestas).

---

## 6. Referencias REA

claude_js (2.1.299) — digest `6beba69e0fe50575e17eeeada18c2d6b18a9df0d02da5d51db2576fe0060dc5a`:

- `ev_71fa3fd807993cc24a2e362ea9dd886fa28597a7c393a664f0a97e8abdab7602` (vista `ev_b60b59d90181b33eaa1dc852cb38b233950363f251e149ffac086b378a044cf6`) — OK: `xywp7esx` (credenciales, discovery, UA), `s2t7g8m9` (betas), `yz8yf8mg` (3p-probe), `rshryz75` (endpoint custom).
- `ev_951be01a189eb5d7f21eb59cad143f8e55231cc5ddd5c4362fd13434e107d61f` (vista `ev_7ecab1c0c2dcf1b722128a28f0feb732e94f36c5d11bc382e7af3348f1367103`) — OK: `gmq0qwep` (SDK Anthropic embebido, `jF`, `Nl()`, `$Mt()`), `4jswj7c0` (gateway/count_tokens, hosts), `b47tzzqx`, `am9nyq9j`.
- `ev_a1d31ff12d823775a28d2520329062c169d127d853bf3b52b93d8240d54e5b7c` (vista `ev_f01a4b7c2900cdd97853027f5425fb42cf2972a037f755380e1bdd99571c299e`) — **partial** (solo facts estáticos): `84yp45y8` (bundle principal, `IIo`/`sge`, `cache_touch`, countTokens `qLe`/`Tao`).
- `ev_464fbae3f109132e46257628eec6ad62ac30cc01651c930c404d6beafb2eedd1` — obsoleto/superado (primer intento de importación del grafo completo).
- Abiertos de esta misión: `chunk-1qwezzd3.js` (`mZe()`/`dHe`), `chunk-jtbwa3j2.js` (validación `model_switch` / `unrecognized_model`), `chunk-sqb9meyh.js` (`ya()` base URL, `TG`), `chunk-z11rpmzg.js` (CCR), `chunk-0ats23mq.js` (posible manejo `/v1`).

opencode (v1.19.3):

- `ev_832ca0ed40a310c2a2ccc56c2fbe771ebcf815974d71c4dbda24d1c86ec909e7` (vista `ev_97eddf0d3cacccfc633a5c0f6d665fd7bcad0fef63884a3c95c478a4237d6646`) — OK: catálogo Zen y `@ai-sdk/openai-compatible` (`Authorization: Bearer`, `/chat/completions`).

Evidencia previa citada (no REA de esta misión):

- `INFORME-TRANSFORMER-OPENCODE-ZEN.md` §5 (puerta FreeTier, algoritmo `ses_`), §6 (CC 2.1.296: bloqueos 1–2 y contrapueba `space-bunny-free` 200+SSE), §7 (interfaz mínima).
- `FREYA-MUSE-ZEN-INTEGRATION.md` (§5: `_new_opencode_id`, tests 6/6).
- Docs oficiales: `https://opencode.ai/v2/docs/console/models/` (tabla de endpoints); `https://opencode.ai/inference/v1/models` (lista pública).

---

## 7. Procedimiento de prueba propuesto (NO ejecutado — requiere autorización)

Cuando el usuario autorice, el orden de menor a mayor coste:

1. **Ruta A, 1 petición mínima** (1 modelo ya demostrado, `space-bunny-free`): lanzar CC 2.1.299 con el entorno de §4-Ruta A en HOME aislado y observar solo la respuesta HTTP local (¿200/SSE vs 403 FreeTierError vs 400?). Permite resolver de una vez: sensibilidad a mayúsculas de la condición 3 y emisión de IDs en 2.1.299.
2. **Ruta A con `ANTHROPIC_CUSTOM_HEADERS` incluyendo tools no controlables → decidir**: si 403, la Ruta B pasa a ser la única vía realista.
3. **Ruta B**: implementar el adaptador (Freya ya tiene la pieza de IDs y el adaptador de tools de OpenCode como referencia), smoke test local sin red (SSE sintético), y después 1 petición real por modelo.
4. **Selector**: con `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, verificar que el picker lista `claude-free-*` y que el cambio de modelo no dispara `unrecognized_model`.

Criterios de aborto: cualquier 403/400 inesperado → parar y reevaluar sin reintentos (evitar coste/cuota).

---

## 8. Pendientes

- [ ] Autorización (o no) de la prueba mínima de §7.1.
- [ ] Verificar en wire la emisión de IDs arbitrarios por 2.1.299 (`mZe()` estático ya demostrado).
- [ ] Cerrar la duda de nombres de tools capitalizados en la puerta.
- [ ] Implementar el adaptador si se aprueba la Ruta B (reutilizar `_new_opencode_id` de Freya).
- [ ] Probar el resto de gratuitos uno por uno en la superficie elegida (solo `space-bunny-free` E2E en informe previo).
