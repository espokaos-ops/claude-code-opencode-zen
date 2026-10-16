# Evidence — referencias REA, artefactos y reproducción

Este documento cataloga la evidencia utilizada: artefactos, referencias REA, localización exacta de los fragmentos y comandos reproducibles. Las clasificaciones (`DEMOSTRADO` / `DOCUMENTADO` / `INFERIDO` / `NO DEMOSTRADO`) están definidas en el `README.md`.

## 1. Artefactos analizados (identidad)

| Artefacto | Ruta | SHA-256 | Tamaño |
|---|---|---|---|
| OpenCode 1.19.3 (binario) | `/home/kaos/.opencode/bin/opencode` | `179ca421d61eefeadfa0c50e084a6e79c1623734732f0f4593f81ccfd3ab7ee9` | ~106 MB |
| Claude Code 2.1.299 (binario ELF) | `/home/kaos/.local/share/claude/versions/2.1.299` | `2d894a4b1bfaaa9aab72aeff7803e3c73bc2510f279a171f6b8f59f72d17d077` | 265 342 136 B |
| Sección bun descomprimida (OpenCode) | extracto intermedio | `34228fda35001dbd077eae2be334f3e68dbbb67573644d983245489286224586` | 92 388 250 B |

## 2. Referencias REA (session records)

REA (Ghidra headless) produjo los siguientes registros de evidencia, citados en `artifacts/reports/INFORME-CLAUDE-CODE-ZEN.md`:

| Evidence ID | Vista | Cobertura | Contenido |
|---|---|---|---|
| `ev_832ca0ed40a310c2a2ccc56c2fbe771ebcf815974d71c4dbda24d1c86ec909e7` | `ev_97eddf0d3cacccfc633a5c0f6d665fd7bcad0fef63884a3c95c478a4237d6646` | OK | OpenCode 1.19.3: catálogo Zen, `@ai-sdk/openai-compatible` |
| `ev_71fa3fd807993cc24a2e362ea9dd886fa28597a7c393a664f0a97e8abdab7602` | `ev_b60b59d90181b33eaa1dc852cb38b233950363f251e149ffac086b378a044cf6` | OK | Claude Code: `xywp7esx` (credenciales, discovery, UA), `s2t7g8m9` (betas), `yz8yf8mg` (3p-probe), `rshryz75` (endpoint custom) |
| `ev_951be01a189eb5d7f21eb59cad143f8e55231cc5ddd5c4362fd13434e107d61f` | `ev_7ecab1c0c2dcf1b722128a28f0feb732e94f36c5d11bc382e7af3348f1367103` | OK | Claude Code: `gmq0qwep` (SDK Anthropic embebido), `4jswj7c0` (gateway/count_tokens), `b47tzzqx`, `am9nyq9j` |
| `ev_a1d31ff12d823775a28d2520329062c169d127d853bf3b52b93d8240d54e5b7c` | `ev_f01a4b7c2900cdd97853027f5425fb42cf2972a037f755380e1bdd99571c299e` | **partial** (solo facts estáticos; el grafo semántico excedió el presupuesto) | Claude Code: `84yp45y8` (bundle principal 4.88 MB, telemetría, cache_touch, countTokens) |
| `ev_464fbae3f109132e46257628eec6ad62ac30cc01651c930c404d6beafb2eedd1` | — | obsoleto | Primer intento de análisis del bundle completo (superado) |

Digest del conjunto claude_js (2376 módulos): `6beba69e0fe50575e17eeeada18c2d6b18a9df0d02da5d51db2576fe0060dc5a`.

## 3. Mapa chunk → función → hallazgo → extracto

Claude Code 2.1.299 (`chunk-*.js`, extraídos a `/tmp/opencode/re/claude_js/root/`):

| Chunk | SHA-256 (del chunk) | Función / símbolo | Hallazgo | Extracto |
|---|---|---|---|---|
| `chunk-gmq0qwep.js` | `c8f4b705b2f4b89b2c8518015a7108b1b2cb747393c7278c44631dd805f7eaf5` | `buildURL()` | F-01 concatenación baseURL+path | `CC-01` |
| `chunk-gmq0qwep.js` | ídem | constructor SDK: `ANTHROPIC_CUSTOM_HEADERS` | F-02 parseo custom headers | `CC-02` |
| `chunk-gmq0qwep.js` | ídem | `Nl()` | F-02/F-08 cabeceras base (UA `$0()`, `X-Claude-Code-Session-Id`) | `CC-03` |
| `chunk-gmq0qwep.js` | ídem | `jF()` | F-02 orden `{...Nl(), ...te, ...n$()}` | `CC-04` |
| `chunk-gmq0qwep.js` | ídem | `jF()` | F-08 throw `K6e` sin credencial | `CC-05` |
| `chunk-gmq0qwep.js` | ídem | `jF()` → `new twe(ah)` | F-01/F-08 baseURL tal cual + defaultHeaders | `CC-06` |
| `chunk-gmq0qwep.js` | ídem | `$Mt()` | F-02 parseo de lista de custom headers | `CC-07` |
| `chunk-1qwezzd3.js` | `27fbcecc39e0b0bd05a8cae87de5374c1ff91d6d913873471d92a5242dc53992` | `mZe()`, `dHe()` | F-03 validación omitida | `CC-08` |
| `chunk-xywp7esx.js` | `d6b4961aceffaacaac4164b7becd1f0dd588c35a7d51a56a12822cd6979fb7b1` | discovery gateway | F-04 `GET /v1/models?limit=1000`, filtro `/claude\|anthropic/i`, override custom headers | `CC-09` |
| `chunk-xywp7esx.js` | ídem | `kDt` | F-08 `X-Claude-Code-Session-Id` | `CC-10` |
| `chunk-xywp7esx.js` | ídem | `$0()` | F-08 User-Agent `claude-cli/2.1.299 (external, cli)` | `CC-11` |
| `chunk-jtbwa3j2.js` | `f24eb8039255226da38543878c5341be1bf1131334df6c2b4bc6fc26778bba3c` | `opn()` | F-05 bloqueo en `model_switch` | `CC-12` |
| `chunk-84yp45y8.js` | `90753a793616ab8ad573768c8ce35f70a402475afc1deab0221b20d198cfb0da` | `IIo`, `sge()` | F-06 telemetría `unrecognized_model` | `CC-13` |
| `chunk-84yp45y8.js` | ídem | `cache_touch` | F-07 keepalive | `CC-14` |
| `chunk-gmq0qwep.js` | `c8f4…eaf5` | SDK messages | F-07 `/v1/messages/count_tokens` | `CC-15` |
| `chunk-gmq0qwep.js` | ídem | `validateHeaders()` | F-08 mapeo credenciales → cabeceras | `CC-16` |

