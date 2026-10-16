# INSTALL — claude-code-local-gateway

## Requisitos

* `python3` ≥ 3.10 (probado 3.14.4), sin dependencias (stdlib).
* `claude` 2.x en PATH, puerto `127.0.0.1:8479` libre (o `CLAUDE_GATEWAY_PORT`).
* WARP/Privoxy en marcha (no los toca; el gateway solo añade un listener local).

## Instalación

Ninguna: los archivos ya están en `~/workspace/Transformers/Claude-Code/`.

```sh
cd ~/workspace/Transformers/Claude-Code
python3 -m py_compile gateway.py freya_wire.py freya_tools.py zen_bridge.py && echo compile-ok
python3 -m unittest discover -s tests 2>&1 | tail -n 3   # 24 tests OK esperado
```

## Arranque / parada / estado

```sh
./bin/claude-gateway start    # mock por defecto; health-poll con --noproxy
./bin/claude-gateway status
./bin/claude-gateway doctor   # python, claude, warp, proxy, puertos, health
./bin/claude-gateway stop
```

Variables (solo entorno del proceso, nada persistente):

| var | defecto | efecto |
|---|---|---|
| `CLAUDE_GATEWAY_PORT` | `8479` | puerto loopback |
| `CLAUDE_GATEWAY_UPSTREAM` | `mock` | `mock` \| `passthrough` \| `zen` |
| `CLAUDE_GATEWAY_UPSTREAM_URL` | según upstream (`zen`→`https://opencode.ai/zen/v1`) | destino en `passthrough`/`zen` |

En `passthrough` la clave se aporta por entorno al arrancar
(p. ej. `CLAUDE_GATEWAY_API_KEY` propia) y nunca se escribe a disco ni a logs.

## Desinstalación / reversión

```sh
./bin/claude-gateway stop
rm -rf ~/workspace/Transformers/Claude-Code/{run,gateway.log}
# Los docs y el código del gateway son autocontenidos; borrar el directorio
# revierte todo. ~/.claude/settings.json no se modifica nunca.
```
