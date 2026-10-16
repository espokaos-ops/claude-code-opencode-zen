# Artefactos — manifiesto y seguridad

Esta carpeta contiene la evidencia publicable de la investigación. Todo el contenido fue revisado antes de publicarse; en la sección **Exclusiones** se detalla qué NO se publica y por qué.

## Manifiesto (con SHA-256)

### `reports/` — informes originales

| Archivo | SHA-256 | Origen |
|---|---|---|
| `INFORME-CLAUDE-CODE-ZEN.md` | `8b103752b5937be0da08424318efa1c45c49e4b23d5fc73a3e719b1e96b232fa` | Informe base de esta investigación (16-oct-2026) |
| `INFORME-TRANSFORMER-OPENCODE-ZEN.md` | `35e2c64c36011707c590dba0c4e9e69bd23d10f1516e771aa9d2d3769da79901` | Misión previa: puerta FreeTier (bisectada con curl), algoritmo `ses_*`, superficie unificada Anthropic, CC 2.1.296 bloqueado |

### `code-excerpts/` — fragmentos verbatim analizados

| Archivo | SHA-256 | Contenido |
|---|---|---|
| `claude-code-2.1.299-code-excerpts.md` | `69ea7fc67860575eaf4c22ffba418c48dcaafa23fed61e295b87040df2556265` | 16 extractos (`CC-01`…`CC-16`) con chunk, offset y SHA-256 del módulo |
| `opencode-1.19.3-code-excerpts.md` | `cb3d55a8d37f3da6b073de71ac30f24f803e3387d70726e0559569ba3c68010e` | 2 extractos (`OC-01`, `OC-02`) |

### `catalogs/` — catálogos de modelos (datos públicos)

| Archivo | SHA-256 | Contenido |
|---|---|---|
| `models.dev-opencode-provider.json` | `4e66fb5790eeb48b26f8005693850f885257ac57cd2a4eec48a09964f93f3a39` | Provider `opencode` del catálogo público models.dev en caché local (127 modelos; snapshot 16-oct) |
| `opencode-1.19.3-zen-provider-block.js` | `4e353224c50cf8b97bb461a4e64ce8553650baa89c2a66a53aceb1af6038125a` | Bloque del catálogo Zen embebido en el binario OpenCode 1.19.3 |

### `probes/` — respuestas HTTP de sondas anónimas (16-oct 15:01 UTC)

| Archivo | SHA-256 |
|---|---|
| `avail_deepseek-v4.1-flash-free.hdr` | `2ea47053c719b1eb66d47d86b13d9b7e50d213ddc6d584e1d00bea13c8029fd1` |
| `avail_mimo-v2.6-flash-free.hdr` | `483cbc9b220c6f6d4c153e7abf02677bec003d141c3a00687e2a833cb99ce635` |
| `avail_nemotron-3.5-lightning-free.hdr` | `cfa67f57424d4f2b37d885024ce597f8a57834512af9646d030a36e2e199f25e` |
| `avail_*.json` (×3, contenido idéntico) | `0539e65d668bf1822258ea3c625c5ec95d4918c478267b9b90dd596934288ed0` |

Las sondas devolvieron `HTTP/2 403` + `FreeTierError`. Las respuestas conservan `cf-ray`/`x-opencode-log-id` (identificadores efímeros de Cloudflare, no secretos). El endpoint exacto empleado por la sonda no se conservó (limitación documentada).

## Exclusiones (deliberadas)

| Material | Motivo de exclusión |
|---|---|
| `mitm/` (CA/forge `.key`, `.crt`, `mitm.py`, `redirect.so`, `sniff.so`, dumps) | Contiene **claves privadas TLS** y maquinaria de captura; riesgo de seguridad. No publicable. |
| `~/.local/share/opencode/auth.json` | Credenciales (aunque solo contuviera un provider, es material sensible por definición). |
| `opencode_ro.db`, `audit_export_*.json` | Bases de datos/exportaciones locales con contenido no revisado; fuera del alcance de esta evidencia. |
| Capturas de tráfico sin redactar | Podrían contener prompts/cabeceras privadas; no se publican. |
| Informes `INFORME-OPENCODE-ZEN-MUSE.md`, `INFORME-OPENCODE-ZEN-FASE2-TRANSFORMER.md`, `FREYA-MUSE-ZEN-INTEGRATION.md`, `WARP-PROXY-SETUP.md`, `AUDITORIA-MOTOR-VT-*.md` | Fuera del alcance de este repositorio (otros sistemas/proyectos); solo se incluye el informe directamente relacionado con la puerta y la superficie Zen. |

## Aviso

- Los extractos de Claude Code son fragmentos mínimos con fines de interoperabilidad e investigación; Claude Code es software propietario de Anthropic. Los extractos de OpenCode provienen de software de código abierto.
- Los datos de catálogo son públicos (models.dev / binario).
- Ningún archivo de esta carpeta contiene credenciales, tokens ni cookies.
