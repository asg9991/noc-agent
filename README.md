# NOC Agent

Conversational operations assistant for infrastructure monitoring. It answers questions and runs controlled actions over observability tools (Zabbix first) from the channels the team already uses (Discord first, Telegram later).

> **Status: scaffold.** No agent code yet. Canonical design now lives here in `docs/arquitectura.md` (plus `propuesta-bosquejo.md` and `arquitectura-resumen.md`). Lab data work (Phases 0–2) continues in the zbx-in-docker repo. This repo holds the agent skeleton only.

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
| Channels | Discord-first (buttons, threads, modals, ephemeral replies); Telegram later reusing the same orchestrator vocabulary. |
| Security | Layered: network → bearer token → OAuth 2.1; least privilege; per-user Zabbix credentials as production goal; explicit confirmation for writes; full audit trail. |

## Repository structure

```text
mcp/      # MCP hub client configuration and curated tool subsets (empty)
agent/    # Orchestrator: router L0/L1/L2, channel adapters (empty)
docs/     # Design docs; arquitectura.md is canonical, plus propuesta-bosquejo.md and arquitectura-resumen.md
```

## Next steps

- [x] Canonical architecture doc migrated here from zbx-in-docker (`docs/arquitectura.md`).
- [ ] Add MCP client config once Phase 2 selects the Zabbix MCP server.
- [ ] Add L0/L1 router skeleton (Phase 3), then the Discord adapter (Phase 4).
