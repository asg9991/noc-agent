# NOC Agent

Conversational operations assistant for infrastructure monitoring. It answers questions and runs controlled actions over observability tools (Zabbix first) from the channels each client already uses (adapters: mail, Discord, Telegram) and from code agents talking directly to the same MCP hub (no chat in the middle). Reference instance (Cespal): mail-first.

> **Status: Phase 3 in progress (L2 thin client done on main).** Canonical design lives here in `docs/arquitectura.md` (plus `propuesta-bosquejo.md` and `arquitectura-resumen.md`). `agent/` holds the L0/L1/L2 router + read-only Zabbix CLI + thin MCP client (`agent/mcp_client.py`, allowlist-gated); `mcp/` holds the curated client catalog (`mcp/curated-tools.json`, 20 read-only tools split operator/technician). Lab data work (Phases 0–2) continues in the zbx-in-docker repo. Operations: `docs/runbook-operativo.md`.

## Quick path

1. Read `docs/arquitectura.md` for the one-page design summary.
2. Follow active lab work in [zbx-in-docker](https://github.com/asg9991/zbx-in-docker) (Phases 0–2, hub MCP lives there).
3. See `mcp/curated-tools.json` (client catalog, 20 tools) and `agent/mcp_client.py` (thin allowlist-gated client) — `agent/` (orchestrator).

## Details

| Topic | Decision |
|-------|----------|
| What it is | Additive conversational layer over Zabbix; Zabbix keeps detecting and notifying. Flow: Monitor → Notify → Understand → Assist → Act. |
| What it is not | Not a monitoring replacement, not a fork of zbx-in-docker. No compose files, templates, or scripts are copied here. |
| Relation to zbx-in-docker | [zbx-in-docker](https://github.com/asg9991/zbx-in-docker) is the data engine: local Zabbix lab, simulated data, and the MCP hub the agent connects to. This repo is the consumer/orchestrator side. Canonical design lives here in `docs/arquitectura.md`. |
| Cost doctrine | L0 deterministic (0 tokens) → L1 classifier (~$0) → L2 agent (curated tools only). Cheapest level that resolves each interaction wins. |
| Channels | Channel-agnostic adapters (mail, Discord, Telegram) over one orchestrator vocabulary, plus n8n at the edge (transform only, never decides). Code agents (OpenCode/Claude/Codex) query the same MCP hub directly with their own token/role. Reference instance (Cespal): mail-first. |
| Security | Layered: network → bearer token → OAuth 2.1; least privilege; per-user Zabbix credentials as production goal; explicit confirmation for writes; full audit trail. |

## Repository structure

```text
mcp/      # Curated client catalog (curated-tools.json, 20 read-only) + loader/validator
agent/    # Orchestrator: router L0/L1/L2, Zabbix read-only client, thin MCP client, CLI (Discord pending Phase 4)
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
- [x] MCP curated catalog (20 tools) + thin allowlist-gated client (merged to main, 18 tests green).
- [ ] Add Discord adapter (Phase 4).
