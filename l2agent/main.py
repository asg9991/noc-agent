"""Entrypoint del agente L2: la Casa 3 en un proceso.

Uso:
  python -m l2agent.main "¿hay alertas?" [--role operator] [--audit audit.jsonl]
  python -m l2agent.main --list-tools [--role technician]

Todo por env, nada en argv ni en imagen:
  MCP_URL (default: hub lab), MCP_BEARER o /tmp/.mcp_bearer (600),
  LLM_BASE_URL (default: Ollama local), LLM_MODEL (obligatorio para correr),
  LLM_API_KEY (opcional, solo nube), LLM_MIN_INTERVAL_S (opcional: pacing
  proactivo entre requests, ej. 2 para el free tier; default 0 = off).
"""

from __future__ import annotations

import argparse
import os
import sys

from agent.mcp_client import DEFAULT_MCP_URL, MCPClient
from l2agent.loop import MAX_ITERS, run_loop
from l2agent.model import DEFAULT_BASE_URL, ChatModel
from l2agent.tools import list_available


def build_client_from_env() -> MCPClient:
    return MCPClient(url=os.getenv("MCP_URL", DEFAULT_MCP_URL))


def build_model_from_env(role: str) -> ChatModel:
    name = os.getenv("LLM_MODEL", "").strip()
    if not name:
        print(
            "Falta LLM_MODEL: el operador elige el cerebro por env "
            "(ej. LLM_MODEL=qwen3:8b con Ollama local).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return ChatModel(
        base_url=os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL),
        model=name,
        api_key=os.getenv("LLM_API_KEY", ""),
        role=role,
        min_interval_s=float(os.getenv("LLM_MIN_INTERVAL_S", "0")),
    )


def main(argv: list[str] | None = None, *,
         client: MCPClient | None = None,
         model: ChatModel | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agente local L2 de noc-agent")
    parser.add_argument("goal", nargs="?", help="objetivo en lenguaje natural")
    parser.add_argument("--role", default="operator",
                        help="rol del catálogo curado (operator|technician)")
    parser.add_argument("--audit", default="audit.jsonl",
                        help="ruta del log JSONL de decisiones")
    parser.add_argument("--actor", default=None,
                        help="quién pregunta (identidad de audit, "
                             "arquitectura §7); default: NOC_ACTOR, $USER")
    parser.add_argument("--max-iters", type=int, default=MAX_ITERS)
    parser.add_argument("--list-tools", action="store_true",
                        help="muestra el menú curado y sale (sin red, sin modelo)")
    args = parser.parse_args(argv)
    if args.list_tools:
        print("\n".join(list_available(args.role)))
        return 0
    if not args.goal:
        parser.error("falta el objetivo (o usá --list-tools)")
    actor = (args.actor or os.getenv("NOC_ACTOR")
             or os.getenv("USER") or "cli")
    the_client = client if client is not None else build_client_from_env()
    the_model = model if model is not None else build_model_from_env(args.role)
    print(run_loop(args.goal, model=the_model, client=the_client,
                   actor=actor, audit_path=args.audit,
                   max_iters=args.max_iters))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
