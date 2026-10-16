# Test Plan

> **Estado: NO EJECUTADO.** Ninguna prueba de este plan se ha realizado. Todas las pruebas con proveedor real (fases 4+ de `IMPLEMENTATION-PLAN.md`) requieren **autorización explícita** porque consumen la red y potencialmente cuota del tier gratuito. Los dos puntos pendientes del `README.md` solo se cierran con las pruebas A-1 y B-2.

## 1. Objetivos

1. Cerrar los dos **NO DEMOSTRADO**: (a) herramientas capitalizadas vs puerta FreeTier; (b) comportamiento real en el cable de Claude Code 2.1.299.
2. Validar la traducción Anthropic ↔ OpenAI (unitaria, sin red).
3. Validar streaming, tool-loop, continuidad y errores de la Ruta B.
4. Decidir entre Ruta A y Ruta B con evidencia, no con inferencias.

## 2. Precondiciones y salvaguardas

- Autorización del usuario para: (i) ejecutar Claude Code 2.1.299 con envs de prueba; (ii) 1–n peticiones reales a Zen (empezar por 1).
- Todo en **HOME aislado** (patrón de la misión previa: `HOME=/tmp/…` con `CLAUDE_CONFIG_DIR`), sin tocar `~/.claude` ni `~/.config` reales.
- Registro de evidencia: guardar request/response (redactando `Authorization` y cualquier token) en `/tmp`, nunca en el repo.
- Regla de coste: una petición por paso; parar ante cualquier resultado inesperado.
- El adaptador escucha **solo en 127.0.0.1**; no se expone.

## 3. Herramientas

| Herramienta | Uso |
|---|---|
| `curl` | peticiones controladas directas (A-1, B-2) con cabeceras de puerta reproducibles |
| Servidor de fixtures local | upstream simulado para B-1 (SSE OpenAI pre-grabado, sin red) |
| Logs estructurados del adaptador | verificar traducción en vivo (entrada Anthropic / salida OpenAI) |
| HOME aislado + `ANTHROPIC_*` | Claude Code sin tocar configuración real |
| `python3` | fixture server, parseo de SSE, comparación de transcriptos |
| (Opcional) captura de tráfico local | solo para CC ↔ adaptador (loopback), nunca para tráfico externo sin autorización |

## 4. Matriz de pruebas

### 4.1 Compatibilidad — Ruta A

| ID | Prueba | Procedimiento | Criterio de aceptación | Cierra |
|---|---|---|---|---|
| A-1 | **1 petición CC 2.1.299 → Zen** con `ANTHROPIC_BASE_URL=https://opencode.ai/inference`, `ANTHROPIC_AUTH_TOKEN=public`, `ANTHROPIC_MODEL=space-bunny-free`, custom headers con `User-Agent: opencode/<ver>` y `x-opencode-session` válida | lanzar CC en HOME aislado con un prompt trivial; capturar la primera petición (log local o proxy loopback si se habilita) | 200 + SSE consumido por CC; se registra si la condición 3 (tools capitalizadas) pasó o devolvió 403 | **Pendiente 1 + 2** |
| A-2 | Igual que A-1 pero sin la cabecera de sesión | ídem | 403 `FreeTierError` (control negativo de la puerta) | — |

### 4.2 Compatibilidad — Ruta B (adaptador)

| ID | Prueba | Procedimiento | Criterio |
|---|---|---|---|
| B-1 | Adaptador + upstream fixture (sin red) | CC (o curl imitando su petición) → adaptador → fixture SSE OpenAI | SSE Anthropic válido consumido sin errores de parseo |
| B-2 | Adaptador + Zen real (1 petición, `space-bunny-free`) | misma petición que B-1 pero upstream real | 200 + SSE traducido; logs muestran puerta inyectada correctamente |
| B-3 | `/v1/models` del adaptador | GET directo | JSON con ids `claude-free-*` que pasan `/claude\|anthropic/i` |
| B-4 | `count_tokens` y `cache_touch` del adaptador | POST directos | `{input_tokens}` numérico; `200 {}` |

### 4.3 Herramientas (tools)

