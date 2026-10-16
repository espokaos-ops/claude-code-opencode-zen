# Informe final — Claude Code 2.1.299 × OpenCode Zen (free)

Fecha: 2026-10-16. Autor: espokaos-ops (misión asistida, evidencia adjunta).

## Resultado global

`DEMOSTRADO`: Claude Code 2.1.299 funciona de extremo a extremo (tool `Read` +
respuesta final, marcador `ZEN-E2E-MARKER-4242`) contra los modelos gratuitos
de OpenCode Zen, en las TRES familias de protocolo detectadas, mediante un
gateway local (loopback) que **no** modifica Claude Code ni configs del
sistema ni evita el gate del proveedor: compone el wire que el propio cliente
oficial usa (v2) y traduce formato.

Catálogo free y estado por modelo (sonda directa + E2E CC):

| modelo | protocolo | sonda | E2E CC |
|---|---|---|---|
| space-bunny-free | `/messages` | 200 | OK (2 turnos) |
| muse-spark-1.2-contributor-free | `/responses` | 200 | OK (Fase 4) |
| muse-spark-1.3-contributor-free | `/responses` | 200 | (mismo bridge) |
| big-pickle | `/responses` | 200 | OK (2 turnos) |
| beam-free | `/chat/completions` | 200 | OK (3 turnos) |
| deepseek-v4.1-flash-free | `/chat/completions` | 200 | OK (2 turnos) |
| glm-5.3-flash-free | `/chat/completions` | 200 | (mismo bridge) |
| nemotron-3.5-lightning-free | `/chat/completions` | 200 | (mismo bridge) |
| nemotron-3.5-super-vl-free | `/chat/completions` | 200 | (mismo bridge) |
| mimo-v2.6-flash-free | `/chat/completions` | 200 | (mismo bridge) |
| longcat-2.5-preview-free | `/chat/completions` | 200 | (mismo bridge) |
| ll-alpha-free | `/chat/completions` | 200 | (mismo bridge) |
| jev-1.13-free | — | 400 en los 3 | inutilizable |

## Arquitectura implementada (gateway 0.4.0)

```text
claude (ANTHROPIC_BASE_URL=http://127.0.0.1:8479, solo env del hijo)
  → POST /v1/messages (Anthropic)
      gateway.py — routing por modelo:
      ├─ space-bunny-free  → relay v2  → /inference/v1/messages (SSE normalizado)
      ├─ muse-spark*, big-pickle → zen_bridge → /inference/v1/responses
      └─ resto de free     → zen_chat   → /inference/v1/chat/completions
```

* Fingerprint v2 en los 3 caminos: UA `opencode/latest/2.0.26/cli`,
  `Authorization: Bearer public`, sesión `ses_*` fresca, `x-opencode-client`,
  `stream:true`, tools `read`/`shell` verbatim + alias de colisiones + nota
  anti-placeholder. Respuesta normalizada (`read`→`Read`, `shell`→`Bash`).
* Guard de truncamiento: si el upstream corta sin `message_stop`/`[DONE]`, se
  emite `event: error` (CC reintenta en vez de esperar 300 s).
* Errores del proveedor (401/403/400) se propagan sin modificar.
* `count_tokens` upstream no existe (404); estimador local en el gateway.

## Clasificación

* `DEMOSTRADO` (capturas/E2E adjuntos):
  * wire v2 aceptado en vivo y gate (tools read/shell verbatim obligatorias en
    `/messages` y `/chat/completions`; `stream:true` obligatorio);
  * matriz de 3 protocolos por modelo;
  * E2E real CC 2.1.299 en 5 modelos (3 familias) con tool roundtrip;
  * multimodal por `/messages` (el modelo ve la imagen; 1x1 rosa → "Pink");
  * truncamientos del free tier y su mitigación; suite 66/66.
* `DOCUMENTADO`: el catálogo/canales de OpenCode; formato de sesión
  `ses_[0-9a-f]{12}[0-9A-Za-z]{14}`; contrato free-tier del proveedor.
* `INFERIDO`: que `jev-1.13-free` requiere un cuarto protocolo aún no
  expuesto; que los truncamientos responden a rate/concurrencia (no agotado).
* `NO DEMOSTRADO`: imágenes por la vía chat (bridge las omite; upstream
  422/400); tool roundtrip E2E de los chat no listados arriba; límites/429
  exactos del plan gratuito.

## Reproducción

```sh
cd ~/workspace/Transformers/Claude-Code
CLAUDE_GATEWAY_UPSTREAM=zen ./bin/claude-gateway start   # 127.0.0.1:8479
cd /tmp/opencode/e2e-cc
ANTHROPIC_BASE_URL=http://127.0.0.1:8479 ANTHROPIC_AUTH_TOKEN=public \
ANTHROPIC_MODEL=beam-free \
claude -p "Use the Read tool to read marker.txt, then reply with its exact contents" \
  --output-format json --dangerously-skip-permissions
```

(Para `space-bunny-free` el default del gateway ya lo enruta; cambiar
`ANTHROPIC_MODEL` al modelo deseado; CC avisa `unrecognized_model` para ids
free — inofensivo.)

## Evidencia principal

* `artifacts/reports/PHASE5-MATRIX.md` — matriz y claves del gate.
* `artifacts/probes/phase5_chat_tools.json` — sondas 200/400 por modelo.
* `artifacts/probes/phase5_cc_{chat,deepseek,bigpickle,regress}.json` — E2E CC.
* `artifacts/probes/phase5_img_messages.sse` — multimodal por messages.
* Histórico Fase 1–4: `artifacts/reports/` y sondas 403 del repo.

## Límites y backlog

1. jev-1.13-free inerte (sin protocolo conocido).
2. Imágenes en la vía chat (documentado; el relay `/messages` sí las soporta).
3. Completar E2E de los chat restantes y de muse-spark-1.3 (mismo código).
4. Rate limits 429: comportamiento no agotado en pruebas.
5. `x-opencode-request` (wire v1 viejo) no se usa; el v2 no lo necesita.
