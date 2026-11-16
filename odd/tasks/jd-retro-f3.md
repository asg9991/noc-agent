# Judgment Day — retro F3, target 1: P9 retención

Target inmutable: `main@eee5667` — `l2agent/retention.py` + `tests/test_retention.py`.
Jueces ciegos: `jd-judge-a` + `jd-judge-b` (paralelos, mismo scope, sin ver al otro).
Round 1. Severos = CRITICAL|HIGH. Corroboración = ambos jueces.

## Ledger fusionado (round 1)

### Confirmados por AMBOS — severos (corregir en round 1)

| ID | Hallazgo | Severidad (A/B) | Hechos |
| --- | --- | --- | --- |
| C1 | **La poda sigue symlinks**: `read_text`/`write_text`/`sqlite3.connect` operan sobre el target del symlink → borra líneas/filas de archivos y DB **fuera** del alcance | CRITICAL/CRITICAL | A: repro symlink borró línea de archivo ajeno + DELETE en DB ajena; B: idéntico |
| C2 | **Carrera read-modify-write sin lock**: una línea appendeada entre la lectura y el rewrite se destruye en silencio (nunca contada en kept/dropped) | HIGH/CRITICAL | A: repro determinista pierde línea; B: repro idéntico, deploy documentado corre retention junto al agente |
| C3 | **P9×P25: la poda rompe la hash-chain** — tras la retención semanal, `--verify` sale 1 ("manipulado", falso positivo) y `--seal` se niega sin recovery posible | HIGH/HIGH | ambos con repro: chain de 4 → prune → verify roto |
| C4 | **El sort lexicográfico del cap invierte con colisiones `-N`** (sin zero-pad): con ≥10 rotaciones del mismo stamp destruye los segmentos NUEVOS y congela el set en viejos; con `--now` fijo (cron determinista) pasa en steady-state desde la run 7 | MEDIUM/CRITICAL | A: repro sort; B: repro steady 15 runs |
| C5 | **Regex anclada con `$` en vez de `\Z`** — un nombre con newline final (que la rotación nunca emite) matchea como rotado y se borra | CRITICAL/LOW | ambos comprueban el defecto; discrepan en impacto (A lo demostró con borrado) |
| C6 | **`--keep 0` aceptado y el cap incluye el archivo recién rotado** — destruye TODO el historial no expirado de una; el reporte nombra un archivo que ya no existe | HIGH/MEDIUM | ambos con repro |

### Sospecha (un solo juez — NO se corrigen, quedan registrados)

| ID | Hallazgo | Juez | Nota |
| --- | --- | --- | --- |
| S1 | El rewrite usa `write_text` (trunca al abrir): crash a mitad de escritura = historia completa perdida; el repo ya tiene el patrón atómico en `seal_audit` | A | proof: ENOSPC simulado dejó el archivo vacío |
| S2 | `splitlines()` corta en U+2028/U+2029/U+0085: registros KEEP con esos caracteres (ensure_ascii=False) quedan **corrompidos** en runs con drop | B | proof: JSON ilegible tras poda |
| S3 | `max_age_days` negativo aceptado por la API de biblioteca (guard solo en CLI) → borra todo lo vigente | A | proof: prune_audit(-1) vació el archivo |
| S4 | Artefactos corruptos (UTF-8 inválido, directorio con nombre de rotado, DB sin schema/locked) crashean sin catch → saltean outbox/db y no hay reporte | A+B | parcialmente corroborado en manejo de errores |

### Info

- I1: `_outbox_ts` coerce bool/Infinity → borra líneas que la política dice conservar (B, LOW).
- I2: la suite (17 tests) no detecta NINGUNO de los anteriores — sin fixtures encadenadas (P25), sin symlinks, sin concurrencia, sin `--keep 0`, sin colisiones (A+B de acuerdo).

### Contradicciones

Ninguna sobre existencia de defectos. Discrepancia de severidad en C5 (CRITICAL vs LOW) — resuelta por el repro de borrado de A.

