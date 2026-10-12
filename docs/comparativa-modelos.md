# Comparativa de modelos y costos de IA — NOC Agent

> **Documento de trabajo** para el cliente. Completa el §5 de la propuesta
> ("números concretos a completar durante el piloto"): todo número de consumo
> es **medido en el lab** el 2026-10-12; todo volumen de uso está marcado como
> **[SUPUESTO]** hasta validar con operación real. Fuentes de precios y límites
> al pie, con fecha.

---

## 1. En qué actúa el agente y cuánto gasta por tarea (medido)

Casos de la Etapa 1 de la propuesta, medidos con el loop real contra el lab
(modelo `qwen/qwen3-32b` vía Groq, 2 corridas por tarea, audit en JSONL):

| Tarea | Qué hace | Éxito | Tokens in/out por corrida | Iters |
|---|---|---|---|---|
| Triage por severidad | 1 tool + resumen | 2/2 | ~1060 / ~208 | 1 |
| Investigar host | plan multi-paso | **0/2** | ~332 / ~77 | 1 |
| Explicar por qué disparó | 2–4 tools + síntesis | 1/2 (otra 429) | ~5900–6300 / ~350–700 | 2–4 |
| Valores de historia | 4 tools | 0/2 (429) | ~3700–4200 / ~330–440 | 4 |

Lectura:

- **El input domina el gasto** (5–10× el output): cada vuelta reinyecta el
  historial. Acortar historial o respuestas no mueve la aguja; acortar
  *vueltas* sí.
- **Investigar host falló 2/2 por formato** (el modelo devolvió prosa en vez
  de JSON de acción). No es límite de cuota: es **calidad del modelo** en
  planificación multi-paso. Ningún precio compensa un modelo que no sigue
  el protocolo.
