"""Demo aislada: flujo webhook Zabbix -> mensaje Discord (version Python puro).

Equivalente determinista (nivel L0) del flujo operativo descrito en
docs/arquitectura.md, seccion 6:

    Webhook Zabbix -> embed con botones [Detalle] [Mantenimiento] [Ack]

Esta demo NO toca agent/ ni mcp/. Solo replica la logica de extraccion
de un handler L0 (ver agent/router.py): reglas exactas, sin modelo,
sin decisiones autonomas.

Uso:
    python3 docs/n8n/01-webhook-discord.python.py

Credenciales: no hay secretos hardcodeados. La URL y el token de Zabbix
se leen de variables de entorno (ZABBIX_URL, ZABBIX_TOKEN) y solo se usan
para un enriquecimiento opcional. Sin esas variables el script funciona
igual con el payload de ejemplo.
"""

from __future__ import annotations

import json
import os
from typing import Any

# Reutiliza la firma del cliente read-only (agent/zabbix_client.py).
# Si el script se ejecuta fuera del paquete, se usa un sustituto local
# con la misma firma para no romper la demo.
try:
    from agent.zabbix_client import ZabbixClient
except ImportError:  # ejecucion standalone desde docs/n8n/

    class ZabbixClient:  # type: ignore[no-redef]
        """Sustituto con la misma firma que agent/zabbix_client.ZabbixClient."""

        def __init__(
            self,
            url: str,
            token: str = "",
            user: str = "",
            password: str = "",
            timeout: float = 15.0,
        ) -> None:
            self.url = url
            self.token = token
            self.user = user
            self.password = password
            self.timeout = timeout

        def get_version(self) -> str:
            return "no conectado (demo)"

        def get_problems(self, limit: int = 20) -> list[dict[str, Any]]:
            return []

        def get_hosts(self, limit: int = 20) -> list[dict[str, Any]]:
            return []


# Payload de ejemplo con los campos tipicos de un webhook de Zabbix.
# En produccion llega por HTTP POST al endpoint del bot.
EXAMPLE_PAYLOAD: dict[str, Any] = {
    "host": "srv-files-01",
    "problem": "Espacio en disco bajo en /data (>90%)",
    "severity": "High",
    "eventid": "12345",
    "clock": "1727745600",
    "trigger_status": "PROBLEM",
    "zabbix_url": "http://zabbix.local/zabbix.php?action=problem.view&eventid=12345",
}

# Severidad Zabbix (0-5) a etiqueta y color del embed de Discord.
SEVERITY_META: dict[str, dict[str, Any]] = {
    "not classified": {"label": "Sin clasificar", "color": 0x95A5A6},
    "information": {"label": "Informativa", "color": 0x3498DB},
    "warning": {"label": "Advertencia", "color": 0xF1C40F},
    "average": {"label": "Media", "color": 0xE67E22},
    "high": {"label": "Alta", "color": 0xE74C3C},
    "disaster": {"label": "Desastre", "color": 0x992222},
}


def extraer_campos(payload: dict[str, Any]) -> dict[str, str]:
    """Extrae host/problema/severidad con logica L0: exacta y determinista.

    Replica el espiritu de route_l0() en agent/router.py: normaliza
    (strip) y aplica valores por defecto. No infiere, no completa,
    no llama a ningun modelo.
    """
    host = str(payload.get("host", "")).strip() or "desconocido"
    problema = str(payload.get("problem", "")).strip() or "problema sin descripcion"
    severidad = str(payload.get("severity", "")).strip().lower() or "not classified"
    if severidad not in SEVERITY_META:
        severidad = "not classified"
    eventid = str(payload.get("eventid", "")).strip()
    url = str(payload.get("zabbix_url", "")).strip()
    return {
        "host": host,
        "problema": problema,
        "severidad": severidad,
        "eventid": eventid,
        "url": url,
    }


def formatear_embed(campos: dict[str, str]) -> dict[str, Any]:
    """Construye el embed de Discord como estructura dict (sin enviarlo).

    Incluye titulo, campos y los tres botones del flujo operativo:
    Detalle, Mantenimiento y Ack. Los botones solo llevan identificadores;
    la accion real (con confirmacion y auditoria) vive en agent/router.py
    y el hub MCP, nunca aqui.
    """
    meta = SEVERITY_META[campos["severidad"]]
    titulo = f"[{meta['label']}] {campos['host']}: {campos['problema']}"
    embed: dict[str, Any] = {
        "title": titulo,
        "color": meta["color"],
        "fields": [
            {"name": "Host", "value": campos["host"], "inline": True},
            {"name": "Severidad", "value": meta["label"], "inline": True},
            {"name": "Evento", "value": campos["eventid"] or "n/a", "inline": True},
            {"name": "Problema", "value": campos["problema"], "inline": False},
        ],
        "components": [
            {
                "type": "buttons",
                "buttons": [
                    {"id": "detalle", "label": "Detalle", "style": "secondary"},
                    {"id": "mantenimiento", "label": "Mantenimiento", "style": "primary"},
                    {"id": "ack", "label": "Ack", "style": "success"},
                ],
            }
        ],
    }
    if campos["url"]:
        embed["url"] = campos["url"]
    return embed


def cliente_desde_entorno() -> ZabbixClient | None:
    """Crea el cliente read-only desde variables de entorno, o None.

    Nunca incluye credenciales en el codigo. Si ZABBIX_URL no esta
    definida, la demo sigue con el payload de ejemplo.
    """
    url = os.environ.get("ZABBIX_URL", "")
    if not url:
        return None
    return ZabbixClient(
        url=url,
        token=os.environ.get("ZABBIX_TOKEN", ""),
        user=os.environ.get("ZABBIX_USER", ""),
        password=os.environ.get("ZABBIX_PASSWORD", ""),
    )


def main() -> None:
    campos = extraer_campos(EXAMPLE_PAYLOAD)
    embed = formatear_embed(campos)
    cliente = cliente_desde_entorno()
    salida = {
        "extraido": campos,
        "discord_embed": embed,
        "zabbix_conectado": cliente is not None,
    }
    print(json.dumps(salida, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
