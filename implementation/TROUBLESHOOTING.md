# TROUBLESHOOTING — claude-code-local-gateway

## `500 Internal Privoxy Error` contra 127.0.0.1

Causa: `HTTP_PROXY` heredado sin `NO_PROXY` (shell no-login). Fix ya aplicado:
tests con opener sin proxy; `bin/claude-gateway` usa `curl --noproxy '*'`.
No tocar Privoxy: el loopback nunca debe ir al proxy.

## Puerto ocupado

`port 127.0.0.1:8479 occupied` → `ss -tln | grep 8479` para ver quién lo tiene;
o `CLAUDE_GATEWAY_PORT=8480 ./bin/claude-gateway start`. Solo 127.0.0.1.

## `403 FreeTierError` en upstream `zen` (2026-10-16)

Con el wire v2 (`zen_fingerprint` 0.4.0) las causas tipicas son:

1. Faltan los tools `read`/`shell` verbatim en el body (`/messages` y
   `/chat/completions` lo exigen; probado: sin ellos → 403 incluso con todo
   lo demas correcto).
2. `stream:false` upstream (el free tier fuerza SSE).
3. UA/authorization/sesion alterados (debe ser el wire completo del gateway;
   no añadir cabeceras a mano en passthrough: usar `--upstream zen`).
4. Modelo pagado sin credencial (401 AuthError, p.ej. `glm-5`).
5. Modelo usando un protocolo que no soporta (400
   `ModelProtocolUnsupported`): el routing del gateway ya elige el correcto
   por modelo; si agregas un id nuevo al catalogo, comprueba su protocolo.

Errores del proveedor se propagan sin modificar (para que CC los muestre).

## `event: error` "truncated by provider" a mitad de stream

El free tier a veces corta el SSE sin `message_stop`/`[DONE]`. El gateway
emite `event: error` a proposito para que CC reintente en vez de esperar
300 s. Reintentar suele resolverlo; no es corrupcion del gateway.

## Imagenes en modelos chat

El bridge `zen_chat` omite bloques `image` (el upstream chat devuelve 422/400
con `image_url`). Usa un modelo de `/messages` (space-bunny-free) para
multimodal; ahi el relay pasa las imagenes tal cual (DEMOSTRADO).

## Claude Code ignora el gateway (`/status` sin base URL)

La variable no llegó a la sesión: arrancar con `./bin/claude-with-gateway`
desde el mismo shell (no exportarla en otro terminal). Si `ANTHROPIC_API_KEY`
convive, el lanzador ya la des-setea en el hijo.

## Timeouts en streams largos

Subir `API_TIMEOUT_MS` en el entorno del hijo si el upstream es lento; en mock
los chunks llevan 2 ms de pausa intencionada.

## Logs sin secretos

`bin/claude-gateway logs [N]` (defecto 50). `Authorization`/`x-api-key` salen
como `[REDACTED]`. Si se sospecha fuga, `grep -i "sk-ant\|bearer sk" run/gateway.log`
debe dar vacío (la clave de passthrough nunca se loguea).

## Recuperación

`stop` + `start` bastan (stateless). Si un turno quedó a medias, reenviar el
historial completo: el gateway no guarda estado entre requests.
