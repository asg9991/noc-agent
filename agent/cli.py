"""CLI read-only contra el LAB: python -m agent.cli problemas | estado."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from agent.config import Settings
from agent.router import handle_ack, handle_estado
from agent.zabbix_client import ZabbixClient


def build_client(settings: Settings) -> ZabbixClient:
    return ZabbixClient(
        url=settings.zabbix_url,
        token=settings.zabbix_token,
        user=settings.zabbix_user,
        password=settings.zabbix_password,
        timeout=settings.timeout,
    )


def cmd_problemas(client: ZabbixClient, limit: int = 20) -> str:
    problems = client.get_problems(limit=limit)
    if not problems:
        return "Sin problemas activos."
    lines = [f"Problemas activos: {len(problems)}"]
    for p in problems:
        ts = datetime.fromtimestamp(
            int(p.get("clock", 0)), tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%SZ")
        lines.append(
            f"- [{p.get('severity', '?')}] {p.get('name', '?')} "
            f"(event {p.get('eventid', '?')}, {ts})"
        )
    return "\n".join(lines)


def cmd_estado(client: ZabbixClient) -> str:
    return handle_estado(client)


def cmd_ack(client: ZabbixClient) -> str:
    return handle_ack(client)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NOC agent CLI (read-only, lab)")
    sub = parser.add_subparsers(dest="command", required=True)
    p_prob = sub.add_parser("problemas", help="Listar problemas activos")
    p_prob.add_argument("--limit", type=int, default=20)
    sub.add_parser("estado", help="Resumen de estado del lab")
    sub.add_parser("ack", help="Guia de ack (no escribe, solo informa)")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    client = build_client(settings)

    if args.command == "problemas":
        print(cmd_problemas(client, limit=args.limit))
    elif args.command == "estado":
        print(cmd_estado(client))
    elif args.command == "ack":
        print(cmd_ack(client))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
