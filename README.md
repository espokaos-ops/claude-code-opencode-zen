# claude-code-opencode-zen

Investigación técnica (análisis estático con REA) sobre la viabilidad de usar los **modelos gratuitos de OpenCode Zen** desde **Claude Code 2.1.299**, conservando selector de modelo y funciones habituales.

> **Estado (2026-10-16):** investigación completada **y adaptador implementado y verificado de extremo a extremo** con Claude Code 2.1.299 real (marcador `ZEN-E2E-MARKER-4242` con tool `Read`) en las tres familias de protocolo del free tier. Código en `implementation/`; evidencia nueva en `artifacts/probes/phase5_*` y `artifacts/reports/PHASE5-MATRIX.md`. Los dos pendientes históricos quedaron **DEMOSTRADO** (ver «Estado real»).

---

## Objetivo

Determinar si Claude Code puede hablar con Zen (modelos gratuitos) y de qué forma:

- **Ruta A — Directa:** solo variables de entorno (`ANTHROPIC_BASE_URL`, `ANTHROPIC_CUSTOM_HEADERS`, `ANTHROPIC_MODEL`…) apuntando a la superficie Anthropic de Zen.
- **Ruta B — Adaptador:** un servidor local que expone Anthropic Messages API a Claude Code y traduce a OpenAI Chat Completions, inyectando la puerta FreeTier. **Ruta preferida a día de hoy**, pendiente de decisión final tras revisar las evidencias.

## Resumen de hallazgos

| # | Hallazgo | Clasificación |
|---|---|---|
| 1 | El SDK de Claude Code concatena `baseURL + path` sin normalizar: `ANTHROPIC_BASE_URL` **no debe terminar en `/v1`** o el POST saldría a `…/v1/v1/messages`. | DEMOSTRADO (estático) |
| 2 | `ANTHROPIC_CUSTOM_HEADERS` se fusiona **después** de `Nl()`: puede sobrescribir `User-Agent` (permite `User-Agent: opencode/*`) y añadir `x-opencode-session`. | DEMOSTRADO (estático) |
| 3 | `mZe()`/`dHe()` (chunk `1qwezzd3.js`): con `ANTHROPIC_MODEL` o `ANTHROPIC_DEFAULT_*_MODEL` definidos se omite la validación de modelo que bloqueó la versión 2.1.296. | DEMOSTRADO (estático) |
| 4 | Zen sirve los gratuitos por endpoints OpenAI (docs) y, además, existe una superficie unificada Anthropic (`/inference/v1/messages`) que sirvió `space-bunny-free` con **200 + SSE** (con la puerta satisfecha, vía curl en misión previa; NO vía Claude Code). | DEMOSTRADO (captura previa) |
| 5 | La puerta FreeTier exige 3 condiciones: UA `opencode/*`, cabecera de sesión `ses_*` válida (validación por valor) y `tools` con nombres OpenCode (`bash, edit, glob, grep, read, write`). | DEMOSTRADO (misión previa) |
| 6 | `muse-spark-1.3-contributor-free` es **Responses-only**: 400 `ModelProtocolUnsupported` en la superficie Anthropic. | DEMOSTRADO |
| 7 | El gateway model discovery de 2.1.299 filtra ids con `/claude\|anthropic/i` → un adaptador debe servir ids tipo `claude-free-<zen-id>` para el selector. | DEMOSTRADO (estático) |
| 8 | Traducción Anthropic↔OpenAI necesaria en Ruta B (SSE, tools, imágenes, errores, usage). Diseño completo en `FINDINGS.md` y `ARCHITECTURE.md`. | DISEÑO |

## Estado real (honesto)

- **Implementación (`implementation/`, gateway 0.4.0):** `DEMOSTRADO`. Relay
  `/messages` + bridges `/responses` y `/chat/completions`, fingerprint v2
  (tools `read`/`shell` verbatim), routing por modelo, guard de truncamiento.
  Suite 66/66.
- **E2E Claude Code real:** `DEMOSTRADO` con `ZEN-E2E-MARKER-4242` y tool `Read`
  en `space-bunny-free` (messages), `muse-spark-*` (Fase 4) y `big-pickle`
  (responses), `beam-free` y `deepseek-v4.1-flash-free` (chat).
- **Pendiente 1 (herramientas capitalizadas):** resuelto — la puerta v2 exige
  `read`/`shell` verbatim ADICIONALES; las tools capitalizadas de CC conviven
  (DEMOSTRADO en vivo).
