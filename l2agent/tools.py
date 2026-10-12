"""Manos del agente L2: superficie angosta sobre el hub MCP.

El loop nunca llama a MCPClient directo: pasa por acá. Tres garantías:

1. Solo tools curadas: el gate de mcp_client (PermissionError) frena el resto
   antes de tocar la red. Lo denegado se propaga fuerte: es error de
   programación o fuga del prompt, tiene que verse.
2. Salida compactada con límite siempre (doctrina de tokens, palanca #2):
   las listas se truncan y avisan lo que quedó afuera.
3. Errores de transporte normalizados a texto: el loop razona sobre strings,
   no sobre excepciones. Lo transitorio (hub caído) se reporta, no se rompe.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from mcp.catalog import tools_for

from l2agent.errors import classify, result_for

MAX_RESULTS = 50  # límite duro por llamada; el loop puede pedir menos
MAX_CHARS = 4000  # techo de texto devuelto por llamada (tokens)


class ToolClient(Protocol):
    def call_tool(self, name: str, args: dict[str, Any] | None = ...) -> Any: ...


def list_available(role: str) -> list[str]:
    """Nombres curados para un rol ('operator' | 'technician'). Sin schemas."""
    return tools_for(role)


def run(
    client: ToolClient, name: str, args: dict[str, Any] | None = None, *, limit: int = MAX_RESULTS
) -> str:
    """Ejecuta una tool curada y devuelve texto compacto para el loop."""
    try:
        result = client.call_tool(name, dict(args or {}))
    except PermissionError:
        raise  # el gate habla fuerte: no se normaliza ni se esconde
    except Exception as exc:
        # La clase viaja en el prefijo: el loop la lee sin parsear texto.
        # Lo no clasificable keeps "error:" (contrato viejo intacto).
        return f"{result_for(classify(exc))}: {exc}"
    if isinstance(result, list) and len(result) > limit:
        shown = result[:limit]
        rest = len(result) - limit
        return (
            json.dumps(shown, ensure_ascii=False)
            + f"\n…({rest} más afuera: pedí con filtros o menor límite)"
        )
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    return text[:MAX_CHARS]
