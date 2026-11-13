# NOC Agent

Conversational operations assistant for infrastructure monitoring. It answers questions and runs controlled actions over observability tools (Zabbix first) from the channels each client already uses (adapters: mail, Discord, Telegram) and from code agents talking directly to the same MCP hub (no chat in the middle). Reference instance: mail-first.

> **Status: Phase 3 — L2 local agent complete on `feature/l2-local-agent` (pending merge).** Canonical design lives here in `docs/arquitectura.md` (plus `propuesta-bosquejo.md` and `arquitectura-resumen.md`). `agent/` holds the L0/L1/L2 router + read-only Zabbix CLI + thin MCP client (`agent/mcp_client.py`, allowlist-gated); `l2agent/` holds the local L2 agent (decision loop, guardrails, audit JSONL, proactive watch + notify, 0 tokens); `mcp/` holds the curated client catalog (`mcp/curated-tools.json`, 20 read-only tools split operator/technician). Lab data work (Phases 0–2) continues in the zbx-in-docker repo. Operations: `docs/runbook-operativo.md`.

## Quick path

1. Read `docs/arquitectura.md` for the one-page design summary.
2. Follow active lab work in [zbx-in-docker](https://github.com/asg9991/zbx-in-docker) (Phases 0–2, hub MCP lives there).
3. See `mcp/curated-tools.json` (client catalog, 20 tools) and `agent/mcp_client.py` (thin allowlist-gated client) — `agent/` (orchestrator), `l2agent/` (local L2).

## Details

| Topic | Decision |
|-------|----------|
| What it is | Additive conversational layer over Zabbix; Zabbix keeps detecting and notifying. Flow: Monitor → Notify → Understand → Assist → Act. |
| What it is not | Not a monitoring replacement, not a fork of zbx-in-docker. No compose files, templates, or scripts are copied here. |
| Relation to zbx-in-docker | [zbx-in-docker](https://github.com/asg9991/zbx-in-docker) is the data engine: local Zabbix lab, simulated data, and the MCP hub the agent connects to. This repo is the consumer/orchestrator side. Canonical design lives here in `docs/arquitectura.md`. |
| Cost doctrine | L0 deterministic (0 tokens) → L1 classifier (~$0) → L2 agent (curated tools only). Cheapest level that resolves each interaction wins. |
| Channels | Channel-agnostic adapters (mail, Discord, Telegram) over one orchestrator vocabulary, plus n8n at the edge (transform only, never decides). Code agents (OpenCode/Claude/Codex) query the same MCP hub directly with their own token/role. Reference instance: mail-first. |
| Security | Layered: network → bearer token → OAuth 2.1; least privilege; per-user Zabbix credentials as production goal; explicit confirmation for writes; full audit trail. |
| Client artifacts | Canonical home: the per-client private repo (`noc-agent-<cliente>`, under `client/`), seeded from this generic repo. This checkout is also a **lab**: client artifacts and mentions may exist locally under `client/<cliente>/`, organized per client and excluded via `.git/info/exclude` (local-only ignore). Hard rule: they are never committed to this generic repo. |

## Repository structure

```text
mcp/      # Curated client catalog (curated-tools.json, 20 read-only) + loader/validator
agent/    # Orchestrator: router L0/L1/L2, Zabbix read-only client, thin MCP client, CLI
l2agent/  # Local L2 agent: decision loop, guardrails, audit JSONL, watch + notify (0 tokens)
docs/     # Design docs; arquitectura.md is canonical, plus propuesta-bosquejo.md, arquitectura-resumen.md, auditoria-2026-09-10.md, runbook-operativo.md
client/   # LOCAL LAB ONLY: per-client artifacts and mentions, organized per client (never committed)
scripts/  # Lab probes (ceiling probe, model benchmarks)
tests/    # Offline test suite (pytest; fakes, no network)
odd/      # Task trackers (feature docs + backlog)
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
("hay alertas?", "problemas", "versión", "¿cómo está el zabbix?") = L1 al
mismo handler;
resto = L2 (`l2agent`: loop con modelo por env; sin `LLM_MODEL` avisa
en vez de romper). Solo lectura: el CLI no escribe en Zabbix.

## Flujo de desarrollo

`main` es estable. Cada feature vive en su rama y se integra con merge
`--no-ff` (historia visible), tras lo cual la rama queda cerrada
(archivada; no se borra — política local). Cada commit de trabajo lleva
sus tests y docs, y `main` siempre queda verde: la suite completa corre
tras cada merge.

## Next steps

- [x] Canonical architecture doc migrated here from zbx-in-docker (`docs/arquitectura.md`).
- [x] L0/L1 router skeleton + read-only CLI (Phase 3).
- [x] MCP curated catalog (20 tools) + thin allowlist-gated client (merged to main, 18 tests green).
- [x] Local L2 agent: decision loop + guardrails + audit + watch/notify (`l2agent/`, 76 tests green).
- [ ] Merge `feature/l2-local-agent` into `main`.
- [ ] Mail adapter (Phase 4; reference instance is mail-first — Discord/Telegram per instance).
- [ ] Work the open fix backlog: `odd/tasks/backlog-patas-flojas.md`.