- **Pendiente 2 (cable real de 2.1.299):** resuelto — E2E real ejecutado; CC
  emite warning `unrecognized_model` para ids free desconocidos (inofensivo).
- **Descubrimiento Fase 5:** el catálogo free se reparte en 3 protocolos
  (matriz completa en `artifacts/reports/PHASE5-MATRIX.md`); `jev-1.13-free`
  no acepta ninguno (NO DEMOSTRADO/inerte).
- **Multimodal:** `DEMOSTRADO` por `/messages` (el modelo ve la imagen); por
  chat `image_url` → 422/400 (NO DEMOSTRADO; el bridge omite imágenes).
- **`count_tokens` upstream:** 404 (no existe); el gateway sirve estimador
  local y CC funciona (DEMOSTRADO).
- **Restricciones respetadas:** sin modificar Claude Code, configs del sistema,
  WARP/Privoxy; logs sin secretos; errores del proveedor sin transformar.

Leyenda de clasificación: `DEMOSTRADO` (evidencia directa: código o captura) · `DOCUMENTADO` (documentación oficial) · `INFERIDO` (derivado razonado) · `NO DEMOSTRADO` (pendiente de verificación empírica).

## Estructura del repositorio

```
├── README.md                  ← este archivo
├── ARCHITECTURE.md            ← arquitectura + diagramas Mermaid
├── FINDINGS.md                ← hallazgos detallados, rutas A/B, recomendación
├── EVIDENCE.md                ← referencias REA, funciones, fragmentos, comandos
├── IMPLEMENTATION-PLAN.md     ← qué crear/modificar, dependencias, secuencia
├── TEST-PLAN.md               ← plan de pruebas (no ejecutado)
└── artifacts/
    ├── README.md              ← manifiesto de artefactos y exclusiones
    ├── reports/               ← informes originales (evidencia narrativa)
    ├── code-excerpts/         ← extractos verbatim del código analizado
    ├── catalogs/              ← catálogos de modelos (binario OpenCode + models.dev)
    └── probes/                ← sondas HTTP (403 históricas) + evidencia Fase 5
├── implementation/            ← adaptador funcional (gateway 0.4.0 + tests + docs)
│   ├── gateway.py             ← servidor loopback (routing 3 protocolos)
│   ├── zen_fingerprint.py     ← contrato v2 + normalizador SSE + routing
│   ├── zen_bridge.py          ← Anthropic ↔ Responses (muse, big-pickle)
│   ├── zen_chat.py            ← Anthropic ↔ chat/completions (resto de free)
│   ├── freya_wire.py / freya_tools.py
│   ├── bin/                   ← claude-gateway / claude-with-gateway
│   └── tests/                 ← 66 tests stdlib (unittest)
```

## Recomendación de modelo (separada de los hechos)

Los hechos demuestran protocolo y puerta, no calidad de modelo. Como **recomendación preliminar** (no verificada empíricamente):

1. `space-bunny-free` — único gratuito con 200+SSE demostrado en la superficie Anthropic unificada; úsalo como primera prueba de cada ruta.
2. `deepseek-v4.1-flash-free` — candidato principal para uso de agente de código (V4.1 flash; `tools=True reasoning=True` en el snapshot).
3. `glm-5.3-flash-free` o `longcat-2.5-preview-free` — candidatos para tareas de fondo (`ANTHROPIC_DEFAULT_HAIKU_MODEL`).
4. **Evitar** `muse-spark-1.3-contributor-free` en este diseño (Responses-only).

Alternativas si la recomendación no convence: cualquiera de los otros gratuitos activos con `tools=True` (ver `artifacts/catalogs/`). La elección final requiere el TEST-PLAN.

## Enlaces

- Informe base: [`artifacts/reports/INFORME-CLAUDE-CODE-ZEN.md`](artifacts/reports/INFORME-CLAUDE-CODE-ZEN.md)
- Evidencia de la puerta FreeTier: [`artifacts/reports/INFORME-TRANSFORMER-OPENCODE-ZEN.md`](artifacts/reports/INFORME-TRANSFORMER-OPENCODE-ZEN.md)
- Docs oficiales de Zen: https://opencode.ai/v2/docs/console/models/

## Aviso legal

Los extractos de código de `artifacts/code-excerpts/` son fragmentos mínimos de artefactos propietarios (Claude Code) y de código abierto (OpenCode), incluidos exclusivamente como evidencia técnica para interoperabilidad. No se redistribuyen binarios completos.
