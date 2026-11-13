# Backlog: patas flojas del proyecto — tareas separadas

> Origen: revisión completa del repo (2026-11-06): código, docs, tests y
> proceso. Cada ítem es una unidad simple y verificable; se ejecutan de a una,
> con su propio commit. Prioridad: 🔴 alta (rompe comportamiento o expone
> datos) · 🟠 media · 🟡 baja.

## Cierre del bloque P9–P14 (2026-11-12)

Código + tests (132 green) y verificación de tier completas: P9 con
verificador independiente (2 blockers encontrados y corregidos), P14 con
e2e backup/restore, P10–P13 con tests de aceptación. La revisión NATIVA no
se completó por bug del runtime de reviewers (gentle-ai#4873 — ocurrencia
reportada en ese issue); decisión del usuario: cerrar sin ese receipt.
Todas las transacciones de review quedaron liberadas (abandon):
`review-facbb8a0…`, `review-b44e826f…` y la stale `review-991fa5dc…`
(sep 2026, candidato del catálogo MCP, ya commiteado). Opción futura:
outside-view del rango como slice nuevo al mergear a main (P16).

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

- [x] **P11 · Las decisiones de routing L0/L1 no se auditan** 🟠
  `agent/router.py` no registra nada; la arquitectura §5 promete "cada
  decisión de routing se registra → informe mensual de distribución por
  nivel" (insumo de costos para el cliente). Agregar log por nivel y un
  reporte agregable. Verificación: una corrida por nivel deja traza.
  Incorporado (2026-11-09): default de `actor` por identidad del kernel
  (`pwd.getpwuid(os.getuid())`) en vez de `$USER` spoofeable — la cadena
  `--actor` → `NOC_ACTOR` → `$USER` → `"cli"` es auto-declarada; el único
  nivel con valor de autenticación es el dueño real del proceso.
  Hecho (2026-11-09): traza `action="route"` con `result` = L0/L1/L2 +
  handler/pregunta en `detail` — `route()` registra L0/L1, `handle_l2` la
  decisión L2 (cubre llamadores directos), `l2agent.main` la suya. Informe
  agregable `python -m l2agent.audit [--since]` (por nivel, handler y
  actor). Identidad por kernel: `$USER` reemplazado por
  `pwd.getpwuid(os.getuid())` con test de no-spoof. 4 tests nuevos (122
  suite). Runbook §11. Fuera de alcance: dispatch de `agent/cli.py`
  (comandos fijos, sin decisión de routing).

- [x] **P12 · Secretos y permisos pendientes de rotar** 🟠
  Según `docs/auditoria-2026-09-10.md`: toml del hub con token en 644, `.env`
  del lab en 664, token de Telegram presente en historial git del lab.
  Rotar y corregir permisos (sin pegar valores en ningún repo).
  Verificación: checklist tildada en el runbook §4.
  Hecho (2026-11-09) — permisos: toml → 600 sin ACLs (se removió la ACL
  huérfana `user:dnsmasq` que dejaba lectura extra), `.env` ya estaba 600;
  ambos ignorados por git (verificado con `git ls-files`/`check-ignore`);
  hub sano tras el cambio (problem_active_get OK). Pendiente — rotaciones
  manuales: `api_token` Zabbix del toml (UI, procedimiento P17) y token del
  media Telegram (BotFather; media activo id 16 en el lab). El token de
  Telegram queda en el historial de `zbx-in-docker`
  (`template_telegram_webhook.xml`, commits da12351/1765f40/5be7da0/
  ac7bd77) — purgar historial = decisión destructiva posterior a rotar.
  Decisión del usuario (2026-11-09): en LAB los tokens quedan como están
  (aceptado); lo que tiene que quedar cristalino es la rotación para
  CLIENTES → criterio reforzado en P17.
  Corrección (2026-11-12, detectado por el drill de P17): la ACL
  `user:dnsmasq` **no era huérfana** — `dnsmasq` es el nombre en el host del
  uid 999, que es el uid del servicio `zabbix-mcp` dentro del contenedor.
  Quitarla junto al `600` dejó al hub sin poder leer su config al reiniciar
  (EACCES + crash loop latente; solo se manifiesta al recrear el contenedor).
  Estado correcto: `600` + ACL `u:999:r--` (aplicado en lab); ver
  `zbx-in-docker/docs/operacion-hub.md` §Permisos del toml. Además, el
  `api_token` de lab quedó rotado en el drill de P17 (tokenid 3 dado de baja).

