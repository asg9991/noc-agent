# Backlog: patas flojas del proyecto — tareas separadas

> Origen: revisión completa del repo (2026-11-06): código, docs, tests y
> proceso. Cada ítem es una unidad simple y verificable; se ejecutan de a una,
> con su propio commit. Prioridad: 🔴 alta (rompe comportamiento o expone
> datos) · 🟠 media · 🟡 baja.

## A. Bugs de código

- [x] **P1 · `watch.sweep` no parsea la respuesta real del hub (crítico)** 🔴
  `l2agent/watch.py` itera el resultado de `call_tool` como lista de dicts,
  pero el hub devuelve el envelope MCP `{"content": [{"type": "text",
  "text": "<json>"}], "isError": ...}`: el barrido ve 0 problemas siempre —
  nunca alarma NUEVO y declara RECUPERADO falso a los 2 barridos. El timer de
  15 min corre hoy sobre esta lógica. Los tests usan fakes con lista plana y
  la verificación live fue con 0 activos; por eso pasó.
  Fix: desempaquetar `content[0].text` y parsear el JSON interno (tolerante a
  lista o dict). Verificación: test RED con payload en forma real + barrido
  live contra el lab con ≥1 problema activo (debe ver NUEVO, no vacío).
  Hecho (2026-11-06): `_problem_list` en `watch.py`. La forma real medida
  tiene además guarda `[System: ...]` y payload `{"problems": [...]}`;
  `isError` o forma desconocida fallan fuerte (nunca vacío silencioso).
  4 tests RED→GREEN con esa forma; suite 80 passed; barrido live: NUEVO
  `43151` y segundo barrido RECURRENTE sin re-alarma.

- [x] **P2 · Sin backoff/retry ante 429 en el modelo** 🟠
  `l2agent/model.py` corta con `raise_for_status`; el diseño del watch y la
  comparativa de modelos piden explícito pausa entre vueltas y reintento con
  header `retry-after`. Verificación: test con transporte fake que responda
  429 + `retry-after: 1` y luego 200 (con espera simulada).
  Hecho (2026-11-06): reintento acotado en `ChatModel.decide` — intento + 2
  reintentos; `retry-after` manda y sin header usa backoff creciente
  (2s→4s, tope 60s); espera inyectable para tests. 4 tests RED→GREEN
  (incluye el pin de que los errores no-429 NO se reintentan); suite
  84 passed. Nota: la pausa *preventiva* entre vueltas quedó como P2b.

- [x] **P2b · Pacing proactivo entre requests (default off)** 🟠
  La otra mitad del pedido de diseño "pausa entre vueltas y reintento con
  backoff": esperar un intervalo fijo entre requests para no disparar los
  429 de raíz. Configurable por `LLM_MIN_INTERVAL_S` (ej. 2 para el free
  tier, 0 para inferencia local); default 0 = sin comportamiento nuevo.
  Hecho (2026-11-06): `min_interval_s` en `ChatModel` (espera inyectable;
  espacia cada request, reintentos incluidos) + wiring `LLM_MIN_INTERVAL_S`.
  4 tests RED→GREEN (espaciamiento, no-espera si ya pasó, default 0 intacto,
  configuración por env); suite 88 passed.

- [x] **P3 · L1 no matchea su propio ejemplo documentado** 🟠
  `agent/router.py:classify_l1` no reconocía "¿cómo está el zabbix?" (la
  keyword `estado` no matchea `está`): caía a L2 y consumía tokens. Decisión:
  ampliar el matching (normalizar tildes/variantes) o redefinir el contrato
  L1. Verificación: test por cada ejemplo publicado en README/runbook.
  Hecho (2026-11-06): matching por PALABRA COMPLETA sin tildes (variantes
  por concepto + frase `como esta(s|n)?` para consultas de estado). Los 4
  ejemplos publicados matchean L1; pin de falsos positivos de subcadena
  (backup, estación, estadística). Ejemplo original restaurado en README.

- [x] **P4 · Falsos positivos en la clasificación de errores** 🟡
  `l2agent/errors.py` trataba "401"/"403" como substrings ("build 4014" →
  auth) y "connect" matcheaba "connected/disconnect". Acotar a tokens
  completos o patrones de status code. Verificación: tests por caso.
  Hecho (2026-11-06): códigos por regex con límite de palabra
  (`\b(?:401|403)\b`, `\b(?:429|50[0234])\b`); "connect" fuera de las
  huellas (queda "connection"). Test con "4014"/"5000"/"disconnect".

