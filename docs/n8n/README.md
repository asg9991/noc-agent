# Demo: webhook Zabbix → mensaje Discord (Python vs n8n)

Comparativa aislada del flujo operativo de `docs/arquitectura.md`
(sección 6): webhook Zabbix → embed con botones
[Detalle] [Mantenimiento] [Ack]. No modifica `agent/` ni `mcp/`.

## Archivos

| Archivo | Contenido |
|---|---|
| `01-webhook-discord.python.py` | Script Python puro y determinista (lógica L0 + embed como dict, salida por `print`). |
| `01-webhook-discord.n8n.json` | Export n8n equivalente (webhook → extraer campos → formatear embed → Discord). Importar desde el editor n8n. |

Ambas versiones hacen lo mismo: extraer `host` / `problema` /
`severidad` con valores por defecto y formatear el embed con los tres
botones como identificadores. Ninguna escribe en Zabbix.

## Comparativa

| Criterio | Python puro | n8n |
|---|---|---|
| Latencia | Mínima (proceso local, sin red intermedia) | Mayor (saltos entre nodos + colas del ejecutor) |
| Costo | Nulo (solo intérprete, 0 tokens) | Costo de la instancia n8n (self-hosted o nube) |
| Auditoría | Manual (hay que agregar log propio) | Ejecuciones visibles por defecto (historial por nodo) |
| Retry / schedule | Hay que programarlos a mano | Nativos (reintentos y triggers por tiempo integrados) |
| Quién lo modifica | Desarrollador (código y tests) | Operador (editor visual, sin despliegue) |

## Regla de gobierno

**n8n solo en el borde; el cerebro siempre en `agent/router.py` + hub MCP.**

n8n recibe, transforma y entrega. Nunca decide (sin clasificadores ni
prompts), nunca autoriza acciones y nunca escribe directo en Zabbix.
Detalle, Mantenimiento y Ack se resuelven fuera de n8n, con confirmación
explícita y auditoría según la arquitectura vigente.
