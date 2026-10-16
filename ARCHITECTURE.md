# Arquitectura

Este documento describe la arquitectura de las dos rutas de integración y los flujos de petición/respuesta. Todos los diagramas son **diseño**; el estado de demostración de cada pieza está en `FINDINGS.md` y `EVIDENCE.md`.

## 1. Vista general

```mermaid
flowchart LR
    subgraph Local["Host del usuario"]
        CC["Claude Code 2.1.299\n(harness Anthropic Messages)"]
        AD["Ruta B:\nAdaptador local\nAnthropic ↔ OpenAI\n127.0.0.1:8787"]
    end

    subgraph Zen["opencode.ai (Zen)"]
        U["Superficie unificada\n/inference/v1/messages\n(protocolo Anthropic)"]
        O["OpenAI-compatible\n/inference/openai/v1\n(chat/completions · responses)"]
        A["Anthropic documentada\n/inference/anthropic/v1/messages\n(pagos Claude/Qwen)"]
        MOD["Catálogo público\nGET /inference/v1/models"]
    end

    GT{"Puerta FreeTier\nUA opencode/*\n+ ses_* válida\n+ tools OpenCode"}

    CC -- "Ruta A: envs\nANTHROPIC_BASE_URL\n+ CUSTOM_HEADERS" --> U
    CC -- "Ruta B: /v1/messages" --> AD
    AD -- "chat/completions\n+ puerta inyectada" --> O
    U --> GT
    O --> GT
    A --> GT
    CC -. "discovery (opcional)\nGET /v1/models" .-> MOD
    AD -. "expone /v1/models\n(ids claude-free-*)" .-> CC
```

- **Ruta A**: Claude Code habla directo con la superficie unificada Anthropic de Zen, configurado solo con variables de entorno.
- **Ruta B**: Claude Code habla con el adaptador local (protocolo Anthropic nativo); el adaptador habla OpenAI-compatible con Zen e inyecta la puerta FreeTier.

## 2. Ruta A — secuencia (diseño)

```mermaid
sequenceDiagram
    participant CC as Claude Code 2.1.299
    participant Z as Zen /inference/v1/messages

    Note over CC: env: ANTHROPIC_BASE_URL=https://opencode.ai/inference<br/>ANTHROPIC_AUTH_TOKEN=public<br/>ANTHROPIC_MODEL=space-bunny-free<br/>ANTHROPIC_CUSTOM_HEADERS: User-Agent opencode/*, x-opencode-session ses_*
    CC->>CC: SDK buildURL: baseURL + "/v1/messages"
    CC->>Z: POST /inference/v1/messages (SSE, anthropic-version 2023-06-01)<br/>headers: UA custom, ses_*, x-app, X-Claude-Code-Session-Id<br/>body: tools (nombres capitalizados Bash/Read/Edit/…)
    alt Puerta satisfecha
        Z-->>CC: 200 + SSE (message_start … message_stop)
    else Falta condición 1 o 2
        Z-->>CC: 403 FreeTierError
    else tools no aceptadas (¿case-sensitive?)
        Z-->>CC: 403 FreeTierError — NO DEMOSTRADO qué ocurre con nombres capitalizados
    else modelo sin protocolo Anthropic (p. ej. muse)
        Z-->>CC: 400 ModelProtocolUnsupported
    end
    Note over CC: count_tokens → POST /v1/messages/count_tokens<br/>(fallback local si falla — demostrado en código)<br/>keepalive → /v1/messages/cache_touch cada 30 s
```

## 3. Ruta B — secuencia (diseño)

```mermaid
sequenceDiagram
    participant CC as Claude Code 2.1.299
    participant AD as Adaptador local :8787
    participant Z as Zen /inference/openai/v1/chat/completions

    Note over CC: ANTHROPIC_BASE_URL=http://127.0.0.1:8787<br/>ANTHROPIC_AUTH_TOKEN=placeholder<br/>ANTHROPIC_MODEL=claude-free-<zen-id><br/>CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1
    CC->>AD: GET /v1/models (discovery)
    AD-->>CC: {data:[{id:"claude-free-…"},…]}  ← pasa el filtro /claude|anthropic/i
    CC->>AD: POST /v1/messages (Anthropic Messages, stream)
    AD->>AD: 1) mapear id claude-free-<zen> → <zen><br/>2) traducir mensajes/tools/imágenes → OpenAI<br/>3) normalizar tools a [bash,edit,glob,grep,read,write]<br/>4) generar ses_* válida (algoritmo invertido)
    AD->>Z: POST /chat/completions (stream)<br/>Bearer public · UA opencode/* · x-opencode-session ses_*<br/>tools minúsculas OpenCode
    Z-->>AD: SSE OpenAI (delta chunks, tool_calls)
    AD-->>CC: SSE Anthropic (message_start, content_block_delta,<br/>input_json_delta, message_delta, message_stop)
    CC->>AD: POST /v1/messages/count_tokens
    AD-->>CC: {input_tokens: estimación}
    CC->>AD: POST /v1/messages/cache_touch (cada 30 s)
    AD-->>CC: 200 {}
```