Los extractos `CC-*` están en `artifacts/code-excerpts/claude-code-2.1.299-code-excerpts.md` (verbatim, con offset y SHA del chunk).

OpenCode 1.19.3 (`/tmp/opencode/re/opencode_js/root/`):

| Chunk | SHA-256 | Función / símbolo | Hallazgo | Extracto |
|---|---|---|---|---|
| `chunk-bbwy2mqb.js` | `9e8a… (ver extracto)` | `createOpenaiCompatible` | F-09 Bearer + `${base}${path}` | `OC-01` |
| `chunk-3w3d1rw9.js` | `(ver extracto)` | provider `opencode` | F-09 `apiKey:"public"` + filtro coste 0 | `OC-02` |

## 4. Evidencia de pruebas reales contra el proveedor

No realizadas en esta fase (restricción). Evidencia existente citada:

- **Puerta FreeTier (bisectada con curl, misión previa):** `artifacts/reports/INFORME-TRANSFORMER-OPENCODE-ZEN.md` §5 y §7 — las 3 condiciones, el algoritmo de `ses_*` y los descartes experimentales.
- **Superficie unificada Anthropic:** `space-bunny-free` → 200+SSE con puerta; `muse-spark-1.3-contributor-free` → 400 `ModelProtocolUnsupported` (§6 del informe previo).
- **Sondas anónimas 403 (16-oct):** `artifacts/probes/*.hdr` y `*.json` (3 modelos; `FreeTierError`).

## 5. Comandos de inspección reproducibles

### 5.1 Hashes

```bash
sha256sum /home/kaos/.opencode/bin/opencode
sha256sum /home/kaos/.local/share/claude/versions/2.1.299
```

### 5.2 Localizar los fragmentos (una vez extraídos los módulos con REA)

```bash
cd /tmp/opencode/re/claude_js/root
python3 - <<'EOF'
s = open("chunk-gmq0qwep.js", errors="replace").read()
i = s.find("buildURL(r,n,s){")
print(s[i:i+520])
EOF
```

El mismo patrón (`find(ancla)` + ventana) genera los extractos de `artifacts/code-excerpts/`; los offsets quedan anotados en cada extracto.

### 5.3 Extracción con REA (MCP)

La obtención de los módulos usó las herramientas REA sobre los binarios:

1. `open_binary(path="/home/kaos/.local/share/claude/versions/2.1.299")` y `analyze_javascript_application(input_path=…, source_paths=[…], detail="summary", max_heap_mb=4096)` sobre el bundle (los módulos grandes requirieron `source_paths` acotado + heap ampliado; el bundle `84yp45y8.js` quedó en cobertura parcial por presupuesto del grafo semántico).
2. `open_binary(path="/home/kaos/.opencode/bin/opencode")` y el mismo flujo para `opencode_js`.
3. `inspect_analysis_view(source={kind:"retained-evidence", evidence_id:…}, view={kind:"javascript", …})` para paginar módulos concretos.

Las llamadas se documentan aquí como procedimiento; los Evidence ID resultantes están en §2.

### 5.4 Consultas públicas (sin autenticación) — no consumen cuota

```bash
curl -s https://opencode.ai/inference/v1/models | head -c 400
cat /home/kaos/.cache/opencode/models.json | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["opencode"]["api"], len(d["opencode"]["models"]))'
```

La tabla de endpoints oficial está en `https://opencode.ai/v2/docs/console/models/` (DOCUMENTADO).

## 6. Cobertura y limitaciones de la evidencia

- `chunk-84yp45y8.js`: **REA parcial** (1 192 511 nodos AST, 10 306 findings; el grafo semántico excedió el presupuesto). Todo lo citado de ese chunk es análisis estático de facts, no grafo.
- No hay captura de red de una petición de **Claude Code** hacia Zen (nunca ejecutado contra el proveedor).
- El endpoint exacto de las sondas `403` no se conservó (solo respuesta).
- Los informes previos son evidencia narrativa verificable por sus propios comandos (incluidos en `artifacts/reports/`).
