# Fase 5 — Matriz de protocolos por modelo (openCode Zen free)

Fecha: 2026-10-16. Todo por sonda directa al wire v2 (`zen_headers` + UA
`opencode/latest/2.0.26/cli` + Bearer public + sesión `ses_...` fresca).

## Hallazgo central
El catálogo free se reparte en TRES protocolos distintos:

| protocolo | modelos (verificado 200) | evidencia |
|---|---|---|
| `/inference/v1/messages` (Anthropic SSE) | space-bunny-free | P2/P4, E2E CC |
| `/inference/v1/responses` | muse-spark-1.2-contributor-free, muse-spark-1.3-contributor-free, big-pickle | phase5_matrix/phase5_responses, E2E CC muse |
| `/inference/v1/chat/completions` (OpenAI SSE) | beam-free, deepseek-v4.1-flash-free, glm-5.3-flash-free, nemotron-3.5-lightning-free, nemotron-3.5-super-vl-free, mimo-v2.6-flash-free, longcat-2.5-preview-free, ll-alpha-free (+space-bunny-free tambien responde) | phase5_chat_tools.json |
| ninguno de los 3 | jev-1.13-free (400 ModelProtocolUnsupported en los tres) | phase5_chat_tools.json |

## Claves del gate para /chat/completions (DEMOSTRADO)
- El 403 FreeTierError era por NO mandar los tools `read`/`shell` verbatim
  (como en /messages). Con el body completo (tools fingerprint + stream:true
  + headers v2) TODOS los modelos chat devuelven 200 SSE.
- Ademas viajan `x-session-affinity` = `x-session-id` = session y
  `x-opencode-project: global` (usados por la referencia; inocuos en messages).
- `x-opencode-request` NO hizo falta.

## Wire chat observado (p3e/p3f y sondas)
```
data: {"id":..,"object":"chat.completion.chunk",...,"choices":[{"index":0,"delta":{"role":"assistant"}}],"usage":null}

data: {... "delta":{"content":"OK"} ...}

data: {... "choices":[],"usage":{"prompt_tokens":959,"completion_tokens":3,...}}

data: [DONE]
```

## Implementacion (gateway 0.4.0)
- `zen_chat.py`: Anthropic<->chat (tools funcion, tool_result->role tool,
  tool_calls deltas acumulados, usage prompt/completion->input/output,
  fingerprint v2 estilo chat con nota anti-placeholder).
- Routing en gateway: `is_responses_model` (muse-spark*, big-pickle) ->
  /responses; `is_chat_model` (resto) -> /chat/completions; default relay
  /messages para space-bunny-free.
- Guard de truncamiento tambien en chat (`saw_done`/`finish_reason`), emite
  `event: error` si el upstream corta.
- Tests: 66/66 OK (test_zen_chat.py nuevo + 4 tests de gateway para el path chat).

## E2E real CC 2.1.299 (evidencia, tool Read -> "ZEN-E2E-MARKER-4242")
- `phase5_cc_chat.json`: beam-free (chat), num_turns 3, is_error false.
- `phase5_cc_deepseek.json`: deepseek-v4.1-flash-free (chat), num_turns 2, 3.8s.
- `phase5_cc_bigpickle.json`: big-pickle (responses), num_turns 2, 4.7s.
- `phase5_cc_regress.json` (stdout+stderr mezclados; el JSON es la linea 2):
  space-bunny-free (messages), num_turns 2 (regresion relay).
- Fase 4: texto space-bunny y muse-spark (muse via /responses).
- CC emite warning `[claude-code:unrecognized_model]` para ids free desconocidos
  (inofensivo; sigue funcionando via gateway).

## count_tokens (Fase 5b)
- Upstream Zen: `/messages/count_tokens` y `/responses/count_tokens` -> 404
  (no existe el endpoint).
- Gateway sirve un estimador local en `/v1/messages/count_tokens` (200);
  CC funciona sin count_tokens real (E2E).

## Multimodal (Fase 5b)
- `/messages` con bloque `image` base64: 200 y el modelo VE la imagen
  (1x1 rosa -> thinking "The image is a 1x1 pink image", texto "Pink").
  Evidencia: `artifacts/probes/phase5_img_messages.sse`. DEMOSTRADO en el relay messages.
- `/chat/completions` con `image_url` data-URI: deepseek 422 ("Endpoint is
  unavailable"), nemotron-3.5-super-vl-free 400 -> NO DEMOSTRADO en chat.
  El bridge chat omite bloques `image` (limitacion documentada).

## Pendiente / NO DEMOSTRADO
- jev-1.13-free: ningun protocolo 200 (modelo listado pero inutilizable).
- Imagenes por la via chat (bridge las descarta); tool roundtrip de los
  modelos chat restantes (ll-alpha, mimo, longcat, glm, nemotron).
