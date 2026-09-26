# NOC Agent

Conversational operations assistant for infrastructure monitoring. It answers questions and runs controlled actions over observability tools (Zabbix first) from the channels the team already uses (Discord first, Telegram later) and from code agents talking directly to the same MCP hub (no chat in the middle).

> **Status: Phase 3 skeleton done.** Canonical design lives here in `docs/arquitectura.md` (plus `propuesta-bosquejo.md` and `arquitectura-resumen.md`). `agent/` holds the L0/L1/L2 router + read-only Zabbix CLI; `mcp/` is still an empty placeholder pending Phase 2 server selection. Lab data work (Phases 0–2) continues in the zbx-in-docker repo. Operations: `docs/runbook-operativo.md`.

## Quick path

1. Read `docs/arquitectura.md` for the one-page design summary.
2. Follow active lab work in [zbx-in-docker](https://github.com/asg9991/zbx-in-docker) (Phases 0–2).
3. Watch `mcp/` (tool hub clients) and `agent/` (orchestrator) — both empty placeholders for now.

## Details

| Topic | Decision |
|-------|----------|
| What it is | Additive conversational layer over Zabbix; Zabbix keeps detecting and notifying. Flow: Monitor → Notify → Understand → Assist → Act. |
| What it is not | Not a monitoring replacement, not a fork of zbx-in-docker. No compose files, templates, or scripts are copied here. |
| Relation to zbx-in-docker | [zbx-in-docker](https://github.com/asg9991/zbx-in-docker) is the data engine: local Zabbix lab, simulated data, and the MCP hub the agent connects to. This repo is the consumer/orchestrator side. Canonical design lives here in `docs/arquitectura.md`. |
| Cost doctrine | L0 deterministic (0 tokens) → L1 classifier (~$0) → L2 agent (curated tools only). Cheapest level that resolves each interaction wins. |
| Channels | Discord-first (buttons, threads, modals, ephemeral replies) for on-call; Telegram later reusing the same orchestrator vocabulary. Code agents (OpenCode/Claude/Codex) query the same MCP hub directly with their own token/role, never via Discord. |
| Security | Layered: network → bearer token → OAuth 2.1; least privilege; per-user Zabbix credentials as production goal; explicit confirmation for writes; full audit trail. |

## Repository structure

```text
mcp/      # MCP hub client configuration and curated tool subsets (empty, pending Phase 2)
agent/    # Orchestrator: router L0/L1/L2, Zabbix read-only client, CLI (Phase 3 done, Discord pending Phase 4)
docs/     # Design docs; arquitectura.md is canonical, plus propuesta-bosquejo.md, arquitectura-resumen.md, auditoria-2026-09-10.md, runbook-operativo.md
```

## Orquestador

Esqueleto Fase 3: router L0/L1/L2 + cliente Zabbix read-only + CLI.

```bash
cp .env.example .env        # completar con valores del operador, nunca commitear
python3 -m agent.cli estado --help
ZABBIX_URL=http://localhost/api_jsonrpc.php python3 -m agent.cli estado
ZABBIX_URL=http://localhost/api_jsonrpc.php python3 -m agent.cli problemas
python3 -m pytest -q
```

Niveles: `estado`/`ack` exactos = L0; lenguaje natural con keywords
("hay alertas?", "cómo está el zabbix?") = L1 al mismo handler;
resto = L2 stub ("no implementado, usar MCP"). Solo lectura: el CLI
no escribe en Zabbix.

## Next steps

- [x] Canonical architecture doc migrated here from zbx-in-docker (`docs/arquitectura.md`).
- [x] L0/L1 router skeleton + read-only CLI (Phase 3).
- [ ] Add MCP client config once Phase 2 selects the Zabbix MCP server.
- [ ] Add Discord adapter (Phase 4).
