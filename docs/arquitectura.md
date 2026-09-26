# NOC Agent — Arquitectura

> Documento de arquitectura del asistente inteligente para la operación y
> observabilidad de infraestructura. Versión inicial, producto de las decisiones
> acordadas en el diseño del laboratorio.

---

## 1. Visión

Evolucionar la plataforma de observabilidad (Zabbix como núcleo) desde un modelo
de **notificación pasiva** hacia uno de **asistencia proactiva**, mediante un
agente conversacional centralizado:

```text
Monitorear → Notificar → Comprender → Asistir → Actuar
```

El NOC Agent es un compañero interno que conoce el estado del NOC, al que se le
habla en lenguaje natural desde los canales que el equipo ya usa, y que —en
etapas posteriores y bajo permisos— ejecuta acciones sobre la infraestructura.

## 2. Principios rectores

1. **No reemplaza nada**: capa aditiva sobre Zabbix; Zabbix sigue detectando y notificando.
2. **Determinista antes que IA**: lo que se puede resolver sin modelo, se resuelve sin modelo.
3. **Anti-alucinación por diseño**: el agente solo responde con datos devueltos por herramientas verificadas; si no hay dato, lo dice.
4. **Seguridad en capas**: red → token → OAuth; privilegio mínimo siempre; ninguna conversación es autorización ilimitada.
5. **Costo por diseño**: cada interacción consume el nivel más barato que la resuelve; el consumo de tokens es medible y reportable.
6. **Auditoría completa**: quién pidió qué, cuándo, desde qué canal y con qué resultado.

## 3. Arquitectura general

```text
   Discord (primario)     Telegram (futuro)      OpenCode / Claude Code / Codex
        │                        │                        │
        └────► Orquestador bot ◄─┘                        │
              (loop propio, cliente MCP) ◄────────────────┘
                          │  MCP streamable HTTP + auth
                          ▼
              ┌──────────────────────────────┐
              │    VM DEDICADA · HUB MCP     │
              │  ├── zabbix-mcp (curado)     │
              │  ├── fortinet-mcp (futuro)   │
              │  └── authz + rate limit      │
              └──────────────┬───────────────┘
                             ▼
                    Zabbix API · (FortiGate REST, futuro)
```

- **Discord/Telegram son adapters**, no sistemas independientes: distintos frentes hacia el mismo cerebro.
- Los endpoints de desarrollo/administración (OpenCode, Claude Code, Codex) se conectan al mismo hub vía MCP nativo: independencia total de endpoint.
- El orquestador define un **vocabulario abstracto de interacción** (`reply`, `menu`, `form`, `ephemeral`) que cada canal traduce a sus componentes nativos.

## 4. Decisión de integración: MCP

Se adopta el **Model Context Protocol** (especificación vigente `2026-07-28`)
como bus de integración.

### Por qué MCP

1. **Independencia de endpoint**: los endpoints principales hablan MCP nativamente; las herramientas viven en nuestra VM y cualquier cliente presente o futuro se conecta sin glue code por consumidor.
2. **Multi-consumidor real**: el mismo server sirve al bot, a ingeniería con agentes de código, y a una futura web.
3. **Escalado por configuración**: sumar Fortinet u otro servicio = agregar otro MCP server al hub, mismo patrón.
4. **Punto único de gobernanza**: scopes, rate limiting y auditoría centralizados.
5. **Estándar maduro**: transporte streamable HTTP y autorización OAuth 2.1 estandarizados.

### Alternativas evaluadas y descartadas

| Alternativa | Por qué no |
|---|---|
| Herramientas nativas in-process | Máximo control de tokens, pero cero independencia de endpoint y re-implementación por consumidor |
| API HTTP propietaria propia | Es "MCP casero": mismas piezas sin el estándar ni su ecosistema |
| Bot clásico sin IA | Se conserva como **base determinista** (nivel L0), no como sustituto |

### Advertencias asumidas

- MCP estandariza la capa de herramientas, **no el cerebro**: el bot necesita su propio orquestador (cliente MCP).
- El catálogo completo (~237 tools) cuesta ~100k tokens solo en schemas por turno: **se expone siempre un subconjunto curado** (~15–25 tools por etapa/rol), nunca el catálogo entero.

## 5. Doctrina de tokens: la escalera de costos

```text
Nivel 0 · Determinista   comandos, botones, plantillas          → 0 tokens
Nivel 1 · Clasificador   intención + parámetros (JSON forzado)  → ~$0
Nivel 2 · Agente         diagnóstico, correlación, NL complejo  → tokens curados
```

**Flujo**: todo mensaje pasa por un router. Reglas exactas primero (L0); si hay
lenguaje natural, un clasificador elige intent + extrae parámetros y —con
confianza suficiente— corre el MISMO handler determinista de L0; ambigüedad o
baja confianza escala a L2.

