"""Taxonomía de errores del L2: credencial vencida vs transitorio vs resto.

La idea en una frase: un 401 nunca se arregla reintentando (la credencial
sigue vencida), un timeout a veces sí. Si el agente no distingue, o bien
reintenta lo inútil, o bien no grita cuando hay que rotar un token.

Reglas, en orden:

1. Código HTTP manda: 401/403 = credencial, 429/5xx = transitorio.
2. Si no hay código (excepción plana), se buscan huellas en el texto.
3. Si no hay huellas, es "unknown": no se inventa (anti-alucinación
   también vale para errores).

Pura y sin red: entra excepción o texto, sale un string. Testeable con fakes.
"""

from __future__ import annotations

import re

AUTH = "auth"
TRANSIENT = "transient"
UNKNOWN = "unknown"

AUTH_HINTS = (
    "not authorized",
    "unauthorized",
    "invalid token",
    "invalid api key",
    "invalid apikey",
    "authentication failed",
    "auth failed",
    "access denied",
    "forbidden",
)

TRANSIENT_HINTS = (
    "timed out",
    "timeout",
    "connection",
    "temporary",
    "temporarily",
    "unavailable",
    "too many requests",
    "network",
    "dns",
    "reset by peer",
    "broken pipe",
)

# Códigos como TOKEN completo: "build 4014" no es un 401 ni "5000" un 500.
_AUTH_CODE_RE = re.compile(r"\b(?:401|403)\b")
_TRANSIENT_CODE_RE = re.compile(r"\b(?:429|50[0234])\b")


def classify(exc: BaseException | str) -> str:
    """Clasifica un fallo: 'auth' | 'transient' | 'unknown'."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 403):
        return AUTH
    if status == 429 or (isinstance(status, int) and 500 <= status < 600):
        return TRANSIENT
    text = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if _AUTH_CODE_RE.search(lowered) or any(h in lowered for h in AUTH_HINTS):
        return AUTH
    if (_TRANSIENT_CODE_RE.search(lowered)
            or any(h in lowered for h in TRANSIENT_HINTS)):
        return TRANSIENT
    return UNKNOWN


def result_for(kind: str) -> str:
    """Mapea clase a resultado de audit: error_auth | error_transient | error."""
    return {"auth": "error_auth", "transient": "error_transient"}.get(kind, "error")
