# NOC Agent — Architecture (summary)

> **Note:** one-page summary. The canonical design document lives here in
> `docs/arquitectura.md` (plus `propuesta-bosquejo.md` and
> `arquitectura-resumen.md`). Migration from zbx-in-docker is complete; in
> case of divergence, this repo prevails.

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
| Channels | Discord-first para guardia (alertas→hilos, botones, ephemeral); Telegram después con el mismo vocabulario. Agentes de código (OpenCode/Claude/Codex) van directo al hub MCP sin pasar por el chat, con token y rol propios. |
| Security | Network (hub on trusted nets only) → bearer token per consumer → OAuth 2.1 when crossing org boundaries. Channel-ID → profile (Operator / Technician / Admin) → capabilities; per-user Zabbix credentials as production goal. Dual audit: Zabbix native log + agent channel ledger. Sensitive writes need explicit modal confirmation. |

## Lab roadmap

| Phase | Content | Status |
|-------|---------|--------|
| 0 | Local lab compose, Zabbix stack up | done (zbx-in-docker) |
| 1 | Simulated data: flapping hosts/triggers | done (zbx-in-docker) |
| 2 | MCP hub: initMAX zabbix-mcp-server v1.36.1, filtered read-only; external endpoint validation | done 2026-09-26 (curated 15–25 tools per token) |
| 3 | Orchestrator: L0/L1 router + shared client library; CLI first | skeleton done (L2 stub; real L2 waits for `mcp/` client config) |
| 4 | Discord adapter: alerts→threads, buttons, ephemeral, routing ledger | pending (here) |

Decision Phase 2 (2026-09-26, ratified): initMAX zabbix-mcp-server v1.36.1, curated 15–25 tools per read-only token.

Open decisions: production strong model (client's call); long-term memory persistence (after Phase 4).
