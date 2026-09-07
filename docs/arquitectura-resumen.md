# NOC Agent — Architecture (summary)

> **Note:** one-page summary. The canonical design document currently lives in
> [zbx-in-docker](https://github.com/asg9991/zbx-in-docker) at
> `docs/noc-agent/arquitectura.md` (plus `propuesta-bosquejo.md`) and will
> migrate here. In case of divergence, the zbx-in-docker version prevails
> until migration is declared complete.

## Vision

Evolve observability from passive notification to proactive assistance:
Monitor → Notify → Understand → Assist → Act. Additive layer over Zabbix;
verified tool data only — no data, no answer.

## Design

| Topic | Decision |
|-------|----------|
| Integration bus | MCP (spec `2026-07-28`), streamable HTTP. One hub on a dedicated VM serves the bot, code-agent endpoints, and a future web UI. Adding a tool (e.g. Fortinet) = adding one MCP server, no per-consumer glue. |
| Hub contents | `zabbix-mcp` (curated, read-only first) → future `fortinet-mcp`; central authz + rate limit. Full catalog (~237 tools) is never exposed; each stage/role gets a curated subset (~15–25 tools). |
| Cost ladder | L0 deterministic: commands, buttons, templates (0 tokens). L1 classifier: intent + params, runs the same L0 handler on confidence (~$0). L2 agent: diagnosis and open NL (curated catalog only). L0/L1 bypass the tool catalog via a shared client library; every routing decision is logged for monthly cost reporting. |
| Channels | Discord-first: alert embeds with buttons open per-incident threads; natural language inside threads; modals confirm writes. Abstract vocabulary (`reply`, `menu`, `form`, `ephemeral`) so Telegram reuses the orchestrator later. |
| Security | Network (hub on trusted nets only) → bearer token per consumer → OAuth 2.1 when crossing org boundaries. Channel-ID → profile (Operator / Technician / Admin) → capabilities; per-user Zabbix credentials as production goal. Dual audit: Zabbix native log + agent channel ledger. Sensitive writes need explicit modal confirmation. |

## Lab roadmap

| Phase | Content | Status |
|-------|---------|--------|
| 0 | Local lab compose, Zabbix stack up | done (zbx-in-docker) |
| 1 | Simulated data: flapping hosts/triggers | done (zbx-in-docker) |
| 2 | MCP hub: filtered read-only zabbix-mcp; external endpoint validation | in progress (zbx-in-docker) |
| 3 | Orchestrator: L0/L1 router + shared client library; CLI first | pending (here) |
| 4 | Discord adapter: alerts→threads, buttons, ephemeral, routing ledger | pending (here) |

Open decisions: final MCP server choice (empirical, Phase 2); production strong model (client's call); long-term memory persistence (after Phase 4).