- Los 429 de esta tanda confirman lo ya medido: tareas de 4 decisiones
  disparan ~4 requests en ~3 segundos (≈80/min vs 30 permitidos). Con
  cadencia entre tareas no alcanza: hace falta **pausa entre vueltas y
  reintento con backoff** (diseño del watch, diario #53).

## 2. Límites free y precios pagos (Groq, relevado 2026-10-12)

| Modelo | Free (RPM / TPM / RPD / TPD) | Pago (u$d / 1M in+out) | Velocidad |
|---|---|---|---|
| `qwen/qwen3-32b` (actual) | 30 / 8K / 1K / 200K | 0.80 + 4.00 | ~450 tok/s |
| `openai/gpt-oss-20b` | 30 / 8K / 1K / 200K | 0.075 + 0.30 | ~1000 tok/s |
| `openai/gpt-oss-120b` | 30 / 8K / 1K / 200K | 0.15 + 0.60 | ~500 tok/s |
| `llama-3.1-8b` | — (Enterprise, sin free) | Contact Sales | — |

Fuentes: `console.groq.com/docs/rate-limits` y `console.groq.com/docs/models`
(consultados 2026-10-12). Sin suscripción: se paga solo por tokens, factura
desde u$d 1 acumulado.

Descartados con motivo:

- **Cerebras**: sin free permanente (u$d 5 de prueba, 30 días, con tarjeta).
  No es alternativa gratuita.
- **Gemini free (AI Studio)**: tokens gratis en Flash, pero Google **no
  publica** los límites (solo visibles por proyecto, sin garantía) y usa el
  contenido para entrenar. Para un NOC con datos sensibles de
  infraestructura, ambos puntos son bandera roja. Requiere evaluación propia.
- **LLM local en VM**: sin datos. Un 27B en Q8 pide ~30 GB de VRAM; en CPU
  común serían ~2–5 tok/s (una respuesta de 400 tokens = 1–3 min). Solo se
  considera con benchmark de latencia y calidad en mano.

## 3. Escenarios mensuales (30 días)

Fórmula: `consultas/día × tokens/tarea × 30 × precio`. Volúmenes **[SUPUESTO]**.

**S1 — Piloto lab: 10 consultas/día** (70 % triage 1.3k tok + 30 % investigación 6k tok ≈ 27k tok/día, ~30 req/día):

| | Free qwen | Pago qwen | Pago gpt-oss-20b |
|---|---|---|---|
| Mes | ✅ sobra (27K≪200K/día) | ~u$d 1.00 | **~u$d 0.09** |

**S2 — cliente real estimado: 30 consultas/día + watch triage cada 15 min** (≈200k tok/día, ~300 req/día):

| | Free qwen | Pago qwen | Pago gpt-oss-20b |
|---|---|---|---|
| Mes | ⚠️ al límite (200K/día) | ~u$d 7.50 | **~u$d 0.65** |

**S3 — Watch cada 5 min**: ~580k tok/día — excede el free en todos los
modelos. Solo pago o cadencia menor.

## 4. Día pico: cuándo el free no alcanza (análisis, 2026-10-12)

El piloto entra en free; el peor día, no. Matemática con volúmenes
**[SUPUESTO]** a validar en operación:

- **Crisis (1 técnico × 6 h × 12 consultas/h = 72):** mezcla pesada
  (70 % investigación 5k + 30 % triage 1.3k) ≈ 280K textos + vigilancia
  125K = **~405K vs 200K TPD** ❌. Consultas ~416 vs 1.000 RPD ✓: el que
  corta es siempre el cupo diario de textos, no el de consultas.
- **Jornada de construcción** (altas, dashboards, idas y vueltas con
  confirmación): tareas de escritura y contexto grande ≈ 8k cada una;
  8 tareas/h × 8 h ≈ **~500K/día** ❌.
- **Costo del peor día en pago (120b):** ~500K in + ~80K out ≈
  **u$d 0,15 por día**. Aun con 20 días pico al mes: ~u$d 3. El dinero
  nunca es la restricción; los techos sí, y el pago los multiplica ×10.

Palancas estructurales (antes de cambiar de proveedor): capa determinista
para lo repetitivo —en crisis todos preguntan lo mismo— (costo y cupo
cero), modelos por nivel (chico para triage, grande para investigar),
caché por incidente, historial corto y heartbeat. Con el 80 % repetitivo
por vía determinista, el día pico vuelve a entrar en free.

Regla de decisión: free hasta 429 diarios reiterados; entonces pago mismo
proveedor (sin cambio técnico). LLM local solo por privacidad o
continuidad, con benchmark previo. Presupuesto de desarrollo (herramientas
del equipo) y de operación (Groq del cliente) van separados.

## 5. Recomendación por etapas (honesta)

1. **Piloto: free actual, u$d 0.** Alcanza con margen; sirve para validar
   volúmenes reales y afinar prompts.
2. **Antes de producción: benchmark ciego qwen vs gpt-oss-20b** (mismas 4
   tareas × N corridas; puntaje: éxito + formato + calidad de respuesta).
   El 20b cuesta **10× menos** en pago y es 2× más rápido — *si* la calidad
   acompaña, es el candidato natural. Hoy la calidad está **sin medir**.
3. **Producción: pago gpt-oss-20b o qwen según benchmark** (u$d 1–8/mes a
   estos volúmenes; irrelevante frente a cualquier VM). Free como fallback,
   nunca como plan.
4. **LLM local: solo si un benchmark lo justifica** (privacidad total o
   costo a escala). No antes.

Palancas de diseño que estiran cualquier presupuesto (valen para todos los
modelos): backoff+retry ante 429, pausa entre vueltas del loop, historial
corto, heartbeat (saltear el LLM si nada cambió), comandos deterministas
sin IA para lo repetitivo (ya previsto en §5 de la propuesta).

## 6. Panorama escritura y modelos frontera (análisis, 2026-10-12)

**Sesión-incidente medida (120b, 4 tareas encadenadas):** rep1 13.429 in +
1.825 out (≈15k), 3/4 ok; rep2 ≈10k, 3/4. El fallo restante es estrategia
(repite `trigger_get`, lo frena el anti-loop): la familia gpt-oss tiende a
reintentar la misma acción ante la duda. Una sesión de incidente completa
cuesta entonces **10–15k textos**.

**Modo escritura (Etapa 2, proyección, sin medir):** cada escritura suma
propuesta + confirmación + ejecución + verificación a una investigación
base (≈2–4k): estimado 5–7k por operación. Jornada de construcción con
contextos grandes (configs, dashboards en el prompt): ~500K/día
[SUPUESTO]. A medir en piloto.

**Modelos de suscripción tipo zen:** no son reutilizables como motor del
servicio (licencia de uso interactivo por usuario, sin clave para
servidor propio, facturación personal, sin auditoría). Las capacidades
equivalentes sí son evaluables por API oficial con clave propia:

| Vía | Ejemplo | Precio /1M in+out | Rol posible |
|---|---|---|---|
| Groq pago | 120b / 20b | 0.15+0.60 / 0.075+0.30 | Hoy |
| Anthropic API | Haiku (u$d 0.05+0.25) / Sonnet (2+10) | barato / frontera | Triage barato / investigación profunda |
| OpenAI API | gpt-5-nano (0.05+0.40) / mini (0.25+2.00) | barato | Mismo esquema por niveles |

Calidad de frontera en este loop: sin medir. Presupuesto de desarrollo
y de operación, separados.

## 7. Benchmark ciego 2026-10-12 (4 tareas Etapa 1 × 2 corridas, mismo harness)

| Modelo | Éxito | Formato | Calidad útil | Lectura |
|---|---|---|---|---|
| `qwen3-32b` (actual) | 3–4/8 | JSON ok | Buena en triage/explicación; honesto sin datos | Baseline; 429 solo en ráfaga |
| `gpt-oss-20b` | **5/8** | Nativo ok | Adapter funciona: investiga-host 2/2 con datos reales. Flojo en estrategia (repite la misma acción y dispara el anti-loop) y más verborrágico (~800 tok salida/corrida vs ~350 qwen). Pago S2 ≈ u$d 1.00/mes |
| `gpt-oss-120b` | **6/8** | Nativo ok | La mejor calidad hasta acá: resolvió *investigar host* (0/4 en qwen) con tools reales, explicaciones con umbral. Los 2 fallos son 429 en la tarea más pesada (mismo pacing intra-tarea, independiente del modelo) |
| `allam-2-7b` (500K/día) | 2/8 nominal, 0/8 útil | No sigue el JSON | Repite la misma acción (dispara anti-repetición), devuelve prosa, respuestas evasivas genéricas | Presupuesto generoso, protocolo pobre: 7B no alcanza para este loop |

Respuestas completas por modelo en `/tmp/opencode/bench_*.jsonl` (calidad a
juicio del lector; el éxito/formato es automático).

Consecuencia para la recomendación: el 120b con adapter es el mejor
candidato técnico (6/8, calidad) y sale ~u$d 1.30/mes en pago a volumen S2;
el 20b rinde 5/8 con el mismo adapter pero repite acciones y gasta más
salida (~u$d 1.00/mes). qwen sigue como producción free. allam descartado.
Todos los precios pagos son irrelevantes frente a cualquier VM; el free
sigue alcanzando para piloto.
