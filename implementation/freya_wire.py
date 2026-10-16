#!/usr/bin/env python3
"""Port vendored del transformer Freya-Hermes para Claude-Code (stdlib only).

Origen (solo lectura, NO modificado):
  ~/.hermes/hermes-agent/agent/opencode_affinity.py
    - _OPENCODE_FREE_MODELS, _OPENCODE_CLI_VERSION
    - _new_opencode_id, _free_session_for_scope
    - _is_opencode_free_wire_target, _opencode_free_wire_headers
    - merge_opencode_free_wire_headers
  ~/.hermes/hermes-agent/agent/chat_completion_helpers.py:1544-1568 (build_api_kwargs)
  ~/.hermes/hermes-agent/agent/transports/codex.py:878-890 (refresh msg_* por request)
  ~/.hermes/hermes-agent/hermes_cli/models.py:2549-2570 (api_mode por modelo)

Diferencias de adaptacion (Claude-Code es HTTP Anthropic, no in-process Hermes):
  - Sin imports Hermes: logica copiada, no importada.
  - Sesion estable por conversacion: Hermes deriva scope de conversation ROOT;
    aqui se deriva de forma determinista del historial Anthropic (hash del primer
    texto user + modelo), con cache en memoria por scope (misma semantica que
    _free_session_for_scope original).
  - Request fresco por request: msg_* nuevo en cada llamada a Zen (igual que el
    transporte codex refresca en cada request).
  - Sin tocar el original: este archivo es copia; el transformer Freya-Hermes
    sigue intacto en ~/.hermes.

HISTORICO (wire v1, 2026-10-15): superado el 2026-10-16 por el contrato v2
(``zen_fingerprint.py``): /inference/v1, UA `opencode/latest/<ver>/cli`,
`Bearer public`, tools read/shell VERBATIM y stream:true obligatorio. Este
modulo queda por sus helpers vivos (``conversation_scope``, catalogo free,
``zen_model_for_request``) y como referencia del wire 1.19.0; el wire HTTP lo
construye ahora ``zen_fingerprint``.

Opcion 1 (2026-10-15, historico): wire alineado al cliente real opencode
1.19.0 (verificado en el binario `~/.opencode/bin/opencode`):
  - UA `opencode/1.19.0` (antes 1.18.31 pineado en septiembre).
  - SIN `Authorization: Bearer public`: el literal no existe en el binario
    1.19.0; el cliente real no lo manda (sin cuenta y sin OPENCODE_API_KEY
    no hay header Authorization).
  - `x-opencode-session-id` (= mismo sessionID) ademas de `x-opencode-session`;
    `x-opencode-parent-session-id` solo si hay padre (aqui nunca).
  - `x-opencode-request` = ID del user message del turno (fresco por request);
    `x-opencode-project` = project.id real (`global` aqui);
    `x-opencode-client` = `cli`.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time

OPENCODE_CLI_VERSION = "1.19.0"  # historico v1; la UA viva esta en zen_fingerprint
OPENCODE_ZEN_BASE = "https://opencode.ai/zen/v1"  # cerrado el 2026-10-14; usar /inference/v1
OPENCODE_ZEN_RESPONSES_PATH = "/responses"
ZEN_MODEL_DEFAULT = "muse-spark-1.3-contributor-free"

# Catalogo free vigente al 2026-10-16 (sonda P1: GET /inference/v1/models,
# 88 modelos / 13 free; salio nemotron-3-ultra-free, entraron big-pickle
# (Fase 4) y jev-1.13-free). El catalogo vivo se consulta en runtime via
# ``zen_fingerprint.fetch_models``; este set es el fallback sin red.
OPENCODE_FREE_MODELS = frozenset({
    "beam-free",
    "big-pickle",
    "ll-alpha-free",
    "mimo-v2.6-flash-free",
    "muse-spark-1.2-contributor-free",
    "muse-spark-1.3-contributor-free",
    "nemotron-3.5-super-vl-free",
    "nemotron-3.5-lightning-free",
    "jev-1.13-free",
    "longcat-2.5-preview-free",
    "deepseek-v4.1-flash-free",
    "glm-5.3-flash-free",
    "space-bunny-free",
})

# Alias que el gateway acepta y sirve en GET /v1/models para que el selector
# de Claude Code (filtra ids con "claude"/"anthropic") muestre los free.
MODEL_ALIAS_PREFIX = "claude-free-"

_id_counter = 0
_id_counter_ms = 0
_id_counter_lock = threading.RLock()

_free_session_cache: dict[str, str] = {}
_free_session_lock = threading.RLock()


def new_opencode_id(prefix: str) -> str:
    """Generador fiel al cliente oficial (port de _new_opencode_id).

    {prefix}_{12 hex invertidos}{14 base62 CSPRNG}. El servidor parsea el
    timestamp de vuelta desde la parte hex; IDs no invertidos -> 403.
    """
    global _id_counter, _id_counter_ms
    with _id_counter_lock:
        ms = int(time.time() * 1000)
        if ms != _id_counter_ms:
            _id_counter_ms = ms
            _id_counter = 0
        _id_counter += 1
        n = ms * 0x1000 + _id_counter
        low48 = (~n) & ((1 << 48) - 1)
    hex_part = f"{low48:012x}"
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    rand_part = "".join(secrets.choice(alphabet) for _ in range(14))
    return f"{prefix}_{hex_part}{rand_part}"


def free_session_for_scope(scope: str) -> str:
    """ses_* estable por scope de conversacion (cache en memoria)."""
    with _free_session_lock:
        if scope not in _free_session_cache:
            _free_session_cache[scope] = new_opencode_id("ses")
        return _free_session_cache[scope]


def normalize_model_id(model: str | None) -> str:
    raw = str(model or "").strip()
    # Acepta "opencode-zen/<slug>" y "provider/<slug>"; Zen ve el slug pelado.
    return raw.rsplit("/", 1)[-1].strip().lower()


def is_free_model(model: str | None) -> bool:
    return normalize_model_id(model) in OPENCODE_FREE_MODELS


def is_muse_spark(model: str | None) -> bool:
    return normalize_model_id(model).startswith("muse-spark")


def model_alias(model: str | None) -> str:
    """Id del selector para un free: ``claude-free-<slug>``."""
    return MODEL_ALIAS_PREFIX + str(model or "").strip()


def resolve_zen_model(requested: str | None) -> str:
    """Modelo free verificado al que se enruta el request (estricto).

    Acepta el slug pelado (``beam-free``), con prefijo provider
    (``opencode/beam-free``) o alias del selector (``claude-free-beam-free``).
    Un id desconocido lanza ValueError: jamas se sustituye en silencio por
    otro modelo (un fallback oculto haria responder a un modelo distinto del
    solicitado).
    """
    raw = str(requested or "").strip()
    if not raw:
        raise ValueError(
            "missing model: set ANTHROPIC_MODEL to a free OpenCode Zen id "
            f"(available: {', '.join(sorted(OPENCODE_FREE_MODELS))})")
    bare = raw.rsplit("/", 1)[-1].strip().lower()
    if bare.startswith(MODEL_ALIAS_PREFIX):
        bare = bare[len(MODEL_ALIAS_PREFIX):]
    if bare in OPENCODE_FREE_MODELS:
        return bare
    raise ValueError(
        f"unknown/unsupported model '{raw}': the gateway only routes the "
        f"verified free models (available: {', '.join(sorted(OPENCODE_FREE_MODELS))})"
        "; set ANTHROPIC_MODEL to one of them")


def zen_model_for_request(requested: str | None) -> str:
    """Compat: alias estricto de ``resolve_zen_model`` (lanza si no es free)."""
    return resolve_zen_model(requested)


def conversation_scope(body: dict) -> str:
    """Scope estable por conversacion para ses_* (adaptacion del ROOT de Hermes).

    Hermes usa conversation ROOT estable; aqui el gateway es stateless, asi que se
    deriva del primer texto user + modelo. Turnos de la misma conversacion
    comparten primer mensaje -> mismo scope -> mismo ses_*. Sesiones distintas
    (primer texto distinto) -> scope distinto. Determinista, sin estado en disco.
    """
    try:
        model = normalize_model_id(body.get("model"))
        msgs = body.get("messages") or []
        first_text = ""
        for m in msgs:
            if isinstance(m, dict) and m.get("role") == "user":
                c = m.get("content")
                if isinstance(c, str):
                    first_text = c
                elif isinstance(c, list):
                    bits = []
                    for b in c:
                        if isinstance(b, dict) and b.get("type") == "text":
                            bits.append(str(b.get("text", "")))
                    first_text = "\n".join(bits)
                break
        seed = f"{model}\x00{first_text[:500]}"
        return "conv-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    except Exception:
        return "conv-oneshot"


def free_wire_headers(scope: str) -> dict[str, str]:
    """Los 5 headers del wire free-tier (port de _opencode_free_wire_headers)."""
    return {
        "User-Agent": f"opencode/{OPENCODE_CLI_VERSION}",
        "x-opencode-session": free_session_for_scope(scope or "oneshot"),
        "x-opencode-request": new_opencode_id("msg"),
        "x-opencode-client": "cli",
        "x-opencode-project": "global",
    }


def zen_request_headers(scope: str, parent_scope: str | None = None) -> dict[str, str]:
    """Headers HTTP completos hacia POST /zen/v1/responses (wire 1.19.0).

    Sin `Authorization`: el cliente real no manda `Bearer public` (literal
    ausente en el binario 1.19.0) y hoy ese literal es 403 siempre.
    Incluye `x-opencode-session-id` (= sessionID, como el real) y padre
    solo si lo hay.
    """
    h = free_wire_headers(scope)
    out = {
        "Content-Type": "application/json",
        **h,
        "x-opencode-session-id": h["x-opencode-session"],
    }
    if parent_scope:
        out["x-opencode-parent-session-id"] = free_session_for_scope(parent_scope)
    return out