## 4. Puerta FreeTier (común a ambas rutas)

```mermaid
flowchart TD
    REQ["Petición entrante a Zen"] --> C1{"¿User-Agent\nopencode/*?"}
    C1 -- No --> E["403 FreeTierError"]
    C1 -- Sí --> C2{"¿Cabecera de sesión\nx-opencode-session | x-session-id | x-session-affinity\ncon valor ses_* válido?"}
    C2 -- No --> E
    C2 -- Sí --> C3{"¿tools no vacío con\nnombres OpenCode\n[bash, edit, glob, grep, read, write]?"}
    C3 -- "No (¿case-sensitive?)" --> E2["403 — comportamiento exacto con nombres\ncapitalizados de CC: NO DEMOSTRADO"]
    C3 -- Sí --> OK["200 · respuesta del modelo"]

    VAL["Validación por valor del ses_*:\n12 hex = 48 bits bajos de ~(ms*0x1000 + contador)\n(IY(true)/Bce(); IDs sin invertir → 403)"]
    C2 -.-> VAL
```

Detalles de la puerta (demostrados en la misión previa, ver `artifacts/reports/INFORME-TRANSFORMER-OPENCODE-ZEN.md`):

- `Authorization` es **suprimible**.
- La IP, el TLS (OpenSSL vs BoringSSL), HTTP/1.1 vs 2, el contenido de `instructions` y el resto de cabeceras fueron descartados experimentalmente como factores.
- La interfaz mínima reutilizable: 3 constantes + 6 esquemas de tools, sin dependencias.

## 5. Traducción Anthropic Messages ↔ OpenAI (Ruta B)

### 5.1 Petición (Anthropic → OpenAI)

```mermaid
flowchart LR
    subgraph A["Anthropic Messages (lo que envía CC)"]
        A1["system (string | bloques)"]
        A2["messages: text / tool_use / tool_result / image"]
        A3["tools[{name, description, input_schema}]"]
        A4["tool_choice, max_tokens, temperature, stop_sequences"]
    end
    subgraph O["OpenAI Chat Completions (lo que espera Zen)"]
        O1["role:system"]
        O2["content text | assistant.tool_calls | role:tool | image_url data:"]
        O3["tools[{type:function, function:{name(minúsculas), description, parameters}}]"]
        O4["tool_choice, max_tokens, temperature, stop"]
    end
    A1 --> O1
    A2 --> O2
    A3 --> O3
    A4 --> O4
```

- `cache_control` se elimina en la traducción (Zen/OpenAI-compatible no lo usa).
- Los bloques `thinking` se descartan.
- Los nombres de tools se normalizan a minúsculas dentro del set OpenCode y se guarda el mapa inverso para la respuesta (las 6 tools por defecto de CC mapean 1:1: `Bash→bash`, `Read→read`, `Edit→edit`, `Glob→glob`, `Grep→grep`, `Write→write`).

### 5.2 Respuesta (SSE OpenAI → SSE Anthropic)

```mermaid
sequenceDiagram
    participant Z as Zen (SSE OpenAI)
    participant AD as Adaptador
    participant CC as Claude Code

    Z-->>AD: chunk {delta:{content:"…"}}
    AD-->>CC: message_start {message:{usage:{input_tokens,…}}}
    AD-->>CC: content_block_start {index:0, type:"text"}
    loop por chunk
        AD-->>CC: content_block_delta {text_delta}
    end
    Z-->>AD: chunk {delta:{tool_calls:[…]}}
    AD-->>CC: content_block_start {type:"tool_use"}
    AD-->>CC: content_block_delta {input_json_delta}
    Z-->>AD: [DONE] / finish_reason
    AD-->>CC: content_block_stop + message_delta {stop_reason, usage.output_tokens}
    AD-->>CC: message_stop
```

Mapeo de `finish_reason` → `stop_reason`:

| OpenAI | Anthropic |
|---|---|
| `stop` | `end_turn` |
| `tool_calls` | `tool_use` |
| `length` | `max_tokens` |

Mapeo de usage: `prompt_tokens → input_tokens`, `completion_tokens → output_tokens`; campos de caché a 0/ausentes.

## 6. Discovery de modelos (selector de Claude Code)

```mermaid
flowchart TD
    CC["Claude Code\nCLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1\n+ firstParty + ANTHROPIC_BASE_URL"] --> G["GET {base}/v1/models?limit=1000\n(custom headers con override de UA)"]
    G --> F{"filtrar ids\n/claude|anthropic/i"}
    F -- "ids claude-free-<zen>" --> P["Aparecen en el selector (/model)"]
    F -- "ids <zen> sin prefijo" --> X["No aparecen"]
    P --> S["ANTHROPIC_MODEL / ANTHROPIC_DEFAULT_*_MODEL\npara el modelo por defecto y tareas de fondo"]
```

- El adaptador debe servir ids que contengan `claude` (p. ej. `claude-free-deepseek-v4.1-flash-free`).
- `opn()` (validación al cambiar de modelo) bloquea ids no reconocidos en la superficie `model_switch`; los descubiertos por gateway se asumen reconocidos (INFERIDO).