- [x] **P13 · Bearer en `/tmp/.mcp_bearer`** 🟡
  Aceptable en lab; `/tmp` es directorio compartido. Replantear la ubicación
  para producción (ej. `XDG_RUNTIME_DIR` o archivo 600 bajo el home del
  servicio). Verificación: documentación de prod actualizada.
  Hecho (2026-11-09): knob `MCP_BEARER_FILE` en `agent/mcp_client.py`
  (prioridad: explícito > `MCP_BEARER` > archivo; default de lab sin
  cambios). Prod documentado en runbook §4 (`$XDG_RUNTIME_DIR/noc-agent/
  mcp_bearer` o home del servicio, 600, jamás `/tmp`; ejemplo systemd con
  `%t`). 4 tests de la cadena de resolución.

- [x] **P14 · Backups automáticos/offsite de estado del agente** 🟡
  audit JSONL + watch DB sin backup (el patrón de backups de repos de cliente
  ya existe en ops). Incorporar al esquema de backups existente.
  Verificación: backup + restore probados.
  Hecho (2026-11-09): `scripts/backup-estado.sh` siguiendo el esquema de
  ops (`engram-backup.sh`): snapshot WAL-safe del SQLite → tar.gz con
  MANIFEST+sha256 → cifrado age/openssl (passphrase por env, jamás en
  archivo) → staging `~/backups/noc-agent-estado` con rotación
  `NOC_BACKUP_KEEP` → upload a Drive `backups/noc-agent/` vía google-agent.
  Upload en claro prohibido (rechazado). En lab el offsite se simula con
  `--dry-run`/`--output`. Restore verificado (`--force` para pisar,
  checksums validados). 6 tests: round-trip de punta a punta, refusal sin
  --force, rotación, tamper detectado, cifrado round-trip, rechazo de
  upload sin cifrar (132 suite). Camino de prod allanado pero NO probado
  en producción (decisión del usuario 2026-11-09: lab simula, prod se
  prueba al pasar a instancia con cliente). Runbook §12.

## C. Proceso y repos

- [x] **P15 · El nombre del cliente está en el historial público de `main`** 🟠
  README/docs ya desidentificados en HEAD, pero el nombre queda en commits
  viejos del repo público. Limpiar el historial requiere reescritura
  destructiva + force push: decidir explícitamente (en zbx-in-docker se hizo
  con autorización) o aceptar y documentar la exposición.
  Decisión del usuario (2026-11-12): reescribir (autorización explícita).
  Hecho: `git filter-repo` con reemplazo del nombre → `cliente` en blobs y
  mensajes (8 commits de contenido 2026-09-26→2026-11-06 + 2 mensajes),
  3 ramas forzadas a origin con lease: `main` 85e34fb→8ac3744,
  `feature/l2-local-agent` cda4737→fa2264b (el trabajo P9–P15 de esta
  sesión se publica recién con este push), `feature/mcp-client`
  6ba555c→e56d8da. Verificado: 0 menciones en contenido y mensajes, tree
  hash idéntico antes/después (contenido intacto byte a byte). Backup
  pre-rewrite: bundle local. CAVEAT: los SHAs viejos pueden seguir
  accesibles por URL directa en GitHub (objetos colgados) hasta GC o purga
  por soporte; para borrado total hay que pedir la purga con los SHAs
  viejos (85e34fb4, bcfaf7c, 224aadc, 6ba555c3...).

- [x] **P16 · `feature/l2-local-agent` sin merge a `main`** 🟠
  20 commits (~2.5k líneas, 76 tests) esperan integración. Definir el flujo
  de branches del repo (patrón zbx-in-docker: `main` estable + ramas de
  feature que se mergean y cierran) y mergear. Verificación: `main` verde.
  Hecho (2026-11-12): flujo definido en README §Flujo de desarrollo (main
  estable, features merge `--no-ff`, ramas cerradas/archivadas sin borrar).
  Merge `708114e` integra la rama completa (Fase 3: P9–P15 + verificaciones).
  `main` verde verificado: **132 passed** tras el merge. La rama queda
  cerrada (archivada); borrarla queda pendiente de autorización expresa
  (política local: no borrar ramas).