### Limpios (verificado por ambos)

- Invariante 1 (fila `active` de watch.db jamás borrada): **limpio** — el DELETE es `status='inactive' AND last_seen < cutoff`.
- Invariante 3 (kept reconcilia con disco) en paths deterministas: **limpio** (salvo C2/S2).

## Round 1 — decisión

6 confirmados severos (C1–C6) → por gate del skill: **preguntar antes de la corrección**.
Estado: esperando autorización del usuario para corregir con `jd-fix-agent`.

## Re-juicio (round 1 de fix)

Delta: `869d15c` (C1–C6). Ambos jueces: los 6 confirmados **corregidos**
(probes positivos C1–C6 PASS). Defectos INTRODUCIDOS por el fix:

| ID | Hallazgo | Severidad (A/B) | Estado |
| --- | --- | --- | --- |
| R1 | La constancia `retention_prune` se saltea cuando rotación y poda coinciden (guard `p.exists()` tras el rename) | MEDIUM/HIGH | **CORREGIDO** en round 2 |
| R2 | `file_lock` sigue symlinks en el sidecar `.lock` | LOW/LOW | info (confirmado, no severo) |
| A-1 | `rechain_lines` re-hashea sin verificar → **un archivo manipulado se lava en la retención** (pasa `--verify` tras podar) | CRITICAL/— | **SOSPECHA — decisión humana** |
| A-2 | `rechain_lines` reinicia el ancla en líneas en blanco pero `verify_audit` las salta sin reiniciar → falso positivo tras podar | HIGH/— | sospecha |
| B-3 | El test CLI de C6 es falso green: `main()` no acepta posicionales, sale 2 por "unrecognized arguments" con o sin el guard | —/MEDIUM | sospecha (test) |
| R3 | `detail.rotated` puede nombrar un segmento que el mismo cap destruyó (stamps no-monotónicos) | LOW/— | sospecha (round 2) |

## Veredicto terminal (round 2 de fix + re-juicio 2)

Round 2: R1 corregido (`2ed6327`, RED→GREEN, 155 passed). Re-juicio 2:
Juez B limpio; Juez A solo R3 (LOW). Presupuesto agotado (2 rounds fix +
2 re-juicios; sin tercero).

**JUDGMENT: ESCALATED ⚠️** — todo lo confirmado severo (C1–C6 + R1) está
corregido y re-verificado, pero queda A-1 (CRITICAL, un juez: bypass de
tamper-evidence vía rechain) más sospechas A-2/B-3/R2/R3 sin resolver. Por
regla del skill las sospechas no se auto-corrigen: requieren decisión
explícita del usuario. El branch NO se mergea a main hasta esa decisión
(el fix intercambia el falso-alarma de C3 por el laundering de A-1 si se
mergea sin corregir).

## Cierre de sospechas (autorización del usuario, 2026-11-13)

El usuario autorizó corregir TODAS las sospechas. Batch `7d52b6f` + `015c43c`:
A-1 (validación de cadena **pre-poda** completa — los gaps de la poda son
legítimos, la manipulación previa bloquea), A-2 (blancos no reinician el
ancla), B-3 (test CLI corregido), R2 (O_NOFOLLOW en el sidecar), R3
(constancia no nombra segmentos destruidos; `cap_removed`), S2 (split solo
por "\n"; registros con U+2028 intactos), S3 (ventana negativa rechazada),
S4 (aislamiento por artefacto; rc=1; reporte siempre impreso) y **cap de
tamaño para outbox** (cola acotada, `overflow_dropped`, lo más viejo primero
— pregunta del usuario: "¿no necesitan cap también?").

Vista externa (F1): verificador independiente sobre el batch → **1 blocker**
(B1: la primera guard de A-1 confundía los gaps de la poda legítima con
borrados; rechazaba la retención sana) + tests vacíos detectados. Corregido
en `015c43c` con validación pre-poda + tests durables probe-validados.
Recheck limitado a los blockers: verde. Suite: **166 passed**.