- [x] **P5 · Truncado silencioso en `tools.run`** 🟡
  `l2agent/tools.py` cortaba a `MAX_CHARS` sin aviso (el límite de listas sí
  avisa "N más afuera"). Marcar el truncado en el texto devuelto.
  Verificación: test con payload > MAX_CHARS que assertee la marca.
  Hecho (2026-11-06): texto cortado + `…(N caracteres afuera: salida
  recortada)`; test con payload MAX_CHARS+1000.

- [x] **P6 · `watch.main` sin manejo del handshake y chequeo duplicado** 🟡
  `init()` no tenía try/except (en `loop.py` sí) y `--check-alive` llamaba
  `is_alive()` dos veces. Clasificar el error del handshake como en el loop y
  llamar una sola vez. Verificación: test con cliente que reviente en
  `initialize`.
  Hecho (2026-11-06): handshake con try/except + `classify` (auth → mensaje
  de alarma con rotación de token, exit 1); `--check-alive` consulta una
  sola vez; `main(client=...)` inyectable para tests. 3 tests nuevos.

- [x] **P7 · Etiqueta engañosa en el digest de `notify`** 🟡
  `l2agent/notify.py` usaba `average-nuevo` para todo lo bajo umbral (también
  warning/info). Renombrar a algo neutro (`bajo-umbral`) y revisar el caso
  `outbox_path=None` (el cooldown queda sin efecto entre corridas).
  Verificación: tests existentes + uno por la etiqueta.
  Hecho (2026-11-06): etiqueta `bajo-umbral` con test de neutralidad
  (Warning/Info) + contrato de cooldown documentado en `decide()`: persiste
  entre corridas solo con `outbox_path` (sin buzón no hay dónde recordar).

## B. Gobernanza de datos (prioridad del cliente)

- [x] **P8 · `.gitignore` no cubre `*.jsonl`** 🔴
  `audit.jsonl` (preguntas de operadores + hosts), `outbox.jsonl` y su
  cooldown pueden entrar al repo con un `git add .`. Agregar los patrones.
  Verificación: `git status` limpio tras correr el agente desde la raíz.
  Hecho (2026-11-06): `*.jsonl` + `*.jsonl.*` en `.gitignore`. RED observado
  con artefactos generados por el código real (aparecían `??`); tras el fix
  `git check-ignore` los cubre a los 3 (audit, outbox y cooldown) y
  `git status` queda limpio.

- [x] **P9 · Sin retención ni rotación de audit y watch DB** 🔴
  El JSONL de auditoría y la SQLite del watch (datos del cliente en claro)
  crecen sin política de vida ni backup offsite (ya marcado en la auditoría
  2026-09-10). Definir retención (días/tamaño), rotación y backup; documentar
  en el runbook. Verificación: procedimiento ejecutado de punta a punta.
  Hecho (2026-11-09): `l2agent/retention.py` + CLI `python -m
  l2agent.retention` (commits 021f5fd + f3528cd). Política: audit 90d con
  rotación 5 MiB/5 rotados, outbox+cooldown 30d, watch.db sweeps 90d e
  `observations` solo `inactive` — regla dura: una fila `active` jamás se
  borra (probado: tras retención el problema vivo sigue siendo RECURRENTE,
  no NUEVO). Líneas sin `ts` parseable se conservan. Runbook §10 con
  procedimiento y cron. Verificación independiente (17 tests + 113 suite):
  2 blockers corregidos en f3528cd (regex de rotados hardcodeada a
  `audit.jsonl`; `kept` no reconciliaba tras el tope) + 2 advisories (no-op
  byte-estable, rechazo de negativos). E2E del procedimiento ejecutado.
  Backup offsite + restore queda en P14.

- [x] **P10 · Identidad difusa en la auditoría** 🟠
  `actor` queda fijo en `"l2"` y el hub se habla con un bearer compartido.
  El objetivo de la arquitectura §7 es identidad por usuario/consumidor.
  Propagar actor real hasta `run_loop` y un token por consumidor.
  Verificación: registro de audit con actor distinto por origen.
  Hecho (2026-11-09): `actor`/`channel` se propagan desde cada origen hasta
  `run_loop` — CLI `l2agent.main` (`--actor`, fallback `NOC_ACTOR` →
  `$USER`) y `route()`/`handle_l2` (`actor=`, `channel=` para los adapters
  de Fase 4). Test de aceptación: misma pregunta vía CLI (`actor=juan`) y
  vía router (`actor=ana`, `channel=mail`) deja actores distintos en el
  mismo audit. 5 tests nuevos (118 suite). Identidad documentada en runbook
  §4 ("Identidad por consumidor"): token por consumidor = `MCP_BEARER`
  propio por proceso (el hub ya cura tools por token/rol); el alta/baja/
  rotación de tokens queda en P17.

