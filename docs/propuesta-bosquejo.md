# Propuesta NOC Agent — Bosquejo v0.1

> **Borrador de trabajo** para discusión interna. Supuestos y números marcados
> como estimaciones a validar con el cliente antes de cualquier presentación.

---

## 1. Resumen ejecutivo

Se propone la implementación del **NOC Agent**: un asistente inteligente
centralizado que permite al equipo técnico interactuar con la plataforma de
monitoreo en lenguaje natural, desde los mismos canales donde ya recibe las
alertas.

El agente no reemplaza ninguna herramienta existente: agrega una capa de
inteligencia sobre Zabbix que transforma la notificación técnica en una
conversación operativa —con contexto, antecedentes y, progresivamente,
capacidad de acción controlada—.

La transición propuesta:

**Monitorear → Notificar → Comprender → Asistir → Actuar**

## 2. El problema hoy

- Las alertas llegan como eventos técnicos crudos; interpretarlas exige abrir consolas y conocer dónde buscar.
- El conocimiento operacional (qué pasó antes, qué significa este patrón) está disperso o en la cabeza de pocas personas.
- El tiempo de diagnóstico se extiende por fricción de acceso a la información, especialmente fuera de horario y desde dispositivos móviles.

## 3. La solución

Un servicio centralizado —alojado en infraestructura dedicada— al que el equipo
accede por dos caminos independientes al mismo hub: guardia por el canal que ya
usa (adapters: mail, Discord, Telegram) y técnicos con agentes directos al MCP:

```text
   Guardia                    Técnicos / ingeniería
   Mail · Discord · Telegram  OpenCode · Claude Code · Codex
        │  (adapter a elección)        │  (MCP directo, sin chat)
         ▼                              ▼
        ┌─────────────────┐        ┌──────────────────────┐
        │   NOC AGENT     │  MCP   │  Servicios de red    │
        │  orquestación,  │◄──────►│  Zabbix (hoy)        │
        │  permisos,      │        │  Fortinet (futuro)   │
        │  auditoría      │        └──────────────────────┘
        └─────────────────┘
```

> Instancia Cespal: guardia por mail (hilos por incidente). Discord/Telegram
> disponibles para otras instancias sin cambiar el orquestador.

### Características principales

- **Cada alerta abre un hilo de conversación**: el incidente se investiga desde el celular, sin abrir la consola de Zabbix.
- **Lenguaje natural con respuestas basadas en datos reales**: el asistente solo responde con información verificada de las herramientas; si no hay dato, lo dice.
- **Comandos directos sin costo de IA**: status, problemas críticos, estado de hosts — respuesta inmediata mediante botones y menús.
- **Arquitectura abierta y escalable**: integración basada en MCP (Model Context Protocol), estándar abierto compatible con los principales asistentes de IA del mercado. Sumar un nuevo sistema (p. ej. Fortinet) es agregar un componente, no reescribir el proyecto.

## 4. Etapas del proyecto

### Etapa 1 — Monitoreo y consulta (solo lectura)

- Resumen de problemas activos por severidad y grupo.
- Investigación guiada de un host: métricas, historial, duración del problema.
- Explicación en lenguaje humano de por qué disparó una alarma.
- Antecedentes: si el comportamiento ya ocurrió anteriormente.

### Etapa 2 — Operación controlada

- Reconocimiento de alarmas con comentarios contextuales.
- Ventanas de mantenimiento gestionadas por conversación.
- Toda escritura requiere **confirmación explícita** y queda registrada en la auditoría nativa de Zabbix más el registro propio del agente.

### Etapa 3 — Inteligencia operacional

- Correlación de eventos en cascada (identificación de causa raíz).
- Detección de desviaciones contra línea base.
- Procedimientos recomendados según tipo de incidencia.

### Etapa 4 — Expansión

Incorporación progresiva de nuevas fuentes: seguridad de perímetro (Fortinet),
servicios, inventario — bajo el mismo modelo de permisos y auditoría.

## 5. Transparencia de costos de IA

Diferencial de esta propuesta: **el consumo de IA es medible, acotado por
diseño y reportable**. Cada interacción se resuelve en el nivel más económico
posible:

| Nivel | Qué resuelve | Costo |
|---|---|---|
| Determinista | Comandos, botones, consultas frecuentes | Sin costo de IA |
| Clasificación | Interpretar mensajes simples y derivarlos a flujos fijos | Mínimo |
| Agente IA | Diagnóstico complejo, análisis, lenguaje natural abierto | Por uso, acotado |

En la práctica diaria esto significa que la mayoría del tráfico operativo
(status, consultas repetidas) **no consume IA**, reservando el presupuesto para
donde genera valor real. Se entrega un informe mensual de distribución de uso
y costos estimados.

> Números concretos de consumo y arancelamiento: a completar durante el piloto
> con datos reales de uso.

## 6. Seguridad y gobernanza

- **Privilegio mínimo**: perfiles Operador / Técnico / Administrador; cada acción ejecuta solo lo que el usuario tiene permitido.
- **Sin cuentas genéricas privilegiadas**: objetivo productivo de credenciales individuales.
- **Trazabilidad completa**: identidad, canal, solicitud, validación, acción, resultado y fecha/hora de cada interacción.
- **Confirmación explícita** previa a toda operación modificativa.
- **Aislamiento de red**: el servicio no queda expuesto innecesariamente.

## 7. Beneficios esperados

**Para los operadores**: menor tiempo de interpretación de alarmas; acceso inmediato a contexto desde el canal habitual.

**Para los técnicos**: investigación de incidentes en movilidad; asistencia experta en diagnósticos; acciones autorizadas sin depender de una PC.

**Para la institución**: reducción de MTTR; centralización y trazabilidad de la operación; arquitectura preparada para futuras integraciones; adopción gradual de IA sin reemplazar las herramientas actuales ni exponer datos más allá de lo necesario.

## 8. Próximos pasos

1. **Laboratorio fiel a producción**: réplica del entorno (monitoreo + agente + Discord) con datos simulados para validar el flujo completo sin riesgo.
2. Demo con escenarios reales del cliente.
3. Piloto acotado en producción (Etapa 1, solo lectura).
4. Evaluación y plan de expansión.

---

*Documento de trabajo — sujeto a revisión técnica y comercial.*