| ID | Prueba | Criterio |
|---|---|---|
| T-1 | Unitaria: schema `tools` Anthropic → `parameters` OpenAI, incluidos `required`, `enum`, anidados | round-trip fiel |
| T-2 | Unitaria: normalización de nombres a `[bash, edit, glob, grep, read, write]` + mapa inverso en respuesta | el nombre devuelto al cliente coincide con el original |
| T-3 | Unitaria: `tool_use`/`tool_result` ↔ `tool_calls`/`role:"tool"` (incl. argumentos JSON en streaming, `input_json_delta`) | mensajes equivalentes |
| T-4 | E2E: CC pide una tool real (p. ej. `Read` de un fixture) contra el adaptador | el loop completa: `tool_use` → `tool_result` → respuesta final |
| T-5 | Petición directa con las 6 tools en minúsculas (curl, puerta satisfecha) | 200 (control positivo de la condición 3) |
| T-6 | Petición directa con las 6 tools en mayúsculas (curl) | determina si la puerta es case-sensitive (evidencia para A-1) |

### 4.4 Streaming

| ID | Prueba | Criterio |
|---|---|---|
| S-1 | Unitaria: chunks OpenAI parciales (texto) → secuencia Anthropic completa (`message_start`…`message_stop`) | secuencia válida y sin eventos fuera de orden |
| S-2 | Unitaria: tool_call troceado en varios deltas → `input_json_delta` concatenable | JSON de argumentos parseable al final |
| S-3 | E2E: abortar la conexión a mitad de stream | adaptador no deja conexiones colgadas; CC muestra error controlado |
| S-4 | E2E: keepalive `cache_touch` cada 30 s durante una respuesta larga | no rompe la sesión |

### 4.5 Continuidad

| ID | Prueba | Criterio |
|---|---|---|
| C-1 | Multi-turno (2 turnos) con historial Anthropic → OpenAI | contexto preservado; sin duplicación de system |
| C-2 | Resume de sesión de CC | misma sesión de puerta (`ses_*`) renovada correctamente dentro del adaptador |
| C-3 | Respuesta con contexto grande (modelo 200k–1M) | `max_tokens` y truncados gestionados; error claro si excede |
| C-4 | `ANTHROPIC_DEFAULT_HAIKU_MODEL` para tarea de fondo (título/resumen) | petición enrutada al modelo pequeño; no falla por la puerta |

### 4.6 Errores

| ID | Prueba | Criterio |
|---|---|---|
| E-1 | Puerta insatisfecha (sin UA/sesión) | 403 `FreeTierError` mapeado a error Anthropic legible |
| E-2 | Modelo Responses-only (`muse`) en Ruta A/B | 400 `ModelProtocolUnsupported` → error legible; sin reintentos infinitos |
| E-3 | 429 / 5xx / 529 del upstream | backoff respetado; CC recibe error o reintento según su lógica estándar |
| E-4 | Timeout de upstream | abort limpio; sin fugas de conexión |
| E-5 | Error de parseo SSE (chunk corrupto) | se descarta el chunk o se corta con error controlado (política documentada) |

### 4.7 Validación final

| ID | Prueba | Criterio |
|---|---|---|
| V-1 | Matriz de modelos: `space-bunny-free`, `deepseek-v4.1-flash-free`, `glm-5.3-flash-free`, `longcat-2.5-preview-free` (1 petición cada uno, en la ruta elegida) | resultado por modelo (OK/rechazo/motivo) registrado |
| V-2 | Decisión Ruta A vs Ruta B con evidencias de A-1/A-2/B-* | decisión argumentada y documentada en el repo |
| V-3 | Checklist de cierre: P1 y P2 resueltos o re-clasificados | actualización de `FINDINGS.md` con evidencias |

## 5. Orden recomendado (mínimo coste → máximo coste)

1. `T-1..T-3`, `S-1..S-2` (unitarias, sin red) — si se decide construir la Ruta B.
2. `A-1` (**una** petición) — resuelve P1/P2 para la Ruta A. Si da 403 por tools capitalizadas, decidir Ruta B con ese dato.
3. `B-1`, `B-3`, `B-4` (sin red) — adaptador con fixtures.
4. `B-2`, `T-4`, `S-3`, `S-4`, `C-1..C-4` — E2E mínimo.
5. `E-*`, `V-1` — endurecimiento y matriz.

## 6. Resultados

Ninguno todavía. Este documento se actualizará con una tabla de resultados (fecha, test, resultado, evidencia, clasificación) a medida que se ejecuten, manteniendo los no ejecutados como **NO DEMOSTRADO**.