- [ ] **P11 · Las decisiones de routing L0/L1 no se auditan** 🟠
  `agent/router.py` no registra nada; la arquitectura §5 promete "cada
  decisión de routing se registra → informe mensual de distribución por
  nivel" (insumo de costos para el cliente). Agregar log por nivel y un
  reporte agregable. Verificación: una corrida por nivel deja traza.

- [ ] **P12 · Secretos y permisos pendientes de rotar** 🟠
  Según `docs/auditoria-2026-09-10.md`: toml del hub con token en 644, `.env`
  del lab en 664, token de Telegram presente en historial git del lab.
  Rotar y corregir permisos (sin pegar valores en ningún repo).
  Verificación: checklist tildada en el runbook §4.

- [ ] **P13 · Bearer en `/tmp/.mcp_bearer`** 🟡
  Aceptable en lab; `/tmp` es directorio compartido. Replantear la ubicación
  para producción (ej. `XDG_RUNTIME_DIR` o archivo 600 bajo el home del
  servicio). Verificación: documentación de prod actualizada.

- [ ] **P14 · Backups automáticos/offsite de estado del agente** 🟡
  audit JSONL + watch DB sin backup (el patrón de backups de repos de cliente
  ya existe en ops). Incorporar al esquema de backups existente.
  Verificación: backup + restore probados.

## C. Proceso y repos

- [ ] **P15 · El nombre del cliente está en el historial público de `main`** 🟠
  README/docs ya desidentificados en HEAD, pero el nombre queda en commits
  viejos del repo público. Limpiar el historial requiere reescritura
  destructiva + force push: decidir explícitamente (en zbx-in-docker se hizo
  con autorización) o aceptar y documentar la exposición.

- [ ] **P16 · `feature/l2-local-agent` sin merge a `main`** 🟠
  20 commits (~2.5k líneas, 76 tests) esperan integración. Definir el flujo
  de branches del repo (patrón zbx-in-docker: `main` estable + ramas de
  feature que se mergean y cierran) y mergear. Verificación: `main` verde.

- [ ] **P17 · Doc de operación del hub + rotación de tokens** 🟡
  El procedimiento vive suelto en `odd/tasks/l2-local-agent.md` §Cierre.
  Pasarlo a `docs/` (operación del hub, alta/baja/rotación de tokens por
  rol). Verificación: alguien lo sigue sin leer la bitácora.

- [ ] **P18 · Runbook de upgrade incompleto** 🟡
  `zbx-in-docker/docs/instalacion.md`: 3 pasos sin backup/restore/
  verificación. Completar (repo zbx-in-docker).

## D. Arquitectura e IA local

- [ ] **P19 · Benchmark de inferencia local (sin datos hoy)** 🟠
  Un 27B Q8 pide ~30 GB de VRAM; en CPU común ~2–5 tok/s. Con gobernanza de
  datos como prioridad del cliente, la inferencia local deja de ser opcional:
  medir latencia y calidad en la infraestructura del proyecto de IA local
  antes de prometer tiempos de respuesta. Verificación: corrida del mismo
  benchmark de `scripts/sonda_techo.py` contra el endpoint local.

- [ ] **P20 · Contrato `pedir_criterio` (agent-as-tool)** 🟠
  Fila 7 del mapa de triggers: escalamiento entre agentes. Definir quién paga
  los tokens, el formato del handoff y el aislamiento de datos si el LLM es
  compartido con el proyecto de IA local (los prompts contienen datos del
  cliente). Verificación: contrato documentado y una integración de prueba.

- [ ] **P21 · Adapter mail (Fase 4) + transporte del outbox** 🟡
  `notify.py` deja mensajes "mail-ready" en un JSONL sin transporte. La
  instancia de referencia es mail-first: implementar el adapter (hilos por
  incidente) sobre el vocabulario abstracto del orquestador.

- [ ] **P22 · Redactado LLM sobre novedad confirmada** 🟡
  Pendiente del runbook §9b: el LLM redacta resúmenes solo cuando las
  compuertas ya confirmaron novedad (nunca decide qué suena).

- [ ] **P23 · Decisión del modelo fuerte de producción** 🟡
  La comparativa recomienda cloud pago por costo; con gobernanza de datos la
  balanza se corre hacia el proyecto de IA local. Re-evaluar con el cliente
  (costo vs datos dentro del perímetro) antes de fijar proveedor.

- [ ] **P24 · Memoria de largo plazo del NOC** 🟡
  Runbooks, incidentes históricos y contexto para "conocer el NOC"
  (arquitectura §9): definir tras Fase 4, alineado con el proyecto de IA
  local (dónde vive la memoria, quién la consulta).