- [x] **P17 · Doc de operación del hub + rotación de tokens** 🟡
  El procedimiento vive suelto en `odd/tasks/l2-local-agent.md` §Cierre.
  Pasarlo a `docs/` (operación del hub, alta/baja/rotación de tokens por
  rol). Verificación: alguien lo sigue sin leer la bitácora.
  Criterio (2026-11-09, decisión sobre P12): la rotación tiene que quedar
  cristalina para instancias de CLIENTE (en lab los tokens quedan como
  están, aceptado).
  Hecho (2026-11-12): `zbx-in-docker/docs/operacion-hub.md` (repo genérico
  según la regla de routing) — identidad en 3 capas, alta/baja/rotación sin
  ventana de ciego, diagnóstico y checklist ejecutable; enlazado desde
  `seguridad-secretos.md`. Verificación: checklist ejecutado de punta a punta
  por el operador (sin leer la bitácora) con rotación real del `api_token`
  del hub: `token.create`/`generate` (tokenid 4, `hub-lab-rot-20261112`) →
  swap → smoke verde → `token.delete` del viejo (tokenid 3, `lab_hub`) →
  smoke final verde → inventario limpio. Con esto también queda rotado el
  `api_token` de lab que P12 dejaba pendiente. El drill detectó un bug real:
  el `600` del P12 sin ACL para el uid del servicio (999 `zabbix-mcp`; se
  mostraba como `dnsmasq` en el host) rompía la lectura del toml al reiniciar
  el hub (EACCES + crash loop latente). Corregido con `setfacl -m u:999:r--`
  y documentado en el runbook (§Permisos del toml). Rollback del runbook no
  ejercitado (sin rojo; mismos mecanismos ya probados).

- [x] **P18 · Runbook de upgrade incompleto** 🟡
  `zbx-in-docker/docs/instalacion.md`: 3 pasos sin backup/restore/
  verificación. Completar (repo zbx-in-docker).
  Hecho (2026-11-13): sección "Actualizar la versión de Zabbix" completa —
  §0 backup pre-upgrade (pg_dump + `.env.bak` + snapshot de tags; "sin dump
  no hay rollback"), §1 upgrade, §2 verificación post (checklist §1–§10 +
  apiinfo + log de esquema + hub smoke), §3 rollback (restore sobre base
  vacía). Verificado ejecutándolo en lab: backup real (29 MB, `gzip -t` OK),
  **restore drill** en postgres descartable (207 tablas, 387 hosts, 0
  errores), **dry-run del upgrade** a versión idéntica (build + recreate +
  migración no-op) y verificación completa verde. El drill agarró 2 fallos
  latentes más de la clase "config que se resuelve una sola vez":
  (a) `data/certs/` vacío desde sep → `zbx-nginx` crash-loops al primer
  recreate (`cannot load certificate`); corregido con par self-signed en el
  layout 600/644 — el contenedor viejo escondía la config rota, igual que la
  ACL del P17; (b) el servicio compose es `nginx` (el contenedor
  `zbx-nginx`) — trampa de nombres. Además Paso 4 usaba `http://` (301 con
  TLS) → `https://`. **PENDIENTE**: bump real de versión con migración de
  esquema entre versiones (ejercitar en la primera actualización de patch);
  marcado en el runbook §1.

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
  Criterio de aceptación (2026-11-09): la identidad del audit proviene del
  usuario AUTENTICADO del canal (mapa usuario de canal → actor), nunca del
  contenido del mensaje — un actor auto-declarado en el payload no es
  identidad.

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

- [x] **P25 · Integridad y tamper-evidence del audit** 🟠
  `audit.jsonl` es un archivo plano: "append-only" es convención, no
  mecanismo — cualquiera con write sobre el archivo reescribe historia y el
  backup (P14) conservaría hasta la versión falsificada. Mitigar con
  permisos estrictos (usuario dedicado/600) y un mecanismo anti-manipulación
  (hash-chain ligera o sink externo append-only). Urgencia real al abrir
  Fase 4: un actor falsificado no debería poder ordenar writes con evidencia
  imposible de auditar. Verificación: intento de modificación de una línea
  pasada es detectable.
  Hecho (2026-11-13): hash-chain ligera en `l2agent/audit.py` — cada línea
  encadenada (`prev_hash`/`entry_hash`, sha256 canónico), archivo en `600`
  (fchmod, también en legados) y lock por archivo contra carrera. CLI:
  `python -m l2agent.audit <log> --verify` (exit 0 intacto / 2 sin sellar /
  1 manipulado con `broken_line`) y `--seal` (migración atómica de historia
  legada; se niega si la cadena sellada está rota — no lava manipulaciones).
  Verificado con TDD: RED (`ImportError`) → GREEN con 7 tests nuevos
  (modificación detectada ✓, borrado ✓, inserción ✓, sello preservando
  contenido ✓, rechazo de sello sobre cadena rota ✓, permisos 600 ✓);
  **139 passed** en total. Runbook §13 con el modelo de amenaza honesto
  (cadena ligera: no cubre atacante que recalcule toda la cadena; sink
  externo append-only queda pendiente para Fase 4).
