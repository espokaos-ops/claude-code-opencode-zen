# claude-code-opencode-zen

Investigación técnica (análisis estático con REA) sobre la viabilidad de usar los **modelos gratuitos de OpenCode Zen** desde **Claude Code 2.1.299**, conservando selector de modelo y funciones habituales.

> **Estado:** investigación y diseño **solamente**. No se ha implementado el adaptador, no se ha modificado Claude Code, no se han hecho pruebas de extremo a extremo contra el proveedor con Claude Code. Dos puntos permanecen **NO DEMOSTRADO** (ver abajo).

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

- **Ruta A:** los mecanismos están demostrados en código, pero **NO DEMOSTRADO** que funcione de extremo a extremo:
  - **Pendiente 1 — herramientas capitalizadas:** Claude Code envía `Bash`, `Read`, `Edit`…; la puerta se demostró con nombres minúsculos. Sensibilidad a mayúsculas de la condición 3: desconocida.
  - **Pendiente 2 — comportamiento real en el cable:** 2.1.299 nunca se ha ejecutado contra Zen. Que emita IDs arbitrarios solo está demostrado estáticamente (`mZe()`).
  - Además: aceptación por-modelo de la superficie unificada (solo `space-bunny-free` demostrado), y comportamiento de `count_tokens`/`cache_touch`.
- **Ruta B:** diseño completo; **no implementada, no probada**. No se afirma que funcione.
- **Restricciones respetadas en toda la investigación:** sin peticiones de prueba al proveedor (salvo las capturas previas documentadas), sin instalar nada, sin modificar Claude Code ni configs del sistema.

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
    └── probes/                ← respuestas HTTP 403 FreeTierError (sondas anonimizadas)
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