Reglas operativas:

- **L0/L1 no tocan el catálogo de tools**: hablan directo con Zabbix vía la librería cliente compartida. El catálogo curado existe solo en L2.
- Con modelos chicos, las respuestas salen de **plantillas con datos reales**; la prosa generada queda para L2.
- Cada decisión de routing se registra → informe mensual de distribución por nivel (insumo directo de costos para el cliente).

### Clasificador intercambiable

La escalera es doctrina de costos, no topología fija. Configuraciones equivalentes:

| Config | L0 | L1 | L2 | Uso |
|---|---|---|---|---|
| A | reglas + botones | modelo local (Ollama) | pago fuerte | laboratorio / clientes con infra local |
| B | reglas + botones | modelo pago chico (clase Haiku) | pago fuerte | clientes sin IA local |
| C | reglas + botones | — | pago fuerte | mínima: todo lo ambiguo al agente |

El cambio entre configuraciones es configuración del adaptador de proveedor,
no refactor.

### Palancas de ahorro (orden de impacto)

1. Slash commands deterministas que golpean Zabbix sin LLM.
2. Catálogo curado con salida compactada y límite de resultados siempre.
3. Routing local → pago.
4. Memoria externa (incidentes, runbooks, contexto histórico) para no arrastrar historial largo.
5. Prompt caching del catálogo y system prompt.

## 6. Canales: Discord primero

Discord es el canal primario del primer cliente y el adapter más completo:

| Necesidad | Componente Discord |
|---|---|
| Acciones rápidas | Buttons (hasta 25/mensaje) |
| Selección de opciones | Select menus |
| Formularios (ej. mantenimiento, ack con comentario) | Modals |
| Respuestas que no molestan al canal | Ephemeral replies |
| Contexto por incidente | Threads vinculados a cada alerta |

Flujo operativo tipo:

```text
#alertas
   Webhook Zabbix → embed con botones [Detalle] [Mantenimiento] [Ack]
        └── crea hilo 🧵 #host-problema
              ├── consultas por botón (respuesta ephemeral)
              ├── preguntas en lenguaje natural (L1/L2 dentro del hilo)
              └── acciones con confirmación via modal + auditoría
```

El historial del hilo alimenta al agente como contexto natural del incidente.
Telegram se implementa después reutilizando el mismo orquestador y vocabulario.

## 7. Seguridad y gobernanza

Capas, en orden de adopción:

1. **Red**: hub MCP solo alcanzable desde redes confiables (LAN/túnel).
2. **Token**: bearer token por consumidor del hub.
3. **OAuth 2.1**: cuando el acceso cruce límites organizativos.

Modelo de identidad: ID de usuario de canal → perfil (Operador / Técnico /
Administrador) → capacidades permitidas. Objetivo productivo: credenciales
Zabbix por usuario (la IA nunca opera como super-admin genérico).

Auditoría doble:

- **Acciones sobre Zabbix** → Audit Log nativo de Zabbix (quién/qué/cuándo).
- **Metadatos de canal** (usuario, canal, solicitud, resultado) → registro propio del agente.

Escrituras sensibles requieren **confirmación explícita** (modal) antes de
ejecutarse.

## 8. Hoja de ruta del laboratorio

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Adaptar compose a lab local (`DATA_DIR` parametrizado) y levantar stack Zabbix | hecha |
| 1 | Datos simulados: hosts falsos con triggers que flappean (problemas reales para consultar) | hecha |
| 2 | Hub MCP: initMAX zabbix-mcp-server v1.36.1 filtrado read-only; validación con endpoint externo (Claude Code/OpenCode) | hecha (decisión 2026-09-26) |
| 3 | Orquestador: router L0/L1 + librería cliente compartida; CLI primero | skeleton hecho (L2 stub; L2 real pendiente de `mcp/` client config) |
| 4 | Adapter Discord: alertas→hilos, botones, ephemeral, ledger de routing | pendiente |

Decisión Fase 2 (2026-09-26, ratificada): initMAX `zabbix-mcp-server` v1.36.1.
Criterios aplicados: filtrado de tools por token (curado 15–25, nunca catálogo
completo), modo read-only real (sin writes ni `raw_api_call`), madurez del
proyecto (analytics: anomaly_detect y capacity_forecast verificados en lab).
Evidencia: spike MCP en lab (rotación de tokens, ACL 600), research §3–§4.

## 9. Decisiones abiertas

- Modelo fuerte de producción (decisión del cliente; adapter ya contempla nube).
- Persistencia de memoria de largo plazo para "conocer el NOC" (runbooks, incidentes): a definir tras Fase 4.
